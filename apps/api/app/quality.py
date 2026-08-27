from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError

from .models import ImageQuality


class ImageValidationError(ValueError):
    pass


ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
FORMAT_TO_CONTENT_TYPE = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
Image.MAX_IMAGE_PIXELS = 40_000_000


def inspect_image(raw: bytes, content_type: str | None) -> ImageQuality:
    """Validate the safe subset that can be checked without a biometric model.

    This is deliberately not marketed as face ownership or liveness verification.
    Production should add a dedicated one-face detector, abuse/moderation service,
    and an auditable identity/liveness workflow before any sharing is enabled.
    """
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ImageValidationError("JPG, PNG 또는 WebP 파일만 업로드할 수 있습니다.")
    if not raw:
        raise ImageValidationError("빈 이미지 파일은 사용할 수 없습니다.")
    if len(raw) > 12 * 1024 * 1024:
        raise ImageValidationError("이미지는 12MB 이하로 업로드해 주세요.")
    try:
        image = Image.open(BytesIO(raw))
        actual_content_type = FORMAT_TO_CONTENT_TYPE.get(image.format or "")
        width, height = image.size
        if actual_content_type is None:
            raise ImageValidationError("JPG, PNG 또는 WebP 파일만 업로드할 수 있습니다.")
        if actual_content_type != content_type:
            raise ImageValidationError("파일 내용과 업로드 형식이 일치하지 않습니다.")
        if width < 256 or height < 256:
            raise ImageValidationError("가로와 세로가 각각 256px 이상인 사진을 사용해 주세요.")
        if width * height > 40_000_000:
            raise ImageValidationError("이미지 해상도가 너무 큽니다. 40MP 이하로 줄여 주세요.")
        image.verify()
        image = Image.open(BytesIO(raw)).convert("RGB")
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as error:
        raise ImageValidationError("손상되었거나 지원하지 않는 이미지입니다.") from error

    hints: list[str] = []
    score = 100
    if min(width, height) < 512:
        score -= 17
        hints.append("512px 이상 사진을 사용하면 얼굴 디테일이 더 안정적입니다.")
    ratio = width / height
    if ratio < 0.55 or ratio > 1.8:
        score -= 9
        hints.append("세로 또는 정사각형에 가까운 상반신 사진을 권장합니다.")
    thumbnail = image.copy()
    thumbnail.thumbnail((240, 240))
    edge = thumbnail.filter(ImageFilter.FIND_EDGES)
    contrast = sum(ImageStat.Stat(edge).var) / 3
    if contrast < 170:
        score -= 18
        hints.append("사진이 흐릿할 수 있습니다. 밝고 선명한 정면 사진을 권장합니다.")
    if not hints:
        hints.append("기본 해상도·비율 검사를 통과했습니다. 얼굴 수와 권리 검증은 별도 보호 절차가 필요합니다.")
    return ImageQuality(width=width, height=height, score=max(0, score), hints=hints)
