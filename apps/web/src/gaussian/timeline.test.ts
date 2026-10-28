// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AudioPlayout, decodePcm16, MotionTimeline, PlaybackCompletion, sanitizeWeights } from './timeline'

const pcm = btoa(String.fromCharCode(0, 0, 255, 127, 0, 128, 0, 64))

describe('audio-clock motion alignment', () => {
  it('interpolates by presentation timestamp even when frames arrive out of order', () => {
    const timeline = new MotionTimeline()
    timeline.add({ turn_id: 'reply', pts_ms: 100, weights: { JawOpen: 1 }, head: { pitch: 10, yaw: 8, roll: 0 } })
    timeline.add({ turn_id: 'reply', pts_ms: 0, weights: { jawOpen: 0 }, head: { pitch: 0, yaw: 0, roll: 0 } })
    expect(timeline.sample('reply', -1)).toBeNull()
    expect(timeline.sample('reply', 25)?.weights.jawOpen).toBe(.25)
    expect(timeline.sample('reply', 25)?.head?.pitch).toBe(2.5)
  })
  it('interpolates measured upper-face coefficients for continuous residual motion', () => {
    const timeline = new MotionTimeline()
    timeline.add({ turn_id: 'raw', pts_ms: 0, weights: {}, raw_weights: { browInnerUp: .1 } })
    timeline.add({ turn_id: 'raw', pts_ms: 100, weights: {}, raw_weights: { browInnerUp: .5 } })
    expect(timeline.sample('raw', 50)?.raw_weights?.browInnerUp).toBeCloseTo(.3)
  })
  it('does not replace audible response motion with a newer idle frame', () => {
    const timeline = new MotionTimeline()
    timeline.add({ turn_id: 'reply', pts_ms: 0, weights: { jawOpen: .6 } })
    timeline.add({ turn_id: 'idle', pts_ms: 10, weights: { jawOpen: 0 } })
    expect(timeline.sample('reply', 50)?.weights.jawOpen).toBe(.6)
    expect(timeline.sample('reply', 301)).toBeNull()
  })
  it('drops cancelled epochs including late packets and leaves the next turn usable', () => {
    const timeline = new MotionTimeline()
    timeline.cancel('old')
    timeline.add({ turn_id: 'old', pts_ms: 0, weights: { jawOpen: 1 } })
    timeline.add({ turn_id: 'new', pts_ms: 0, weights: { jawOpen: .2 } })
    expect(timeline.sample('old', 0)).toBeNull()
    expect(timeline.sample('new', 0)?.weights.jawOpen).toBe(.2)
  })
  it('rejects nonfinite coefficients and clamps actual ARKit range', () => {
    expect(sanitizeWeights({ JawOpen: 2, BrowInnerUp: -1, EyeBlinkLeft: NaN })).toEqual({ jawOpen: 1, browInnerUp: 0, eyeBlinkLeft: 0 })
    expect([...decodePcm16(pcm)]).toEqual([0, 32767/32768, -1, .5])
  })
})

describe('completed generation versus completed playback', () => {
  it('reports completion exactly once only after the audio clock drains', () => {
    const completion = new PlaybackCompletion()
    expect(completion.poll({ turn: 'a', ms: 5000, queuedMs: 0 })).toBeNull()
    completion.mark('a', 1000)
    expect(completion.poll({ turn: 'a', ms: 0, queuedMs: 1000 })).toBeNull()
    expect(completion.poll({ turn: 'a', ms: 1000, queuedMs: 20 })).toBeNull()
    expect(completion.poll({ turn: 'a', ms: 1000, queuedMs: 0 })).toBe('a')
    completion.mark('a', 1000) // duplicate server packet
    expect(completion.poll({ turn: 'a', ms: 1100, queuedMs: 0 })).toBeNull()
  })
  it('never commits unheard cancelled speech into completed conversation history', () => {
    const completion = new PlaybackCompletion()
    completion.mark('old', 1000); completion.cancel('old'); completion.mark('old', 1000)
    expect(completion.poll({ turn: 'old', ms: 5000, queuedMs: 0 })).toBeNull()
    completion.mark('new', 1000)
    expect(completion.poll({ turn: 'new', ms: 1000, queuedMs: 0 })).toBe('new')
  })
})

class FakeSource {
  buffer: { duration: number } | null = null
  start = vi.fn(); stop = vi.fn(); connect = vi.fn(); disconnect = vi.fn()
  onended: (() => void) | null = null
}
class FakeAudioContext {
  currentTime = 0
  destination = {}
  sources: FakeSource[] = []
  resume = vi.fn(async () => {})
  close = vi.fn(async () => {})
  createBuffer(_channels: number, length: number, sampleRate: number) {
    return { duration: length / sampleRate, copyToChannel: vi.fn() }
  }
  createBufferSource() { const source = new FakeSource(); this.sources.push(source); return source }
}

describe('real PCM playout scheduling', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal('AudioContext', FakeAudioContext) })
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
  it('waits for animation then starts sound and its clock from a 200ms buffer', async () => {
    const audio = new AudioPlayout(); await audio.prepare()
    const context = audio.context as unknown as FakeAudioContext
    audio.enqueue('a', 0, 0, pcm, 24000)
    expect(context.sources).toHaveLength(0)
    audio.markAnimationReady('a')
    expect(context.sources[0].start).toHaveBeenCalledWith(.2)
    expect(audio.clock().ms).toBe(-200)
    context.currentTime = .2
    expect(audio.clock().ms).toBe(0)
    audio.enqueue('a', 0, 0, pcm, 24000)
    expect(context.sources).toHaveLength(1)
    audio.close()
  })
  it('cancels both pending and scheduled buffers and ignores old network chunks', async () => {
    const audio = new AudioPlayout(); await audio.prepare()
    const context = audio.context as unknown as FakeAudioContext
    audio.enqueue('old', 0, 0, pcm, 24000); audio.stop()
    audio.markAnimationReady('old'); audio.enqueue('old', 1, 100, pcm, 24000)
    vi.advanceTimersByTime(2000)
    expect(context.sources).toHaveLength(0)
    audio.markAnimationReady('new'); audio.enqueue('new', 0, 0, pcm, 24000)
    audio.stop('new')
    expect(context.sources[0].stop).toHaveBeenCalledOnce()
    audio.close()
  })
  it('explicitly counts degraded synchronization after bounded animation wait', async () => {
    const audio = new AudioPlayout(); await audio.prepare()
    const context = audio.context as unknown as FakeAudioContext
    audio.enqueue('reply', 0, 0, pcm, 24000)
    vi.advanceTimersByTime(1799)
    expect(context.sources).toHaveLength(0)
    vi.advanceTimersByTime(1)
    expect(context.sources).toHaveLength(1)
    expect(audio.syncTimeouts).toBe(1)
    audio.close()
  })
})
