# Contributing

Thanks for taking a look at MI2 AIO. The project targets **Windows** and the
Melvor Idle 2 demo build. Much of the automation depends on fixed reference
coordinates, so keep the rules in [AGENTS.md](AGENTS.md) and
[docs/display.md](docs/display.md) in mind.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item config\settings.default.toml config\settings.toml
```

`config/settings.toml` is git-ignored: it holds your character pin and local
preferences. `config/settings.default.toml` is the bundled template and the
reset target.

`tools/bin/SaveTool.exe` is built from `tools/SaveTool` by
`scripts/build_savetool.ps1`; `doctor` builds it automatically if missing.

## Before opening a pull request

```powershell
ruff check src tests
pytest -q
python -m mi2_aio doctor   # needs the game running on Windows
```

- Keep new UI regions and click points in `src/mi2_aio/ui.py` in reference
  space (2560x1369). Never use desktop or monitor coordinates.
- Add tests for new readers/parsers where practical.
- Update the matching `docs/*.md` page and the README when behaviour changes.
- Bump the version in `src/mi2_aio/__init__.py` and `pyproject.toml`.
- Do not commit `config/settings.toml`, logs, captures, or build output.

## Reporting bugs

Open an issue with:

- what task/feature was running,
- the relevant lines from the in-app Logs view or `logs/`,
- the game build (`doctor` shows it) and your display scale/resolution,
- a screenshot of the game page if the UI reader misidentified something.

Please don't attach your save file unless you are comfortable sharing the
character data in it.
