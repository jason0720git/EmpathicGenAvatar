import { describe, expect, it, vi } from 'vitest'
import { PreviewCapture, type PreviewStatus } from './previewCapture'
import type { WireEvent } from './types'

const sample = {type:'telemetry', event:'motion.sample'}
const action = {type:'telemetry', event:'control.nod', granted:true}
const decision = {type:'telemetry', event:'policy.nod_requested', details:{at_s:12, grant:1, amplitude_deg:15}}

describe('disconnected preview capture', () => {
  it('creates sessions only on actions, keeps exact decisions, and flushes the final partial batch', async () => {
    const create = vi.fn(async (avatar:string) => avatar + '-session')
    const post = vi.fn<(id:string,events:WireEvent[])=>Promise<void>>().mockResolvedValue(undefined)
    const status = vi.fn<(s:PreviewStatus)=>void>()
    const capture = new PreviewCapture(create,post,status)
    capture.add(sample)
    capture.tick(10_000)
    expect(create).not.toHaveBeenCalled()
    capture.start('official',12_000,action)
    capture.add(decision)
    for(let i=0;i<5;i++)capture.add(sample)
    capture.tick(12_550)
    await vi.waitFor(()=>expect(post).toHaveBeenCalledTimes(1))
    capture.tick(18_000)
    await vi.waitFor(()=>expect(status.mock.lastCall?.[0]).toMatchObject({state:'saved',saved:7,dropped:0}))
    expect(capture.active()).toBe(false)
    const packets = post.mock.calls.flatMap(call=>call[1])
    expect(packets[0]).toMatchObject(action)
    expect(packets[1]).toMatchObject(decision)
    expect(packets.map(p=>p.preview_seq)).toEqual([1,2,3,4,5,6,7])
    expect(post.mock.calls.map(call=>call[1].length)).toEqual([5,2])
  })

  it('does not overwrite a new avatar session when an older session finishes late', async () => {
    let finishFirst!: ()=>void
    const delayed = new Promise<void>(resolve=>{finishFirst=resolve})
    const post = vi.fn(async (id:string) => {if(id==='old')await delayed})
    const status = vi.fn<(s:PreviewStatus)=>void>()
    const capture = new PreviewCapture(async id=>id,post,status)
    capture.start('old',0,action)
    capture.start('new',300,action)
    capture.finish()
    await vi.waitFor(()=>expect(status.mock.lastCall?.[0]).toMatchObject({id:'new',state:'saved'}))
    finishFirst()
    await delayed
    expect(post.mock.calls.map(call=>call[0]).sort()).toEqual(['new','old'])
    expect(status.mock.lastCall?.[0].id).toBe('new')
  })

  it('reports an unsuccessful upload and can start a fresh run', async () => {
    const status = vi.fn<(s:PreviewStatus)=>void>()
    const post=vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(undefined)
    const capture = new PreviewCapture(async id=>id,post,status)
    capture.start('official',0,action)
    capture.finish()
    await vi.waitFor(()=>expect(status.mock.lastCall?.[0]).toMatchObject({state:'error',saved:0,dropped:1,error:'Error: offline'}))
    capture.start('official',100,action)
    capture.finish()
    await vi.waitFor(()=>expect(status.mock.lastCall?.[0]).toMatchObject({state:'saved',saved:1,dropped:0}))
  })
})
