# MI2 AIO

[![CI](https://github.com/3amlatte/Melvor-Idle-2-AIO/actions/workflows/ci.yml/badge.svg)](https://github.com/3amlatte/Melvor-Idle-2-AIO/actions/workflows/ci.yml)

Local, config-driven automation toolkit for **Melvor Idle 2** on Windows. It
reads the game's save file and UI, then sends normal mouse/keyboard input — it
does not patch the game or modify saves.

> **Unofficial project.** Not affiliated with or endorsed by the Melvor Idle
> developers. Automation may violate the game's terms of service and can put your
> account at risk; use it at your own discretion. Game names, artwork, UI
> reference crops and extracted game data remain their owners' property and are
> not covered by the MIT license — see [NOTICE.md](NOTICE.md).

## Download (no Python required)

Download **`MI2-AIO-<version>-win64.zip`** from
[Releases](https://github.com/3amlatte/Melvor-Idle-2-AIO/releases), extract it,
and run **`MI2 AIO.exe`**. No Python, pip, .NET or commands are needed.

- The first launch checks your setup and explains anything missing.
- Settings and logs live in `%APPDATA%\MI2 AIO`.
- Keep `MI2 AIO.exe` next to `_internal`; don't move individual files.
- The build is unsigned, so Windows SmartScreen may warn. Use **More info →
  Run anyway** after checking the SHA256 published with the release. Code
  signing options are in [docs/signing.md](docs/signing.md).

## Requirements

- **Packaged release:** Windows 10/11 and Melvor Idle 2. Nothing else.
- **From source:** Python 3.11+ and the .NET 8 SDK (to build the save helper).

Melvor Idle 2 is tested with the demo build `v0.11.4-alpha`.

## Quick start (from source)

```powershell
git clone https://github.com/3amlatte/Melvor-Idle-2-AIO.git
cd Melvor-Idle-2-AIO

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Local settings are git-ignored.
Copy-Item config\settings.default.toml config\settings.toml

# Verify the window, save file, header and capture.
python -m mi2_aio doctor

# Launch the desktop app. The first launch checks Python, packages, the .NET
# save helper, saves and the game window, and explains anything that is missing.
python -m mi2_aio gui
```

Standalone build:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_app.ps1
# -> dist\MI2 AIO\MI2 AIO.exe
```

Release package (portable zip + SHA256):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package_app.ps1
# -> dist\MI2-AIO-<version>-win64.zip
```

The packaged app keeps writable config/logs in `%APPDATA%\MI2 AIO`. GitHub
Actions builds and attaches the zip for every `v*` tag.

## Features

- **Combat** — Slayer, Dungeons, Farm Prayer Points, automatic melee style and
  owned-gear upgrades.
- **Farming** — allotments, herbs, trees, flowers, orchard, compost bins and The
  Mill. Farming settings live on **Features → Farming**.
- **Fishing** — 7 locations / 23 spots with a fish database; pick a location and
  spot before starting.
- **Cooking** — Basic Food recipes; optionally stop after an exact product count
  via the in-game Products Gained condition.
- **Queue** — per-character task list with its own duration, fishing location/spot
  and cooking recipe/amount. Stop pauses; Resume continues.
- **Desktop app** - Dashboard, Features, Queue, Settings, Diagnostics, live logs,
  character bubbles, idle failsafe and pre-run action restore.
- **Startup check** - the first launch validates Python, packages, the .NET save
  helper, saves and the game window, with install instructions for missing
  items. Re-run it from **Diagnostics → Startup check**.
- **Display-independent** - readers/click points use the fixed 2560×1369
  reference space and scale to the live game window.

Example queue: Dungeons → Fishing Glowfin ×100 → Cooking Glowfin ×100 → Dungeons.

## CLI

```powershell
python -m mi2_aio preflight
python -m mi2_aio doctor
python -m mi2_aio status
python -m mi2_aio tasks
python -m mi2_aio features

python -m mi2_aio run --task slayer --duration 60
python -m mi2_aio run --task fishing --location "Shrapnel River" --spot "Pebble Bank"
python -m mi2_aio run --task cooking --recipe Glowfin --amount 100

python -m mi2_aio farm --inspect   # show farming state without changing it
python -m mi2_aio gui
```

Task names: `slayer`, `dungeons`, `farm_bones`, `fishing`, `cooking`, `observe`.
Durations are minutes; `0` means until stopped.

## Configuration

- `config/settings.toml` — your local settings (git-ignored). Copy
  `config/settings.default.toml` to create it.
- General bot options live in **Settings**; feature-specific options live on
  their **Features** page.
- **Diagnostics → Reset to default settings** restores the bundled template.
- Settings are validated before writing, with comments and ordering preserved.

## Safety

- Back up `%APPDATA%\Games By Malcs\Melvor Idle 2\steam\<SteamID>\saves` first.
- Keep the game **unminimized**; covered, unfocused and off-screen are supported.
- Start with short runs (`--duration 10`) and watch the log before running
  unattended.
- Use **Stop**, the `STOP` file, or `--duration` to end a run.

## Documentation

| Topic | Document |
| --- | --- |
| Desktop app and packaging | [docs/ui.md](docs/ui.md) |
| Code signing | [docs/signing.md](docs/signing.md) |
| Display independence | [docs/display.md](docs/display.md) |
| Combat, Slayer, Dungeons, gear | [docs/combat.md](docs/combat.md), [docs/combat-gear.md](docs/combat-gear.md), [docs/slayer.md](docs/slayer.md) |
| Farming | [docs/farming.md](docs/farming.md) |
| Fishing | [docs/fishing.md](docs/fishing.md) |
| Cooking | [docs/cooking.md](docs/cooking.md) |
| Prayer upkeep | [docs/prayer.md](docs/prayer.md) |
| Failsafe and restore | [docs/failsafe.md](docs/failsafe.md), [docs/restore.md](docs/restore.md) |
| Save format and game modes | [docs/save-format.md](docs/save-format.md), [docs/game-modes.md](docs/game-modes.md) |
| Background operation | [docs/background-operation.md](docs/background-operation.md) |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Tests and lint:

```powershell
ruff check src tests
pytest -q
```

## License

Source code and documentation: **MIT** ([LICENSE](LICENSE)). Third-party
libraries keep their own licenses; game content and extracted data are excluded
from the MIT grant ([NOTICE.md](NOTICE.md)).
