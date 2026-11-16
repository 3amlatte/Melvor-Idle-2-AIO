# Desktop app

The desktop app is a Python/PySide6 front end over the same automation code the
CLI uses. It can run while another window is focused; the game window may be
covered or off-screen, but it must not be minimized.

## Launch

Development (uses the repository venv):

```powershell
.\launch_ui.cmd
# or
python -m mi2_aio gui
# or
python -m mi2_aio.app
```

The app holds a named `MI2_AIO_App` lock; a second app window is refused. Every
bot run also holds a `MI2_AIO_Bot` lock, so the CLI and the app can never click
the game at the same time.

## Screens

### Dashboard

- **Quick Controls**: Pause / Resume / Stop, **Farm Run** and **Farm Prayer
  Points**.
- Live status: character, mode, current action, gold, Prayer points, bank item
  count, and HP (the HP bar is another 15% narrower). HP is read from the save
  (`Combat.Player` → `CharacterHealth.Current`) and the maximum is the Hitpoints
  level × 10, so the dashboard does not need a screenshot for it. Food/ammo keep
  a single launch-time screenshot fallback.
- A **Skills** grid showing every parsed skill as `Name Level`, refreshed from
  the save every 10 seconds. Astrology, Summoning, Herblore and Agility are not
  playable in the demo yet; they are greyed out and display `—`. The bottom of
  the grid shows **Total Level**, for example `Total Level 735/1320`; the
  maximum counts only the 22 playable skills at level 60.
- Recent activity (the full log is on the Diagnostics tab).
- The top-left **character bubbles** show one bubble per saved character. The
  active save is green; clicking another bubble makes the app exit to the Melvor
  character-selection screen, load that save, then refresh the header/status/
  skills.
- The top-right **bot** pill shows the bot run state: `Bot Idle`,
  `Bot Running`, `Bot Paused`, etc. The **client** pill next to it shows the
  character's current skill/entity (`Fishing`, `Combat`, `Woodcutting`, ...) or
  `Idle`; it is green while an action is active and gray when idle. Hovering
  either pill explains its value.
- While a dry run is active, a **DRY RUN** badge appears next to the state.

### Features

Tasks are started here. The left sidebar lists the feature categories:
**Combat**, **Farming**, **Fishing** and **Cooking**.

- **Combat**: pick Slayer, Dungeons or Farm Prayer Points, set duration and
  task limit (`Unlimited` by default), then **Start** or **Queue**. The page also
  shows the active Slayer task/progress and the combat feature descriptions.
- **Farming**: farming description, a **Farm Run** action, the farming feature
  description, and the full **Farming settings** form. Feature-specific settings
  live here; the Settings tab keeps the general bot options.
- **Fishing**: pick a **Location** and a **Spot** (demo-locked entries are
  disabled), set a duration, then **Start Fishing** or **Add to queue**. The
  **Fish at this spot** box lists each fish with its catch percentage, plus the
  spot's fish/junk chance, XP, catch interval and special items.
- **Cooking**: pick a Basic Food **Recipe**, set an optional **Amount**
  (0 = until stopped), then **Start Cooking** or **Add to queue**. The Recipe
  box shows the ingredient → product, level, XP, interval, bank counts and the
  Products Gained stop condition. Amount and Duration are typed directly (no
  spin buttons); Duration always shows the "Minutes" unit, and "0 Minutes"
  means no time limit.

Feature pages scroll when their content is taller than the window.

### Queue

The **Queue** tab lists tasks added from **Features → Combat/Fishing/Cooking →
Queue**. Each row shows the character, task, duration and task limit. Fishing
rows keep their location/spot and Cooking rows keep their recipe/amount, shown
in the Task column (`Fishing · Location / Spot`, `Cooking · Recipe × Amount`).
The queue runs in order and auto-switches the Melvor client to the row's
character when needed. **Stop** pauses the queue after the current task;
**Resume queue** continues. **Remove selected** and **Clear queue** manage
pending rows. The queue is kept in memory for the app session.

### Quick Controls

- Pause / Resume / Stop.
- **Farm Run**: runs a standalone full farming pass when the bot is idle. During
  an active run it pauses the current task, queues the pass, services it between
  task steps and then continues the same task. Its tooltip explains this.
- **Farm Prayer Points**: starts `farm_bones` immediately. Its tooltip reads
  *Uses current combat setup to farm Giant Chicken for prayer points.* The task
  selects Combat Areas → Corrupted Farmlands → Giant Chicken, keeps the current
  gear/stance, and fights until Stop or until the Eat button is disabled (out of
  food). Prayer upkeep is forced on for the run, and farming follows the
  **Prioritise farming** setting (default on). The idle failsafe is skipped so
  the kill loop stays continuous.

