import type { MotionFrame, RendererStats } from './types'

const labels: Record<string, string> = {
  Neutral: '중립', RoutineInformation: '일상 안내', AttunedListening: '공감적 경청',
  ExploratoryInquiry: '탐색 질문', PerspectiveReflection: '관점 반영', EmotionValidation: '감정 인정',
  CompassionateComfort: '위로', GroundingSupport: '안정 지원', CollaborativeEmpowerment: '함께 해결',
  SharedPositive: '기쁨 공유', SafetyBoundary: '안전 대응', RelationshipRepair: '관계 회복',
  idle: '대기', down: '숙임', up: '복귀', gap: '동작 사이', manual: '수동',
  spoken_receipt: '응답 시작', short_pause: '경청 중 쉼', speech_continuer: '경청 중 맞장구', llm_plan: '응답 계획',
  Baseline:'기본 자세', ManualEmotion:'수동 감정', LowConfidence:'판단 보류', SharedSurprise:'놀람 공유',
  acknowledge:'호응', answer:'답변', clarify:'확인 질문', reflect:'되짚기', repair:'관계 회복', protect:'안전 대응',
  plain:'담담하게', comfort:'위로', steady:'차분하게', encourage:'격려', celebrate:'축하', surprise:'놀람', none:'없음',
}
const name = (value?: string | null) => value ? labels[value] ?? value : '—'
const angles = (values?: number[]) => values ? values.map(v => v.toFixed(1) + '°').join(' / ') : '—'

export function PolicyReadout({frame, stats, official}: {frame: MotionFrame | null; stats: RendererStats | null; official:boolean}) {
  const motion = frame?.natural_motion
  const policy = motion?.policy
  const receipt = stats?.headMotion
  return <section className="gs-policy-readout" aria-label="공감 행동 정책 진단">
    <div className="gs-policy-group">
      <h3>표정과 끄덕임 <small>{policy?.version ?? '프레임 대기'}</small></h3>
      <dl>
        <dt>전달 상태</dt><dd title={policy?.state}>{name(policy?.state)}</dd>
        <dt>대화 행동 · 태도</dt><dd>{[name(policy?.move),name(policy?.stance)].join(' · ')}</dd>
        <dt>끄덕임 계기 · 단계</dt><dd>{name(policy?.nod_cue)} · {name(policy?.nod_phase)}</dd>
        <dt>끄덕임 각도 · 누적 승인</dt><dd>{policy ? `${policy.nod_pitch_deg.toFixed(1)}° · ${policy.nod_grants}회` : '—'}</dd>
        <dt>유성음 · 쉼</dt><dd>{policy ? `${policy.voiced_s.toFixed(2)}초 · ${policy.pause_s.toFixed(2)}초` : '—'}</dd>
      </dl>
    </div>
    <div className="gs-policy-group">
      <h3>머리와 몸통 <small>{official ? stats?.renderSequence !== undefined ? `GPU 프레임 #${stats.renderSequence}` : 'GPU 응답 대기' : 'LAM 리그'}</small></h3>
      <dl>
        <dt>제어 각도 <small>상하 / 좌우 / 기울임</small></dt><dd>{angles(frame?.head && [frame.head.pitch,frame.head.yaw,frame.head.roll])}</dd>
        {official && <>
          <dt>목에 적용한 각도</dt><dd>{angles(receipt && [receipt.applied.pitch,receipt.applied.yaw,receipt.applied.roll])}</dd>
          <dt>몸통 루트 각도</dt><dd>{angles(receipt?.root)}</dd>
          <dt>고정 몸통점 최대 변위</dt><dd>{receipt ? `${receipt.torsoDriftMm.toFixed(3)} mm · ${receipt.torsoAnchorSplats.toLocaleString()}점` : '—'}</dd>
        </>}
        <dt>음성 강세 · 쉼 강도</dt><dd>{motion ? `${(motion.accent ?? 0).toFixed(2)} · ${(motion.boundary ?? 0).toFixed(2)}` : '—'}</dd>
      </dl>
    </div>
  </section>
}
