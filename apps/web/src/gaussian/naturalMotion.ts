import type { MotionFrame } from './types'
import { CausalProsody } from './prosody'
const clamp=(v:number,a=0,b=1)=>Math.max(a,Math.min(b,v))
const smooth=(v:number)=>{v=clamp(v);return v*v*(3-2*v)}
const noise=(t:number,seed:number)=>{
  const hash=(n:number)=>{const x=Math.sin(n*127.1+seed*311.7)*43758.5453;return (x-Math.floor(x))*2-1}
  const n=Math.floor(t);return hash(n)+(hash(n+1)-hash(n))*smooth(t-n)
}
const faceChannel=/^(brow|cheek|noseSneer|eyeSquint|eyeWide|mouthSmile|mouthFrown|mouthDimple)/
const follow=(current:number,target:number,dt:number,tau:number)=>current+(target-current)*(1-Math.exp(-dt/tau))

/** SOBIA-derived layered dynamics: audible prosody -> accents/boundaries ->
 * distinct face groups + head gestures. A2F retains articulation ownership.
 * Procedural motion is explicitly logged; it is not measured human motion. */
export class NaturalMotion {
  private last:number|null=null
  private head={pitch:0,yaw:0,roll:0}
  private gaze={x:0,y:0}
  private affect:Record<string,number>={}
  private rawMean:Record<string,number>={}
  private rawTurn=''
  private activation=0
  private nextBlink=2.3
  private blinkAt=-10
  private blinkIndex=0
  private accentAt=-10
  private accentStrength=0
  private gestureIndex=0
  private prosody=new CausalProsody()
  apply(frame:MotionFrame,now:number,speaking:boolean,enabled=true,vitality=1):MotionFrame {
    if (!enabled || vitality<=0) {this.last=now;return frame}
    const dt=this.last===null?1/60:clamp(now-this.last,0,.05);this.last=now
    const gain=clamp(vitality,0,1.5)
    this.activation=follow(this.activation,Number(speaking),dt,.3)
    if(speaking && frame.turn_id!==this.rawTurn){this.rawTurn=frame.turn_id;this.rawMean={}}
    const p=this.prosody.update(frame.speech_energy??0,speaking,dt,frame.turn_id)
    if(p.triggered){this.accentAt=now;this.accentStrength=p.accent;this.gestureIndex++}
    const phase=(now-this.accentAt)/.72
    const beat=phase>=0&&phase<1?Math.sin(Math.PI*phase)**2*this.accentStrength:0
    const activity=this.activation*(.35+.65*p.energy)
    const emotion=frame.behavior?.emotion??'neutral'
    const negative=['sad','angry','fear','disgust'].includes(emotion)
    const wide=['fear','surprise'].includes(emotion)
    const focus=['angry','disgust'].includes(emotion)
    const direction=noise(this.gestureIndex,44)
    // Gaze shifts lead slower head orientation, rather than a common sine wave.
    const gx=.25*noise(now*.63,12),gy=.13*noise(now*.49,13)
    this.gaze.x=follow(this.gaze.x,gx,dt,.12);this.gaze.y=follow(this.gaze.y,gy,dt,.17)
    const target={
      pitch:gain*(1.05*noise(now*.23,1)+activity*1.5*noise(now*.61,2)+beat*3.6*(emotion==='sad'?.65:1)),
      yaw:gain*(1.4*noise(now*.18,3)+activity*3.8*noise(now*.43,4)+beat*1.8*direction+this.gaze.x*2),
      roll:gain*(.6*noise(now*.21,5)+activity*1.5*noise(now*.36,6)+beat*.65*direction),
    }
    for(const axis of ['pitch','yaw','roll'] as const) {
      const step=(target[axis]-this.head[axis])*(1-Math.exp(-dt/(speaking?.22:.65)))
      this.head[axis]+=clamp(step,-(speaking?14:3)*dt,(speaking?14:3)*dt)
    }
    if(now>=this.nextBlink){this.blinkAt=now;this.blinkIndex++;this.nextBlink=now+2.7+1.8*(noise(this.blinkIndex,17)+1)/2}
    const blinkPhase=(now-this.blinkAt)/.38
    const blink=blinkPhase>=0&&blinkPhase<1?Math.sin(Math.PI*blinkPhase)**2:0
    const weights={...frame.weights}
    const envelopes={
      brow:clamp(.86+.18*noise(now*.56,23)+.28*p.accent-.10*p.boundary,.68,1.12),
      eye:clamp(.91+.13*noise(now*.74,24)+.16*beat-.08*p.boundary,.72,1.1),
      cheek:clamp(.87+.17*noise(now*.48,25)+.22*p.energy-.12*p.boundary,.68,1.1),
      mouth:clamp(.88+.16*noise(now*.4,26)+.25*beat-.10*p.boundary,.70,1.12),
    }
    let rawResidualPeak=0
    for(const name of new Set([...Object.keys(weights),...Object.keys(this.affect)])) if(faceChannel.test(name)) {
      const group=name.startsWith('brow')?'brow':name.startsWith('eye')?'eye':name.startsWith('mouth')?'mouth':'cheek'
      const base=weights[name]??0
      const measured=frame.raw_weights?.[name]??0
      const mean=this.rawMean[name]??measured
      this.rawMean[name]=follow(mean,measured,dt,.65)
      // Preserve changing measured upper-face detail, not A2F's inferred mood.
      const allowRaw=!name.startsWith('mouth') && !(focus && /Up/.test(name)) && !(wide && /Squint/.test(name))
      const residual=speaking && allowRaw?clamp((measured-this.rawMean[name])*1.4,-.12,.12)*gain:0
      rawResidualPeak=Math.max(rawResidualPeak,Math.abs(residual))
      const goal=clamp(base*(1+(envelopes[group]-1)*gain)+residual)
      this.affect[name]=follow(this.affect[name]??goal,goal,dt,.13)
      weights[name]=this.affect[name]
    }
    const phasic=(.30*p.energy+.70*p.accent)*(1-.65*p.boundary)*this.activation
    const idlePulse=(.5+.5*noise(now*.36,51))**3*(1-this.activation*.75)
    const add=(name:string,value:number)=>{weights[name]=clamp((weights[name]??0)+value*gain)}
    add('browInnerUp',(focus?.015:.16)*phasic+(focus?0:.055)*idlePulse)
    for(const side of ['Left','Right']) {
      const asym=1+.16*noise(now*.57,side==='Left'?61:62)
      add('browOuterUp'+side,(focus?.01:emotion==='sad'?.025:.18)*phasic*asym+.035*idlePulse)
      add('browDown'+side,(focus?.13:.02)*phasic*asym)
      add('eyeSquint'+side,(wide?.012:.14)*phasic*asym+.025*idlePulse)
      add('eyeWide'+side,(wide?.12:focus?0:.045)*phasic*asym)
      add('cheekSquint'+side,(negative?.025:.15)*phasic*asym+.018*idlePulse)
      if(focus) add('noseSneer'+side,.10*phasic*asym)
      // Do not inject a smile in neutral/negative states. Modulate selected corners.
      const corner=negative?'mouthFrown'+side:'mouthSmile'+side
      if((frame.weights[corner]??0)>.01) add(corner,.12*beat*asym)
      if(!speaking){
        add('mouthPress'+side,.04*idlePulse*(1-(weights.jawOpen??0)))
        add('mouthShrugLower',.008*idlePulse)
      }
      // Wide and squint are antagonistic. Blink has final ownership of closure.
      weights['eyeSquint'+side]=(weights['eyeSquint'+side]??0)*(1-.8*(weights['eyeWide'+side]??0))
      if(negative) {weights['mouthSmile'+side]=0;weights['mouthDimple'+side]=0}
      // Lip rounding must remain visible at full emotional intensity.
      const rounding=speaking?Math.max(weights.mouthFunnel??0,weights.mouthPucker??0):0
      weights['mouthSmile'+side]=(weights['mouthSmile'+side]??0)*(1-.75*smooth((rounding-.25)/.65))
    }
    const gaze={x:clamp((frame.gaze?.x??0)+this.gaze.x*gain,-1,1),y:clamp((frame.gaze?.y??0)+this.gaze.y*gain,-1,1)}
    weights.eyeLookInLeft=weights.eyeLookOutRight=Math.max(0,gaze.x)*.55
    weights.eyeLookOutLeft=weights.eyeLookInRight=Math.max(0,-gaze.x)*.55
    for(const side of ['Left','Right']) {
      weights['eyeLookUp'+side]=Math.max(0,gaze.y)*.55;weights['eyeLookDown'+side]=Math.max(0,-gaze.y)*.55
      weights['eyeBlink'+side]=blink;weights['eyeWide'+side]=(weights['eyeWide'+side]??0)*(1-blink)
    }
    const head={pitch:clamp((frame.head?.pitch??0)+this.head.pitch,-10,10),yaw:clamp((frame.head?.yaw??0)+this.head.yaw,-12,12),roll:clamp((frame.head?.roll??0)+this.head.roll,-6,6)}
    return {...frame,weights,head,gaze,source:frame.source+'+sobia_causal_dynamics_v8',natural_motion:{
      speaking,energy:p.energy,head_offset:{...this.head},blink,version:'sobia-causal-v8',gain,emotion,
      accent:p.accent,boundary:p.boundary,accent_count:this.gestureIndex,face_envelopes:envelopes,raw_residual_peak:rawResidualPeak,
    }}
  }
}
