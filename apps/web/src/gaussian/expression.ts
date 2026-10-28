import profiles from '../../../api/app/emotion_profiles.json'
import type { Controls, MotionFrame } from './types'

export const ARKIT_NAMES = ['browDownLeft','browDownRight','browInnerUp','browOuterUpLeft','browOuterUpRight','cheekPuff','cheekSquintLeft','cheekSquintRight','eyeBlinkLeft','eyeBlinkRight','eyeLookDownLeft','eyeLookDownRight','eyeLookInLeft','eyeLookInRight','eyeLookOutLeft','eyeLookOutRight','eyeLookUpLeft','eyeLookUpRight','eyeSquintLeft','eyeSquintRight','eyeWideLeft','eyeWideRight','jawForward','jawLeft','jawOpen','jawRight','mouthClose','mouthDimpleLeft','mouthDimpleRight','mouthFrownLeft','mouthFrownRight','mouthFunnel','mouthLeft','mouthLowerDownLeft','mouthLowerDownRight','mouthPressLeft','mouthPressRight','mouthPucker','mouthRight','mouthRollLower','mouthRollUpper','mouthShrugLower','mouthShrugUpper','mouthSmileLeft','mouthSmileRight','mouthStretchLeft','mouthStretchRight','mouthUpperUpLeft','mouthUpperUpRight','noseSneerLeft','noseSneerRight','tongueOut']
export const neutralWeights = () => Object.fromEntries(ARKIT_NAMES.map(name => [name, 0]))

export function manualFrame(control: Controls, elapsed: number): MotionFrame {
  const weights = neutralWeights()
  const intensity = Math.max(0, Math.min(1, control.intensity))
  const profile: Record<string, number> = profiles[control.emotion as keyof typeof profiles] ?? {}
  for (const [name, maximum] of Object.entries(profile)) weights[name] = maximum * intensity
  // Deterministic idle blink, explicitly separate from measured A2F motion.
  const blinkPhase = elapsed % 4.7
  weights.eyeBlinkLeft = weights.eyeBlinkRight = blinkPhase < 0.30 ? Math.sin(blinkPhase / 0.30 * Math.PI) : 0
  const gazeX = control.gaze_x, gazeY = control.gaze_y
  weights.eyeLookInLeft = weights.eyeLookOutRight = Math.max(0, gazeX) * 0.6
  weights.eyeLookOutLeft = weights.eyeLookInRight = Math.max(0, -gazeX) * 0.6
  weights.eyeLookUpLeft = weights.eyeLookUpRight = Math.max(0, gazeY) * 0.6
  weights.eyeLookDownLeft = weights.eyeLookDownRight = Math.max(0, -gazeY) * 0.6
  return { turn_id: 'manual', pts_ms: elapsed * 1000, weights,
    head: { yaw: control.head_yaw, pitch: control.head_pitch, roll: control.head_roll },
    gaze: { x: gazeX, y: gazeY }, behavior:{emotion:control.emotion,intensity}, source: 'manual-preview' }
}

/** Apply a manual expression at playback time, including already-buffered speech. */
export function manualSpeechFrame(frame: MotionFrame, control: Controls, elapsed: number): MotionFrame {
  const manual = manualFrame(control, elapsed)
  // These articulation channels were preserved by the server and interpolated
  // by MotionTimeline; raw_weights would reintroduce 30 Hz stepping.
  const raw = frame.weights
  for (const name of ARKIT_NAMES) {
    if ((name.startsWith('mouth') || name.startsWith('jaw') || name === 'tongueOut')
      && !/mouth(Smile|Frown|Dimple)/.test(name)) manual.weights[name] = raw[name] ?? 0
  }
  return { ...frame, weights: manual.weights, behavior:manual.behavior, head: manual.head, gaze: manual.gaze, source: 'nvidia_a2f+manual_expression' }
}
