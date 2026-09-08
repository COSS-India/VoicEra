"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import protobuf from "protobufjs";
import { createWebCall } from "@/lib/api/calls";

const SAMPLE_RATE = 16000;
const NUM_CHANNELS = 1;

const PROTO = `
syntax = "proto3";
package pipecat;

message TextFrame {
  uint64 id = 1;
  string name = 2;
  string text = 3;
}

message AudioRawFrame {
  uint64 id = 1;
  string name = 2;
  bytes audio = 3;
  uint32 sample_rate = 4;
  uint32 num_channels = 5;
  optional uint64 pts = 6;
}

message TranscriptionFrame {
  uint64 id = 1;
  string name = 2;
  string text = 3;
  string user_id = 4;
  string timestamp = 5;
}

message MessageFrame {
  string data = 1;
}

message InterruptionFrame {
  uint64 id = 1;
  string name = 2;
}

message Frame {
  oneof frame {
    TextFrame text = 1;
    AudioRawFrame audio = 2;
    TranscriptionFrame transcription = 3;
    MessageFrame message = 4;
    InterruptionFrame interruption = 5;
  }
}
`;

export interface TranscriptMessage {
  type: "user" | "assistant";
  content: string;
  id: string;
}

function getBrowserWsUrl(orgId: string, agentId: string, callId?: string): string {
  // Get the base WebSocket URL from the environment; strip trailing slash if present.
  // This is used to build the runtime connection URI for audio/voice agent interactions.
  const base = (process.env.NEXT_PUBLIC_RUNTIME_WS_URL ?? "").replace(/\/$/, "");
  // Same route as telephony — the runtime dispatches by the agent's agent_category.
  const path = `${base}/agent/${orgId}/${agentId}`;
  return callId ? `${path}?call_id=${encodeURIComponent(callId)}` : path;
}

function convertFloat32ToS16PCM(float32Array: Float32Array): Int16Array {
  const int16Array = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const clamped = Math.max(-1, Math.min(1, float32Array[i]!));
    int16Array[i] = clamped < 0 ? clamped * 32768 : clamped * 32767;
  }
  return int16Array;
}

interface DecodedFrame {
  text?: { id?: unknown; name?: string; text?: string };
  audio?: { audio?: Uint8Array | number[]; sampleRate?: number; numChannels?: number };
  transcription?: { text?: string; userId?: string; timestamp?: string };
  message?: { data?: string };
}

/** Average frequency-bin energy, normalized 0–1 with a boost since raw
 * speech levels rarely approach the analyser's theoretical max. */
function levelFromAnalyser(analyser: AnalyserNode, buffer: Uint8Array<ArrayBuffer>): number {
  analyser.getByteFrequencyData(buffer);
  let sum = 0;
  for (let i = 0; i < buffer.length; i++) sum += buffer[i]!;
  const avg = sum / buffer.length / 255;
  return Math.min(1, avg * 3.2);
}

function int16BytesToFloat32(bytes: Uint8Array): Float32Array {
  const validLen = bytes.length - (bytes.length % 2);
  const int16 = new Int16Array(bytes.buffer, bytes.byteOffset, validLen / 2);
  const out = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) out[i] = int16[i]! / 32768;
  return out;
}

