import type { WireEvent } from './types'

type Run = {
  avatar: string
  id: Promise<string>
  events: WireEvent[]
  expires: number
  flushing: boolean
  closed: boolean
  saved: number
  dropped: number
  sequence: number
}
export type PreviewStatus = {
  id?: string
  state: 'recording' | 'saved' | 'error'
  saved: number
  dropped: number
  error?: string
}

// Six seconds covers the full nod, recovery, and post-action rest.
const previewMs = 6000
const batchSize = 5
const maxPending = 64

/** Record direct control experiments without opening a microphone or audio socket. */
export class PreviewCapture {
  private run?: Run
  private latest?: Run

  constructor(
    private create: (avatar: string) => Promise<string>,
    private post: (id: string, events: WireEvent[]) => Promise<void>,
    private status: (status: PreviewStatus) => void,
  ) {}

  active() { return !!this.run }

  start(avatar: string, now: number, event: WireEvent) {
    if (this.run && (avatar !== this.run.avatar || now >= this.run.expires)) this.finish()
    if (!this.run) {
      const run: Run = {
        avatar, id: this.create(avatar), events: [], expires: 0, flushing: false,
        closed: false, saved: 0, dropped: 0, sequence: 0,
      }
      this.run = this.latest = run
      this.status({state: 'recording', saved: 0, dropped: 0})
      run.id.then(id => {
        if (this.latest === run) this.status({id, state: 'recording', saved: 0, dropped: 0})
      }).catch(error => {
        if (this.run === run) this.run = undefined
        if (this.latest === run) {
          this.status({state: 'error', saved: 0, dropped: run.dropped + run.events.length, error: String(error)})
        }
      })
    }
    this.run.expires = now + previewMs
    this.add(event)
  }

  add(event: WireEvent) {
    const run = this.run
    if (!run) return
    // Preserve control decisions in preference to frame samples during congestion.
    if (run.events.length >= maxPending) {
      const sample = run.events.findIndex(item => item.event === 'motion.sample')
      if (sample === -1 && event.event === 'motion.sample') { run.dropped++; return }
      run.events.splice(Math.max(0, sample), 1)
      run.dropped++
    }
    run.events.push({...event, preview_seq: ++run.sequence})
  }

  tick(now: number) {
    const run = this.run
    if (!run) return
    if (now >= run.expires) this.finish()
    else if (run.events.length >= batchSize) void this.flush(run)
  }

  finish() {
    const run = this.run
    if (!run) return
    this.run = undefined
    run.closed = true
    void this.flush(run)
  }

  private async flush(run: Run) {
    if (run.flushing) return
    run.flushing = true
    try {
      const id = await run.id
      while (run.events.length) {
        const batch = run.events.splice(0, batchSize)
        try {
          await this.post(id, batch)
          run.saved += batch.length
        } catch (error) {
          run.dropped += batch.length + run.events.length
          run.events = []
          if (this.run === run) this.run = undefined
          if (this.latest === run) {
            this.status({id, state: 'error', saved: run.saved, dropped: run.dropped, error: String(error)})
          }
          return
        }
        if (!run.closed) break
      }
      if (this.latest === run) {
        this.status({id, state: run.closed ? 'saved' : 'recording', saved: run.saved, dropped: run.dropped})
      }
    } catch {
      // start() reports session creation failures together with buffered events.
    } finally {
      run.flushing = false
    }
  }
}
