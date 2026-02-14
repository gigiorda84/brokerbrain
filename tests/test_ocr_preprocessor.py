"""Tests for OCR image preprocessor — no mocks, in-memory Pillow images."""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from src.ocr.preprocessor import (
    MAX_LONG_SIDE,
    ImagePreprocessingError,
    PreprocessedImage,
    preprocess_image,
)


def _make_image(width: int = 100, height: int = 100, mode: str = "RGB", fmt: str = "JPEG") -> bytes:
    """Create an in-memory image and return raw bytes."""
    img = Image.new(mode, (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _make_image_with_exif_rotation(width: int = 100, height: int = 200) -> bytes:
    """Create a JPEG with EXIF orientation tag 6 (rotated 90 CW)."""
    img = Image.new("RGB", (width, height), color="blue")
    # Pillow's ExifTranspose reads tag 0x0112 (Orientation)
    from PIL.ExifTags import Base as ExifBase
    exif = img.getexif()
    exif[ExifBase.Orientation] = 6  # Rotate 270 CW (displayed as 90 CW)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


class TestPreprocessImage:
    def test_small_image_preserved(self) -> None:
        raw = _make_image(200, 150)
        result = preprocess_image(raw)
        assert isinstance(result, PreprocessedImage)
        assert result.final_width == 200
        assert result.final_height == 150

    def test_large_image_resized(self) -> None:
        raw = _make_image(3000, 2000)
        result = preprocess_image(raw)
        assert max(result.final_width, result.final_height) <= MAX_LONG_SIDE
        assert result.original_width == 3000
        assert result.original_height == 2000

    def test_exif_rotation_applied(self) -> None:
        raw = _make_image_with_exif_rotation(100, 200)
        result = preprocess_image(raw)
        # After 90-degree rotation, width and height should swap
        assert result.final_width == 200
        assert result.final_height == 100

    def test_rgba_converted_to_rgb(self) -> None:
        raw = _make_image(100, 100, mode="RGBA", fmt="PNG")
        result = preprocess_image(raw)
        # Result should be valid JPEG (no alpha)
        img = Image.open(io.BytesIO(result.jpeg_bytes))
        assert img.mode == "RGB"

    def test_corrupt_bytes_raises(self) -> None:
        with pytest.raises(ImagePreprocessingError) as exc_info:
            preprocess_image(b"not an image at all")
        assert "Non riesco a leggere" in exc_info.value.user_message

    def test_valid_jpeg_output(self) -> None:
        raw = _make_image(300, 200)
        result = preprocess_image(raw)
        # Verify output is valid JPEG
        img = Image.open(io.BytesIO(result.jpeg_bytes))
        assert img.format == "JPEG"

    def test_base64_roundtrip(self) -> None:
        raw = _make_image(100, 100)
        result = preprocess_image(raw)
        decoded = base64.b64decode(result.base64_str)
        assert decoded == result.jpeg_bytes

    def test_low_contrast_enhancement(self) -> None:
        # Create a very low contrast image (all nearly the same grey)
        img = Image.new("L", (100, 100), color=128)
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        raw = buf.getvalue()
        # Should not raise — enhancement is best-effort
        result = preprocess_image(raw)
        assert result.final_width == 100
