# Avatar additions — 2026-09-28

Emma uses the built-in image_gen tool, followed by local LAM reconstruction. Reference: `data/gaussian/western-emma-reference.png`.

Final image prompt:

Create a photorealistic studio reference portrait for single-photo 3D Gaussian head reconstruction. A fictional adult white European woman around 30, natural facial proportions, brown shoulder-length hair tucked behind both ears, no glasses, no jewelry, subtle natural skin texture, simple light gray crew-neck shirt. Exactly frontal, eyes looking straight into camera, head and shoulders level with no yaw/pitch/roll, relaxed neutral expression, lips gently touching without pursing, no smile or teeth. Full head including hair and both ears, neck and shoulders visible, centered square composition with comfortable margins. Soft even diffuse frontal lighting, minimal shadows, plain light gray background. Portrait lens appearance, no wide-angle distortion, no beauty retouching, no text, no watermark. This must be a new fictional identity unrelated to previous reference images.

The second entry is reconstructed locally from the user's attached PNG (`codex-clipboard-b0430432-ed3f-41f2-a18c-64721f15d279.png`). It is labeled **기본 남성 · 첨부 이미지 기반**, and is not represented as the original GaussianAvatars trained checkpoint. The official GaussianAvatars demo uses its own mesh-bound PLY/FLAME pipeline, unlike the current LAM ARKit ZIP runtime. Screenshot resolution, open mouth and non-frontal pose can reduce reconstruction fidelity.

Source images, generated assets, camera calibration, generation metadata, and per-job logs are stored under `data/gaussian/avatars/<id>/` and `data/gaussian/jobs/<id>/`.