export function usePipecatAudio(orgId: string, agentId: string) {
  const [status, setStatus] = useState("Ready");
  const [isMuted, setIsMuted] = useState(false);
  const [isSpeakerMuted, setIsSpeakerMuted] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [transcriptHistory, setTranscriptHistory] = useState<TranscriptMessage[]>([]);
  const [liveAssistantText, setLiveAssistantText] = useState("");
  const [liveUserText, setLiveUserText] = useState("");
  // Normalized 0–1 mic/output levels, for a voice-reactive avatar (orb-ui
  // controlled mode) — sampled off analyser taps, not part of the audio
  // routing graph itself, so they can't affect what's actually heard/sent.
  const [inputVolume, setInputVolume] = useState(0);
  const [outputVolume, setOutputVolume] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const frameTypeRef = useRef<protobuf.Type | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const gainNodeRef = useRef<GainNode | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const inputAnalyserRef = useRef<AnalyserNode | null>(null);
  const outputAnalyserRef = useRef<AnalyserNode | null>(null);
  const meterIntervalRef = useRef<number | null>(null);
  const isMutedRef = useRef(false);
  const assistantBufRef = useRef("");
  const userBufRef = useRef("");
  const messageCounterRef = useRef(0);

  useEffect(() => {
    isMutedRef.current = isMuted;
    micStreamRef.current?.getAudioTracks().forEach((t) => {
      t.enabled = !isMuted;
    });
  }, [isMuted]);

  useEffect(() => {
    const root = protobuf.parse(PROTO).root;
    frameTypeRef.current = root.lookupType("pipecat.Frame");
    setStatus("Ready to connect");
  }, []);

  const pushTranscript = useCallback((type: "user" | "assistant", content: string) => {
    const text = content.trim();
    if (!text) return;
    setTranscriptHistory((prev) => {
      if (prev.some((m) => m.type === type && m.content === text)) return prev;
      messageCounterRef.current += 1;
      return [...prev, { type, content: text, id: `${type}-${messageCounterRef.current}` }];
    });
  }, []);

  // The user's utterance streams in as a sequence of interim, unstable
  // guesses rather than growing deltas — each one *replaces* the current
  // best guess instead of being appended. We show it live but only commit
  // it as a finished transcript line once the turn is over.
  const streamUserText = useCallback((text: string) => {
    userBufRef.current = text;
    setLiveUserText(text);
  }, []);

  const commitUserTurn = useCallback(() => {
    if (!userBufRef.current) return;
    pushTranscript("user", userBufRef.current);
    userBufRef.current = "";
    setLiveUserText("");
  }, [pushTranscript]);

  // The runtime reports the assistant's speech through more than one frame
  // channel at once for the same utterance (a protobuf transcription/text
  // frame *and* a JSON "message" frame) — treating each arrival as new
  // content, regardless of source, showed every line duplicated 2-3x. A
  // chunk that's already contained anywhere in what we've built for this
  // turn is a resend of the same text, not new text, from whichever channel
  // — so it's dropped instead of being set or appended again.
  const streamAssistantText = useCallback((chunk: string, mode: "replace" | "append") => {
    if (!chunk) return;
    if (assistantBufRef.current && assistantBufRef.current.includes(chunk)) return;
    assistantBufRef.current =
      mode === "replace" ? chunk : assistantBufRef.current ? `${assistantBufRef.current} ${chunk}` : chunk;
    setLiveAssistantText(assistantBufRef.current);
  }, []);

  const commitAssistantTurn = useCallback(() => {
    if (!assistantBufRef.current) return;
    pushTranscript("assistant", assistantBufRef.current);
    assistantBufRef.current = "";
    setLiveAssistantText("");
  }, [pushTranscript]);

  const handleAudioFrame = useCallback(
    (frame: DecodedFrame) => {
      setIsPlaying(true);
      // The bot speaking is the clearest signal we have that the user's turn
      // just ended — commit whatever partial transcript we were streaming.
      commitUserTurn();

      const audioMsg = frame.audio;
      if (!audioMsg || !audioContextRef.current || !workletRef.current) return;

      const audioField = audioMsg.audio;
      let bytes: Uint8Array;
      if (audioField instanceof Uint8Array) bytes = audioField;
      else if (Array.isArray(audioField)) bytes = new Uint8Array(audioField as number[]);
      else return;

      const float32 = int16BytesToFloat32(bytes);
      workletRef.current.port.postMessage({
        event: "write-float32",
        buffer: float32,
        sampleRate: audioContextRef.current.sampleRate,
        trackId: `chunk-${Date.now()}`,
      });
    },
    [commitUserTurn],
  );

  const handleServerFrame = useCallback(
    (frame: DecodedFrame) => {
      const transcription = frame.transcription;
      if (transcription) {
        const userId = String(transcription.userId ?? "");
        const text = String(transcription.text ?? "").trim();
        if (!text) return;
        if (userId && userId !== "bot" && userId !== "ai") {
          streamUserText(text);
        } else {
          commitUserTurn();
          streamAssistantText(text, "replace");
        }
        return;
      }

      const textFrame = frame.text;
      if (textFrame) {
        const text = String(textFrame.text ?? "").trim();
        if (text) {
          commitUserTurn();
          streamAssistantText(text, "replace");
        }
        return;
      }

      const message = frame.message;
      if (message) {
        try {
          const raw = String(message.data ?? "");
          const data = JSON.parse(raw);
          const frameType = data?.type;
          if (frameType === "bot-tts-text" || frameType === "bot-output" || frameType === "generated_text") {
            const aiText = (
              data?.data?.text ??
              data?.data?.content ??
              data?.text ??
              ""
            ).trim();
            if (aiText) {
              commitUserTurn();
              streamAssistantText(aiText, "append");
            }
          } else if (frameType === "user-transcription" || frameType === "transcription") {
            const userText = (data?.data?.text ?? data?.text ?? "").trim();
            if (userText) streamUserText(userText);
          } else if (frameType === "bot-stopped-speaking") {
            setIsPlaying(false);
            commitAssistantTurn();
          }
        } catch {
          /* ignore non-json message frames */
        }
      }
    },
    [streamUserText, commitUserTurn, streamAssistantText, commitAssistantTurn],
  );

  const stopAudio = useCallback((closeWs: boolean) => {
    setIsConnected(false);
    setIsSpeaking(false);
    setIsPlaying(false);
    setIsSpeakerMuted(false);
    setInputVolume(0);
    setOutputVolume(0);
    if (meterIntervalRef.current !== null) {
      window.clearInterval(meterIntervalRef.current);
      meterIntervalRef.current = null;
    }
    inputAnalyserRef.current?.disconnect();
    inputAnalyserRef.current = null;
    outputAnalyserRef.current?.disconnect();
    outputAnalyserRef.current = null;
    workletRef.current?.port.postMessage({ event: "clear" });
    workletRef.current?.disconnect();
    workletRef.current = null;
    gainNodeRef.current?.disconnect();
    gainNodeRef.current = null;
    processorRef.current?.disconnect();
    processorRef.current = null;
    sourceRef.current?.disconnect();
    sourceRef.current = null;
    micStreamRef.current?.getTracks().forEach((t) => t.stop());
    micStreamRef.current = null;
    if (audioContextRef.current?.state !== "closed") {
      audioContextRef.current?.close().catch(() => {});
    }
    audioContextRef.current = null;
    if (closeWs && wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setStatus("Disconnected");
  }, []);

  const connect = useCallback(async () => {
    if (!frameTypeRef.current || !orgId || !agentId) return;
    setStatus("Connecting…");

    // Register a CallLog up front so this session's recording/transcript get
    // persisted like a telephony call. Best-effort: if it fails, still connect
    // — the runtime auto-registers one itself when call_id is absent.
    let callId: string | undefined;
    try {
      const call = await createWebCall({ agent_id: agentId });
      callId = call.call_id;
    } catch (err) {
      console.warn("Couldn't pre-register web call, connecting without call_id", err);
    }

    const ctx = new AudioContext({ latencyHint: "interactive", sampleRate: SAMPLE_RATE });
    audioContextRef.current = ctx;
    await ctx.audioWorklet.addModule("/stream-processor-worklet.js");
    const worklet = new AudioWorkletNode(ctx, "stream-processor");
    const gain = ctx.createGain();
    worklet.connect(gain);
    gain.connect(ctx.destination);
    workletRef.current = worklet;
    gainNodeRef.current = gain;

    // Analyser taps — connected off the graph, not into it, so metering
    // volume can never affect what's actually played or sent.
    const outputAnalyser = ctx.createAnalyser();
    outputAnalyser.fftSize = 256;
    gain.connect(outputAnalyser);
    outputAnalyserRef.current = outputAnalyser;

    const outputBuffer = new Uint8Array(outputAnalyser.frequencyBinCount);
    const inputBuffer = new Uint8Array(outputAnalyser.frequencyBinCount); // input analyser uses the same fftSize
    meterIntervalRef.current = window.setInterval(() => {
      const out = outputAnalyserRef.current;
      setOutputVolume(out ? levelFromAnalyser(out, outputBuffer) : 0);
      const inp = inputAnalyserRef.current;
      setInputVolume(inp ? levelFromAnalyser(inp, inputBuffer) : 0);
    }, 80);

    const ws = new WebSocket(getBrowserWsUrl(orgId, agentId, callId));
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = async () => {
      setIsConnected(true);
      setStatus("Connected");
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            sampleRate: SAMPLE_RATE,
            channelCount: NUM_CHANNELS,
            echoCancellation: true,
            noiseSuppression: true,
          },
        });
        micStreamRef.current = stream;
        const source = ctx.createMediaStreamSource(stream);
        const processor = ctx.createScriptProcessor(512, 1, 1);
        source.connect(processor);
        processor.connect(ctx.destination);
        sourceRef.current = source;
        processorRef.current = processor;

        const inputAnalyser = ctx.createAnalyser();
        inputAnalyser.fftSize = 256;
        source.connect(inputAnalyser);
        inputAnalyserRef.current = inputAnalyser;

        processor.onaudioprocess = (event) => {
          if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
          if (isMutedRef.current) {
            setIsSpeaking(false);
            return;
          }
          const pcm = convertFloat32ToS16PCM(event.inputBuffer.getChannelData(0));
          const frame = frameTypeRef.current!.create({
            audio: {
              audio: Array.from(new Uint8Array(pcm.buffer)),
              sampleRate: SAMPLE_RATE,
              numChannels: NUM_CHANNELS,
            },
          });
          wsRef.current.send(new Uint8Array(frameTypeRef.current!.encode(frame).finish()));
          setIsSpeaking(true);
        };
      } catch {
        setStatus("Microphone access denied");
      }
    };

    ws.onmessage = (event) => {
      if (!frameTypeRef.current) return;
      try {
        const parsed = frameTypeRef.current.decode(
          new Uint8Array(event.data as ArrayBuffer),
        ) as unknown as DecodedFrame;
        if (parsed.audio) handleAudioFrame(parsed);
        else handleServerFrame(parsed);
      } catch {
        /* ignore decode errors */
      }
    };

    ws.onclose = () => stopAudio(false);
    ws.onerror = () => {
      setStatus("Connection error");
      stopAudio(false);
    };
  }, [orgId, agentId, handleAudioFrame, handleServerFrame, stopAudio]);

  const disconnect = useCallback(() => {
    commitUserTurn();
    commitAssistantTurn();
    stopAudio(true);
  }, [stopAudio, commitUserTurn, commitAssistantTurn]);

  useEffect(() => {
    return () => {
      stopAudio(true);
    };
  }, [stopAudio]);

  const toggleSpeakerMute = useCallback(() => {
    setIsSpeakerMuted((muted) => {
      const next = !muted;
      if (gainNodeRef.current) gainNodeRef.current.gain.value = next ? 0 : 1;
      return next;
    });
  }, []);

  return {
    status,
    isMuted,
    isSpeakerMuted,
    isConnected,
    isSpeaking,
    isPlaying,
    inputVolume,
    outputVolume,
    transcriptHistory,
    liveAssistantText,
    liveUserText,
    connect,
    disconnect,
    toggleMute: () => setIsMuted((m) => !m),
    toggleSpeakerMute,
  };
}
