"""Desktop app entry point (source and packaged)."""

from __future__ import annotations

import sys


def _console_preflight() -> int:
    from mi2_aio.preflight import check_environment, format_report

    result = check_environment()
    if result.ok:
        return 0
    print(format_report(result))
    return 2


def main() -> int:
    # A source checkout can check dependencies before importing PySide6. The
    # frozen app bundles them, and shows the full startup-check dialog instead.
    if not getattr(sys, "frozen", False):
        code = _console_preflight()
        if code:
            if sys.stdin.isatty():
                try:
                    input("\nPress Enter to close...")
                except EOFError:
                    pass
            return code
    from mi2_aio.app import main as app_main

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