### Hide/show shortcut and overlay

Press **Ctrl+A** to hide or show the main window. It works while Melvor is
focused and while the app is focused outside a text field; Ctrl+A in a text
field or another application keeps its normal select-all behavior.

The top-left **AIO CTRL + A** overlay is a separate click-through window that
follows the Melvor client. It is visible **only while the Melvor window itself is
foreground**; focusing the bot UI (or any other application, including a movie
covering the game area) hides it, so it never floats over unrelated windows. It is
positioned at reference point `(136, 0)`
with a 13 px upward nudge, a 5%-of-width left shift and a 10 px right nudge, in
the dark header between the Melvor logo and the Bank icon. It scales the PNG to
`303px` physical width (two 15% reductions from the original 420px
presentation).

Display independence: geometry is expressed as a fraction of the 2560×1369
reference client, with offsets treated as physical pixels. The app reads the
game's logical client rect and device-pixel ratio from Qt (`QWindow.fromWinId`),
converts the target size/offsets accordingly, and renders the PNG at the target
physical size. At 100% it is `303×98` at `(131, 10)`; at 150% Qt scale it remains
`303×98` physical (verified at `(132, 9)`), so it keeps the same physical
appearance relative to the game client at any display scale or resolution. Hiding the main UI leaves the hint
visible while playing. Replace `assets/overlay_ctrl_a.png` with a different PNG
to change the artwork; adjust `OVERLAY_WIDTH` / `OVERLAY_REFERENCE_POINT` in
`overlay.py` to change size or placement. The header **Hide UI** button and the
tray **Hide / Show UI** action are fallbacks if the keyboard hook is
unavailable.

### Settings

The form is generated from `src/mi2_aio/settings_schema.py` and writes back to
`config/settings.toml` with `tomlkit`, so comments and ordering are preserved.
Validation happens before the file is replaced; an invalid value never destroys
a working config. The tab holds the **general bot options** (automation, combat
tasks, Prayer upkeep, failsafe, restore, logging); feature-specific sections are
marked in the schema and rendered on their Features page instead (currently
Farming). Low-level fields (`window_title`, save root/poll interval, character
selector) and the Slayer/Dungeon weapon-name maps are hidden; the header
character bubbles select saves, and the weapon defaults remain editable in
`settings.toml`. Spin boxes use the same light up/down buttons throughout, and
the Settings scroll bar uses the matching light handle.

`Learn fallback…` opens a two-click wizard: click the fallback skill's sidebar
icon, then the action's Start button. The app records both reference-space
points and enables `[failsafe]` with the action name. This removes the need to
edit coordinates by hand.

### Diagnostics

`doctor` output, the detected game window, the selected save and a character
table. `Use selected character` writes `[save].character`; `Use newest save`
clears it. Buttons capture a screenshot, open logs and open the settings file.

The Diagnostics toolbar has a **Logs** button next to **Open settings file**.
The default view is the report (`doctor` output, run options, settings
maintenance and the character table). Clicking **Logs** swaps the view to the
live log stream, with a **Clear** button; clicking **Logs** again returns to the
report. Diagnostics toolbar buttons keep the standard dark style; the
scrollbar navigation buttons use the same light style as the Settings spin
buttons. The log-folder shortcut stays in the toolbar.

The **Run options** box holds **Dry run (no clicks)**: it logs the bot's
decisions without sending input. Start the task from the **Features** tab; the game
and save still need to be available. This is a diagnostic/safety mode, not a
separate simulator.

**Settings maintenance → Reset to default settings** replaces the active
`settings.toml` with the bundled `config/settings.default.toml`. It asks for
confirmation first and cannot be undone. If a run is active, the reset applies
to the next run; the current run keeps its settings snapshot.

## Architecture

```
app.py (PySide6) ── AppService ── RunController ── runner.run
       │                 │               │
       │                 ├─ settings_io / settings_schema
       │                 ├─ diagnostics
       │                 └─ savefile / ui / window
       └─ Qt signals for status + log records
```

- `status.py` — `RunStatus` / `SlayerStatus` snapshots; the stable UI boundary.
- `control.py` — `RunController` starts one daemon run thread, exposes
  pause/resume/stop and calls listeners with status snapshots.
- `service.py` — environment snapshots, settings read/write, diagnostics,
  manual farming passes, screenshot capture.
