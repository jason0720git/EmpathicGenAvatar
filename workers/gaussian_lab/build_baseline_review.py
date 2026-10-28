"""Publish local, self-contained evidence for the completed LAM baseline experiment."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data/gaussian/reconstruction-v9'
OUT = ROOT / 'apps/web/public/gaussian-review-v9'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sections = []
    for slug, label, aid in [('emma','Emma','2a80fe76d5f44beba2a3c0ac'),
                             ('seoyeon','서연','88546d4a362b4a97979c5360')]:
        target = OUT / slug; target.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / 'data/gaussian/avatars' / aid / 'source.png', target/'source.png')
        for filename in ['native-neutral.png','native-jaw-contact.png','native-motion.mp4','native-validation.json']:
            shutil.copyfile(DATA/slug/filename, target/filename)
        for path in (DATA/'web').glob(f'{slug}-*.png'):
            shutil.copyfile(path, target/path.name)
        screenshots = ''.join(f'<figure><img loading="lazy" src="{slug}/{slug}-{variant}-{pose}.png"><figcaption>{caption} · {pose}</figcaption></figure>'
                              for variant,caption in [('raw','무보정 자산 / 셰이더 보정 꺼짐'),('current','기존 자산 / 기존 보정 켜짐')]
                              for pose in ['neutral','blink','jaw']
                              if (target/f'{slug}-{variant}-{pose}.png').exists())
        sections.append(f'''<section><h2>{label}</h2><div class="three">
          <figure><img alt="{label} 입력 사진" src="{slug}/source.png"><figcaption>입력 사진</figcaption></figure>
          <figure><img alt="{label} LAM 중립 렌더링" src="{slug}/native-neutral.png"><figcaption>LAM 재생성 · 공식 Python 렌더러 / 중립</figcaption></figure>
          <figure><video aria-label="{label} 공식 LAM 모션" controls loop muted preload="metadata" poster="{slug}/native-neutral.png" src="{slug}/native-motion.mp4"></video><figcaption>같은 기록된 FLAME 표정·턱·눈 모션 / 90프레임</figcaption></figure>
          </div><h3>턱 관절만 단계적으로 열기</h3><img class="wide" src="{slug}/native-jaw-contact.png">
          <p>왼쪽부터 0 / 0.10 / 0.25 / 0.45 rad. 큰 개구에서 밝고 평평한 구강이 나타납니다. 웹 ARKit jawOpen 수치와 같은 단위가 아닙니다.</p>
          <details><summary>웹 무보정·현재 보정 대조 캡처</summary><div class="two">{screenshots}</div></details></section>''')
    html = '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
      <title>3DGS 생성 비교 · LAM 기준 실험</title><style>
      *{box-sizing:border-box}body{margin:0;background:#10232d;color:#e9f1f3;font:16px/1.65 system-ui,sans-serif}main{max-width:1320px;margin:auto;padding:36px 28px}h1{font-size:32px;line-height:1.3}h2{font-size:25px}h3{font-size:18px}a{color:#83e0cf}p{color:#bfd1d8}section{background:#19333f;border:1px solid #38535e;border-radius:16px;padding:24px;margin:24px 0}figure{margin:0;min-width:0}figcaption{font-size:14px;color:#bfd1d8;padding:10px 0}img,video{display:block;width:100%;border-radius:8px} .three{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.three img,.three video{aspect-ratio:1;object-fit:contain;background:#fff}.two{display:grid;grid-template-columns:repeat(2,1fr);gap:18px;margin-top:18px}.wide{background:white}summary{cursor:pointer;color:#83e0cf;font-weight:600}.status{display:flex;flex-wrap:wrap;gap:12px}.badge{border-radius:8px;padding:10px 16px;background:#225448}.blocked{background:#634b2e}code{overflow-wrap:anywhere;color:#fff} @media(max-width:800px){.three,.two{grid-template-columns:1fr}main{padding:20px}h1{font-size:25px}}
      </style><main><p>2026-09-29 · 재현 가능한 원인 분리 실험</p><h1>원본 LAM에서도 입·눈 문제가 생기는가?</h1>
      <div class="status"><span class="badge">LAM 두 얼굴 재생성·비교 완료</span><span class="badge blocked">CAP4D: 공식 FLAME 자산 대기 / 생성 미실행</span></div>
      <p>기존 아바타는 보존했습니다. 새 “LAM 무보정 비교용 v9”는 진단 기준이며, 개선된 최종 아바타가 아닙니다.</p>
      <p><a href="/gaussian">대화·WAV 테스트</a> · <a href="/gaussian/rig-check">직접 눈·입·표정 검사</a></p>
      <section><h2>확인된 결과</h2><ul><li>입 안의 밝은 면은 웹 보정 없이 공식 Python 렌더링에서도 두 얼굴에 재현됩니다.</li><li>웹 원본 리그는 blink=1이 GPU에 전달돼도 눈꺼풀 위로 안구가 노출됩니다.</li><li>기존 보정은 안구 노출을 줄이지만 눈꺼풀의 평평함 등 품질 문제가 남습니다.</li><li>사진·보정·리그·카메라 영향을 분리해야 합니다. 이 두 사례로 인종이 원인이라고 판단할 수 없습니다.</li></ul>
      <p>정면 사진과 3D 중립 프레임은 목 자세·중립화·구도 차이가 있어 픽셀 단위 동일 비교가 아닙니다. Python FLAME 모션과 웹 ARKit 리그의 계수도 서로 다릅니다.</p></section>'''+''.join(sections)+'''
      <section><h2>CAP4D 준비 상태</h2><p>공식 MMDM 가중치 3.60GB 다운로드·SHA-256·830개 텐서 유한값 검사 완료. RTX 5090 / CUDA 12.8에서 gsplat 전방·역전파 검사 통과. 이는 전체 CAP4D 생성 성공을 의미하지 않습니다.</p>
      <p>현재 필요한 파일: <code>flame2023_no_jaw.pkl</code>. 맞춤 사진 추적용 Pixel3DMM/MICA는 FLAME2020 자산도 사용합니다. 공식 파일을 확보한 뒤 추적 환경 마무리 → 공식 smoke → Emma·서연 생성 → 학습·동일 모션 검증 순서로 이어갑니다.</p>
      <p><a href="https://flame.is.tue.mpg.de/">공식 FLAME 다운로드·계정</a> · <a href="https://github.com/felixtaubner/cap4d">CAP4D 공식 안내</a></p></section></main></html>'''
    (OUT/'index.html').write_text(html, encoding='utf8')
    print(OUT/'index.html')


if __name__=='__main__': main()
