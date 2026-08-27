import type { Avatar, TurnResponse } from './types'

export function localTurn(text: string, avatar: Avatar): TurnResponse {
  const normalized = text.toLowerCase()
  if (['미성년', '아동', '아이 사진', '유명인 사칭', '딥페이크 범죄'].some((term) => normalized.includes(term))) {
    return {
      turn_id: `assistant-${Date.now()}`,
      assistant_text: '그 용도는 도와드릴 수 없어요. 이 공간에서는 권리를 보유한 성인 인물의 private 아바타만 다루며, 사칭이나 위해 목적의 생성은 지원하지 않습니다.',
      visemes: [],
      renderer: { mode: 'preview', status: 'safety-blocked' },
    }
  }
  let assistantText = `말씀해 주셔서 고마워요. ${avatar.name}로서 핵심을 함께 정리해 볼게요. ${text.length > 42 ? '가장 중요한 지점부터 차분히 살펴보는 것이 좋겠습니다.' : '어떤 방향이 가장 도움이 될지 조금 더 들려주실 수 있을까요?'}`
  if (normalized.includes('안녕') || normalized.includes('hello')) assistantText = `안녕하세요, 저는 ${avatar.name}입니다. AI 생성 아바타로서 지금 이 대화를 함께할게요. 오늘 무엇을 도와드릴까요?`
  if (normalized.includes('기분') || normalized.includes('힘들')) assistantText = '그렇게 느끼고 계셨군요. 바로 해결하려 하기보다, 지금 가장 크게 느껴지는 부분을 한 가지부터 이야기해 볼까요?'
  return { turn_id: `assistant-${Date.now()}`, assistant_text: assistantText, visemes: [], renderer: { mode: 'preview', status: 'local-browser-fallback' } }
}
