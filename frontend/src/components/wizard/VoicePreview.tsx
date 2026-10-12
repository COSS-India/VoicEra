"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Play, Square } from "lucide-react";
import { Select } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Spinner";
import type { StackFieldsValue } from "@/components/wizard/AgentStackFields";
import type { WizardCatalogs } from "@/lib/use-wizard-catalogs";
import { buildModelConfigsFromCatalogs, languageLabel } from "@/lib/use-wizard-catalogs";
import { useVoicePreview } from "@/lib/use-voice-preview";
import { getPreviewLimits } from "@/lib/api-client";
import { stripPlaceholders } from "@/lib/voice-preview-text";

interface VoiceSelectProps {
  value: StackFieldsValue;
  catalogs: WizardCatalogs;
  voices: { id: string; name: string }[];
  onChange: (voice: string) => void;
  /** The agent's greeting, spoken by each play button (the server strips
   * {{placeholders}}). Omitted → a plain voice dropdown with no play buttons. */
  welcome?: string;
}

type PlayState = "idle" | "loading" | "playing";

/** The primary language, when the chosen model declares languages and it isn't one of them. */
function unsupportedLanguage(value: StackFieldsValue, catalogs: WizardCatalogs): string | null {
  const lang = value.langs[0];
  const declared = catalogs.ttsSettings?.capabilities?.[value.ttsModel]?.languages;
  if (!lang || !declared) return null;
  return lang in declared ? null : lang;
}

/** Why the play buttons are disabled, or null when they can run. Uses the
 * primary language — the one the agent opens the call in. `maxChars` comes from
 * the server (Infinity until it loads; the server still enforces it). */
function blockedReason(
  value: StackFieldsValue,
  catalogs: WizardCatalogs,
  welcome: string,
  maxChars: number,
): string | null {
  const lang = unsupportedLanguage(value, catalogs);
  if (lang) return `This model doesn't support ${languageLabel(catalogs.languages, lang)}.`;
  const spoken = stripPlaceholders(welcome).length;
  if (spoken === 0) return "Add a greeting on the Agent step to preview voices.";
  if (spoken > maxChars) {
    return `The greeting is over ${maxChars} characters; shorten it on the Agent step to preview.`;
  }
  return null;
}

/** The server's preview character limit; Infinity until loaded or if the fetch fails. */
function usePreviewMaxChars() {
  const [maxChars, setMaxChars] = useState(Number.POSITIVE_INFINITY);
  useEffect(() => {
    getPreviewLimits()
      .then((limits) => setMaxChars(limits.max_chars))
      .catch(() => {
        /* the server still enforces the limit with a 413 */
      });
  }, []);
  return maxChars;
}

/** Plays each new clip URL as it arrives; stops it when replaced or on unmount. */
function useClipPlayback(url: string | null) {
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    if (!url) return;
    const audio = new Audio(url);
    audioRef.current = audio;
    audio.onplay = () => setPlaying(true);
    audio.onended = () => setPlaying(false);
    audio.onpause = () => setPlaying(false);
    void audio.play().catch(() => setPlaying(false));
    return () => {
      audio.pause();
      audioRef.current = null;
    };
  }, [url]);

  const stop = useCallback(() => audioRef.current?.pause(), []);
  return { playing, stop };
}

const PLAY_VERBS: Record<PlayState, string> = { idle: "Play", loading: "Stop", playing: "Stop" };

const PLAY_ICONS: Record<Exclude<PlayState, "loading">, ReactNode> = {
  playing: <Square className="size-3" fill="currentColor" strokeWidth={0} />,
  idle: <Play className="ml-0.5 size-3.5" fill="currentColor" strokeWidth={0} />,
};

/** The selected voice's button is solid accent; the others are a pale tint that
 * fills on hover, so the current choice stands out in the list. */
const PLAY_TONES = [
  {
    className: "bg-v-pale text-v-accent hover:bg-v-accent hover:text-white",
    spinner: <Spinner light={false} />,
  },
  { className: "bg-v-accent text-white hover:bg-v-accent-deep", spinner: <Spinner /> },
]; // [unselected, selected], indexed by Number(selected)

