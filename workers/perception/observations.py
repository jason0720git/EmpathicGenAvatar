"""Bounded, media-free single-user observations. Scores are not emotion truth."""
from collections import deque
from statistics import mean
import math

LABELS = ('neutral', 'happiness', 'sadness', 'anger', 'fear', 'surprise', 'disgust')


class ObservationBuffer:
    def __init__(self):
        self.samples = deque(maxlen=1800)

    def clear(self):
        self.samples.clear()

    def add(self, now, face, inference_ms=0):
        self.samples.append((now, face, inference_ms))

    def summarize(self, now, window_ms=3000, speaking=False, end_age_ms=0):
        window_ms = max(200, min(120000, window_ms))
        end = now-max(0,min(5000,end_age_ms))/1000
        rows = [r for r in self.samples if 0 <= end-r[0] <= window_ms/1000]
        age = round((now-self.samples[-1][0])*1000) if self.samples else None
        result = dict(status='unavailable', reason='no_face', age_ms=age,
                      window_ms=window_ms, sample_count=len(rows), valid_ratio=0,
                      provider='', scores={}, cues={}, head={}, inference_ms=0,
                      speaking=speaking)
        if not rows or age is None or age > 1000:
            result['reason'] = 'stale' if self.samples else 'no_samples'
            return result
        # Never reuse a face after it leaves the frame, even if older samples exist.
        if not rows[-1][1] or not self.samples[-1][1]:
            return result
        valid = [r for r in rows if r[1] and r[1].get('usable')]
        result['valid_ratio'] = round(len(valid)/len(rows), 2)
        if len(valid) < 3 or result['valid_ratio'] < .5 or not rows[-1][1].get('usable'):
            result['reason'] = 'insufficient_quality'
            return result
        def avg(group, name):
            values = [r[1].get(group, {}).get(name, 0) for r in valid]
            return round(mean(v if math.isfinite(v) else 0 for v in values), 2)
        scores = {name: avg('scores', name) for name in LABELS}
        cues = {name: avg('cues', name) for name in ('smile', 'browTension', 'browRaise', 'eyeClosure', 'mouthOpen', 'eyeWide')}
        label = max(scores, key=scores.get)
        # Talking mouths alone are not evidence of surprise. Do not relabel as neutral.
        if speaking and label == 'surprise' and cues['browRaise'] < .25 and cues['eyeWide'] < .2:
            label = 'uncertain'
        ordered = sorted(scores.values(), reverse=True)
        if ordered[0] < .45 or ordered[0]-ordered[1] < .1:
            label = 'uncertain'
        result.update(status='observed', reason='', provider=valid[-1][1]['provider'],
                      label=label, score=max(scores.values()), scores=scores, cues=cues,
                      head={n: avg('head', n) for n in ('yaw', 'pitch', 'roll')},
                      inference_ms=round(mean(r[2] for r in valid), 1),
                      latest=valid[-1][1])
        return result
