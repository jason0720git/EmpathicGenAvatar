import type { MotionFrame } from './types'

const clamp = (value: number, low: number, high: number) => Math.max(low, Math.min(high, value))
export function sanitizeWeights(weights: Record<string, number>): Record<string, number> {
  return Object.fromEntries(Object.entries(weights).map(([name, value]) =>
    [name.charAt(0).toLowerCase() + name.slice(1), Number.isFinite(value) ? clamp(value, 0, 1) : 0]))
}

/** Frame times are relative to the audible turn, never websocket arrival times. */
export class MotionTimeline {
  private turns = new Map<string, MotionFrame[]>()
  private cancelled = new Set<string>()
  private received = 0
  add(frame: MotionFrame) {
    if (this.cancelled.has(frame.turn_id) || !Number.isFinite(frame.pts_ms)) return
    const frames = this.turns.get(frame.turn_id) ?? []
    const outOfOrder = frames.length > 0 && frames[frames.length - 1].pts_ms > frame.pts_ms
    frames.push({ ...frame, weights: sanitizeWeights(frame.weights) })
    if (outOfOrder) frames.sort((a, b) => a.pts_ms - b.pts_ms)
    this.received++
    // Retain a bounded rolling history while a long response is playing.
    if (frames.length > 5400) frames.splice(0, frames.length - 5400)
    this.turns.set(frame.turn_id, frames)
  }
  sample(turn: string, atMs: number): MotionFrame | null {
    const frames = this.turns.get(turn)
    if (!frames?.length || atMs < 0 || atMs < frames[0].pts_ms) return null
    let index = frames.findIndex(frame => frame.pts_ms > atMs)
    if (index < 0) index = frames.length
    const a = frames[index - 1]
    const b = frames[index]
    // Missing animation does not leave a speaking mouth stuck open.
    if (!b && atMs - a.pts_ms > 300) return null
    if (!b) return a
    const mix = clamp((atMs - a.pts_ms) / Math.max(1, b.pts_ms - a.pts_ms), 0, 1)
    const lerp = (left: number, right: number) => left + (right - left) * mix
    const names = new Set([...Object.keys(a.weights), ...Object.keys(b.weights)])
    return { ...a, pts_ms: atMs, speech_energy: lerp(a.speech_energy ?? 0,b.speech_energy ?? 0),
      raw_weights: a.raw_weights && b.raw_weights ? Object.fromEntries(Object.keys(a.raw_weights).map(name=>[name,lerp(a.raw_weights![name]??0,b.raw_weights![name]??0)])) : a.raw_weights,
      weights: Object.fromEntries([...names].map(name => [name, lerp(a.weights[name] ?? 0, b.weights[name] ?? 0)])),
      head: a.head && b.head ? { pitch: lerp(a.head.pitch, b.head.pitch), yaw: lerp(a.head.yaw, b.head.yaw), roll: lerp(a.head.roll, b.head.roll) } : a.head,
      gaze: a.gaze && b.gaze ? { x: lerp(a.gaze.x, b.gaze.x), y: lerp(a.gaze.y, b.gaze.y) } : a.gaze,
    }
  }
  cancel(turn: string) {
    this.cancelled.add(turn); this.turns.delete(turn)
    if (this.cancelled.size > 128) this.cancelled.delete(this.cancelled.values().next().value!)
  }
  clear() { this.turns.clear(); this.cancelled.clear(); this.received = 0 }
  get count() { return this.received }
}

export function decodePcm16(base64: string): Float32Array {
  const bytes = Uint8Array.from(atob(base64), character => character.charCodeAt(0))
  const view = new DataView(bytes.buffer)
  return Float32Array.from({ length: Math.floor(bytes.length / 2) }, (_, index) => view.getInt16(index * 2, true) / 32768)
}

/** Server generation-done and browser playback-done are deliberately separate. */
export class PlaybackCompletion {
  private generated = new Map<string, number>()
  private reported = new Set<string>()
  mark(turn: string, durationMs: number) {
    if (!this.reported.has(turn)) this.generated.set(turn, durationMs)
  }
  poll(clock: { turn: string; ms: number; queuedMs: number }): string | null {
    const duration = this.generated.get(clock.turn)
    if (duration === undefined || clock.ms < duration || clock.queuedMs > 0) return null
    this.generated.delete(clock.turn); this.reported.add(clock.turn)
    if (this.reported.size > 128) this.reported.delete(this.reported.values().next().value!)
    return clock.turn
  }
  cancel(turn: string) { this.generated.delete(turn); this.reported.add(turn) }
  clear() { this.generated.clear(); this.reported.clear() }
}

