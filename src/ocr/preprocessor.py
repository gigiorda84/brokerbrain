"""Image preprocessing for the OCR pipeline.

Synchronous, pure Python (Pillow). Normalizes images before VLM processing:
EXIF orientation, resize, contrast enhancement, RGB conversion, base64 encoding.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image, ImageOps

MAX_LONG_SIDE = 1440
JPEG_QUALITY = 85
LOW_CONTRAST_CUTOFF = 0.05


class ImagePreprocessingError(Exception):
    """Raised when image preprocessing fails."""

    def __init__(self, message: str, user_message: str) -> None:
        super().__init__(message)
        self.user_message = user_message


@dataclass(frozen=True)
class PreprocessedImage:
    """Result of image preprocessing."""

    jpeg_bytes: bytes
    base64_str: str
    original_width: int
    original_height: int
    final_width: int
    final_height: int


def preprocess_image(raw_bytes: bytes) -> PreprocessedImage:
    """Preprocess a raw image for VLM consumption.

    Steps:
        1. Decode image bytes
        2. Apply EXIF orientation
        3. Resize if longer side exceeds MAX_LONG_SIDE
        4. Enhance contrast if low
        5. Convert to RGB JPEG
        6. Base64 encode

    Args:
        raw_bytes: Raw image bytes (any format Pillow supports).

    Returns:
        PreprocessedImage with JPEG bytes, base64 string, and dimensions.

    Raises:
        ImagePreprocessingError: If the image cannot be decoded or processed.
    """
    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except Exception as exc:
        raise ImagePreprocessingError(
            f"Cannot decode image: {exc}",
            user_message="Non riesco a leggere l'immagine. Per favore invii una foto leggibile del documento.",
        ) from exc

    original_width, original_height = img.size

    # EXIF orientation correction
    img = ImageOps.exif_transpose(img) or img

    # Resize if needed (preserve aspect ratio)
    long_side = max(img.size)
    if long_side > MAX_LONG_SIDE:
        ratio = MAX_LONG_SIDE / long_side
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    # Enhance contrast if low
    try:
        if _is_low_contrast(img):
            img = ImageOps.autocontrast(img)
    except Exception:
        pass  # Non-critical, skip on failure

    # Convert to RGB (drop alpha, handle grayscale)
    if img.mode != "RGB":
        img = img.convert("RGB")

    final_width, final_height = img.size

    # Encode to JPEG bytes
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    jpeg_bytes = buf.getvalue()

    # Base64 encode
    b64_str = base64.b64encode(jpeg_bytes).decode("ascii")

    return PreprocessedImage(
        jpeg_bytes=jpeg_bytes,
        base64_str=b64_str,
        original_width=original_width,
        original_height=original_height,
        final_width=final_width,
        final_height=final_height,
    )


def _is_low_contrast(img: Image.Image) -> bool:
    """Check if the image has low contrast by comparing extrema spread."""
    try:
        grayscale = img.convert("L")
        lo, hi = grayscale.getextrema()
        return (hi - lo) / 255.0 < LOW_CONTRAST_CUTOFF
    except Exception:
        return False
