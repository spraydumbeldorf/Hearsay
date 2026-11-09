"""Entry point for both development (`python run.py`) and the packaged .exe."""
import multiprocessing
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        from ytx.cli import main as cli_main

        return cli_main(sys.argv[2:])
    from ytx.ui import main as ui_main

    return ui_main(sys.argv[1:])


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
