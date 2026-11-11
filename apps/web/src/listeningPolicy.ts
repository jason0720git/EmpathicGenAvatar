export const LISTENING_POLICY_VERSION = 'sobia-listening-20261111'
export type ListeningCue = 'nod' | 'double_nod' | 'glance'
export const cueVariants: Record<ListeningCue, number> = {nod: 3, double_nod: 5, glance: 4}
export const cueLabels: Record<ListeningCue, string> = {nod: '한 번 끄덕임', double_nod: '두 번 끄덕임', glance: '시선 이탈·복귀'}
export interface ListeningDecision {
  kind: ListeningCue
  trigger: 'short_pause' | 'speech_continuer' | 'sustained_listening'
  gate: 'allow' | 'head_busy'
  voiced_ms: number
  pause_ms: number
}

export class ListeningPolicy {
  private previous = -1
  private voiced = 0
  private silence = 0
  private elapsed = 0
  private lastReservation = -Infinity
  private lastTurnNod = -Infinity
  private alternating = 0
  private pauseConsumed = false
  private glanced = false

  // Keep minimum spacing and the single/double alternation across mic turns.
  reset() {
    this.previous = -1
    this.voiced = this.silence = this.elapsed = 0
    this.lastTurnNod = -Infinity
    this.pauseConsumed = this.glanced = false
  }

  observe(now: number, rms: number, busy = false): ListeningDecision | null {
    if (!Number.isFinite(now) || !Number.isFinite(rms)) return null
    const dt = now - this.previous
    if (this.previous < 0 || dt <= 0 || dt > .25) {
      this.reset()
      this.previous = now
      return null
    }
    this.previous = now
    this.elapsed += dt
    const speaking = rms >= .018
    if (speaking) {
      this.voiced += dt
      this.silence = 0
      this.pauseConsumed = false
    } else {
      this.silence += dt
    }
    if (now - this.lastReservation < 2.2) return null
    const pause = !speaking && !this.pauseConsumed && this.voiced >= .65 && this.silence >= .35 && this.silence <= 2
    const continuer = speaking && this.voiced >= 1.6 && now - this.lastTurnNod >= 6
    let kind: ListeningCue
    let trigger: ListeningDecision['trigger']
    if (pause || continuer) {
      this.lastTurnNod = now
      this.pauseConsumed = pause
      kind = continuer && this.alternating % 2 === 0 ? 'double_nod' : 'nod'
      trigger = pause ? 'short_pause' : 'speech_continuer'
      if (continuer && !busy) this.alternating++
    } else if (speaking && !this.glanced && this.voiced >= 4 && this.elapsed >= 5) {
      this.glanced = true
      kind = 'glance'
      trigger = 'sustained_listening'
    } else {
      return null
    }
    this.lastReservation = now
    return {kind, trigger, gate: busy ? 'head_busy' : 'allow',
      voiced_ms: Math.round(this.voiced * 1000), pause_ms: Math.round(this.silence * 1000)}
  }
}
