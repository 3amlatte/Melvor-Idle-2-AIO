# Combat category

Combat automation lives under the `Combat` category. It currently has four
features: three runnable tasks and one maintenance pass that runs alongside them.

| Feature | Task | What it does |
|---|---|---|
| Slayer | `run --task slayer` | Jumps to the task enemy, counters its combat style, stops when food runs out. |
| Prayer | alongside any task | Buries banked bones in batches to restore Prayer points. |
| Dungeons | `run --task dungeons` | Enters a standard dungeon and keeps fighting through its waves for the completion loot. |
| Farm Prayer Points | `run --task farm_bones` | Switches to Corrupted Farmlands, kills Giant Chicken for its guaranteed Big Bone and lets Prayer maintenance bury the bones. |

```powershell
python -m mi2_aio tasks              # features grouped by category
python -m mi2_aio features           # one line per feature (UI-friendly)
python -m mi2_aio features --json    # same data as JSON
python -m mi2_aio run --task slayer
python -m mi2_aio run --task dungeons
python -m mi2_aio run --task farm_bones
```

### Why Giant Chicken?

Giant Chicken in **Corrupted Farmlands** is the best Prayer-points-per-hour bone
source in the demo:

| Target | Drop | Prayer points | HP | Points per HP |
|---|---|---:|---:|---:|
| Giant Chicken | Big Bone (guaranteed) | 6 | 50 | **0.120** |
| Hobgolbin | Big Bone (guaranteed) | 6 | 70 | 0.086 |
| Golbin | Bone (guaranteed) | 1 | 20 | 0.050 |
| Magic Cow | Bone (guaranteed) | 1 | 60 | 0.017 |

Giant Chicken takes longer per kill than Golbin, but it gives **6x the Prayer
points for 2.5x the HP**, so it is about **2.4x better per HP**. Hobgolbin also
drops a Big Bone but has 70 HP, making it slower than Giant Chicken.

> `data/enemies.json` stores Hitpoints **levels**; actual HP is level × 10.
> Golbin's level 2 is 20 HP and Giant Chicken's level 5 is 50 HP.

The task keeps the current equipment, stance and auto-eat setup. It stops when
the Eat button is disabled (out of food) or when the user presses Stop. Prayer
maintenance is forced on for this task, so banked bones are buried at the
configured thresholds even if Prayer upkeep was disabled globally. Farming is
serviced according to `[farming].prioritise` (default on, so a needed farm pass
runs before the task step). The idle failsafe is skipped while Farm Prayer
Points runs so the kill loop stays continuous; the **Farm Run** button can still
queue a manual pass, and the failsafe runs again after the task stops.

Both tasks share the same combat primitives: the combat-style reader, the
combat-triangle weapon switch through the bank, the ammo guard, the food/HP
safety stops and the "Run from Combat" flee. Slayer-specific behaviour
(jumping, stall recovery, switch revert) is documented in
[slayer.md](slayer.md); this page covers the category and the dungeon task.

## Category layout

The category is part of the feature registry in
`src/mi2_aio/features.py`, which the desktop app reads:

```
Combat
  slayer     [combat.slayer]
  prayer     [combat.prayer]
  dungeons   [combat.dungeons]
Farming
  farming    [farming]
Global
  failsafe   [failsafe]
```

Config sections follow the same shape, so a UI can map a feature to the TOML
section it edits. The legacy top-level `[slayer]` section is still parsed as a
fallback for older configs, but new configs should use `[combat.slayer]`.

## Dungeons

### How a dungeon is entered

The dungeon list is reached from the Combat page:

```
Combat page -> Select Area -> Standard Dungeons -> <dungeon row> -> Start Dungeon
```

The task finds the dungeon row by matching a binarized template of the dungeon
name against the list (`assets/templates/dungeon_harvest_farm.png`). The name
text is white on dark/green rows, so a brightness mask matches reliably without
OCR.

