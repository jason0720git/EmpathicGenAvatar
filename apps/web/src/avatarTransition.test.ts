import { expect, it, vi } from 'vitest'
import { beginIdleEntryTransition, beginTransition, ease, estimateShift, drawTransition, drawLiveExit, ENTRY_MIX_MS, MIX_MS, TRANSITION_MS } from './avatarTransition'
import { GeometryHandoff } from './geometryHandoff'

it('blends directly into live idle during the silent tail without a source portrait', () => {
  const idle=document.createElement('canvas')
  for (const t of [0,40,220,400,440,480]) {
    const h=new GeometryHandoff(),draw=vi.spyOn(h,'draw').mockImplementation(()=>{})
    const ctx={canvas:{width:96,height:120},drawImage:vi.fn(),save:vi.fn(),restore:vi.fn(),globalAlpha:1}
    expect(drawLiveExit(ctx as unknown as CanvasRenderingContext2D,idle,1000+t,1000,idle,h)).toBe(t>=440)
    if(t>0) {
      expect(draw).toHaveBeenCalledExactlyOnceWith(ctx,idle,idle,ease(t/440))
      expect(ctx.globalAlpha).toBe(1)
    } else expect(draw).not.toHaveBeenCalled()
  }
})

it('passes LIVE sources to a geometry-only handoff and finishes before speech', () => {
  const idle=document.createElement('canvas'),incoming=document.createElement('canvas')
  const transition=beginIdleEntryTransition(idle,1000)
  const draw=vi.spyOn(transition.geometry!,'draw').mockImplementation(()=>{})
  expect(transition.from).toBe(idle)
  for(const elapsed of [0,160,240,440,480,520]) {
    const ctx={canvas:{width:96,height:120},drawImage:vi.fn(),save:vi.fn(),restore:vi.fn(),translate:vi.fn(),rotate:vi.fn(),scale:vi.fn(),globalAlpha:1}
    drawTransition(ctx as unknown as CanvasRenderingContext2D,incoming,transition,1000+elapsed)
    expect(ctx.translate).not.toHaveBeenCalled()
    expect(ctx.rotate).not.toHaveBeenCalled()
    expect(ctx.scale).not.toHaveBeenCalled()
    expect(draw).toHaveBeenLastCalledWith(ctx,idle,incoming,ease(elapsed/ENTRY_MIX_MS))
    expect(ctx.globalAlpha).toBe(1)
  }
})

it('source-anchor fallback never estimates or applies an image displacement', () => {
  const drawImage=vi.fn(),getImageData=vi.fn(()=>{throw new Error('registration must not run')})
  const spy=vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage,getImageData} as unknown as CanvasRenderingContext2D)
  try {
    const source=document.createElement('canvas')
    expect(beginTransition(source,source,96,120,0,false)).toMatchObject({dx:0,dy:0,angle:0,scale:1,accepted:false})
    expect(getImageData).not.toHaveBeenCalled()
  } finally {spy.mockRestore()}
})

it('registers a shifted face-region texture in the correct direction', () => {
  const w=96,h=120,a=new Float32Array(w*h),b=new Float32Array(w*h)
  for(let y=0;y<h;y++) for(let x=0;x<w;x++) a[y*w+x]=(x*17+y*31+(x*y)%71)%256
  for(let y=1;y<h;y++) for(let x=2;x<w;x++) b[y*w+x]=a[(y-1)*w+x-2]
  const shift=estimateShift(a,b,w,h)
  expect(shift.accepted).toBe(true)
  expect(shift.dx*w).toBeCloseTo(-2)
  expect(shift.dy*h).toBeCloseTo(-1)
})
it('does not invent a correction for blank or identical frames', () => {
  const a=new Float32Array(96*120).fill(42)
  expect(estimateShift(a,a,96,120)).toMatchObject({dx:0,dy:0,accepted:false})
})
it('never converts a face roll/scale mismatch into full-frame rotation or zoom', () => {
  const w=96,h=120,a=new Float32Array(w*h),b=new Float32Array(w*h)
  const angle=2*Math.PI/180, scale=1.03
  const texture=(x:number,y:number)=>120+35*Math.sin(x*.27)+30*Math.cos(y*.34)+25*Math.sin(x*.13+y*.24)
  for(let y=0;y<h;y++) for(let x=0;x<w;x++) {
    a[y*w+x]=texture(x,y)
    const px=(x-w*.5)/scale,py=(y-h*.38)/scale
    b[y*w+x]=texture(Math.cos(angle)*px+Math.sin(angle)*py+w*.5,-Math.sin(angle)*px+Math.cos(angle)*py+h*.38)
  }
  const shift=estimateShift(a,b,w,h)
  expect(shift.angle).toBe(0)
  expect(shift.scale).toBe(1)
})
it('ignores legacy rotation/zoom throughout both transition directions', () => {
  const to={} as HTMLCanvasElement
  for (const sign of [-1,1]) for (const time of [0,80,160,240,479,480]) {
    const ctx={canvas:{width:100,height:120},drawImage:vi.fn(),save:vi.fn(),restore:vi.fn(),translate:vi.fn(),rotate:vi.fn(),scale:vi.fn(),globalAlpha:1}
    drawTransition(ctx as unknown as CanvasRenderingContext2D,to,{from:to,dx:sign*.01,dy:sign*.02,angle:sign*Math.PI/180,scale:1.015,started:0,accepted:true,improvement:.5},time)
    expect(ctx.rotate).not.toHaveBeenCalled()
    expect(ctx.scale).not.toHaveBeenCalled()
    if(time<TRANSITION_MS) expect(ctx.translate).toHaveBeenCalledExactlyOnceWith(sign*(1-ease(time/TRANSITION_MS)),sign*2.4*(1-ease(time/TRANSITION_MS)))
  }
})
it('uses zero-velocity endpoints and finishes mixing before motion correction', () => {
  expect(ease(0)).toBe(0); expect(ease(1)).toBe(1)
  expect(ease(.001)).toBeLessThan(.000001)
  expect(1-ease(.999)).toBeLessThan(.000001)
  expect(MIX_MS).toBeLessThan(TRANSITION_MS)
})
it('returns to the exact unshifted incoming frame after transition', () => {
  const calls:unknown[][]=[]
  const ctx={canvas:{width:100,height:120},drawImage:(...args:unknown[])=>calls.push(args)}
  const to={} as HTMLCanvasElement
  drawTransition(ctx as unknown as CanvasRenderingContext2D,to,{from:to,dx:.01,dy:.02,started:0,accepted:true,improvement:.5},TRANSITION_MS)
  expect(calls).toEqual([[to,0,0,100,120]])
})
