"""Extract text from images.

On Windows 10/11 we use the OCR engine built into Windows (via the `winrt`
packages), so nothing else has to be installed. Tesseract is supported as a
fallback on any OS if `pytesseract` and the tesseract binary are available.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
from typing import Callable, Optional

OcrFunc = Callable[[str], str]

_com_ready = threading.local()


def _init_winrt_thread() -> None:
    """Join the multi-threaded COM apartment (needed once per thread before using WinRT)."""
    if getattr(_com_ready, "done", False):
        return
    try:
        from winrt.runtime import ApartmentType, init_apartment

        init_apartment(ApartmentType.MULTI_THREADED)
    except Exception:
        pass  # already initialised, or an older winrt that does this on import
    _com_ready.done = True


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

    _init_winrt_thread()
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
            # winrt 3.x names each overload separately; older versions share one name.
            get_bitmap = getattr(decoder, "get_software_bitmap_transformed_async",
                                 decoder.get_software_bitmap_async)
            bitmap = await get_bitmap(
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
        _init_winrt_thread()
        return asyncio.run(recognize(path))

    return run


def probe_windows_ocr(timeout: float = 90, with_embedder: bool = False) -> tuple[bool, str]:
    """Try Windows OCR on a test image in a separate process.

    If the native WinRT code crashes, it takes down only that helper process,
    not the app. With `with_embedder`, the helper first loads the meaning-search
    runtime like the app does, so a clash between the two is caught here too.
    Returns (works, details).
    """
    cmd = [sys.executable, "-X", "faulthandler", "-m", "screenshot_findr.ocr", "--probe"]
    if with_embedder:
        cmd.append("--with-embedder")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "the Windows text reader did not answer in time"
    if proc.returncode == 0:
        return True, proc.stdout.strip()
    details = (proc.stderr or proc.stdout).strip().splitlines()
    return False, f"exit code {proc.returncode}: " + " | ".join(details[-6:])


def _probe_main() -> int:
    """Child-process side of probe_windows_ocr: OCR a generated image and print the text."""
    import tempfile

    from PIL import Image, ImageDraw, ImageFont

    if "--with-embedder" in sys.argv:
        try:
            import fastembed  # noqa: F401  (loads onnxruntime, as the app does before OCR)
        except ImportError:
            pass
    func = _windows_ocr()
    if func is None:
        print("winrt OCR packages missing or no OCR language installed", file=sys.stderr)
        return 3
    img = Image.new("RGB", (600, 120), "white")
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except OSError:
        font = ImageFont.load_default()
    ImageDraw.Draw(img).text((20, 30), "Hello Findr 123", fill="black", font=font)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "probe.png")
        img.save(path)
        text = func(path)
    print(text or "(no text read)")
    return 0


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


def get_ocr(preferred: str = "auto",
            with_embedder: bool = False) -> tuple[str, Optional[OcrFunc]]:
    """Return (backend_name, ocr_function). The function is None if no OCR is available.

    Pass with_embedder=True when meaning search is already loaded in this process.
    """
    backends = {"windows": _windows_ocr, "tesseract": _tesseract_ocr}
    if preferred == "none":
        return "none", None
    order = [preferred] if preferred in backends else ["windows", "tesseract"]
    for name in order:
        if name == "windows":
            if sys.platform != "win32":
                continue
            works, details = probe_windows_ocr(with_embedder=with_embedder)
            if not works:
                print(f"Windows text reader unavailable ({details})", file=sys.stderr)
                continue
        func = backends[name]()
        if func is not None:
            return name, func
    return "none", None


if __name__ == "__main__" and "--probe" in sys.argv:
    raise SystemExit(_probe_main())
