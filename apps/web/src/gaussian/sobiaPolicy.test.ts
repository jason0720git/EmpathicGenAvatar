import { describe, expect, it } from 'vitest'
import { companionState, type CompanionMove, type CompanionStance } from './companionFace'
import { NaturalMotion } from './naturalMotion'
import { SobiaPolicy } from './sobiaPolicy'
import type { MotionFrame } from './types'

const base: MotionFrame = {turn_id:'turn-1',pts_ms:0,weights:{jawOpen:.37,mouthPucker:.7,tongueOut:.18,mouthSmileLeft:.9},
  head:{pitch:0,yaw:0,roll:0},speech_energy:.4}

function semantic(move: CompanionMove, stance: CompanionStance, confidence=.9): MotionFrame {
  return {...base,behavior:{source:'llm_tool_call',move,stance,confidence,intensity:1,emotion:'happy'}}
}

describe('SOBIA captured-voice and reply nods', () => {
  it('requires real captured voice and elapsed pause, then runs one bounded neck stroke', () => {
    const policy = new SobiaPolicy()
    const sample = (t: number) => policy.sample(base,t,false,true,0,0).diagnostics
    for (let i=0; i<50; i++) policy.observeVoice(i/20,.05,false)
    expect(sample(2.5).nod_grants).toBe(0)
    for (let i=50; i<64; i++) policy.observeVoice(i/20,.05,true)
    for (let i=64; i<70; i++) policy.observeVoice(i/20,.05,false)
    expect(sample(3.45).nod_grants).toBe(0)
    policy.observeVoice(3.5,.05,false)
    expect(sample(3.5)).toMatchObject({nod_cue:'short_pause',nod_cycles:1,nod_pitch_deg:0})
    expect(sample(4.05).nod_pitch_deg).toBeCloseTo(15,5)
    expect(sample(4.61).nod_pitch_deg).toBe(0)
    expect(policy.drainEvents().map(event=>event.event)).toEqual(expect.arrayContaining(['nod_gate','nod_requested','nod_motion_start','nod_motion_end']))
    expect(policy.drainEvents()).toEqual([])
  })

  it('uses 1.6 s and 6 s for continuers, alternates a soft double with a single, and shares the cooldown with receipts', () => {
    const policy=new SobiaPolicy()
    const sample=(t:number)=>policy.sample(base,t,false,true,0,0).diagnostics
    for(let i=0;i<31;i++) policy.observeVoice(i*.05,.05,true)
    expect(sample(1.5).nod_grants).toBe(0)
    policy.observeVoice(1.55,.05,true)
    expect(sample(1.75)).toMatchObject({nod_cue:'speech_continuer',nod_cycles:2})
    expect(sample(1.75).nod_pitch_deg).toBeCloseTo(5)
    expect(sample(1.98).nod_pitch_deg).toBe(0)
    expect(sample(2.21).nod_pitch_deg).toBeCloseTo(4.1)
    expect(policy.requestNod(2.51,'spoken_receipt')).toBe(false)
    for(let i=32;i<151;i++) policy.observeVoice(i*.05,.05,true)
    expect(sample(7.5).nod_grants).toBe(1)
    for(let i=151;i<154;i++) policy.observeVoice(i*.05,.05,true)
    expect(sample(7.65)).toMatchObject({nod_cycles:1,nod_grants:2})
    policy.endListeningTurn()
    expect(policy.requestNod(9,'spoken_receipt')).toBe(false)
    expect(policy.requestNod(10,'spoken_receipt')).toBe(true)
    expect(sample(10.2)).toMatchObject({nod_cue:'spoken_receipt',nod_cycles:2,nod_grants:3})
  })

  it('forgets voice on gaps and invalid chunk sizes, and never treats an old pause as a new turn', () => {
    const policy=new SobiaPolicy()
    for(let i=0;i<15;i++) policy.observeVoice(i/20,.05,true)
    for(let i=0;i<50;i++) policy.observeVoice(2+i/20,.05,false)
    expect(policy.sample(base,4.5,false,true,0,0).diagnostics).toMatchObject({nod_grants:0,voiced_s:0})
    policy.observeVoice(5,.4,true)
    expect(policy.sample(base,5,false,true,0,0).diagnostics.pause_s).toBe(0)
  })

  it('applies manual nod even with dynamics off, restores exact pose, ignores the same LLM cue after receipt', () => {
    const motion = new NaturalMotion()
    motion.requestNod(1,'manual')
    const peak=motion.apply(base,1.55,false,false)
    expect(peak.head).toEqual({pitch:15,yaw:0,roll:0})
    expect(peak.weights).toBe(base.weights)
    expect(motion.apply(base,2.11,false,false)).toBe(base)
    motion.resetPolicy()
    motion.requestNod(3,'spoken_receipt')
    const f = {...semantic('acknowledge','comfort'),pts_ms:600}
    f.behavior!.nod=true
    motion.apply(f,3.6,true)
    expect(motion.apply(f,6,true).natural_motion?.policy?.nod_grants).toBe(1)
  })

  it('cancels a running gesture on interruption and preserves the inter-gesture interval', () => {
    const motion=new NaturalMotion()
    motion.requestNod(1,'manual')
    motion.apply(base,1.3,false)
    motion.cancelTurn()
    expect(motion.apply(base,1.4,false).natural_motion?.policy?.nod_phase).toBe('idle')
    expect(motion.drainPolicyEvents().some(row=>row.event==='nod_cancelled')).toBe(true)
    expect(motion.requestNod(1.5,'spoken_receipt')).toBe(false)
    expect(motion.requestNod(3.2,'spoken_receipt')).toBe(true)
  })
})

