# Slayer automation

`python -m mi2_aio run --task slayer` keeps a slayer task running while you are
away:

1. **Jump to the task enemy** when the run starts (optional) and whenever the
   task monster changes.
2. **Switch weapons** when the combat triangle says the current style is
   ineffective against the current enemy.
3. **Stop when food runs out** (optional), before the character can die.
4. **Recover from bad fights**: jump again if task progress stalls, and undo a
   weapon switch that does not produce kills.

Everything is read from the rendered UI and the save header; there is no OCR and
no memory reading.

## What it reads

| Signal | How |
|---|---|
| Combat style word | Three glyph templates (`assets/templates/style_*.png`) matched against the value in the player's Offensive Stats panel |
| Style effectiveness | The game's own tint: green = favourable, orange-red = unfavourable, white = neutral |
| Task monster / progress | Pixel fingerprints of two fixed regions in the Slayer Task panel |
| Active task state | Save `slayer_task`: master, enemy, task length and progress |
| Jump button present | Green fill of the Jump To Enemy button |
| Food left | Eat button fill: green = food available, uniformly dark = disabled (out of food), bright content = covered by a picker/tooltip |
| HP | Filled fraction of the player HP bar |
| Ammo | White quantity text in the equipment panel's ammo slot (an empty slot only shows a translucent placeholder) |
| Current enemy | Save `active_enemy_id` (e.g. `BlueSlime`), with the header `active_action` as fallback |

All regions are defined for a **2560x1369 client area** in `src/mi2_aio/ui.py`.
Captures are resized to that reference before analysis, so a window with a
different size still works as long as the game scales its UI with the window.

## Decision policy

### Jumping

- `jump_on_start = true` clicks **Jump To Enemy** once when the run starts.
  This restarts the current spawn (the game's `SelectEnemy` resets area
  progress), so set it to `false` if you always start the bot while already
  fighting the task monster.
- When the task monster name changes (task completed, new task assigned), the
  bot jumps once.
- If task progress does not move for `stall_minutes`, the bot jumps once and
  retries. After `max_stalls` consecutive stalls it stops with an error instead
  of jumping forever.
- Jumps are rate-limited by `jump_cooldown_seconds`.

With Auto Slayer enabled, the game itself selects the new enemy when the task
completes in the same area. The bot's jump is then redundant but harmless.

### Task completion

The active task is read from the save (`SaveHeader.slayer_task`): master,
enemy, task length and progress. The game immediately assigns a new task when
one completes, so completion is detected by:

- a changed `(master, enemy, length)` key, or
- a progress reset on the same key (covers two tasks against the same enemy), or
- a saved progress equal to the task length (counted once).

The current task is recorded at startup but not counted. Each completion logs
`Slayer task completed (N): ...`. `max_tasks` (or `run --tasks N`) stops the run
after N completions; `0` means no limit. The task panel is still used for the
Jump To Enemy button and task/progress fingerprints.

### Slayer masters

`data/slayer_masters.json` contains all ten demo masters with their areas,
base task lengths, reroll/block costs and unlock requirements. Query it with:

```powershell
python -m mi2_aio slayer-masters
python -m mi2_aio slayer-masters --json
```

The loader (`slayer_master_db.py`) exposes `find()`, `names()` and
`unlocked(levels)`. Automatic master switching is not implemented yet; the
database is ready for it.

### Melee style choice

When `auto_style = true` and the current combat style is Melee, the bot reads
the active enemy id and the equipped Weapon/Offhand slots from the save, then
computes the best slash/block/crush setup with `data/enemies.json`
(`melee.choose_melee_style()`). It equips the best **owned** candidate through
the bank, clicks the stance button and verifies the Attack Stance value.

- Mallets are two-handed crush weapons; scimitars and 1H swords can use a
  defender.
- If no recommended weapon is in the bank, the current setup is kept and the
  bot backs off for 10 minutes instead of thrashing the bank.
- Enemy changes (new task, new dungeon wave) clear the plan immediately.
- When `auto_armour` is on, the bot also upgrades owned armour per slot using
  Defence requirements at task start and every `armour_check_minutes`. Defenders
  are armour too; a defender is only used with a one-handed weapon. Each
  equipped slot is verified from the save before the upgrade is accepted.
- The old melee/ranged/magic triangle switch below remains the fallback when
  `auto_style = false`, when the current style is Ranged/Magic, or when the
  enemy cannot be identified yet.

### Weapon switching (melee/ranged/magic triangle)

