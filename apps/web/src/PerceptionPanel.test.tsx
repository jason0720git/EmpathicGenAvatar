import {act,createRef} from 'react'
import {createRoot} from 'react-dom/client'
import {expect,it,vi} from 'vitest'
import {PerceptionPanel,type PerceptionHandle} from './PerceptionPanel'
import {api} from './api'
vi.mock('./api',()=>({api:{perception:vi.fn(),perceptionPreview:vi.fn()}}))

it('does not capture automatically; snapshots only when enabled and stops on unmount',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true)
  vi.mocked(api.perception).mockResolvedValue({state:'running',observation:{status:'observed',label:'happiness'}})
  const host=document.createElement('div'),root=createRoot(host),ref=createRef<PerceptionHandle>()
  await act(async()=>root.render(<PerceptionPanel ref={ref} sessionId="a" online/>))
  expect(api.perception).not.toHaveBeenCalled()
  expect(ref.current!.turnOptions().use_observation).toBe(false)
  await act(async()=>host.querySelector('button')!.click())
  expect(api.perception).toHaveBeenCalledWith('a','start')
  ref.current!.beginSpeech();ref.current!.endSpeech()
  expect(ref.current!.turnOptions()).toMatchObject({use_observation:true,observation_speaking:true})
  expect(ref.current!.turnOptions().observation_speaking).toBe(false)
  await act(async()=>root.unmount())
  expect(api.perception).toHaveBeenCalledWith('a','stop')
  vi.unstubAllGlobals()
})
