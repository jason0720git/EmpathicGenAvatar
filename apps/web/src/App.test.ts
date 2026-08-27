import { describe, expect, it } from 'vitest'
import { localTurn } from './localTurn'
import type { Avatar } from './types'

const avatar: Avatar = {
  id: 'test-avatar',
  name: 'Test',
  persona: '차분한 안내자',
  voice: 'Calm Korean',
  status: 'ready',
  created_at: new Date().toISOString(),
  engine: 'preview',
}

describe('localTurn', () => {
  it('keeps the avatar explicitly AI-labelled in its greeting', () => {
    const turn = localTurn('안녕하세요', avatar)
    expect(turn.assistant_text).toContain('AI 생성 아바타')
    expect(turn.renderer.mode).toBe('preview')
  })

  it('refuses likeness misuse involving minors or impersonation', () => {
    const turn = localTurn('유명인 사칭 아바타를 만들 수 있나요?', avatar)
    expect(turn.assistant_text).toContain('도와드릴 수 없어요')
  })
})
