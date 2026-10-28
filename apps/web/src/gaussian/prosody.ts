const clamp = (v:number) => Math.max(0,Math.min(1,v))
const approach = (a:number,b:number,dt:number,tau:number) => a+(b-a)*(1-Math.exp(-dt/tau))

/** Playback-clock adaptation of SOBIA's CausalProsodyTracker.
 * Input is the server's normalized 20ms audio energy, not raw microphone RMS.
 * No text sentiment inference and no access to future audio samples. */
export class CausalProsody {
  private energy=0
  private baseline=0
  private accent=0
  private boundary=0
  private quiet=0
  private voiced=false
  private refractory=0
  private wasSpeaking=false
  private turn=''
  update(input:number,speaking:boolean,dt:number,turn:string) {
    if(speaking && turn!==this.turn) {
      this.turn=turn;this.energy=0;this.baseline=0;this.accent=0;this.boundary=0
      this.quiet=0;this.voiced=false;this.refractory=0
    }
    const raw=speaking && Number.isFinite(input)?clamp(input):0
    this.energy=approach(this.energy,raw,dt,raw>this.energy?.045:.145)
    this.baseline=approach(this.baseline,this.energy,dt,.65)
    this.refractory=Math.max(0,this.refractory-dt)
    const prominence=clamp((this.energy-this.baseline)*2.8)
    const triggered=speaking && raw>.12 && prominence>.22 && this.refractory===0
    this.accent*=Math.exp(-dt/.24)
    if(triggered){this.accent=Math.max(this.accent,.55+.45*prominence);this.refractory=.30}
    if(raw>.055){this.voiced=true;this.quiet=0}else this.quiet+=dt
    const boundaryTriggered=this.voiced && (this.quiet>=.18 || (!speaking && this.wasSpeaking))
    this.boundary*=Math.exp(-dt/.32)
    if(boundaryTriggered){this.boundary=1;this.voiced=false}
    this.wasSpeaking=speaking
    return {energy:this.energy,accent:this.accent,boundary:this.boundary,triggered,boundaryTriggered,prominence}
  }
}