/** One clock owns sound and facial motion. stop() invalidates cancelled packets. */
export class AudioPlayout {
  context: AudioContext | null = null
  private starts = new Map<string, number>()
  private ends = new Map<string, number>()
  private sources = new Map<AudioBufferSourceNode, string>()
  private cancelled = new Set<string>()
  private seen = new Set<string>()
  private active = ''
  private awaiting = new Map<string, Array<[string, number, number, string, number]>>()
  private animationReady = new Set<string>()
  private startupTimers = new Map<string, ReturnType<typeof setTimeout>>()
  underruns = 0
  chunks = 0
  syncTimeouts = 0
  async prepare() {
    this.context ??= new AudioContext({ sampleRate: 24000, latencyHint: 'interactive' })
    await this.context.resume()
  }
  enqueue(turn: string, sequence: number, ptsMs: number, base64: string, sampleRate: number) {
    if (!this.context || this.cancelled.has(turn) || this.seen.has(`${turn}:${sequence}`)) return
    if (!this.animationReady.has(turn)) {
      const pending = this.awaiting.get(turn) ?? []
      pending.push([turn, sequence, ptsMs, base64, sampleRate])
      this.awaiting.set(turn, pending)
      if (!this.startupTimers.has(turn)) this.startupTimers.set(turn, setTimeout(() => {
        this.syncTimeouts++; this.markAnimationReady(turn)
      }, 1800))
      return
    }
    this.seen.add(`${turn}:${sequence}`)
    const samples = decodePcm16(base64)
    if (!samples.length) return
    const now = this.context.currentTime
    if (!this.starts.has(turn)) this.starts.set(turn, Math.max(now + 0.2, ...this.ends.values(), 0) - ptsMs / 1000)
    let when = this.starts.get(turn)! + ptsMs / 1000
    if (when < now + 0.008) {
      // Rebase future animation to the delayed audio after a network underrun.
      const delay = now + 0.04 - when
      this.starts.set(turn, this.starts.get(turn)! + delay)
      when += delay
      this.underruns++
    }
    const buffer = this.context.createBuffer(1, samples.length, sampleRate)
    buffer.copyToChannel(new Float32Array(samples), 0)
    const source = this.context.createBufferSource()
    source.buffer = buffer
    source.connect(this.context.destination)
    this.sources.set(source, turn)
    source.onended = () => { this.sources.delete(source); source.disconnect() }
    this.ends.set(turn, when + buffer.duration)
    this.active = turn
    this.chunks++
    source.start(when)
  }
  markAnimationReady(turn: string) {
    if (this.cancelled.has(turn)) return
    clearTimeout(this.startupTimers.get(turn)); this.startupTimers.delete(turn)
    this.animationReady.add(turn)
    const pending = this.awaiting.get(turn) ?? []
    this.awaiting.delete(turn)
    pending.sort((a, b) => a[2] - b[2]).forEach(args => this.enqueue(...args))
  }
  clock(): { turn: string; ms: number; queuedMs: number; speaking: boolean } {
    const now = this.context?.currentTime ?? 0
    const start = this.starts.get(this.active) ?? now
    const end = this.ends.get(this.active) ?? now
    return { turn: this.active, ms: (now - start) * 1000,
      queuedMs: Math.max(0, (end - now) * 1000), speaking: now >= start && now < end }
  }
  stop(turn?: string) {
    for (const id of this.awaiting.keys()) if (!turn || turn === id) {
      this.cancelled.add(id); this.awaiting.delete(id); clearTimeout(this.startupTimers.get(id)); this.startupTimers.delete(id)
    }
    for (const [source, id] of this.sources) {
      if (!turn || turn === id) { try { source.stop() } catch { /* already ended */ }; this.sources.delete(source); this.cancelled.add(id) }
    }
    if (turn) { this.cancelled.add(turn); this.ends.delete(turn) }
    else { for (const id of this.starts.keys()) this.cancelled.add(id); this.ends.clear(); this.active = '' }
  }
  finish(turn: string) {
    this.stop(turn); this.starts.delete(turn); this.ends.delete(turn); this.animationReady.delete(turn)
    for (const key of this.seen) if (key.startsWith(`${turn}:`)) this.seen.delete(key)
    if (this.active === turn) this.active = ''
    if (this.cancelled.size > 128) this.cancelled.delete(this.cancelled.values().next().value!)
  }
  close() { this.stop(); void this.context?.close(); this.context = null; this.starts.clear(); this.seen.clear() }
}
