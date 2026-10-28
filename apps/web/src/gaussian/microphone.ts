// Actual microphone PCM capture. AudioWorklet keeps capture independent of React/render load.
const WORKLET = `
class PcmCapture extends AudioWorkletProcessor {
  constructor() { super(); this.pending = []; this.accum = 0; this.count = 0; this.phase = 0; }
  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;
    for (let i = 0; i < input.length; i++) {
      this.accum += input[i]; this.count++; this.phase += 24000;
      if (this.phase >= sampleRate) {
        const value = Math.max(-1, Math.min(1, this.accum / this.count));
        this.pending.push(Math.round(value * (value < 0 ? 32768 : 32767)));
        this.accum = 0; this.count = 0; this.phase -= sampleRate;
      }
      if (this.pending.length >= 480) {
        const result = new Int16Array(this.pending); this.pending = [];
        this.port.postMessage(result.buffer, [result.buffer]);
      }
    }
    return true;
  }
}
registerProcessor('gaussian-pcm-capture', PcmCapture);
`
export class Microphone {
  private stream: MediaStream | null = null
  private context: AudioContext | null = null
  private node: AudioWorkletNode | null = null
  private source: MediaStreamAudioSourceNode | null = null
  private gate: GainNode | null = null
  async start(onPcm: (base64: string, rms: number) => void) {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: {
      channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true,
    } })
    try {
      this.context = new AudioContext({ sampleRate: 24000 })
      const url = URL.createObjectURL(new Blob([WORKLET], { type: 'text/javascript' }))
      try { await this.context.audioWorklet.addModule(url) } finally { URL.revokeObjectURL(url) }
      this.node = new AudioWorkletNode(this.context, 'gaussian-pcm-capture')
      this.node.port.onmessage = event => {
        const pcm = new Int16Array(event.data as ArrayBuffer)
        let sum = 0
        for (const value of pcm) sum += (value / 32768) ** 2
        const bytes = new Uint8Array(pcm.buffer)
        onPcm(btoa(String.fromCharCode(...bytes)), Math.sqrt(sum / pcm.length))
      }
      this.source = this.context.createMediaStreamSource(this.stream)
      this.gate = this.context.createGain(); this.gate.gain.value = 0
      this.source.connect(this.node); this.node.connect(this.gate); this.gate.connect(this.context.destination)
      await this.context.resume()
    } catch (error) { this.stop(); throw error }
  }
  stop() {
    if (this.node) this.node.port.onmessage = null
    this.node?.disconnect(); this.source?.disconnect(); this.gate?.disconnect()
    this.stream?.getTracks().forEach(track => track.stop())
    void this.context?.close()
    this.node = null; this.context = null; this.stream = null
  }
}
