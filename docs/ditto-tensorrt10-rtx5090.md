# Ditto TensorRT 10 / RTX 5090 엔진화

## 목적과 안전 경계

Ditto 배포본의 `ditto_trt_Ampere_Plus` 엔진은 TensorRT 8/Ampere용이다. RTX 5090
TensorRT 10.8에서 역직렬화하거나 재사용하지 않는다. 새 엔진은 항상 GPU 워커 안에서
원본 ONNX(`/models/ditto/ditto_onnx`, read-only)를 입력으로 삼아
`/data/engines/ditto-trt10`에 생성한다. 현재 서비스의 PyTorch Ditto Realtime은 이
디렉터리를 읽지 않으므로, 빌드 실패가 라이브 데모의 품질이나 가용성을 바꾸지 않는다.

## 실행 절차

```bash
# TensorRT 10 parser/shape 감사 (JSON manifest 생성)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec -T \
  avatar-worker-realtime python -m app.trt10_ditto audit --all

# 재현 가능한 RTX 5090 엔진 생성
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec -T \
  avatar-worker-realtime python -m app.trt10_ditto build --supported

# 각 생성 엔진을 deserialize + 실제 GPU 실행(trtexec)으로 검사
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec -T \
  avatar-worker-realtime python -m app.trt10_ditto verify --supported
```

각 단계는 `/data/engines/ditto-trt10/{audit,build,verify}-manifest.json`에
GPU명·드라이버·TensorRT 버전·입출력 shape·엔진 크기·실패 사유를 남긴다. 이 파일은
원본 음성/이미지/대화 텍스트를 저장하지 않는다.

`audit --all`은 대체용 `warp_network_ori`까지 포함해 호환성 상태를 확인한다. 반대로
`--supported`는 현재 TensorRT 10에서 build/execute 가능한 모든 production 모델(새
`warp_network` plugin 포함)만 선택하므로, 자동화의 성공 여부를 명확하게 판정할 때 사용한다.

`warp_network`까지 다시 생성한 뒤에는 다음 두 gate를 실행한다.

```bash
# Plugin을 포함한 engine deserialize/execute
/opt/tensorrt/bin/trtexec --loadEngine=/data/engines/ditto-trt10/warp_network_fp16.engine \
  --plugins=/worker/trt_plugins/libditto_gridsample3d_trt10.so --warmUp=200 --duration=1

# 동일 텐서 기준 PyTorch vs TensorRT warp numerical parity
python -m app.trt10_warp_parity

# 실제 StreamSDK online pipeline smoke test (사용자 미디어를 저장하지 않음)
python -m app.trt10_stream_smoke
```

## 2026-08-28 RTX 5090 감사 결과

TensorRT 10.8.0.43, NVIDIA GeForce RTX 5090에서 appearance extractor, motion
extractor, stitch, decoder, HuBERT, LMDM 및 검출 모델은 ONNX parser를 통과했다.
HuBERT는 온라인 40 ms chunk의 고정 profile `[1, 6480]`을 사용한다. LMDM은 80-frame
block 하나를 TensorRT로 실행할 수 있지만, diffusion step loop 자체는 Python
orchestration에 남는다.

`warp_network.onnx`는 `GridSample3D` TensorRT-8 custom plugin을 요구한다. 제공된
`libgrid_sample_3d_plugin.so`는 TensorRT 8 ABI용이며 TensorRT 10에 로드할 수 없다.
이 프로젝트는 그 연산의 TensorRT 10 V2DynamicExt 구현을
`workers/avatar/trt_plugins/libditto_gridsample3d_trt10.so`로 새로 빌드한다.
TensorRT 10 CLI에서는 이 legacy ONNX-parser plugin을 `--plugins`로 로드해야 하며,
`--dynamicPlugins`(V3 `getCreators` ABI)는 사용하지 않는다.

RTX 5090에서 새 plugin을 포함한 `warp_network_fp16.engine` 생성·역직렬화·실행까지
통과했다. PyTorch warp와 동일 seed 입력의 component parity는 max abs `0.00791`, mean
abs `0.000355`로 gate(max `0.03`, mean `0.003`)를 통과했다. `warp_network_ori.onnx`는
5D grid sample을 사용하므로 TensorRT 10 native GridSample의 4D 제약으로 대체되지 않는다.

동일한 2-step / 40 ms online smoke 조건에서 TensorRT StreamSDK는 40 frame을 만들고
첫 frame을 `302ms`에 냈다. 이 값은 TTS·HTTP·WebSocket·browser playout과 별개인
GPU pipeline measurement이며, 사용자 체감 first packet은 별도 end-to-end telemetry로
계속 비교한다.

## 다음 release gate

1. PyTorch와 TRT로 동일 source+WAV를 25 fps로 렌더링해 frame-wise pixel/landmark 및
   lip timing을 비교한다. 허용 기준을 정하기 전에는 서비스 라우팅을 바꾸지 않는다.
2. engine manifest의 GPU/driver/TRT version이 배포 노드와 일치할 때만 `DITTO_MODEL_ROOT`
   를 엔진 디렉터리로 전환한다. 불일치나 실행 실패 시에는 명시적으로 PyTorch로
   fallback하고 telemetry에 `runtime=pytorch_fallback`을 남긴다.

이 gate를 통과하면 first-frame 병목 중 LMDM/decoder/feature 추론 시간을 줄일 여지가
있다. 하지만 음성 context(13 preroll frames), 확산 step 수, JPEG/WebSocket 전송은
별도 병목이므로 엔진화만으로 전체 2.5초를 0초로 만들지는 않는다.

## 웹 대화에서의 A/B

일반 GPU compose 기동 시 PyTorch Realtime과 TensorRT 10 worker가 모두 준비된다.
웹의 시작 화면에서 **Ditto Realtime TensorRT 10**을 고르면 API가 전용 worker로
자동 라우팅한다. 환경변수·Docker 명령을 바꿀 필요가 없다. 같은 아바타·대본으로
PyTorch Realtime과 TensorRT 10을 각각 10회 테스트해 first packet, playback start,
lip-sync, 얼굴 경계 artifact를 비교한다.
