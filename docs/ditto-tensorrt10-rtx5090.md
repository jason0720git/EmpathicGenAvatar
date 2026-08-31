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

`audit --all`은 알려진 warp blocker까지 포함해 release gate를 확인한다. 반대로
`--supported`는 현재 TensorRT 10에서 build/execute 가능한 모든 모델만 선택하므로,
자동화의 성공 여부를 명확하게 판정할 때 사용한다.

## 2026-08-28 RTX 5090 감사 결과

TensorRT 10.8.0.43, NVIDIA GeForce RTX 5090에서 appearance extractor, motion
extractor, stitch, decoder, HuBERT, LMDM 및 검출 모델은 ONNX parser를 통과했다.
HuBERT는 온라인 40 ms chunk의 고정 profile `[1, 6480]`을 사용한다. LMDM은 80-frame
block 하나를 TensorRT로 실행할 수 있지만, diffusion step loop 자체는 Python
orchestration에 남는다.

`warp_network.onnx`는 `GridSample3D` TensorRT-8 custom plugin을 요구한다. 제공된
`libgrid_sample_3d_plugin.so`는 TensorRT 8 ABI용이며 TensorRT 10에 로드하지 않는다.
`warp_network_ori.onnx`도 5D grid sample을 사용하므로 TensorRT 10 native GridSample의
4D 제약으로 대체되지 않는다. 따라서 현재 상태에서는 **최종 합성 엔진이 없으므로
TensorRT 전체 renderer를 활성화하지 않는다**. 생성된 부분 엔진을 현재 PyTorch
서비스에 섞어 쓰지 않는 이유도 프레임 parity를 보장하기 위해서다.

## 다음 release gate

1. TensorRT 10 API로 GridSample3D plugin을 포팅하고, ONNX node 이름/version/namespace를
   일치시킨다.
2. 해당 plugin을 RTX 5090/TensorRT 10.8에서 컴파일하고 `warp_network` parser/build를
   통과시킨다.
3. PyTorch와 TRT로 동일 source+WAV를 25 fps로 렌더링해 frame-wise pixel/landmark 및
   lip timing을 비교한다. 허용 기준을 정하기 전에는 서비스 라우팅을 바꾸지 않는다.
4. engine manifest의 GPU/driver/TRT version이 배포 노드와 일치할 때만 `DITTO_MODEL_ROOT`
   를 엔진 디렉터리로 전환한다. 불일치나 실행 실패 시에는 명시적으로 PyTorch로
   fallback하고 telemetry에 `runtime=pytorch_fallback`을 남긴다.

이 gate를 통과하면 first-frame 병목 중 LMDM/decoder/feature 추론 시간을 줄일 여지가
있다. 하지만 음성 context(13 preroll frames), 확산 step 수, JPEG/WebSocket 전송은
별도 병목이므로 엔진화만으로 전체 2.5초를 0초로 만들지는 않는다.