Once started, the game keeps the dungeon going by itself: after the last enemy
of a wave it grants the dungeon's loot and spawns the next wave
(`MoveNextEnemy` fires `DungeonCompleted` and resets progress). The bot therefore
does not restart the dungeon; it stays in it and keeps the character alive.

### Loot

Each dungeon has its own loot table, shown in-game under **View Rewards**. That
table is the reason to raid a dungeon instead of doing slayer: the completion
loot is awarded per cleared run. The bot does not need to read the table — the
game awards the loot automatically — but the rewards panel was used to verify
which dungeon is selected and what it drops.

### In-dungeon confirmation

The bot considers itself "in a dungeon" when either signal is true:

- the on-screen **Dungeon Progress** label is present, or
- the save header's `active_action` equals the configured dungeon name
  (for example `Harvest Farm`).

The save-header check matters because the progress label briefly disappears
during wave transitions and while the area menu dims the screen. Without it the
bot would re-enter the dungeon and reset its progress.

### Combat loop

While in the dungeon the task:

- stops and flees when the Eat button stays disabled for two polls
  (`stop_when_out_of_food`, `flee_when_out_of_food`);
- flees and stops below a hard HP floor (a quarter of the mode profile's
  `min_hp_ratio`);
- switches to the counter combat style through the bank when the game tints the
  current style as disadvantaged, with the same ammo and verification guards as
  slayer;