The game tints the player's **Combat Style** using the combat triangle
(`OffensiveStatsContainer.SetLabelStyle`). Orange-red means the current style is
disadvantaged. The bot then equips the counter style through the bank:

```
Melee -> Ranged -> Magic -> Melee
```

The bank path is used because extra loadouts are shop unlocks. The bot opens the
bank, filters with the search box (posted `WM_CHAR`), clicks the first result,
presses the item's **Equip To** row, and returns to the Combat tab.

Guards:

- **Ammo.** A bow with an empty ammo slot cannot fire. The bot reads the ammo
  slot and refuses to switch to Ranged when it is empty; if the character is
  already on a bow without ammo, it falls back to the configured melee weapon.
- **Alternative style.** If the primary counter is unavailable (no ammo, no
  configured weapon), the other non-current style is tried when it is
  configured.
- **Verification.** After a switch the bot re-reads the style word. If the
  weapon did not change, that style is blocked for the rest of the task and
  switching backs off for 10 minutes.
- **Revert.** If no task progress appears within `switch_grace_minutes` after a
  verified switch, the previous weapon is equipped again and the style is
  blocked for the task. This covers weapons the character cannot actually use
  (for example a staff above its Magic level, or a bow with 0% hit chance).
- A new task clears the blocked styles, because a different enemy can favour a
  style that did not help before.

### Food and HP

- The Eat button is disabled when the selected food quantity reaches 0. After
  two consecutive disabled polls, the bot clicks **Run from Combat** (so the
  character is not left fighting with no food) and stops the run when
  `stop_when_out_of_food = true`.
- If the Eat button is covered (food picker open) the state is "unknown" and
  the bot does not stop on it.
- HP below the mode profile's `min_hp_ratio` is logged as a warning (the game's
  auto-eat normally keeps HP near its own threshold, which can be below the
  profile floor). HP below a quarter of that floor flees combat and stops the
  run as a backstop.

## Configuration

Slayer is a feature of the **Combat** category; see [combat.md](combat.md) for
the category layout and the dungeon task.

```toml
[combat.slayer]
jump_on_start = true
poll_seconds = 2.0
stop_when_out_of_food = true
flee_when_out_of_food = true
stall_minutes = 12.0
max_stalls = 2
jump_cooldown_seconds = 60
switch_cooldown_minutes = 3.0
switch_grace_minutes = 4.0
auto_style = true
style_switch_cooldown_seconds = 20.0
auto_armour = true
armour_check_minutes = 10.0
max_tasks = 0

[combat.slayer.weapons]
melee = "Bone Scythe"
ranged = "Normal Bow"
magic = ""
```

The legacy top-level `[slayer]` section is still read as a fallback, but new
configs should use `[combat.slayer]`.

Set a weapon name to `""` to disable that style. Names must match the first
bank search result for that query. Use names your character can equip: the
revert guard will undo a switch that produces no kills, but the run wastes a
few minutes discovering it.

## Verified against the demo build

- Jump To Enemy via posted clicks works while the game is unfocused.
- Bank search accepts posted `WM_CHAR` after a posted click focuses the box;
  backspaces clear the previous query.
- The combat style label turns orange-red for Melee vs a Magic enemy and green
  for Ranged vs the same enemy.
- A disabled Eat button has no green fill and no bright pixels (max brightness
  90); a filled slot shows the white quantity (max 255).
- Live run: startup jump, switch to `Normal Bow`, verification, then a revert
  to `Bone Scythe` after four minutes without progress, after which kills
  resumed.
- **3-task live run (55m40s):** completed Creeper Vines 0/42,
  Mangrove Strider 0/69 and Mangrove Strider 0/114, then stopped at 3/3 and
  restored **Woodcutting / Spikemoss Shrub**. The second task was the same
  enemy with a new length, and the save-based counter handled it correctly.
- Farming passes ran before combat steps during the same run (one pass
  harvested/composted/planted/watered 2 plots; the others were clean or mill
  only). Auto-eat kept the character alive through low-HP warnings; no food
  stop and no death.
- `slayer-masters` lists all 10 demo masters with areas, lengths and costs.

## Caveats

- The UI must be on the **Combat** page and the window must not be minimized.
  If another page is open, the bot clicks the Combat tab (rate-limited).
- Coordinates assume the reference layout. If the game's UI scale changes,
  re-capture the regions in `src/mi2_aio/ui.py`.
- The bot never buys arrows or food. When ammo or food runs out it degrades
  (melee fallback) or stops.
- Loadouts are not used; only the first (free) loadout exists in the demo.
