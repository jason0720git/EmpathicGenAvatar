import type { AffectIntent, Avatar, LiveSession, MotionPlan, RendererMethod, TurnResponse } from './types'

const base = import.meta.env.VITE_API_BASE_URL ?? ''
const accessToken = import.meta.env.VITE_API_ACCESS_TOKEN

export class ApiError extends Error {
  constructor(message: string, public readonly status?: number) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(accessToken ? { 'X-Avatar-Token': accessToken } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new ApiError(body.detail ?? '요청을 처리하지 못했습니다.', response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string }>('/api/health'),
  avatars: () => request<Avatar[]>('/api/avatars'),
  avatar: (id: string) => request<Avatar>(`/api/avatars/${id}`),
  createAvatar: (input: {
    image: File
    name: string
    persona: string
    voice: string
    consent_likeness: boolean
    consent_adult: boolean
    consent_ai_label: boolean
  }) => {
    const form = new FormData()
    form.append('image', input.image)
    form.append('name', input.name)
    form.append('persona', input.persona)
    form.append('voice', input.voice)
    form.append('consent_likeness', String(input.consent_likeness))
    form.append('consent_adult', String(input.consent_adult))
    form.append('consent_ai_label', String(input.consent_ai_label))
    return request<Avatar>('/api/avatars', { method: 'POST', body: form })
  },
  deleteAvatar: (id: string) => request<void>(`/api/avatars/${id}`, { method: 'DELETE' }),
  prepareIdle: (id: string) => request<{ status: string }>(`/api/avatars/${id}/idle`, { method: 'POST' }),
  createSession: (avatarId: string, rendererMethod: RendererMethod, sessionInstruction?: string) =>
    request<LiveSession>('/api/live/sessions', {
      method: 'POST',
      body: JSON.stringify({ avatar_id: avatarId, renderer_method: rendererMethod, session_instruction: sessionInstruction }),
    }),
  sendTurn: (sessionId: string, text: string, affectOverride?: AffectIntent, clientTurnId?: string, expressionRenderMode?: 'off' | 'native' | 'legacy' | 'speech_safe') => {
    // Auto intentionally omits affect_override, so only that path invokes
    // the Realtime affect tool. Manual evaluation sends two bounded fields.
    const body = {
      text,
      client_turn_id: clientTurnId,
      ...(expressionRenderMode ? { expression_render_mode: expressionRenderMode } : {}),
      ...(affectOverride ? { affect_override: affectOverride } : {}),
    }
    return request<TurnResponse>(`/api/live/sessions/${sessionId}/turns`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },
  turnCaption: (sessionId: string, turnId: string) =>
    request<{ text: string | null; done: boolean }>(`/api/live/sessions/${sessionId}/turns/${turnId}/caption`),
  interrupt: (sessionId: string) =>
    request<{ state: string }>(`/api/live/sessions/${sessionId}/interrupt`, { method: 'POST' }),
  endSession: (sessionId: string) =>
    request<void>(`/api/live/sessions/${sessionId}`, { method: 'DELETE' }),
  telemetry: (payload: { turn_id: string; event: string; elapsed_ms: number; details?: Record<string, number | string | boolean> }) =>
    request<void>('/api/telemetry/turn', { method: 'POST', body: JSON.stringify(payload) }).catch(() => undefined),
  expressionFeedback: (payload: {session_id: string; turn_id: string; issue: string; severity: number; at_ms?: number; note: string}) =>
    request<{saved: boolean; turn_id: string}>('/api/debug/expression-feedback', {method: 'POST', body: JSON.stringify(payload)}),
  expressionReport: (turnId: string) => request<Record<string, unknown>>(`/api/debug/expression-turn/${encodeURIComponent(turnId)}`),
}
