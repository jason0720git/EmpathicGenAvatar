import { expect,it,vi } from 'vitest'
import { drawFaceRegistration,faceWeight,warpPoint } from './faceTransitionMesh'
import { beginIdleEntryTransition,drawTransition,TRANSITION_MS } from './avatarTransition'

it('keeps all image edges fixed while translating the face center',()=>{
  for(let i=0;i<=100;i++) for(const [x,y] of [[0,i/100],[1,i/100],[i/100,0],[i/100,1]]) {
    expect(warpPoint(x,y,.02,-.02,1)).toEqual([x,y])
  }
  expect(faceWeight(.5,.4)).toBe(1)
  expect(warpPoint(.5,.4,.01,-.01,1)).toEqual([.51,.39])
  expect(warpPoint(.5,.4,.01,-.01,0)).toEqual([.5,.4])
})
it('keeps the bounded displacement field monotonic (no foldovers)',()=>{
  for(const sign of [-1,1]) for(let i=0;i<100;i++) {
    const a=warpPoint(i/100,.4,.02*sign,0,1),b=warpPoint((i+1)/100,.4,.02*sign,0,1)
    expect(b[0]).toBeGreaterThan(a[0])
    const c=warpPoint(.5,i/100,0,.02*sign,1),d=warpPoint(.5,(i+1)/100,0,.02*sign,1)
    expect(d[1]).toBeGreaterThan(c[1])
  }
})
it('renders a finite local mesh with no global rotate/scale/translate',()=>{
  const ctx={canvas:{width:512,height:640},save:vi.fn(),restore:vi.fn(),beginPath:vi.fn(),moveTo:vi.fn(),lineTo:vi.fn(),closePath:vi.fn(),clip:vi.fn(),transform:vi.fn(),drawImage:vi.fn(),rotate:vi.fn(),scale:vi.fn(),translate:vi.fn()}
  drawFaceRegistration(ctx as unknown as CanvasRenderingContext2D,{} as HTMLCanvasElement,.01,-.01,1)
  expect(ctx.transform).toHaveBeenCalledTimes(72)
  for(const args of ctx.transform.mock.calls) expect(args.every(Number.isFinite)).toBe(true)
  expect(ctx.rotate).not.toHaveBeenCalled();expect(ctx.scale).not.toHaveBeenCalled();expect(ctx.translate).not.toHaveBeenCalled()
})
it('uses exact native pixels after silent lead even if registration was active',()=>{
  const idle=document.createElement('canvas'),to=document.createElement('canvas')
  const transition={...beginIdleEntryTransition(idle,0),dx:.01,dy:-.01,accepted:true}
  const ctx={canvas:{width:512,height:640},drawImage:vi.fn()}
  drawTransition(ctx as unknown as CanvasRenderingContext2D,to,transition,TRANSITION_MS)
  expect(ctx.drawImage).toHaveBeenCalledExactlyOnceWith(to,0,0,512,640)
})
