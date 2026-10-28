import { expect, it } from 'vitest'
import { manualSpeechFrame } from './expression'
import { DEFAULT_CONTROLS } from './types'

it('changes an already buffered happy response to sad without losing articulation', () => {
  const frame = {turn_id:'speech',pts_ms:900,weights:{jawOpen:.43,mouthFunnel:.27,mouthSmileLeft:.6,browDownLeft:.4}}
  const result = manualSpeechFrame(frame,{...DEFAULT_CONTROLS,emotion:'sad',intensity:.8},1)
  expect(result.weights.jawOpen).toBe(.43)
  expect(result.weights.mouthFunnel).toBe(.27)
  expect(result.weights.mouthSmileLeft).toBe(0)
  expect(result.weights.browInnerUp).toBeCloseTo(.8)
  expect(result.weights.mouthFrownLeft).toBeCloseTo(.68)
})

it('manual neutral removes affect but retains speech and requested head pose', () => {
  const result=manualSpeechFrame({turn_id:'speech',pts_ms:0,weights:{jawOpen:.2,mouthSmileRight:.9,browInnerUp:.9}},
    {...DEFAULT_CONTROLS,head_yaw:8},1)
  expect(result.weights.mouthSmileRight).toBe(0)
  expect(result.weights.browInnerUp).toBe(0)
  expect(result.weights.jawOpen).toBe(.2)
  expect(result.head?.yaw).toBe(8)
})

it('full-strength presets reach primary muscle maxima while zero stays neutral', () => {
  for (const [emotion, muscle] of [['happy','mouthSmileLeft'],['sad','browInnerUp'],['angry','browDownLeft'],['fear','browInnerUp'],['surprise','browOuterUpLeft']]) {
    const strong = manualSpeechFrame({turn_id:'test',pts_ms:0,weights:{jawOpen:.31,mouthFunnel:.42}}, {...DEFAULT_CONTROLS,emotion,intensity:1},1)
    expect(strong.weights[muscle]).toBe(1)
    expect(strong.weights.jawOpen).toBe(.31)
    expect(strong.weights.mouthFunnel).toBe(.42)
    const zero = manualSpeechFrame({turn_id:'test',pts_ms:0,weights:{}},{...DEFAULT_CONTROLS,emotion,intensity:0},1)
    expect(zero.weights[muscle]).toBe(0)
    expect(Object.values(strong.weights).every(v=>v>=0&&v<=1)).toBe(true)
  }
})
