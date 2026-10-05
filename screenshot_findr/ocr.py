"""Extract text from images.

On Windows 10/11 we use the OCR engine built into Windows (via the `winrt`
packages), so nothing else has to be installed. Tesseract is supported as a
fallback on any OS if `pytesseract` and the tesseract binary are available.
"""

from __future__ import annotations

import asyncio
import os
from typing import Callable, Optional

OcrFunc = Callable[[str], str]


def _windows_ocr() -> Optional[OcrFunc]:
    try:
        from winrt.windows.graphics.imaging import (
            BitmapAlphaMode,
            BitmapDecoder,
            BitmapPixelFormat,
            BitmapTransform,
            ColorManagementMode,
            ExifOrientationMode,
        )
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage import FileAccessMode, StorageFile
    except ImportError:
        return None

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        return None

    async def recognize(path: str) -> str:
        file = await StorageFile.get_file_from_path_async(os.path.abspath(path))
        stream = await file.open_async(FileAccessMode.READ)
        try:
            decoder = await BitmapDecoder.create_async(stream)
            transform = BitmapTransform()
            # The engine refuses images bigger than max_image_dimension; scale those down.
            limit = OcrEngine.max_image_dimension
            longest = max(decoder.pixel_width, decoder.pixel_height)
            if longest > limit:
                scale = limit / longest
                transform.scaled_width = int(decoder.pixel_width * scale)
                transform.scaled_height = int(decoder.pixel_height * scale)
            bitmap = await decoder.get_software_bitmap_async(
                BitmapPixelFormat.BGRA8,
                BitmapAlphaMode.PREMULTIPLIED,
                transform,
                ExifOrientationMode.RESPECT_EXIF_ORIENTATION,
                ColorManagementMode.DO_NOT_COLOR_MANAGE,
            )
            result = await engine.recognize_async(bitmap)
            return "\n".join(line.text for line in result.lines)
        finally:
            stream.close()

    def run(path: str) -> str:
        return asyncio.run(recognize(path))

    return run


def _tesseract_ocr() -> Optional[OcrFunc]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None

    # Common install location of the UB Mannheim Windows build.
    default_exe = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.name == "nt" and os.path.exists(default_exe):
        pytesseract.pytesseract.tesseract_cmd = default_exe
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return None

    def run(path: str) -> str:
        with Image.open(path) as img:
            return pytesseract.image_to_string(img.convert("RGB"))

    return run


def get_ocr(preferred: str = "auto") -> tuple[str, Optional[OcrFunc]]:
    """Return (backend_name, ocr_function). The function is None if no OCR is available."""
    backends = {"windows": _windows_ocr, "tesseract": _tesseract_ocr}
    if preferred == "none":
        return "none", None
    order = [preferred] if preferred in backends else ["windows", "tesseract"]
    for name in order:
        func = backends[name]()
        if func is not None:
            return name, func
    return "none", None
