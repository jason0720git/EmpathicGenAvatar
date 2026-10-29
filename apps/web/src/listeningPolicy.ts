// Adapted from SOBIA NoddingPolicy/Settings: acoustic cues, not agreement inference.
export type ListeningCue = 'nod' | 'glance'
export class ListeningPolicy {
  private previous = -1
  private voiced = 0
  private silence = 0
  private elapsed = 0
  private lastNod = -Infinity
  private lastCue = -Infinity
  private pauseConsumed = false
  private glanced = false
  reset() { this.previous=-1; this.voiced=0; this.silence=0; this.elapsed=0; this.lastNod=-Infinity; this.lastCue=-Infinity; this.pauseConsumed=false; this.glanced=false }
  observe(now: number, rms: number): ListeningCue | null {
    if (!Number.isFinite(now) || !Number.isFinite(rms)) return null
    if (this.previous < 0) { this.previous=now; return null }
    const dt=now-this.previous; this.previous=now
    if (dt <= 0 || dt > .5) { this.reset(); this.previous=now; return null }
    this.elapsed+=dt
    const speaking=rms>=.018
    if(speaking){this.voiced+=dt;this.silence=0;this.pauseConsumed=false}else this.silence+=dt
    // Clips last at most three seconds. Never overlap or queue stale gestures.
    if(now-this.lastCue<3.2) return null
    const pause=!speaking&&!this.pauseConsumed&&this.voiced>=.65&&this.silence>=.35&&this.silence<=2
    const continuer=speaking&&this.voiced>=1.6&&(this.lastNod===-Infinity||now-this.lastNod>=6)
    if((pause||continuer)&&now-this.lastNod>=3.2){
      this.lastNod=this.lastCue=now; if(pause)this.pauseConsumed=true;return 'nod'
    }
    // One low-gain glance after sustained listening, only during voiced input.
    if(speaking&&!this.glanced&&this.voiced>=4&&this.elapsed>=5){
      this.glanced=true;this.lastCue=now;return 'glance'
    }
    return null
  }
}
