import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'
import type { AffectIntent, TurnResponse } from './types'

const response: TurnResponse = {
  turn_id: 'turn-1',
  assistant_text: '응답입니다.',
  visemes: [],
  renderer: { mode: 'preview', status: 'ready' },
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api.sendTurn', () => {
  it.each(['off', 'native', 'legacy', 'speech_safe'] as const)('sends comparison mode %s', async (mode) => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => response })
    vi.stubGlobal('fetch', fetchMock)
    await api.sendTurn('session-1', 'test', { emotion: 'happy', intensity: 1 }, 'test-turn', mode)
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).expression_render_mode).toBe(mode)
  })

  it('surfaces feedback save errors instead of silently accepting them', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 403, json: async () => ({detail: 'Debug disabled'}) }))
    await expect(api.expressionFeedback({session_id: 's', turn_id: 't', issue: 'mouth_blur', severity: 2, note: 'test'})).rejects.toThrow('Debug disabled')
  })

  it('requests the report for the selected turn', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({turn_id: 't'}) })
    vi.stubGlobal('fetch', fetchMock)
    await api.expressionReport('t')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/debug/expression-turn/t')
  })
  it('omits motion_plan so the server can plan behavior automatically', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => response,
    })
    vi.stubGlobal('fetch', fetchMock)

    await api.sendTurn('session-1', '안녕하세요', undefined, 'client-turn-1')

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(init.body as string)).toEqual({
      text: '안녕하세요',
      client_turn_id: 'client-turn-1',
    })
  })

  it('sends a manual affect override without a motion plan', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => response,
    })
    vi.stubGlobal('fetch', fetchMock)
    const affectOverride: AffectIntent = {
      emotion: 'happy',
      intensity: 0.5,
    }

    await api.sendTurn('session-1', '반가워요', affectOverride, 'client-turn-2')

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(init.body as string)).toEqual({
      text: '반가워요',
      client_turn_id: 'client-turn-2',
      affect_override: affectOverride,
    })
  })
})
