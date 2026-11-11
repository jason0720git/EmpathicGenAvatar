/** Local Gaussian retarget of the SOBIA Companion reaction trajectories
 * (EmpathicEmotion.Trajectories.cs and EmpathicEmotion.Companion.cs). */
export type CompanionMove = 'acknowledge' | 'answer' | 'clarify' | 'reflect' | 'repair' | 'protect'
export type CompanionStance = 'plain' | 'comfort' | 'steady' | 'encourage' | 'celebrate' | 'surprise'

export const COMPANION_VERSION = 'sobia-companion-v9'
const clamp01 = (value: number) => Math.max(0, Math.min(1, value))
const lerp = (a: number, b: number, t: number) => a + (b - a) * t
const smooth = (value: number) => { const t = clamp01(value); return t * t * (3 - 2 * t) }

// orient, care, focus, affiliation and permitted smile
const ranges = {
  RoutineInformation: [.26, .12, .13, .24, .18],
  AttunedListening: [.62, .48, .26, .64, .22],
  ExploratoryInquiry: [.98, .39, .58, .32, .10],
  PerspectiveReflection: [.69, .57, .89, .30, .06],
  CompassionateComfort: [.21, .99, .48, .78, 0],
  GroundingSupport: [.19, .69, .62, .67, 0],
  CollaborativeEmpowerment: [.76, .31, .29, .86, .57],
  SharedPositive: [.94, .18, .09, 1, .98],
  SharedSurprise: [1, .68, .16, .34, .10],
} as const
type CompanionState = keyof typeof ranges | 'RelationshipRepair' | 'SafetyBoundary'
export function companionState(move: CompanionMove, stance: CompanionStance): CompanionState {
  if (move === 'repair') return 'RelationshipRepair'
  if (move === 'protect') return 'SafetyBoundary'
  if (stance !== 'plain') return ({
    comfort: 'CompassionateComfort', steady: 'GroundingSupport', encourage: 'CollaborativeEmpowerment',
    celebrate: 'SharedPositive', surprise: 'SharedSurprise',
  } as const)[stance]
  return ({acknowledge:'AttunedListening', answer:'RoutineInformation', clarify:'ExploratoryInquiry', reflect:'PerspectiveReflection'} as const)[move]
}

type Style = {open: number; soft: number; side: number; tempo: number}
type Performance = {turn: string; state: CompanionState; seed: number; style: Style; started: number;
  move: CompanionMove; stance: CompanionStance; intensity: number}
const styleDistance = (a: Style, b: Style) => Math.abs(a.open-b.open) + Math.abs(a.soft-b.soft) + .35*Math.abs(a.side-b.side)

// Derive replayable candidate seeds from the turn ID. Log the selected seed so
// that a single performance can be replayed without its prior style history.
function seedFor(text: string) {
  let hash = 2166136261
  for (let i=0; i<text.length; i++) hash = Math.imul(hash ^ text.charCodeAt(i), 16777619)
  return hash >>> 0
}
function styleFor(seed: number): Style {
  let position = seed
  const draw = () => {
    position = (Math.imul(position, 1664525) + 1013904223) >>> 0
    return position / 4294967296
  }
  return {open: draw(), soft: draw(), side: 2*draw()-1, tempo: draw()}
}

function motionEnvelope(age: number, lag: number, rise: number, hold: number,
  fall: number, rest: number, accent: number, boundary: number) {
  const t = Math.max(0, age-lag)
  const attack = smooth(t/rise)
  const decay = smooth((t-rise-hold)/fall)
  return attack * lerp(1, lerp(rest, 1, .75*accent), decay) * (1-.39*boundary)
}

