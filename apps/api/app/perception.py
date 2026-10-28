"""Local perception adapter: allowlisted fields, no raw media in model context."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Literal
import httpx
from pydantic import BaseModel, ConfigDict, Field


class Cues(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    smile: float = Field(default=0,ge=0,le=1)
    browTension: float = Field(default=0,ge=0,le=1)
    browRaise: float = Field(default=0,ge=0,le=1)
    eyeClosure: float = Field(default=0,ge=0,le=1)
    mouthOpen: float = Field(default=0,ge=0,le=1)
    eyeWide: float = Field(default=0,ge=0,le=1)


class UserObservation(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    status: Literal['observed','unavailable'] = 'unavailable'
    reason: str = Field(default='camera_off',max_length=80)
    label: Literal['neutral','happiness','sadness','anger','fear','surprise','disgust','uncertain'] = 'uncertain'
    score: float = Field(default=0,ge=0,le=1)
    valid_ratio: float = Field(default=0,ge=0,le=1)
    age_ms: int | None = Field(default=None,ge=0)
    sample_count: int = Field(default=0,ge=0,le=1800)
    window_ms: int = Field(default=3000,ge=200,le=120000)
    speaking: bool = False
    cues: Cues = Field(default_factory=Cues)
    provider: str = Field(default='',max_length=160)

    def context(self) -> str:
        if self.status != 'observed' or self.age_ms is None or self.age_ms > 1000 or self.valid_ratio < .5:
            return ''
        # Fixed keys + enums only; no camera-provided free text becomes instructions.
        return json.dumps(dict(face=self.label,score=round(self.score,2),coverage=self.valid_ratio,
            smile=self.cues.smile,brow_tension=self.cues.browTension,speaking=self.speaking),separators=(',',':'))


def wav_test_affect(observation: UserObservation):
    # Diagnostic mirroring only, not a conversational empathy policy.
    from .models import AffectIntent
    mapping = {'neutral':'neutral','happiness':'happy','sadness':'sad','anger':'angry',
               'fear':'fear','surprise':'surprise','disgust':'disgust'}
    if not observation.context() or observation.label not in mapping:
        raise ValueError('WAV Auto는 유효한 얼굴 관측이 필요합니다. 얼굴 분석을 켜고 1초 이상 정면을 보거나 감정을 직접 선택해 주세요.')
    emotion = mapping[observation.label]
    return AffectIntent(emotion=emotion, intensity=0 if emotion == 'neutral' else .65)


OBSERVATION_POLICY = (
    'Current-turn facial observations are uncertain appearance cues, NOT the user\'s true emotion. '
    'Prioritize their words and stated feelings. Do not diagnose, copy their emotion automatically, '
    'or announce camera scores. Speaking mouth motion is not proof of surprise. '
    'Use cues only to gently adapt empathy; ignore them when conflicting or unavailable. '
)


class PerceptionClient:
    def __init__(self, data_dir: Path):
        self.url = os.getenv('PERCEPTION_URL','http://127.0.0.1:8020').rstrip('/')
        self.token_path = Path(os.getenv('PERCEPTION_TOKEN_FILE',str(data_dir/'perception-token')))

    async def command(self, action, session_id, window_ms=3000, speaking=False,end_age_ms=0):
        token = self.token_path.read_text().strip()
        async with httpx.AsyncClient(timeout=.6,trust_env=False) as client:
            response = await client.post(self.url+'/'+action,headers={'X-Perception-Token':token},
                json=dict(session_id=session_id,window_ms=window_ms,speaking=speaking,end_age_ms=end_age_ms))
            response.raise_for_status()
            return response

    async def snapshot(self, session_id, enabled, window_ms, speaking,end_age_ms=0):
        if not enabled:
            return UserObservation(), {}
        try:
            packet = (await self.command('summary',session_id,window_ms,speaking,end_age_ms)).json()
            obs = UserObservation.model_validate(packet['observation'])
            return obs, packet['observation']
        except Exception:
            return UserObservation(reason='service_unavailable'), {}
