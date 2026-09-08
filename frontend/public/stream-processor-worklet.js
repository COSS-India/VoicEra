// AudioWorklet processor for streaming audio playback
class StreamProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.hasStarted = false;
    this.hasInterrupted = false;
    this.outputBuffers = [];
    this.bufferLength = 128;
    this.write = { buffer: new Float32Array(this.bufferLength), trackId: null };
    this.writeOffset = 0;
    this.trackSampleOffsets = {};

    this.port.onmessage = (event) => {
      if (!event.data) return;
      const payload = event.data;
      if (payload.event === "write-float32") {
        this.writeData(payload.buffer, payload.trackId);
      } else if (payload.event === "offset" || payload.event === "interrupt") {
        const requestId = payload.requestId;
        const trackId = this.write.trackId;
        const offset = this.trackSampleOffsets[trackId] || 0;
        this.port.postMessage({ event: "offset", requestId, trackId, offset });
        if (payload.event === "interrupt") this.hasInterrupted = true;
      } else if (payload.event === "clear") {
        this.outputBuffers = [];
        this.write = { buffer: new Float32Array(this.bufferLength), trackId: null };
        this.writeOffset = 0;
        this.hasStarted = false;
        this.hasInterrupted = false;
      }
    };
  }

  writeData(float32Array, trackId = null) {
    let { buffer } = this.write;
    let offset = this.writeOffset;
    for (let i = 0; i < float32Array.length; i++) {
      buffer[offset++] = float32Array[i];
      if (offset >= buffer.length) {
        this.outputBuffers.push({ buffer: new Float32Array(buffer), trackId });
        this.write = { buffer: new Float32Array(this.bufferLength), trackId };
        buffer = this.write.buffer;
        offset = 0;
      }
    }
    this.writeOffset = offset;
    return true;
  }

  process(_inputs, outputs) {
    const outputChannelData = outputs[0][0];
    if (this.hasInterrupted) {
      this.port.postMessage({ event: "stop" });
      return false;
    }
    if (this.outputBuffers.length) {
      if (!this.hasStarted) this.hasStarted = true;
      const { buffer, trackId } = this.outputBuffers.shift();
      const samplesToCopy = Math.min(outputChannelData.length, buffer.length);
      for (let i = 0; i < samplesToCopy; i++) outputChannelData[i] = buffer[i];
      for (let i = samplesToCopy; i < outputChannelData.length; i++) outputChannelData[i] = 0;
      if (trackId) {
        this.trackSampleOffsets[trackId] = (this.trackSampleOffsets[trackId] || 0) + samplesToCopy;
      }
      return true;
    }
    for (let i = 0; i < outputChannelData.length; i++) outputChannelData[i] = 0;
    return true;
  }
}

registerProcessor("stream-processor", StreamProcessor);
