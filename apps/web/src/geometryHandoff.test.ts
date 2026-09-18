import {expect,it,vi} from 'vitest'
import {FLOW_W as W,FLOW_H as H,GRID_W,GRID_H,matchGeometry,boundFlow,smoothFlow,appearanceWeight,GeometryHandoff,HANDOFF_FRAGMENT} from './geometryHandoff'

it('does not hallucinate motion for identical or untextured inputs',()=>{
  const a=new Float32Array(W*H).fill(90)
  expect([...matchGeometry(a,a).xy].every(v=>v===0)).toBe(true)
  expect([...matchGeometry(a,new Float32Array(W*H).fill(92)).xy].every(v=>v===0)).toBe(true)
})
it('recovers a known translation with the correct A-to-B sign and fixed border',()=>{
  const a=new Float32Array(W*H),b=new Float32Array(W*H)
  for(let y=0;y<H;y++)for(let x=0;x<W;x++)a[y*W+x]=110+40*Math.sin(x*.4)+30*Math.sin(y*.53)+20*Math.sin(x*.31+y*.2)
  for(let y=3;y<H;y++)for(let x=2;x<W;x++)b[y*W+x]=a[(y-3)*W+x-2]
  const field=matchGeometry(a,b),k=(10*GRID_W+8)*2
  expect(field.xy[k]).toBeCloseTo(2,0);expect(field.xy[k+1]).toBeCloseTo(3,0)
  for(let y=0;y<GRID_H;y++)for(let x=0;x<GRID_W;x++)if(!x||!y||x===GRID_W-1||y===GRID_H-1){
    expect(field.xy[(y*GRID_W+x)*2]).toBe(0);expect(field.xy[(y*GRID_W+x)*2+1]).toBe(0)
  }
})
it('limits the flow derivative to avoid mesh folding',()=>{
  const f=Float32Array.from({length:GRID_W*GRID_H*2},(_,i)=>i%3===0?10:-10)
  boundFlow(f)
  for(let y=0;y<GRID_H-1;y++)for(let x=0;x<GRID_W-1;x++)for(let a=0;a<2;a++){
    const k=(y*GRID_W+x)*2+a
    expect((Math.abs(f[k+2]-f[k])+Math.abs(f[k+GRID_W*2]-f[k]))/8).toBeLessThan(.601)
  }
})
it('preserves exact input endpoints and does not change canvas opacity',()=>{
  const h=new GeometryHandoff(),a={} as HTMLCanvasElement,b={} as HTMLCanvasElement
  const ctx={canvas:{width:100,height:120},drawImage:vi.fn(),globalAlpha:1}
  h.draw(ctx as unknown as CanvasRenderingContext2D,a,b,0)
  expect(ctx.drawImage).toHaveBeenLastCalledWith(a,0,0,100,120)
  h.draw(ctx as unknown as CanvasRenderingContext2D,a,b,1)
  expect(ctx.drawImage).toHaveBeenLastCalledWith(b,0,0,100,120)
  expect(ctx.globalAlpha).toBe(1)
})
it('has continuous aligned appearance transfer, not a midpoint texture cut',()=>{
  expect(HANDOFF_FRAGMENT).not.toContain('if(progress<0.5)')
  expect(HANDOFF_FRAGMENT).toContain('smoothstep(0.2,0.8,progress)')
  expect(HANDOFF_FRAGMENT).toContain('uv+(1.0-progress)*movement')
  expect(appearanceWeight(.5)).toBeCloseTo(.5)
  expect(appearanceWeight(.50001)-appearanceWeight(.49999)).toBeLessThan(.0001)
  expect(appearanceWeight(0)).toBe(0);expect(appearanceWeight(1)).toBe(1)
  expect(HANDOFF_FRAGMENT).toContain('vec4(color.rgb,1.0)')
})
it('limits frame-to-frame correspondence changes without changing native motion',()=>{
  const previous=new Float32Array(GRID_W*GRID_H*2)
  const result=smoothFlow(new Float32Array(previous.length).fill(7),previous)
  expect(Math.max(...result)).toBeLessThan(.351)
})
it('logs a continuous degraded fallback when GPU/readback fails',()=>{
  const spy=vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(null)
  try {
    const h=new GeometryHandoff(),a={} as HTMLCanvasElement,b={} as HTMLCanvasElement
    const ctx={canvas:{width:100,height:120},drawImage:vi.fn(),save:vi.fn(),restore:vi.fn(),globalAlpha:1}
    h.draw(ctx as unknown as CanvasRenderingContext2D,a,b,.7)
    expect(ctx.drawImage).toHaveBeenLastCalledWith(b,0,0,100,120)
    expect(h.stats.mode).toBe('unregistered_blend_fallback');expect(ctx.globalAlpha).toBeCloseTo(appearanceWeight(.7))
  }finally{spy.mockRestore()}
})
