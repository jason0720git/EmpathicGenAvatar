import {act} from 'react'
import {createRoot} from 'react-dom/client'
import {expect,it,vi} from 'vitest'
import {TurnDiagnostics} from './TurnDiagnostics'
import {api} from './api'
vi.mock('./api',()=>({api:{liveDiagnostics:vi.fn()},ApiError:class extends Error{status=403}}))

it('polls incremental current-turn events without duplicate calls and stops on unmount',async()=>{
  vi.useFakeTimers();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true)
  vi.mocked(api.liveDiagnostics).mockResolvedValueOnce({events:[{sequence:1,event:'tool.completed',arguments:{emotion:'happy',intensity:.6},at:'2026-09-22T00:00:00Z'}]}).mockResolvedValue({events:[]})
  const host=document.createElement('div'),root=createRoot(host)
  try{
    await act(async()=>root.render(<TurnDiagnostics sessionId="s" turnId="t" online active error=""/>))
    expect(host.textContent).toContain('happy · 60%')
    await act(async()=>vi.advanceTimersByTimeAsync(1000))
    expect(api.liveDiagnostics).toHaveBeenLastCalledWith('s','t',1)
    await act(async()=>root.render(<TurnDiagnostics sessionId="s" turnId="t" online active={false} error=""/>))
    expect(host.textContent).toContain('happy · 60%')
    await act(async()=>root.unmount())
    const calls=vi.mocked(api.liveDiagnostics).mock.calls.length
    await act(async()=>vi.advanceTimersByTimeAsync(10000))
    expect(api.liveDiagnostics).toHaveBeenCalledTimes(calls)
  }finally{vi.useRealTimers();vi.unstubAllGlobals()}
})
