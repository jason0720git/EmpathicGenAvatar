import { describe, it, expect } from 'vitest'
import { floatToPcm16, pcmBase64, decodeTestWav } from './wavTest'
describe('WAV test PCM conversion',()=>{
  it('clips and encodes little-endian PCM without corrupting signed samples',()=>{
    const bytes=floatToPcm16(new Float32Array([-2,-1,0,1,2,NaN]))
    const view=new DataView(bytes.buffer)
    expect(Array.from({length:6},(_,i)=>view.getInt16(i*2,true))).toEqual([-32768,-32768,0,32767,32767,0])
    expect(atob(pcmBase64(bytes)).length).toBe(bytes.length)
  })
  it('rejects non-WAV input before opening an audio device',async()=>{
    await expect(decodeTestWav(new ArrayBuffer(12))).rejects.toThrow('WAV')
  })
})