function PlayButton({
  voice,
  state,
  selected,
  disabled,
  onToggle,
}: {
  voice: string;
  state: PlayState;
  selected: boolean;
  disabled: boolean;
  onToggle: (voice: string) => void;
}) {
  const label = `${PLAY_VERBS[state]} ${voice}`;
  const tone = PLAY_TONES[Number(selected)];
  const icons = { ...PLAY_ICONS, loading: tone.spinner };
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={() => onToggle(voice)}
      className={`flex size-7 cursor-pointer items-center justify-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${tone.className}`}
    >
      {icons[state]}
    </button>
  );
}

/** The preview request for `voice` in the primary language, or null when the
 * TTS config can't be built yet (no provider/model settings loaded). */
function previewRequest(value: StackFieldsValue, catalogs: WizardCatalogs, voice: string, text: string) {
  const language = value.langs[0] ?? "";
  const tts = buildModelConfigsFromCatalogs(catalogs, {
    ttsModel: value.ttsModel,
    voice,
    primaryLang: language,
    ttsExtra: value.ttsExtra,
  }).tts;
  return tts ? { tts_config: tts, language, text } : null;
}

function playStateOf(
  voice: string,
  activeVoice: string | null,
  loading: boolean,
  playing: boolean,
): PlayState {
  if (voice !== activeVoice) return "idle";
  if (loading) return "loading";
  return playing ? "playing" : "idle";
}

/** Why play is disabled, else the last error; announced to screen readers. */
function VoiceStatus({ blocked, error }: { blocked: string | null; error: string | null }) {
  const isError = !blocked && Boolean(error);
  return (
    <span aria-live="polite" className={`text-xs font-light ${isError ? "text-v-danger" : "text-v-muted"}`}>
      {blocked ?? error}
    </span>
  );
}

/** Voice dropdown with a play button before the selected voice and before every
 * option. Play speaks the greeting in that voice; it never changes the
 * selection. One clip at a time: a new play stops the previous one. */
export function VoiceSelect({ value, catalogs, voices, onChange, welcome }: VoiceSelectProps) {
  const preview = useVoicePreview();
  const [activeVoice, setActiveVoice] = useState<string | null>(null);
  const { playing, stop } = useClipPlayback(preview.audioUrl);
  const maxChars = usePreviewMaxChars();
  const blocked = welcome === undefined ? null : blockedReason(value, catalogs, welcome, maxChars);
  const { reset } = preview;
  const loading = preview.status === "loading";

  // A clip belongs to the model, extras and language it was made with; changing
  // any of them stops it and drops a request still in flight.
  const configKey = JSON.stringify([value.ttsModel, value.ttsExtra, value.langs[0]]);
  useEffect(() => {
    stop();
    reset();
  }, [configKey, stop, reset]);

  function toggle(voice: string) {
    // Second click on the active voice stops it — playing or still generating.
    if (playStateOf(voice, activeVoice, loading, playing) !== "idle") {
      stop();
      reset();
      return;
    }
    const request = previewRequest(value, catalogs, voice, welcome ?? "");
    if (!request) return;
    stop();
    setActiveVoice(voice);
    void preview.generate(request);
  }

  const renderLeading = (voice: string) =>
    voice ? (
      <PlayButton
        voice={voice}
        state={playStateOf(voice, activeVoice, loading, playing)}
        selected={voice === value.voice}
        disabled={Boolean(blocked)}
        onToggle={toggle}
      />
    ) : null;

  return (
    <>
      <Select
        value={value.voice}
        onChange={(e) => onChange(e.target.value)}
        renderLeading={welcome === undefined ? undefined : renderLeading}
      >
        <option value="">Select voice…</option>
        {voices.map((v) => (
          <option key={v.id} value={v.id}>
            {v.name}
          </option>
        ))}
      </Select>
      <VoiceStatus blocked={blocked} error={preview.status === "error" ? preview.error : null} />
    </>
  );
}