- `diagnostics.py` — structured doctor data used by both CLI and app.
- `instance.py` — Windows named mutex / POSIX lock-file single-instance guard.
- `settings_schema.py` / `settings_io.py` — field metadata, validation and
  comment-preserving TOML writes.
- `capture_points.py` — real game-window clicks converted to reference space.
- `hotkey.py` / `overlay.py` — Ctrl+A low-level hook and the click-through,
  always-on-top hint window.
- `tasks/__init__.py` — task classes are created fresh per run.

The runner takes injectable `logger`, `control` (`stop_event` / `pause_event`)
and `on_status` callback arguments. The CLI keeps calling `run()` directly; the
app calls it through `RunController`.

Controls are cooperative: Stop is checked between farming/prayer actions,
before task steps and in the main loop. A long in-game hold finishes first, then
the run stops and restores the previous action.

## Status and logs

`RunStatus` includes run state, task, elapsed time, character, mode, current
action/entity, enemy, level, gold, HP, food, ammo, Prayer, bones, bank item
count, Slayer progress/completed tasks, dry-run flag, last error and exit code.
It serializes with `to_dict()` and is suitable for a future web UI.

The app installs a rotating `logs/app.log` handler and a Qt log handler; the
same records appear in the Diagnostics **Logs** panel and the dashboard activity
panel.

## Performance

- Decoded save headers and skill levels are cached by **path + mtime + size**.
  The app/runner poll repeatedly, but a new decompression only happens after the
  game autosaves. In a 30-second poll test: 4 decompressions instead of 30;
  cached reads take about **1 ms** and a fresh autosave about **50–60 ms**.
- `SaveTool.exe` and the optional `dotnet publish` build run with
  `CREATE_NO_WINDOW` + hidden `STARTUPINFO`, so they no longer flash console
  windows.
- The overlay caches the game-window lookup for 2 s, and the status probes are
  throttled (save 5 s, overlay 500 ms, HP/food 2 s while running).
- Long maintenance passes are skipped when a run is about to end (farming under
  60 s remaining, prayer under 20 s), so a short test no longer overruns its
  requested duration.
- Development startup measured at about **0.9 s**; the packaged build adds the
  normal PyInstaller startup cost (measured ~2.3 s).

## Config and data locations

Development runs read/write `config/settings.toml` and `logs/` in the repo (the
local settings file is git-ignored; copy `config/settings.default.toml` there for
a fresh checkout, or let the app create it when you first save settings).

A frozen/PyInstaller build:

- resources (`config`, `data`, `assets`, `tools/bin`) come from `sys._MEIPASS`
- writable config and logs live in `%APPDATA%\MI2 AIO`
- the first launch copies the bundled default `settings.toml` to the user folder
- `SaveTool.exe` must be shipped; a packaged app does not try to install the
  .NET SDK

## Build a standalone app

```powershell
.\scripts\build_app.ps1
```

It builds any missing `SaveTool.exe`, installs PyInstaller if needed, and runs
`mi2_aio.spec`. Output: `dist\MI2 AIO\MI2 AIO.exe` (windowed, no console).
The icon is `assets/icon.ico`.

### Windows Defender false positives

PyInstaller executables are occasionally quarantined by Defender's machine
learning heuristic (for example `Trojan:Win32/Bearfoos.B!ml`) even though the
build is a normal packed Python app. If a freshly built `MI2 AIO.exe` disappears
or refuses to start:

1. Check `Protection history` (or `Get-MpThreatDetection`) for the detection.
2. Add an exclusion for the build folder, from an elevated PowerShell:

   ```powershell
   Add-MpPreference -ExclusionPath "<path-to-MI2-AIO>\dist"
   ```

3. Rebuild or restore the quarantined file, then launch it again.

Only exclude the build folder, not the whole drive, and only after confirming
the detection points at this executable.

## Tests and diagnostics

```powershell
python -m pytest -q
python -m mi2_aio doctor
```

`MI2_AIO_START_TAB=features|queue|settings|diagnostics` starts the app on that
tab (`logs` is accepted as an alias for `diagnostics`) (useful for screenshots
and UI smoke tests).

## Known limits

- One run at a time; there is no run queue or scheduler yet.
- Pause is cooperative; a current in-game hold completes before the bot pauses.
- The game window must be unminimized.
- Only `Harvest Farm` has a captured dungeon-name template; the dungeon list
  marks unsupported entries.
- Slayer master switching is still a database/reference feature, not automatic.
- The fallback wizard records the two points you click; it does not OCR the
  action name.
