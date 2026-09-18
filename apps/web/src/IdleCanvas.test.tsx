import { act, createRef } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { IdleCanvas, MjpegParser } from './IdleCanvas'

const packet = (body: number[]) => {
  const header = new TextEncoder().encode(`--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${body.length}\r\n\r\n`)
  return new Uint8Array([...header,...body,13,10])
}
it('parses split headers/payloads and multiple frames without loss', () => {
  const bytes=new Uint8Array([...packet([1,2,3]),...packet([4,5])])
  const parser=new MjpegParser(), frames:Uint8Array[]=[]
  for (const byte of bytes) frames.push(...parser.push(new Uint8Array([byte])))
  expect(frames.map(frame=>[...frame])).toEqual([[1,2,3],[4,5]])
  expect(new MjpegParser().push(bytes).length).toBe(2)
})
it('bounds malformed frame headers and lengths', () => {
  expect(()=>new MjpegParser().push(new Uint8Array(4097))).toThrow()
  expect(()=>new MjpegParser().push(new TextEncoder().encode('--frame\r\nContent-Length: 99999999\r\n\r\n'))).toThrow()
})
it('paints the newest burst frame on the snapshot canvas and aborts on unmount', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true)
  let paint:FrameRequestCallback=()=>{}
  vi.stubGlobal('requestAnimationFrame',vi.fn((callback:FrameRequestCallback)=>{paint=callback; return 1}))
  vi.stubGlobal('cancelAnimationFrame',vi.fn())
  const bitmap={width:120,height:160,close:vi.fn()}
  vi.stubGlobal('createImageBitmap',vi.fn().mockResolvedValue(bitmap))
  const draw=vi.fn()
  vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:draw} as unknown as CanvasRenderingContext2D)
  let signal:AbortSignal
  const stream=new ReadableStream<Uint8Array>({start(controller){controller.enqueue(new Uint8Array([...packet([1]),...packet([2])]))}})
  vi.stubGlobal('fetch',vi.fn((_url,options)=>{signal=options.signal; return Promise.resolve({ok:true,body:stream})}))
  const host=document.createElement('div'), root=createRoot(host), ref=createRef<HTMLCanvasElement>(), ready=vi.fn()
  try {
    await act(async()=>root.render(<IdleCanvas source="/idle" canvasRef={ref} className="idle" label="idle" onReady={ready}/>))
    expect(createImageBitmap).toHaveBeenCalledTimes(1)
    expect(draw).not.toHaveBeenCalled()
    await act(async()=>paint(10))
    expect(draw).toHaveBeenCalledWith(bitmap,0,0)
    expect(ref.current?.width).toBe(120)
    expect(ready).toHaveBeenLastCalledWith(true)
    expect(bitmap.close).toHaveBeenCalledTimes(1)
  } finally {
    await act(async()=>root.unmount())
    expect(signal!.aborted).toBe(true)
    vi.restoreAllMocks(); vi.unstubAllGlobals()
  }
})

it('parks on the first frame and restarts from the boundary when unparked', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true)
  let paint:FrameRequestCallback=()=>{}
  vi.stubGlobal('requestAnimationFrame',vi.fn((callback:FrameRequestCallback)=>{paint=callback;return 1}))
  vi.stubGlobal('cancelAnimationFrame',vi.fn())
  const draw=vi.fn(), closed=vi.fn(), decoded:Blob[]=[]
  vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:draw} as unknown as CanvasRenderingContext2D)
  vi.stubGlobal('createImageBitmap',vi.fn((blob:Blob)=>{decoded.push(blob);return Promise.resolve({width:96,height:120,close:closed})}))
  const cancel=vi.fn()
  vi.stubGlobal('fetch',vi.fn(()=>Promise.resolve({ok:true,body:new ReadableStream({start(c){c.enqueue(new Uint8Array([...packet([1]),...packet([2,2])]))},cancel})})))
  const host=document.createElement('div'),root=createRoot(host),ref=createRef<HTMLCanvasElement>(),ready=vi.fn()
  try {
    await act(async()=>root.render(<IdleCanvas parked source="/idle" canvasRef={ref} className="idle" label="idle" onReady={ready}/>))
    expect(decoded[0].size).toBe(1)
    expect(cancel).toHaveBeenCalledTimes(1)
    await act(async()=>paint(0))
    expect(ref.current?.dataset.parked).toBe('true')
    await act(async()=>root.render(<IdleCanvas source="/idle" canvasRef={ref} className="idle" label="idle" onReady={ready}/>))
    expect(fetch).toHaveBeenCalledTimes(2)
    await act(async()=>paint(40))
    expect(ref.current?.dataset.parked).toBe('false')
  } finally {await act(async()=>root.unmount());vi.restoreAllMocks();vi.unstubAllGlobals()}
})