export function sampleCompanionFace(performance: Performance, now: number, accent: number, boundary: number) {
  const {move, stance, state, style} = performance
  const weights: Record<string, number> = {}
  if (state === 'RelationshipRepair' || state === 'SafetyBoundary') return weights
  const [orientMax, careMax, focusMax, affiliateMax, smileMax] = ranges[state]
  const age = Math.max(0, now-performance.started)
  const intensity = clamp01(performance.intensity)
  const question = move === 'clarify'
  const reflection = move === 'reflect'
  const caring = stance === 'comfort'
  const steady = stance === 'steady'
  const surprise = stance === 'surprise'
  const open = clamp01(style.open + .50*(intensity-.5) + (question ? .30 : reflection ? -.22 : 0))
  const soft = clamp01(style.soft - .38*(intensity-.5) + (steady ? .12 : 0))
  const tempo = lerp(.76,1.28,style.tempo)*lerp(1.15,.80,intensity)
  const rise = (surprise ? .19 : caring || steady ? .48 : .32)*tempo
  const hold = (.18+.32*soft)*tempo
  const fall = (surprise ? .48 : .74+.34*soft)*tempo
  const orientEnv = motionEnvelope(age,0,rise,hold,fall,.18,accent,boundary)
  const knitEnv = motionEnvelope(age,.035*tempo,rise*1.12,hold,fall,.37,accent*.65,boundary)
  const cheekEnv = motionEnvelope(age,.09*tempo,rise*1.26,hold,fall,.52,accent*.44,boundary)

  const orient = clamp01(orientMax + (question ? .43 : 0))*lerp(.12,1,open)*orientEnv
  const care = careMax*lerp(1,.18,soft)*knitEnv
  const focus = clamp01(focusMax + (reflection ? .42 : 0))*lerp(1,.10,open)*knitEnv
  const affiliation = affiliateMax*lerp(.17,1,soft)*cheekEnv
  const smile = smileMax*lerp(.38,1,soft)*cheekEnv
  const side = style.side*(question ? .86 : .62)
  const openness = orient*(surprise ? .92 : .60) - (.52*affiliation+.32*focus)
  weights.browInnerUp = clamp01(care+.12*orient)
  weights.browOuterUpLeft = orient*(1-Math.max(0,-side))
  weights.browOuterUpRight = orient*(1-Math.max(0,side))
  for (const suffix of ['Left','Right']) {
    // ARKit has no independent brow-compress channel. Project the downward
    // component to browDown and avoid double-applying compress on both brows.
    weights['browDown'+suffix] = .56*focus*(1-.55*care)
    weights['eyeWide'+suffix] = Math.max(0,openness)
    weights['eyeSquint'+suffix] = Math.max(0,-openness)
    weights['cheekSquint'+suffix] = affiliation
    weights['mouthSmile'+suffix] = smile
    weights['mouthDimple'+suffix] = .25*smile*Math.abs(style.side)
  }
  for (const name of Object.keys(weights)) weights[name] *= intensity
  return weights
}

export class CompanionFace {
  current: Performance | null = null
  private previous = new Map<CompanionState, Style[]>()

  start(turn: string, move: CompanionMove, stance: CompanionStance, intensity: number, now: number) {
    const state = companionState(move, stance)
    const current = this.current
    if (current?.turn === turn && current.state === state) {
      Object.assign(current, {move, stance, intensity})
      return false
    }
    const history = this.previous.get(state) ?? []
    let seed = seedFor(turn + ':' + state)
    let style = styleFor(seed)
    if (history.length) {
      const distance = (candidate: Style) => Math.min(...history.map(prev => styleDistance(candidate,prev)))
      let best = distance(style)
      for (let i=1; i<4; i++) {
        const candidateSeed = seedFor(turn + ':' + state + ':' + i)
        const candidate = styleFor(candidateSeed)
        const separation = distance(candidate)
        if (separation > best) { best=separation; seed=candidateSeed; style=candidate }
      }
    }
    this.previous.set(state,[style,...history.slice(0,1)])
    this.current = {turn,state,seed,style,started:now,move,stance,intensity}
    return true
  }
}
