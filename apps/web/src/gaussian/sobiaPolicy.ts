import { COMPANION_VERSION, CompanionFace, sampleCompanionFace } from './companionFace'
import type { MotionFrame } from './types'

type NodCue = 'short_pause' | 'speech_continuer' | 'spoken_receipt' | 'manual' | 'llm_plan'
type ActiveNod = {cue: NodCue; at: number; cycles: number; duration: number; degrees: number; sampled: boolean}
export type PolicyEvent = {event: string; details: Record<string,unknown>}

const minimumInterval = 2.2
const cycleGap = .06
export const minimumSemanticConfidence = .62

/** Single monotonic clock for microphone trigger, audible reply, and render sampling.
 * Ports SOBIA NoddingPolicy / EmpathicNodding; sampling writes local pitch only. */
export class SobiaPolicy {
  private events: PolicyEvent[] = []
  private face = new CompanionFace()
  private active: ActiveNod | null = null
  private lastGrant = -Infinity
  private grants = 0
  private alternating = 0
  private lastVoiceTime: number | null = null
  private lastVoicing: boolean | null = null
  private voiced = 0
  private pause = 0
  private sinceCandidate = 0
  private hadCandidate = false
  private pauseConsumed = false
  private lastPlanTurn: string | null = null
  private decision = ''
  private manualLabel: string | null = null
  private lowConfidenceTurn: string | null = null

  private emit(event: string, details: Record<string,unknown>) {
    if (this.events.length >= 128) this.events.shift()
    this.events.push({event,details})
  }
  drainEvents() { return this.events.splice(0) }

  endListeningTurn() {
    if (this.lastVoiceTime !== null) this.emit('listener_capture_end', {at_s:this.lastVoiceTime,voiced_s:this.voiced,pause_s:this.pause})
    this.voiced = this.pause = this.sinceCandidate = 0
    this.hadCandidate = this.pauseConsumed = false
    this.lastVoiceTime = this.lastVoicing = null
  }

  observeVoice(now: number, seconds: number, voicing: boolean) {
    if (!Number.isFinite(now) || !Number.isFinite(seconds) || seconds <= 0 || seconds > .25) {
      this.endListeningTurn()
      return
    }
    if (this.lastVoiceTime !== null && (now < this.lastVoiceTime || now-this.lastVoiceTime > .5)) this.endListeningTurn()
    this.lastVoiceTime = now
    if (this.lastVoicing !== voicing) {
      this.emit('listener_voice_state',{at_s:now,voiced:voicing,chunk_s:seconds})
      this.lastVoicing = voicing
    }
    this.sinceCandidate += seconds
    if (voicing) { this.voiced += seconds; this.pause=0; this.pauseConsumed=false }
    else this.pause += seconds
    let cue: NodCue | null = null
    if (!voicing && !this.pauseConsumed && this.voiced >= .65 && this.pause >= .35) {
      if (this.pause <= 2.0001) cue='short_pause'
      else this.pauseConsumed=true
    } else if (voicing && this.voiced >= 1.6 && (!this.hadCandidate || this.sinceCandidate >= 6)) cue='speech_continuer'
    // Unity reserves before publishing a microphone opportunity. A pause that
    // initially falls within the cooldown may still qualify before it expires.
    if (cue && now-this.lastGrant+.0001 >= minimumInterval && this.requestNod(now,cue)) {
      this.pauseConsumed = cue === 'short_pause'
      this.hadCandidate = true
      this.sinceCandidate = 0
    }
  }

  requestNod(now: number, cue: NodCue) {
    if (!Number.isFinite(now)) return false
    // Age and close a previous gesture even when render sampling was suspended.
    this.sampleNod(now, false)
    const reason = this.active ? 'head_busy' : now-this.lastGrant+.0001 < minimumInterval ? 'minimum_interval' : 'allow'
    this.emit('nod_gate',{at_s:now,cue,reason,voiced_s:this.voiced,pause_s:this.pause})
    if (reason !== 'allow') return false
    const single = cue === 'short_pause' || cue === 'manual'
    const cycles = single ? 1 : this.alternating++ % 2 === 0 ? 2 : 1
    const duration = cycles === 2 ? .4 : 1.1
    const degrees = cycles === 2 ? 5 : 15
    this.active = {cue,at:now,cycles,duration,degrees,sampled:false}
    this.lastGrant = now
    this.grants++
    this.emit('nod_requested',{at_s:now,grant:this.grants,cue,cycles,duration_s:duration,amplitude_deg:degrees})
    return true
  }