describe('SOBIA semantic trajectories', () => {
  it('resolves the 4 plain moves and 5 colored stances, prioritizing boundaries and repairs', () => {
    expect((['acknowledge','answer','clarify','reflect'] as const).map(m=>companionState(m,'plain')))
      .toEqual(['AttunedListening','RoutineInformation','ExploratoryInquiry','PerspectiveReflection'])
    expect((['comfort','steady','encourage','celebrate','surprise'] as const).map(s=>companionState('answer',s)))
      .toEqual(['CompassionateComfort','GroundingSupport','CollaborativeEmpowerment','SharedPositive','SharedSurprise'])
    expect(companionState('protect','celebrate')).toBe('SafetyBoundary')
    expect(companionState('repair','surprise')).toBe('RelationshipRepair')
  })

  it('attacks and releases per turn, responds to prosody, and carries the same resting style through listening', () => {
    const policy=new SobiaPolicy()
    const f=semantic('clarify','comfort')
    expect(policy.sample(f,10,true,true,0,0).weights?.browInnerUp).toBe(0)
    const peak=policy.sample(f,10.75,true,true,0,0)
    expect(peak.weights!.browInnerUp).toBeGreaterThan(.1)
    const rest=policy.sample(f,13,true,true,0,0)
    expect(rest.weights!.browInnerUp).toBeLessThan(peak.weights!.browInnerUp)
    expect(policy.sample(f,13,true,true,1,0).weights!.browInnerUp).toBeGreaterThan(rest.weights!.browInnerUp)
    expect(policy.sample(f,13,true,true,0,1).weights!.browInnerUp).toBeLessThan(rest.weights!.browInnerUp)
    const idle=policy.sample({...base,turn_id:'idle'},14,false,true,1,0)
    expect(idle.weights).toEqual(rest.weights)
    expect(idle.diagnostics.seed).toBe(peak.diagnostics.seed)
    expect(policy.sample({...f,turn_id:'next'},15,true,true,0,0).diagnostics.seed).not.toBe(peak.diagnostics.seed)
    const replay=new SobiaPolicy()
    expect(replay.sample(f,40,true,true,0,0).diagnostics.seed).toBe(peak.diagnostics.seed)
    expect(replay.sample(f,40.75,true,true,0,0).weights).toEqual(peak.weights)
  })

  it('guards smiles for care, safety and low confidence while preserving A2F, manual emotion and eyelids', () => {
    for(const [move,stance,confidence,state] of [
      ['clarify','comfort',.9,'CompassionateComfort'],['repair','celebrate',.9,'RelationshipRepair'],
      ['protect','celebrate',.9,'SafetyBoundary'],['answer','celebrate',.61,'LowConfidence'],
    ] as const) {
      const motion=new NaturalMotion()
      const f=semantic(move,stance,confidence)
      motion.apply(f,0,true)
      const r=motion.apply(f,.65,true)
      expect(r.natural_motion!.policy!.state).toBe(state)
      expect(r.weights.mouthSmileLeft).toBe(0)
      expect(r.weights.jawOpen).toBe(.37)
      expect(r.weights.mouthPucker).toBe(.7)
      expect(r.weights.tongueOut).toBe(.18)
      expect(motion.apply(f,2.3,true).weights.eyeBlinkLeft).toBe(0)
      expect(motion.apply(f,2.49,true).weights.eyeBlinkLeft).toBeCloseTo(1)
      const manual=motion.apply({...base,source:'nvidia_a2f+manual_expression',behavior:{emotion:'happy'}},2.9,true)
      expect(manual.natural_motion!.policy!.state).toBe('ManualEmotion')
      expect(manual.weights.mouthSmileLeft).toBeGreaterThan(0)
    }
  })

  it('uses inclusive .62 confidence threshold and logs once per decision', () => {
    const policy=new SobiaPolicy()
    const f=semantic('answer','celebrate',.62)
    for(let i=0;i<50;i++) policy.sample(f,i/25,true,true,0,0)
    expect(policy.drainEvents().map(e=>e.event)).toEqual(['semantic_gate','expression_start'])
    expect(policy.sample(f,2,true,true,0,0).weights!.mouthSmileLeft).toBeGreaterThan(0)
    expect(policy.sample({...f,behavior:{...f.behavior,intensity:0}},2,true,true,0,0).weights!.mouthSmileLeft).toBe(0)
  })
})
