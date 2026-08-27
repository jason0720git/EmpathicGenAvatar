export type AvatarStatus = 'ready' | 'preparing' | 'failed'

export interface Avatar {
  id: string
  name: string
  persona: string
  voice: string
  status: AvatarStatus
  source_url?: string
  created_at: string
  engine: string
  quality?: {
    width: number
    height: number
    score: number
    hints: string[]
  }
}

export type LiveState =
  | 'connecting'
  | 'ready'
  | 'listening'
  | 'transcribing'
  | 'thinking'
  | 'speaking'
  | 'reconnecting'
  | 'error'

export interface LiveSession {
  id: string
  avatar_id: string
  state: 'active' | 'ended'
  created_at: string
}

export type ExpressionIntent = 'neutral' | 'warm' | 'concern'

export interface MotionPlan {
  expression: ExpressionIntent
  head: {
    yaw_deg: number
    pitch_deg: number
    roll_deg: number
  }
  gaze: {
    x: number
    y: number
  }
  nod?: {
    start_ms: number
    duration_ms: number
    amplitude_deg: number
  }
}

export interface TurnResponse {
  turn_id: string
  assistant_text: string
  visemes: Array<{ at_ms: number; value: number }>
  renderer: {
    mode: 'preview' | 'remote'
    stream_url?: string
    audio_url?: string
    status: string
    applied_motion?: MotionPlan
  }
}

export interface TranscriptItem {
  id: string
  role: 'user' | 'assistant'
  text: string
  at: Date
}
