import faulthandler

faulthandler.enable()  # report native crashes (e.g. in Windows components) instead of exiting silently

from .cli import main  # noqa: E402

raise SystemExit(main())
