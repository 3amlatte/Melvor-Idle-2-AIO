# Project rules for contributors and coding agents

## Display independence (hard requirement)

Every feature must run on **any screen, resolution, aspect ratio and display
scale**. The bot forces the game to a 2560x1369 client area, so:

- UI readers must consume `ui.normalize(capture_client(...))` images only.
- Click points and regions live in `src/mi2_aio/ui.py` in reference-space
  pixels; clicks must be scaled with `ui.to_client(...)`.
- Never use desktop/screen coordinates, monitor size, cursor position, or
  "maximized" assumptions to place a click or define a region.
- Templates must be captured at the reference size.
- Do not introduce a second reference size. If the reference must change, it is
  a project-wide change: update `ui.REFERENCE_SIZE`, re-capture every region and
  template, and update `docs/display.md`.

Full invariant, rules and verification matrix: [docs/display.md](docs/display.md).

## Before finishing a change

1. `python -m pytest -q` (all tests must pass).
2. `python -m mi2_aio doctor` (environment, client size, capture).
3. Run the affected task briefly (`--duration 1`) and confirm the log.
4. Update the matching doc in `docs/` and the README when behaviour changes.
5. Bump the app version in `src/mi2_aio/__init__.py` and `pyproject.toml`.
6. When adding or changing settings, update both `config/settings.toml` and
   `config/settings.default.toml` (the Diagnostics reset target).

## Versioning

Every update increments the trailing number: `0.4` → `0.42` → `0.43` → `0.44`.
If the change is minor/cosmetic (for example a bubble size), append another
digit: `0.42` → `0.421`. Milestone updates jump to the next tenth:
`0.31` → `0.4`, `0.44` → `0.5`.

The version is part of every update. Keep `__version__` and the `pyproject.toml`
version in sync (covered by `tests/test_version.py`). The desktop window title,
`--version`, `doctor` and the app metadata all read `__version__`.
