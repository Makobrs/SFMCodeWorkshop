"""Early bootstrap: diagnostics and headless self-test before Qt imports."""
from __future__ import annotations

import sys

from .core import crashlog


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    if "--self-test" in args:
        from .self_test import run as self_test

        return self_test()
    crashlog.install()
    try:
        from .app import run

        return run()
    except SystemExit:
        raise
    except BaseException:
        crashlog.report_startup_failure()
        crashlog.show_startup_failure()
        return 1