  private sampleNod(now: number, rendered: boolean) {
    const nod = this.active
    if (nod) {
      const elapsed = now-nod.at
      const cycle = Math.floor(elapsed/(nod.duration+cycleGap))
      const t = (elapsed-cycle*(nod.duration+cycleGap))/nod.duration
      if (elapsed >= 0 && elapsed < nod.duration*nod.cycles+cycleGap*(nod.cycles-1)) {
        if (rendered && !nod.sampled) {
          this.emit('nod_motion_start',{at_s:now,cue:nod.cue,grant:this.grants})
          nod.sampled=true
        }
        const ease = .5-.5*Math.cos(Math.PI*Math.min(1,t))
        const pitch = t > 1 ? 0 : Math.sin(Math.PI*ease)*nod.degrees*(cycle === 0 ? 1 : .82)
        return {nod_cue:nod.cue,nod_phase:t > 1 ? 'gap' : t < .5 ? 'down' : 'up',nod_cycles:nod.cycles,nod_pitch_deg:pitch}
      }
      this.emit(nod.sampled ? 'nod_motion_end' : 'nod_expired_unsampled',{at_s:now,cue:nod.cue,grant:this.grants})
      this.active=null
    }
    return {nod_cue:null,nod_phase:'idle',nod_cycles:0,nod_pitch_deg:0}
  }

  sample(frame: MotionFrame, now: number, speaking: boolean, automaticMotion: boolean, accent: number, boundary: number) {
    const input = frame.behavior
    const manual = frame.source?.includes('manual') || input?.source === 'manual_expression'
    const idle = frame.turn_id === 'idle' || frame.source === 'auto-preview'
    this.manualLabel = manual ? input?.emotion ?? 'neutral' : null
    if (manual || !automaticMotion) {this.face.current=null; this.lowConfidenceTurn=null; this.decision=''}
    else if (!idle && speaking) {
      if (this.face.current?.turn !== frame.turn_id) this.face.current=null
      if (this.lowConfidenceTurn !== frame.turn_id) this.lowConfidenceTurn=null
      if (input?.move && input.stance) {
        const accepted = input.confidence == null || input.confidence >= minimumSemanticConfidence
        const decision = [frame.turn_id,input.move,input.stance,accepted].join('/')
        if (decision !== this.decision) {
          this.emit('semantic_gate',{at_s:now,turn_id:frame.turn_id,move:input.move,stance:input.stance,
            confidence:input.confidence??null,reason:accepted?'allow':'low_confidence'})
          this.decision = decision
        }
        if (accepted) {
          this.lowConfidenceTurn=null
          if (this.face.start(frame.turn_id,input.move,input.stance,input.intensity??.5,now)) {
            const face = this.face.current!
            this.emit('expression_start',{at_s:now,turn_id:face.turn,state:face.state,seed:face.seed,
              move:face.move,stance:face.stance,intensity:face.intensity})
          }
        } else if (!this.face.current) this.lowConfidenceTurn=frame.turn_id
      }
      if (input?.nod && input.source==='llm_tool_call' && this.lastPlanTurn !== frame.turn_id
           && frame.pts_ms >= (input.nod_start_seconds??.45)*1000) {
        this.lastPlanTurn=frame.turn_id
        this.requestNod(now,'llm_plan')
      }
    }
    const face = this.face.current
    const suppressed = this.lowConfidenceTurn !== null && !face
    const nod = this.sampleNod(now,true)
    const diagnostics = {
      version:COMPANION_VERSION, state:face?.state ?? (suppressed ? 'LowConfidence' : manual ? 'ManualEmotion' : 'Baseline'),
      move:face?.move??null, stance:face?.stance??null, seed:face?.seed??null, age_s:face ? Math.max(0,now-face.started) : 0,
      emotion:this.manualLabel, ...nod, nod_grants:this.grants, voiced_s:this.voiced, pause_s:this.pause,
    }
    // A retained reaction settles to its authored resting value between turns.
    const weights = face ? sampleCompanionFace(face,now,speaking && !idle ? accent : 0,speaking && !idle ? boundary : 0) : suppressed ? {} : null
    return {diagnostics,weights}
  }
}

export type PolicyDiagnostics = ReturnType<SobiaPolicy['sample']>['diagnostics']
