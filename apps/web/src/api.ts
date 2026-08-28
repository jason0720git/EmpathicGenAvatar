import type { Avatar, LiveSession, MotionPlan, RendererMethod, TurnResponse } from './types'

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
  createSession: (avatarId: string, rendererMethod: RendererMethod) =>
    request<LiveSession>('/api/live/sessions', {
      method: 'POST',
      body: JSON.stringify({ avatar_id: avatarId, renderer_method: rendererMethod }),
    }),
  sendTurn: (sessionId: string, text: string, motionPlan?: MotionPlan) =>
    request<TurnResponse>(`/api/live/sessions/${sessionId}/turns`, {
      method: 'POST',
      body: JSON.stringify({ text, motion_plan: motionPlan }),
    }),
  interrupt: (sessionId: string) =>
    request<{ state: string }>(`/api/live/sessions/${sessionId}/interrupt`, { method: 'POST' }),
  endSession: (sessionId: string) =>
    request<void>(`/api/live/sessions/${sessionId}`, { method: 'DELETE' }),
}