- when `auto_style` is on and the current style is Melee, uses the save's active
  wave enemy id to choose slash/block/crush, equip the best owned weapon and set
  the stance (see [Melee gear and styles](#melee-gear-and-styles-scimitars-swords-mallets-defenders));
- when `auto_armour` is on, upgrades owned armour per slot using Defence
  requirements (the save's bank + equipment list is the ownership source, and
  each equipped slot is verified from the next autosave).

If the combat style is unreadable (wrong page, stats tab not selected), the task
clicks the Combat tab and the Offensive Stats tab until it can read it.

When the run ends (runtime limit, `Ctrl+C`, out of food, or an error), the bot
leaves combat and restores whatever the character was doing before the run, so a
dungeon test does not leave the account idle. See
[restore.md](restore.md).

### Configuration

```toml
[combat.dungeons]
dungeon = "Harvest Farm"
template = "assets/templates/dungeon_harvest_farm.png"
poll_seconds = 2.0
stop_when_out_of_food = true
flee_when_out_of_food = true
switch_cooldown_minutes = 3.0
auto_style = true
style_switch_cooldown_seconds = 20.0
auto_armour = true
armour_check_minutes = 10.0

[combat.dungeons.weapons]
melee = "Bone Scythe"
ranged = "Normal Bow"
magic = ""            # empty disables a style
```

`dungeon` is the display name used in logs and the save-header check; the
`template` is what actually locates the row. To raid a different dungeon, capture
its name from the Standard Dungeons list as a binarized mask and point
`template` at it.

## Melee gear and styles (scimitars, swords, mallets, defenders)

Every demo-available melee weapon is in `data/scimitars_defenders.json` with
equip requirements, full combat stats, Smithing recipes and drop sources:

- **Scimitar + defender** — the best slash setup.
- **Sword** — slash/block (1H); a 2H sword adds crush but occupies the off-hand.
- **Mallet** — a two-handed crush weapon; it occupies the off-hand, so no defender.
- **Bone Scythe** — two-handed comparison baseline.

```powershell
python -m mi2_aio gear                    # every table
python -m mi2_aio gear --slot scimitar
python -m mi2_aio gear --slot sword
python -m mi2_aio gear --slot mallet
python -m mi2_aio gear --slot defender
python -m mi2_aio gear --json             # full data for the UI
```

The loader (`equipment_db.py`) exposes `best_scimitar()`, `best_defender()`,
`best_loadout()`, `best_weapon_for_style()` and `weapons_for_style()`, with
craftable-only and standard-tier variants. Full tables and data provenance:
[combat-gear.md](combat-gear.md).

### Choosing the style for an enemy

`data/enemies.json` contains all 155 demo monsters with their Defence level and
Slash/Block/Crush defence bonuses, extracted from the client. `melee.py` ports
the game's exact hit-chance formula (`TargetCharacterStats.ComputeHitChance`):

```text
accuracy = floor((Attack + 9) * (style attack bonus + 64))
evasion  = floor((enemy Defence + 9) * (enemy style defence bonus + 64))
hit      = 1 - evasion/(2*accuracy)   if accuracy >= evasion
         = accuracy/(2*evasion)       otherwise
```

`melee.choose_melee_style()` evaluates slash, block and crush with the best
equippable weapon for each style (adding the best defender to one-handed
weapons) and returns the chosen style. If another style has lower enemy evasion
and its hit chance is within **2 percentage points** of the best, the
lower-evasion style wins. This prevents a counter-intuitive switch to a more
resistant style for a negligible accuracy gain (Mangrove Mantis: Block 37.3% at
+188 evasion vs Slash 36.0% at +178). Run it directly:

```powershell
python -m mi2_aio melee --enemy "Blue Slime"
python -m mi2_aio melee --enemy "Toxic Razorfish" --craftable --no-special
python -m mi2_aio melee --json
```

At Attack 48 / Defence 40 / Smithing 59:

| Enemy | Best style | Setup | Hit |
|---|---|---|---|
| Blue Slime | Crush | Mithril Mallet | 86.1% |
| Toxic Razorfish | Slash | Bone Scythe | 32.4% |
| Mangrove Mantis | Slash | Bone Scythe | 35.3% |
| Wyvern | Slash | Bone Scythe | 39.5% |
| Golbin | Block | Mithril 2H Sword | 97.0% |

The slayer and dungeon tasks use this live. The active enemy and equipped
weapon/off-hand come from the save (the same read that produces the header), so
dungeon waves work without OCR or screen reading. On an enemy change the task
computes the best style, equips the best **owned** candidate through the bank,
then clicks the matching stance button and verifies it from the UI. If no
recommended weapon is in the bank, the current setup is left alone. The scorer
compares the weapon and defender only — other equipped gear adds constant
bonuses. Set `auto_style = false` in `[combat.slayer]` / `[combat.dungeons]` to
use only the melee/ranged/magic triangle switch.

## Adding a combat feature

1. Add a `Feature` entry with `category="combat"` in `features.py`.
2. Put its settings in a `[combat.<feature>]` section and parse it in
   `config.py`.
3. If it is runnable, implement a task in `src/mi2_aio/tasks/` and register it
   in `tasks/__init__.py`.
4. Reuse the readers in `ui.py` (style, food, HP, ammo, area menu) so the
   category behaves consistently.

## Verified against the demo build

- The area menu, Standard Dungeons tab, dungeon rows, Start Dungeon and View
  Rewards all respond to posted clicks while the game is unfocused.
- The Harvest Farm name template matches at score 1.0 in the live list.
- Starting from idle, the task opens the area menu, selects Standard Dungeons,
  finds Harvest Farm, starts it and logs `Dungeon 'Harvest Farm' started.`
- Once inside, the task stays in the dungeon across wave transitions, logs the
  in-dungeon state once, and applies the ammo guard when Ranged is the counter
  style but the ammo slot is empty.

## Caveats

- The window must not be minimized; the UI must be reachable (the task clicks
  the Combat tab itself if another page is open).
- The active enemy and equipped slots are read from the save. The game
  autosaves every 10 seconds, so a dungeon wave change can take up to one
  autosave to be noticed; the bot then switches and verifies the stance from the
  UI. The fight continues in the meantime.
- Coordinates assume the reference 2560x1369 client layout. Re-capture regions
  in `src/mi2_aio/ui.py` if the game's UI scale changes.
- Dungeon names unlocked later in the game may sit outside the captured list
  region; re-capture the template and, if needed, extend `DUNGEON_LIST_BOX`.
- The bot does not buy food or ammo and does not evaluate whether the character
  can survive a dungeon. Use short runs first.
