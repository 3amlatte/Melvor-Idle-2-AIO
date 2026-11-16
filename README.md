# MI2 AIO — Melvor Idle 2 automation toolkit

[![CI](https://github.com/3amlatte/Melvor-Idle-2-AIO/actions/workflows/ci.yml/badge.svg)](https://github.com/3amlatte/Melvor-Idle-2-AIO/actions/workflows/ci.yml)

Local, config-driven automation for **Melvor Idle 2** (Steam, `Melvor2.exe`), built to run unattended while you are away from the keyboard.

> **Unofficial project.** This tool is not affiliated with or endorsed by the
> developers of Melvor Idle. Automation may violate the game's terms of service
> and can put your account at risk; use it at your own discretion. The tool is
> local-only: it reads save files and simulates normal mouse/keyboard input. It
> does not patch the game, inject code, or modify saves. UI reference images and
> game data in this repository were extracted from a local demo installation and
> remain the property of their respective owners.

## What is verified so far

| Item | Value |
|---|---|
| Game process | `Melvor2.exe` |
| Installed at | `...\steamapps\common\Melvor Idle 2 Demo` |
| Build seen | `Melvor Idle 2 v0.11.4-alpha` (Godot 4 + .NET) |
| Save directory | `%APPDATA%\Games By Malcs\Melvor Idle 2\steam\<SteamID>\saves` |
| Save file | `save_<uuid>.sav` (Brotli-compressed binary) |
| Backups | `save_<uuid>.bak` + 10 rotating `save_backups\<uuid>_N.bak` |
| Autosave interval | 10 seconds |
| Header parsed | character `Adventurer`, gamemode `Test`, demo build, total level 731 |
| Latest live run | Prayer buried a 99-bone batch (+105 points), then Spikemoss Shrub restored |
| Desktop app | PySide6 dashboard, schema-driven settings, live logs, diagnostics, fallback wizard |
| UI shortcut | Ctrl+A hides/shows the window; a click-through AIO overlay appears only over the focused game window |
| Save slots | one per character UUID; newest is used unless pinned |

Save format: [docs/save-format.md](docs/save-format.md) · game modes: [docs/game-modes.md](docs/game-modes.md).

## Quick start

```powershell
cd path\to\MI2 AIO

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Local settings (git-ignored): copy the bundled template.
Copy-Item config\settings.default.toml config\settings.toml

# Build the tiny Brotli decompressor (needs the .NET SDK; the game itself runs on .NET).
# doctor builds it automatically on first run, or run the script explicitly:
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_savetool.ps1

# Verify everything: game window, save file, header, capture
python -m mi2_aio doctor

# Launch the desktop app
.\launch_ui.cmd
# or: python -m mi2_aio gui
```

## Desktop app

`launch_ui.cmd`, `python -m mi2_aio gui` and `python -m mi2_aio.app` all open the
same PySide6 app. It is a front end over the same runner and settings the CLI
uses; no bot logic is duplicated.

- **Dashboard** — Quick Controls (Pause / Resume / Stop, **Farm Run** and
  **Farm Prayer Points**: Corrupted Farmlands → Giant Chicken), live status
  (character, mode, action, gold, Prayer, bank, HP from the save), a 26-skill
  grid with greying for skills not in the demo and a **Total Level 735/1320**
  summary, and recent activity. Each saved character has its own bubble in the
  header; clicking a bubble switches characters in Melvor automatically.
- **Features** — Combat / Farming / Fishing / Cooking sidebar. Slayer,
  Dungeons, Farm Prayer Points, Fishing and Cooking can be **Started** or
  **Queued** here. The Farming page has its own **Farm Run** action and the
  **Farming settings** form; the Fishing page picks a location and spot, shows
  the fish that spot produces, and starts the action; the Cooking page picks a
  Basic Food recipe and optional product count.
- **Queue** — ordered task list with character, duration and task limit per row.
  The queue runs tasks one after another and auto-switches the Melvor client to
  each row's character. Fishing rows keep their location/spot and Cooking rows
  keep their recipe/amount. Stop pauses the queue; Resume, Remove and Clear
  manage it.
- **Hide/show** — Ctrl+A toggles the main window; the click-through
  `AIO CTRL + A` overlay is visible only while Melvor itself is focused, and
  hidden when the bot UI or any other application is foreground.
- **Settings** — every operational setting, generated from a schema, validated
  and written back with comments preserved.
- **Diagnostics** — `doctor`, game window, save/character picker, screenshots,
  the dry-run/no-click toggle, **Reset to default settings**, and the live
  **Logs** button/view.
- **Learn fallback…** — two-click wizard for `[failsafe]`; no coordinate editing.

The app holds an application lock, and each run holds a separate bot lock, so
the CLI and GUI cannot click the game at the same time. Status and logs cross
from the run thread to the UI through Qt signals.

Standalone build (PyInstaller): `.\scripts\build_app.ps1` →
`dist\MI2 AIO\MI2 AIO.exe`. A packaged app keeps writable config/logs in
`%APPDATA%\MI2 AIO` and reads bundled resources from the app folder.

Save reads are cached by path/mtime/size, and helper processes run hidden, so
polling does not flash console windows. See [docs/ui.md](docs/ui.md#performance).

Architecture, screens, limitations and packaging: [docs/ui.md](docs/ui.md).

## Commands

```powershell
python -m mi2_aio doctor          # environment + game + save sanity check
python -m mi2_aio status          # newest save header + resolved mode profile
python -m mi2_aio status --all    # every character/save slot
python -m mi2_aio status --json   # machine-readable
python -m mi2_aio levels          # exact skill levels/XP from the save
python -m mi2_aio modes           # game-mode profiles and policies
python -m mi2_aio capture         # screenshot (occluded and off-screen work)
python -m mi2_aio tasks           # features grouped by category
python -m mi2_aio features        # features with config sections (UI data)
python -m mi2_aio features --json # same data as JSON
python -m mi2_aio gui             # launch the desktop app
python -m mi2_aio slayer-masters  # Slayer masters, areas, lengths and costs
python -m mi2_aio gear            # melee gear tables, stats and recipes
python -m mi2_aio gear --slot sword    # 1H + 2H swords
python -m mi2_aio gear --slot mallet   # crush weapons
python -m mi2_aio gear --json     # same data as JSON
python -m mi2_aio gear --compare "Bone Scythe" --attack 48 --defence 40 --smithing 59
python -m mi2_aio melee           # best style for the current save-header enemy
python -m mi2_aio melee --enemy "Blue Slime"   # slash/block/crush comparison
python -m mi2_aio run             # run the safe default task (observe only)
python -m mi2_aio run --task observe --duration 30
python -m mi2_aio run --task slayer --duration 60    # slayer automation
python -m mi2_aio run --task slayer --tasks 3        # stop after 3 completed tasks
python -m mi2_aio run --task dungeons --duration 60  # dungeon raiding
python -m mi2_aio run --task farm_bones --duration 60 # Giant Chicken Prayer farm
python -m mi2_aio farm --inspect                  # farming plot states
python -m mi2_aio farm                            # one farming pass now
```

`run` does **not** send input unless a task explicitly does. The default `observe` task only watches the save header and logs changes — use it to confirm the plumbing before adding actions.

## Combat automation

Combat features live under the **Combat** category. `python -m mi2_aio tasks`
lists the categories and features; the same data is available as JSON with
`python -m mi2_aio features --json` for the desktop app.

```
Combat
  slayer     jump to the task enemy, counter its style, stop when food runs out
  prayer     bury banked bones in batches to restore Prayer points
  dungeons   raid a standard dungeon and collect its completion loot
Farming
  farming    plots, compost bins, the Mill Farm and The Mill
Global
  failsafe   start a fallback action whenever the character is idle
  restore    resume the action the game was doing before the run
```

### Slayer

`run --task slayer` keeps the current slayer task going:

- jumps to the task enemy at startup (optional) and when the task monster changes
- switches weapons when the combat triangle marks the current style ineffective,
  using the bank (extra loadouts are shop unlocks)
- refuses to use a bow when the ammo slot is empty and falls back to melee
- reverts a switch that produces no kills (for example a weapon the character
  cannot use) and stops trying that style for the task
- stops the run when the Eat button shows the selected food ran out
- counts completed tasks from the save's active task (new enemy/length or a
  progress reset) and stops after `--tasks N` / `max_tasks`

```toml
[combat.slayer]
jump_on_start = true
stop_when_out_of_food = true
stall_minutes = 12.0
auto_style = true                       # slash/block/crush from data/enemies.json
style_switch_cooldown_seconds = 20.0
auto_armour = true                      # equip better owned armour (Defence)
armour_check_minutes = 10.0
max_tasks = 0                           # 0 = unlimited

[combat.slayer.weapons]
melee = "Bone Scythe"
ranged = "Normal Bow"
magic = ""            # empty disables a style
```

Task completion is read exactly from the save: the active Slayer master's
current enemy, task length and progress. A new task is detected by a changed
`(master, enemy, length)` key or a progress reset, including two consecutive
tasks against the same enemy. The task panel is still used for Jump To Enemy.

The **Slayer masters** database (`data/slayer_masters.json`) lists all ten demo
masters with their areas, base task lengths, reroll/block costs and unlock
requirements. `python -m mi2_aio slayer-masters` prints it; automatic master
switching is not implemented yet.

Details, verification notes and caveats: [docs/slayer.md](docs/slayer.md).

### Prayer upkeep

Prayer runs **alongside** every task. The bot reads banked bone quantities and
the Prayer-point balance from the save, then opens the bank only when a batch is
due:

- **50+ bones** have accumulated (`bone_threshold`), or
- Prayer points are **below 100** and at least one bone is owned.

It selects the exact bone in the bank search (the search returns Bone Scythe
first), presses **All**, then **Bury N Bones** — one action per stack. Bone,
Big Bone, Magic Dust and Small Dragon Bone all count. Like farming, the pass
happens between main-task steps and restores the current action's page.

```toml
[combat.prayer]
enabled = true
bone_threshold = 50        # bury a full batch regardless of Prayer points
low_prayer_threshold = 100 # top up early when Prayer is low
check_seconds = 60         # minimum time between checks (no bank spam)
verify_seconds = 12        # wait for the save to confirm the bury
```

Details and live verification: [docs/prayer.md](docs/prayer.md).

### Dungeons

`run --task dungeons` raids a standard dungeon, reached from
**Combat → Select Area → Standard Dungeons**. The bot finds the dungeon by a
binarized template of its name, clicks **Start Dungeon**, then keeps the
character alive through the waves. The game itself restarts each wave and awards
the dungeon's special loot table (shown under **View Rewards**) after a cleared
run, so the bot only has to stay in the dungeon.

```toml
[combat.dungeons]
dungeon = "Harvest Farm"
template = "assets/templates/dungeon_harvest_farm.png"
stop_when_out_of_food = true
switch_cooldown_minutes = 3.0
auto_style = true
style_switch_cooldown_seconds = 20.0
auto_armour = true
armour_check_minutes = 10.0

[combat.dungeons.weapons]
melee = "Bone Scythe"
ranged = "Normal Bow"
magic = ""
```

The bot treats itself as "in the dungeon" from the on-screen **Dungeon
Progress** label or the save header's `active_action`, so wave transitions never
make it re-enter and reset progress. Details: [docs/combat.md](docs/combat.md).

### Prayer-point farming

`run --task farm_bones` (or **Quick Controls → Farm Prayer Points**) navigates
to **Combat Areas → Corrupted Farmlands → Giant Chicken**. Giant Chicken always
drops a **Big Bone** (6 Prayer points), and the 6 points per 50 HP is 2.4x the
1 point per 20 HP from a normal Bone, so it is the best Prayer-points-per-hour
target in the demo. The task keeps the current equipment, stance and auto-eat
setup, stops when the Eat button is disabled, forces Prayer upkeep on, and
follows the **Prioritise farming** setting (default on). The idle failsafe is
skipped so the kill loop stays continuous. Details:
[docs/combat.md](docs/combat.md).

### Melee gear database

Every demo-available melee weapon is in `data/scimitars_defenders.json`, with
equip requirements, stats, Smithing recipes and drop sources. The best **slash**
setup is a scimitar + defender:

| Scimitar | Equip | Slash | Str | Smithing |
|---|---|---:|---:|---|
| Copper | Attack 10 | 34 | 16 | 6 (2x Copper Bar) |
| Iron | Attack 20 | 44 | 20 | 11 (2x Iron Bar) |
| Steel | Attack 30 | 56 | 24 | 27 (2x Steel Bar) |
| Mithril | Attack 40 | 69 | 28 | 37 (2x Mithril Bar) |
| Toxic Razors | Attack 42 | 74 | 29 | drop: Toxic Razorfish (Toxic Bog, 0.68%) |
| Adamant | Attack 50 | 82 | 32 | 47 (2x Adamantite Bar) |

| Defender | Equip | Slash Atk | Slash Def | Smithing |
|---|---|---:|---:|---|
| Copper | Defence 10 | 5 | 6 | 5 (1x Copper Bar) |
| Iron | Defence 20 | 8 | 12 | 10 (1x Iron Bar) |
| Steel | Defence 30 | 11 | 17 | 25 (1x Steel Bar) |
| Mithril | Defence 40 | 14 | 22 | 35 (1x Mithril Bar) |
| Mantis | Defence 45 | 17 | 26 | drop: Mangrove Mantis |
| Adamant | Defence 50 | 20 | 27 | 45 (1x Adamantite Bar) |

Swords are slash/block (1H) or slash/crush/block (2H). Mallets are two-handed
crush weapons: they occupy the off-hand, so they cannot use a defender.

Armour lives in the same database under `armour`: every demo helmet, torso,
legs, boots, gloves, cape, amulet, ring and off-hand item. Defenders are in this
list because they use the **Defence** skill. The bot auto-upgrades owned pieces
using all level requirements and ranks them by protection → total defence →
strength. Each equipped slot is verified from the save before the upgrade is
accepted:

| Slot | Best at Defence 40 | Prot | Total Def | Smithing |
|---|---|---:|---:|---|
| Helmet | Mithril Helmet | 93 | 135 | 37 |
| Torso | Mithril Platebody | 246 | 274 | 45 |
| Legs | Mithril Platelegs | 185 | 203 | 43 |
| Boots | Mithril Boots | 93 | 135 | 37 |
| Gloves | Mithril Gloves | 0 | 66 | 36 |
| Off-hand (1H) | Mithril Defender | 0 | 135 | 35 |

Magic/Ranged armour (wizard robes, chainmail) is in the database for reference
but is never selected for melee auto-upgrade.

| Sword | Equip | Slash | Crush | Block | Str | Smithing |
|---|---|---:|---:|---:|---:|---|
| Stone Sword (1H) | Attack 1 | 20 | — | 25 | 12 | 1 (2x Stone) |
| Copper Sword (1H) | Attack 10 | 27 | — | 34 | 16 | 6 (2x Copper Bar) |
| Iron Sword (1H) | Attack 20 | 33 | — | 42 | 20 | 11 (2x Iron Bar) |
| Steel Sword (1H) | Attack 30 | 43 | — | 55 | 24 | 26 (2x Steel Bar) |
| Mithril Sword (1H) | Attack 40 | 54 | — | 70 | 28 | 36 (2x Mithril Bar) |
| Adamant Sword (1H) | Attack 50 | 61 | — | 79 | 32 | 46 (2x Adamantite Bar) |
| Copper 2H Sword | Attack 10 | 47 | 49 | 61 | 42 | 9 (4x Copper Bar) |
| Iron 2H Sword | Attack 20 | 55 | 60 | 73 | 46 | 15 (4x Iron Bar) |
| Steel 2H Sword | Attack 30 | 67 | 72 | 89 | 48 | 31 (4x Steel Bar) |
| Mithril 2H Sword | Attack 40 | 83 | 87 | 108 | 50 | 41 (4x Mithril Bar) |
| Adamant 2H Sword | Attack 50 | 92 | 98 | 121 | 54 | 51 (4x Adamantite Bar) |
| Staggering Lash Greatsword | Attack 55 | 100 | 109 | 136 | 64 | drop: Wyvern |

| Mallet | Equip | Crush | Str | Smithing |
|---|---|---:|---:|---|
| Stone | Attack 1 | 38 | 45 | 3 (4x Stone) |
| Copper | Attack 10 | 61 | 54 | 9 (4x Copper Bar) |
| Iron | Attack 20 | 73 | 56 | 15 (4x Iron Bar) |
| Steel | Attack 30 | 89 | 58 | 31 (4x Steel Bar) |
| Mithril | Attack 40 | 108 | 62 | 41 (4x Mithril Bar) |
| Adamant | Attack 50 | 121 | 66 | 51 (4x Adamantite Bar) |

```powershell
python -m mi2_aio gear                    # every table
python -m mi2_aio gear --slot scimitar
python -m mi2_aio gear --slot sword
python -m mi2_aio gear --slot mallet
python -m mi2_aio gear --slot armour      # all armour slots
python -m mi2_aio gear --slot helmet      # one slot
python -m mi2_aio gear --json             # full data for the UI
python -m mi2_aio gear --compare "Bone Scythe"
python -m mi2_aio levels                  # exact levels/XP from the save
```

`gear --compare` reads the character's Attack/Defence/Smithing levels from the
save (not from the Skills page's `current / demo max` display). `levels` shows
every skill level and XP; the parsed total is checked against the save header.

The loader (`equipment_db.py`) exposes `best_scimitar(attack_level)`,
`best_defender(defence_level)`, `best_loadout(...)`, `best_weapon_for_style()`
and `weapons_for_style()`, plus craftable-only variants, ready for the
auto-upgrade feature. The **Bone Scythe** is stored as a two-handed comparison
baseline; at the current Attack 48 / Defence 40 / Smithing 59, **Mithril
Scimitar + Mithril Defender** is the first clear slash upgrade, or **Toxic
Razors + Mithril Defender** if the drop is owned.

### Best melee style for an enemy

The bot chooses **slash**, **block** or **crush** per enemy. `data/enemies.json`
holds all 155 demo monsters with their Defence level and Slash/Block/Crush
defence bonuses, and `melee.py` applies the game's exact hit-chance formula
(player Attack level + style attack bonus vs enemy Defence level + style defence
bonus):

```powershell
python -m mi2_aio melee --enemy "Blue Slime"
python -m mi2_aio melee --enemy "Toxic Razorfish" --craftable --no-special
python -m mi2_aio melee --json
```

| Enemy | Best style | Setup | Hit |
|---|---|---|---|
| Blue Slime | Crush | Mithril Mallet | 86.1% |
| Toxic Razorfish | Block | Mithril 2H Sword | 33.7% |
| Mangrove Mantis | Block | Mithril 2H Sword | 36.7% |
| Wyvern | Slash | Bone Scythe | 39.5% |

`melee.choose_melee_style()` picks the best weapon for each style (adding the
best defender to one-handed weapons) and returns the highest hit chance, so it
works for any enemy and level. The slayer and dungeon tasks call it for the
active enemy, equip the best owned weapon through the bank and select the
matching stance. The enemy and equipped weapon/off-hand come from the save, so
dungeon waves work too without OCR. **Armour auto-upgrade** runs alongside it:
the bot reads the bank/equipment from the save, picks the best owned armour per
slot that meets every level requirement, and equips upgrades. The game
autosaves every 10 seconds, so a wave change can take up to one autosave to be
noticed. Full stats and comparison: [docs/combat-gear.md](docs/combat-gear.md).

## Farming maintenance

Farming runs **alongside** whatever task is active and is serviced **first**
each loop: the character keeps fighting or skilling while the bot checks the
farm and, only when a plot needs attention, switches to the Farming page,
harvests, **selects the configured compost (Fertiliser by default) and applies
it before planting**, replants the selected crop, then waters it with a
hold-to-water press and returns to the page of the action currently being
performed (combat, woodcutting, mining, ...).

Plots locked by Farming level (or demo restrictions) are skipped and logged as
information, never treated as errors.

The trigger is the red attention badge the game puts on the Farming sidebar
icon when a plot is harvestable — visible from any page, so normal polling
costs one screenshot. A full pass runs **only when that badge is present**;
`check_minutes` is an optional safety fallback and defaults to `0` (off).
`prioritise = true` services a needed pass before the task step; set it to
`false` to let the task step run first.

```toml
[farming]
enabled = true
prioritise = true
badge_poll_seconds = 5.0
check_minutes = 0.0
categories = ["allotments", "herbs", "compost", "trees", "flowers", "orchard", "mill"]
compost = true
select_compost = true   # choose the type in the picker before applying
compost_slot = 1        # 1 = Fertiliser, 2 = Compost, 3 = third compost
water = true            # hold-to-water after planting, with verification
mill = true
```

`python -m mi2_aio farm --inspect` prints what the bot sees for each plot
without changing anything. Flowers and Orchard are serviced like the other crop
categories once their plots are owned; currently purchase/level/demo-locked
cards are recognized and skipped, and the bot never presses **Hold to Buy
Plot**. Details: [docs/farming.md](docs/farming.md).

The **Mill Farm** plots are serviced like any crop; afterwards the bot deposits
the farmed Wheat/Sugarcane/Corn/Flax into **The Mill** and restarts it if it is
stopped with stock to process.

## Fishing

Fishing is a normal task (`fishing`) on **Features → Fishing**. Choose a
**Location** and a **Spot**, then **Start Fishing** or **Add to queue**. The
page lists the fish that spot produces, with the client's catch weights as
percentages, the XP per catch, the catch interval and any special items.

The database (`data/fishing.json`) is extracted from `Melvor2.exe`: all 7
locations and 23 spots, including entries the demo locks. Five locations are
playable in the demo (Shallow Shores, Shrapnel River, Lemvor Pier, Windy
Coastline, Glowing Depths); Coral Reef and Open Ocean are marked
`locked in the demo`, and locked spots inside an available location are shown but
cannot be chosen. Level requirements come from the same client data.

The task:

1. opens Fishing from the skill sidebar (or the active-action button if it is
   already the current page),
2. expands the **Select Location** cards and clicks the requested card,
3. opens the **Select Spot** dropdown, verifies it expanded, and clicks the
   requested row,
4. clicks the green **Start Fishing** button and verifies the save header's
   active action is the chosen spot's name.

The save header is the authority: `active_action` is the spot name (for example
`Pebble Bank`), so a level-locked or demo-locked choice is caught and retried
instead of silently fishing something else. After three failed attempts the run
stops with a message that names the required level.

Two page quirks are handled explicitly:

- **Start Fishing ignores posted window messages.** It only reacts to a real
  cursor click, so that one click briefly focuses the game; every other click
  uses the background path.
- **Selecting a location can resume that location's remembered spot** and the
  first dropdown click can be swallowed while the page switches. The task
  double-clicks the card, checks for the expanded menu's highlighted row, and
  clicks the target row again if the menu is still open.

Per-run choices travel in `options`:

```python
options={"location": "GlowingDepths", "spot": "ShimmeringDepths"}
```

Ids or display names are accepted. A missing, unknown or demo-locked choice falls
back to the first available location and spot, so a bare run still works. The
CLI exposes the same choices:

```text
python -m mi2_aio run --task fishing --location "Shrapnel River" --spot "Pebble Bank"
```

Queued rows keep their own `location`/`spot` options and show them in the Task
column (for example `Fishing · Lemvor Pier / Pier Walk`).

Bait and priority-fish selection are left as configured in the game. Details:
[docs/fishing.md](docs/fishing.md).

## Cooking

Cooking is a task (`cooking`) on **Features → Cooking**. Only the **Basic Food**
category is supported for now. Pick one of the 13 demo recipes, set an optional
**Amount**, then **Start Cooking** or **Add to queue**.

The database (`data/cooking.json`) comes from `Melvor2.exe` and holds the 26
Basic Food recipes (13 demo-available), their ingredients, product, level, XP,
cook interval and the recipe's grid slot. The grid slot is needed because the
demo inserts a locked card after Pike; Salmon/Lobster/Glowfin/Sea Bream are at
slots 10-13 rather than 9-12.

The task:

1. opens Cooking from the skill sidebar,
2. selects **Basic Food** and the requested recipe card,
3. expands **Manage Stop Conditions**, chooses **Products Gained**, sets the
   amount and presses **Create**,
4. waits for the game to stop the action at that product count.

The in-game stop condition gives exact counts. As a safety net the task also
tracks the product's bank stack from the save header: if the condition could not
be set, it presses the red **Stop** when the bank gain reaches the amount. A
wrong recipe (the save header names a different cooking product) or an action
that stops early is logged so the queue can continue.

```text
python -m mi2_aio run --task cooking --recipe Glowfin --amount 100
```

Queued rows keep their own `recipe`/`amount` options and show them in the Task
column (for example `Cooking · Glowfin × 100`). A zero amount means "until
stopped". Bait/priority selection does not exist for cooking; the bot uses the
selected recipe as-is. Details: [docs/cooking.md](docs/cooking.md).

## Never idle (failsafe)

When the save header reports no active action, the bot starts a fallback action
so the account keeps gaining XP. The default is **Woodcutting → Spikemoss
Shrub**:

```toml
[failsafe]
enabled = true
action = "Spikemoss Shrub"
page = [39, 303]        # Woodcutting sidebar icon
button = [1082, 1096]   # Spikemoss Shrub Cut button
cooldown_seconds = 60
```

Farming runs **before** prayer upkeep, the fallback and the main task step, so a
ready plot is serviced first. The fallback also runs after a test/run ends if
restore could not resume an action, so the character is not left idle. Details:
[docs/failsafe.md](docs/failsafe.md).

## Restore the previous action

When a run ends, the bot puts the game back the way it found it. If the
character was cutting a Willow Tree and a dungeon test took over, Woodcutting
resumes when the test stops.

The bot learns the action from the rendered UI at startup (no OCR, no action
registry): it opens the current action's page, matches the page header icon
against the sidebar to remember the page button, and keeps the action name from
the active panel as a template. At the end it leaves combat if needed, opens the
page, finds the same name on an action card, clicks the green start button below
it, and verifies the action restarted.

```toml
[restore]
enabled = true
verify_seconds = 25
poll_seconds = 1.5
```

Restore is conservative: if it cannot identify the page, name, card or button it
logs a warning and leaves the game alone instead of clicking a guess. A previous
combat/dungeon action reopens the Combat page but does not re-enter the exact
enemy. Details and failure behaviour: [docs/restore.md](docs/restore.md).

## Game modes and characters

The full release will add character types such as Regular and Hardcore. The save
header already carries a `Gamemode` string (`Test` in this demo), so the project
resolves it to a **policy profile** instead of hardcoding mode names:

- profiles live in `config/settings.toml` under `[gamemodes.*]`
- matching is by key, display name, or alias, ignoring case/punctuation
- an unknown mode falls back to `unknown`: permanent death assumed, risky tasks blocked
- tasks declare `supported_modes` and `risky`; the runner refuses incompatible work

```powershell
python -m mi2_aio modes
python -m mi2_aio status --all
```

Pin a character when several saves exist:

```toml
[save]
character = "HardcoreGuy"   # name, or UUID/file fragment
```

In the desktop app the header shows a separate bubble per saved character.
Clicking a bubble switches the running Melvor client to that save. Queued tasks
store the character they were queued for, so a queue can mix characters and the
app switches before each row starts. Details and examples:
[docs/game-modes.md](docs/game-modes.md).

## Running while you play or work

The bot reads and clicks the game **without focus**, so you can play another game
or use the browser while it runs. The game must stay **unminimized**.

**Any screen size works.** The UI readers are calibrated for a 2560x1369 client
area, so at startup the bot restores the window if it is maximized and resizes it
to exactly that client size. On a smaller display (laptop, 1080p monitor) the
window simply extends beyond the screen edge — that is fine, because capture uses
`PrintWindow` and clicks are posted to the window, both of which work off-screen.
The process is DPI-aware, so 125%/150%/200% display scaling is handled, and the
window is re-checked every 30 seconds so a resolution or monitor change mid-run
recovers automatically. You do not need to maximize or remember a size; `doctor`
shows the display, scale and client size, and the startup resize is logged.
Details and the rules for new features: [docs/display.md](docs/display.md).

| Window state | Read | Act |
|---|---|---|
| Focused | yes | yes |
| Behind other windows / not focused | yes (live capture) | yes (posted messages) |
| Off-screen, not minimized | yes (live capture) | yes |
| Any size (auto-resized to 2560x1369) | yes | yes |
| Display scaling 125% / 150% / 200% | yes (per-monitor DPI aware) | yes |
| Resolution/monitor changed mid-run | yes (re-applied every 30 s) | yes |
| Minimized | **no** (black frame) | **no** (no client area) |

Minimized windows have no composition surface, so `PrintWindow` returns black.
The game still simulates, but the bot is blind. Leave the window covered, on a
second monitor, or parked off-screen instead.

```toml
[automation]
background_input = true   # post mouse messages; never moves your cursor
```

Details, measurements, and caveats: [docs/background-operation.md](docs/background-operation.md).

## Design

```
Save file (ground truth, 10 s cadence)     Screen (PrintWindow, real-time)
              \                              /
               \--- state / task logic -----/
                              |
                posted mouse messages (works unfocused)
```

- **Read state two ways.** The save header is exact but delayed; screenshots are immediate but noisy. Tasks use whichever fits.
- **Observe before you act.** A task should detect the current screen/state before clicking, so a popup cannot derail a long run.
- **Config over code.** Timings, paths, and jitter live in `config/settings.toml`.
- **Fail safe.** `STOP` file, `Ctrl+C`, pyautogui corner abort (foreground path), max-runtime watchdog, and a screenshot saved on every task exception.
- **No save editing.** Saves are copied read-only to `%TEMP%` for decoding; the live save is never written to.

## Layout

```
MI2 AIO/
├─ AGENTS.md                 # hard rules for contributors/agents (display independence)
├─ launch_ui.cmd             # one-click launcher for the desktop app
├─ run_app.py                # packaged entry point
├─ mi2_aio.spec              # PyInstaller build spec
├─ config/settings.default.toml  # bundled defaults (copy to settings.toml for a dev checkout)
├─ data/scimitars_defenders.json  # melee gear database (weapons + all armour slots)
├─ data/enemies.json         # 155 demo monsters: levels + slash/block/crush defence
├─ data/dungeons.json        # 12 standard dungeons: waves, enemies, rewards
├─ data/weapon_types.json    # stance order per weapon type (Scimitar, Sword, 2H Sword, Mallet, ...)
├─ data/slayer_masters.json  # 10 Slayer masters: areas, lengths, costs, unlocks
├─ data/bones.json           # buryable items + Prayer points per bone
├─ data/fishing.json         # 7 fishing locations, 23 spots, fish weights + demo locks
├─ data/cooking.json         # 26 Basic Food recipes, ingredients, products, grid slots
├─ docs/save-format.md       # verified save format notes
├─ docs/game-modes.md        # mode profiles, task gating, multi-character
├─ docs/background-operation.md  # unfocused/off-screen/minimized behaviour
├─ docs/display.md           # any resolution/scale: invariant + rules
├─ docs/combat.md            # Combat category: slayer + dungeons
├─ docs/combat-gear.md       # melee gear database + style engine + auto-upgrade notes
├─ docs/slayer.md            # slayer task policy, verification, caveats
├─ docs/prayer.md            # bone burying + Prayer upkeep
├─ docs/farming.md           # farming maintenance, triggers, caveats
├─ docs/fishing.md           # fishing task, location/spot page, database
├─ docs/cooking.md           # cooking task, Basic Food grid, stop conditions
├─ docs/failsafe.md          # idle failsafe / fallback action
├─ docs/restore.md           # resume the pre-run action after a run
├─ docs/ui.md                # desktop app: screens, service layer, packaging
├─ scripts/build_savetool.ps1
├─ scripts/build_app.ps1     # PyInstaller desktop build
├─ src/mi2_aio/
│  ├─ __main__.py            # CLI: doctor / status / levels / capture / tasks / features / gear / melee / slayer-masters / farm / gui / run
│  ├─ app.py                 # PySide6 desktop app
│  ├─ service.py             # shared app service: settings, environment, diagnostics, run control
│  ├─ control.py             # RunController + pause/stop/status listeners
│  ├─ status.py              # RunStatus snapshots for the UI
│  ├─ settings_schema.py     # declarative settings metadata
│  ├─ settings_io.py         # validated, comment-preserving TOML writes
│  ├─ diagnostics.py         # structured doctor output
│  ├─ capture_points.py      # real game-window click -> reference coordinates
│  ├─ hotkey.py              # low-level Ctrl+A hide/show hook
│  ├─ overlay.py             # always-on-top click-through shortcut hint
│  ├─ instance.py            # single-instance mutex/lock
│  ├─ config.py              # TOML settings
│  ├─ features.py            # category + feature registry for the desktop app
│  ├─ modes.py               # game-mode profiles + task gating
│  ├─ savefile.py            # discovery, Brotli decompress, header + skills + combat state
│  ├─ window.py              # window lookup, focus, PrintWindow capture
│  ├─ input.py               # posted (background) clicks, typing, holds
│  ├─ ui.py                  # combat, stance, dungeon, farming, fishing + restore readers
│  ├─ equipment.py           # bank search + loadout equip
│  ├─ equipment_db.py        # gear database loader, armour ranking + ownership
│  ├─ enemy_db.py            # enemy database loader (levels, defence bonuses)
│  ├─ dungeon_db.py          # standard-dungeon wave database loader
│  ├─ fishing_db.py          # fishing location/spot/fish database loader
│  ├─ cooking_db.py          # Basic Food recipe database loader
│  ├─ slayer_master_db.py    # Slayer master database loader
│  ├─ melee.py               # exact hit-chance + best slash/block/crush style
│  ├─ weapon_type_db.py      # weapon type -> stance button order
│  ├─ style_switch.py        # live enemy -> best owned weapon + stance + armour
│  ├─ bones.py               # bone database, bank search index, Prayer points
│  ├─ prayer.py              # bury banked bones in batches (Prayer upkeep)
│  ├─ farming.py             # farming maintenance between task steps
│  ├─ failsafe.py            # idle failsafe: start a fallback action
│  ├─ restore.py             # resume the pre-run action at shutdown
│  ├─ vision.py              # template matching helpers
│  ├─ runner.py              # task loop + maintenance + watchdogs + status callbacks
│  └─ tasks/                 # task plugins (observe, slayer, dungeons, fishing, cooking)
├─ assets/icon.ico           # desktop app icon (and icon.png)
├─ assets/overlay_ctrl_a.png # always-on-top Ctrl+A hint (replaceable)
├─ assets/templates/         # combat style + stance glyphs + dungeon name masks
├─ tests/
└─ tools/SaveTool/           # .NET Brotli helper
```

## Adding a task

1. Create `src/mi2_aio/tasks/my_task.py` with a class exposing `name`, `step(ctx)`, and optional `start/stop/on_save` hooks.
2. Register it in `src/mi2_aio/tasks/__init__.py`.
3. Calibrate with real screenshots: `python -m mi2_aio capture`, then build templates under `assets/templates/`.
4. Test with `--dry-run` (logs intended actions, sends none), then run short sessions.

New UI code must stay display-independent: regions and click points go in
`ui.py` in reference-space pixels, readers consume `ui.normalize(...)` captures,
and clicks are scaled with `ui.to_client(...)`. See [docs/display.md](docs/display.md)
for the full rules; `tests/test_display.py` covers the geometry.

## Safety notes

- Back up `%APPDATA%\Games By Malcs\Melvor Idle 2\steam\<SteamID>\saves` before the first real run.
- Keep the game **unminimized**. Covered, unfocused, or off-screen is fine; minimized is not.
- Background input does not move the real cursor, so pyautogui's corner abort does not apply — use `STOP`, `Ctrl+C`, and `--duration` instead.
- Start with short runs (`--duration 10`) and watch the log before trusting it overnight.

## Contributing

Setup, tests and pull-request rules: [CONTRIBUTING.md](CONTRIBUTING.md). The
display-independence requirements are in [AGENTS.md](AGENTS.md) and
[docs/display.md](docs/display.md).

## License

The **source code and documentation** are released under the MIT License; see
[LICENSE](LICENSE). Third-party libraries keep their own licenses. Game names,
artwork, UI reference crops and extracted game data are **not** covered by the
MIT license; see [NOTICE.md](NOTICE.md). This is an unofficial project, not
affiliated with or endorsed by the Melvor Idle developers.

