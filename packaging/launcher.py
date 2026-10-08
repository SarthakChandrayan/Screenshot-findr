"""Entry point for the packaged Windows app (ScreenshotFindr.exe)."""

import faulthandler
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if sys.stderr is not None:
        faulthandler.enable()
    if len(sys.argv) > 1 and sys.argv[1] == "--ocr-probe":
        # Child process used to test Windows OCR safely (see ocr.probe_windows_ocr).
        from screenshot_findr.ocr import _probe_main

        sys.exit(_probe_main())
    from screenshot_findr.cli import main

    sys.exit(main())
