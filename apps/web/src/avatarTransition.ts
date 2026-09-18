import { drawFaceRegistration } from './faceTransitionMesh'
// Small, bounded 2D registration, not anatomical pose estimation or optical flow.
// Match upper-face luminance; avoid the speech-driven mouth. No network/models.
export const TRANSITION_MS = 480
export const MIX_MS = 160
// Only the existing silent lead is corrected. Do not damp native motion.
export const ENTRY_MIX_MS = 480
// Called after painting the current native speech frame. The last of 12
// silent-tail frames is fully idle, so hiding the speech canvas is continuous.
export function drawLiveExit(ctx:CanvasRenderingContext2D,idle:CanvasImageSource,ptsMs:number,startMs:number) {
  const alpha=ease((ptsMs-startMs)/440)
  if(alpha>0) {
    ctx.save();ctx.globalAlpha=alpha
    ctx.drawImage(idle,0,0,ctx.canvas.width,ctx.canvas.height);ctx.restore()
  }
  return alpha>=1
}
export function ease(value: number) {
  const t = Math.max(0, Math.min(1, value))
  return t*t*t*(10 + t*(-15 + 6*t))
}
export function estimateShift(a: Float32Array, b: Float32Array, w: number, h: number) {
  const score = (dx: number, dy: number) => {
    let error = 0, count = 0
    for (let y=Math.ceil(h*.2); y<h*.55; y+=2) for (let x=Math.ceil(w*.25); x<w*.75; x+=2) {
      const bx=x-dx, by=y-dy, ix=Math.floor(bx), iy=Math.floor(by)
      if(ix<0 || iy<0 || ix+1>=w || iy+1>=h) continue
      const fx=bx-ix, fy=by-iy
      const sample=b[iy*w+ix]*(1-fx)*(1-fy)+b[iy*w+ix+1]*fx*(1-fy)+b[(iy+1)*w+ix]*(1-fx)*fy+b[(iy+1)*w+ix+1]*fx*fy
      error+=Math.min(2500,(a[y*w+x]-sample)**2); count++
    }
    return error/Math.max(1,count)
  }
  let dx=0,dy=0,best=score(0,0)
  const initial=best
  for(let y=-3;y<=3;y++) for(let x=-3;x<=3;x++) {
    const error=score(x,y)
    if(error<best) { best=error; dx=x; dy=y }
  }
  const cx=dx,cy=dy
  for(let y=cy-.5;y<=cy+.5;y+=.25) for(let x=cx-.5;x<=cx+.5;x+=.25) {
    const error=score(x,y)
    if(error<best) { best=error; dx=x; dy=y }
  }
  // Facial expression/head roll is not camera motion. Never rotate or zoom
  // the portrait to match the face: doing so visibly tilts the background.
  // Poor matches (blinks, expression changes, missing frames) do not justify
  // shifting the whole portrait. Corrections stay below ~3.7% of image width.
  const accepted=initial>1 && best<initial*.9 && best<600 && Math.abs(dx)<=3.5 && Math.abs(dy)<=3.5
  return {dx:accepted?dx/w:0, dy:accepted?dy/h:0, angle:0, scale:1, improvement:initial>0?1-best/initial:0, accepted}
}
function sample(source: CanvasImageSource) {
  const canvas=document.createElement('canvas'); canvas.width=96; canvas.height=120
  const ctx=canvas.getContext('2d',{willReadFrequently:true})!
  ctx.drawImage(source,0,0,96,120)
  const rgba=ctx.getImageData(0,0,96,120).data
  const gray=new Float32Array(96*120)
  for(let i=0;i<gray.length;i++) gray[i]=rgba[i*4]*.299+rgba[i*4+1]*.587+rgba[i*4+2]*.114
  return gray
}
export type AvatarTransition = {from:HTMLCanvasElement; dx:number; dy:number; angle?:number; scale?:number; started:number; accepted:boolean; improvement:number; mixMs?:number; faceLocal?:boolean}
export function beginIdleEntryTransition(idle:HTMLCanvasElement,mediaStartMs:number,incoming?:CanvasImageSource):AvatarTransition {
  // Deliberately keep the live idle canvas, not a frozen screenshot. Its
  // decoder must not park until this blend completes. Never move the image.
  let shift={dx:0,dy:0,accepted:false,improvement:0}
  try {
    if(incoming) shift=estimateShift(sample(idle),sample(incoming),96,120)
  } catch { /* Unavailable frame: appearance-only fallback, no camera movement. */ }
  // Reject large pose mismatches rather than stretching a face to fit them.
  if(Math.abs(shift.dx)>.02 || Math.abs(shift.dy)>.02) shift={...shift,dx:0,dy:0,accepted:false}
  return {from:idle,...shift,angle:0,scale:1,started:mediaStartMs,mixMs:ENTRY_MIX_MS,faceLocal:true}
}
export function beginTransition(from:CanvasImageSource,to:CanvasImageSource,w:number,h:number,now:number,register=true):AvatarTransition|null {
  try {
    const snapshot=document.createElement('canvas'); snapshot.width=w; snapshot.height=h
    snapshot.getContext('2d')!.drawImage(from,0,0,w,h)
    return {from:snapshot,...(register ? estimateShift(sample(snapshot),sample(to),96,120) : {dx:0,dy:0,angle:0,scale:1,accepted:false,improvement:0}),started:now}
  } catch { return null } // unavailable idle/CORS/canvas: keep normal playback
}
export function drawTransition(ctx:CanvasRenderingContext2D,to:CanvasImageSource,transition:AvatarTransition|null,now:number) {
  const w=ctx.canvas.width,h=ctx.canvas.height
  ctx.drawImage(to,0,0,w,h)
  if(!transition) return
  const elapsed=Math.max(0,now-transition.started)
  const weight=1-ease(elapsed/TRANSITION_MS)
  if(weight<=0) return
  if(transition.faceLocal) {
    drawFaceRegistration(ctx,to,transition.dx,transition.dy,weight)
  } else if (transition.dx || transition.dy) {
    ctx.save()
    ctx.translate(transition.dx*w*weight,transition.dy*h*weight)
  // Ignore even legacy angle/scale values defensively. Only translation is
  // allowed on a full frame; anatomical pose must be handled by the renderer.
    ctx.drawImage(to,0,0,w,h)
    ctx.restore()
  }
  const mix=1-ease(elapsed/(transition.mixMs ?? MIX_MS))
  if(mix>0) {
    ctx.save(); ctx.globalAlpha=mix; ctx.drawImage(transition.from,0,0,w,h); ctx.restore()
  }
}
