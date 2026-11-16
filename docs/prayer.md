# Prayer upkeep: burying bones

Prayer maintenance keeps Prayer points topped up by burying the bones the
character collects while fighting. It runs **alongside every task** (slayer,
dungeons, or any skilling task) between main-task steps.

## Trigger

The bot reads two values from the save on every poll:

| Value | Source |
| --- | --- |
| Bone quantity | Bank tab stack list (`bank_stacks`), summed per item |
| Prayer points | Player wallet currency `PrayerPoints` |

A bury pass starts when **either** condition is true:

- `bone_count >= bone_threshold` (default **50**), or
- `prayer_points < low_prayer_threshold` (default **100**) and at least one
  bone is owned.

No bones means no bank visit at all, so normal polling costs nothing. The
`check_seconds` throttle (default 60 s) prevents bank spam when the save has
not refreshed yet or a bury failed.

## Supported bones

`data/bones.json` is generated from the game's item `Bury` capability:

| Item | Prayer points |
| --- | --- |
| Bone | 1 |
| Big Bone | 6 |
| Magic Dust | 8 |
| Small Dragon Bone | 80 |

Some monsters drop only one variation, so all four are counted and buried.
Dungeons have no regular enemy drops; bones come from Battle Areas (for example
Corrupted Farmlands → Giant Chicken, which drops a Big Bone).

## Bank flow

1. Open the bank.
2. Search a single word from the bone name (`Bone`, `Dust`).
3. Select the **exact** result cell. The save's bank order reproduces the grid:
   the demo's `Bone` search shows `Bone Scythe` first, then `Bone`, so the bot
   computes the index from `bank_order` filtered by the search word instead of
   trusting the first cell.
4. Press the quantity row's **All** button (`BANK_BURY_ALL`).
5. Press **Bury N Bones** (`BANK_BURY_ROW`). This is a normal button: one press
   buries the selected quantity. The panel's green `+N Prayer Points` total is
   used to confirm it is a bury panel before clicking.
6. Wait for the save to show a lower bone count or higher Prayer points.
7. Repeat for the next owned bone type / duplicate stack.
8. Restore the current action's page with the sidebar action button (the same
   mechanism farming uses), so combat/skilling resumes.

All clicks are posted to the game window and every point is in the reference
coordinate space (`ui.py`), so the pass works on any display while the game is
unfocused.

Duplicate bank stacks are supported: the save can contain several stacks of the
same bone (for example `Bone x2` and `Bone x53`). Quantities are summed for the
trigger, and the bury loop removes one stack per pass.

## Configuration

```toml
[combat.prayer]
enabled = true
bone_threshold = 50        # bury a full batch regardless of Prayer points
low_prayer_threshold = 100 # top up early when Prayer is low
check_seconds = 60         # minimum time between checks
verify_seconds = 12        # wait for the save to confirm the bury
```

Set `low_prayer_threshold = 0` to bury **only** when the bone batch threshold
is reached.

## Live verification (Demo 0.11.4-alpha)

- The bank parser was corrected to read the stack record
  `quantity, placeholder, locked, item` (quantity **before** the id). It now
  also sums duplicate stacks, so a live `Bone x75` stack is counted correctly.
- Search `Bone` showed `Bone Scythe` in cell 0 and `Bone` in cell 1; selecting
  cell 1 showed **Bury Item**.
- Pressing **All** changed the action row to **Bury 57 Bones** and the total to
  **+57 Prayer Points**.
- One press produced the game's `+60 PP` toast (live drops added bones between
  the quantity click and the bury). The next save showed
  `PrayerPoints = 58`, no `Bone` stack, and bank space down by one.
- A full runner pass (`run --task slayer --duration 1`) logged
  `Prayer upkeep: 99 bone(s) banked at 0 Prayer points; burying.` and then
  `Prayer upkeep done: buried 104 bone(s), +105 Prayer points (now 105).` It
  then restored the combat page and continued the Slayer task.
- After the run the save showed `PrayerPoints = 98`, one newly dropped `Bone`,
  and the failsafe had resumed `Spikemoss Shrub`.
- While Fishing (`run --task observe --duration 1`), the low-Prayer branch
  triggered with one bone: `1 bone(s) banked at 98 Prayer points; burying.`
  It buried it (+1, now 99) and returned to the Fishing page.
- The sidebar action button returned from the bank to the combat page.

## Caveats

- The save lags the UI by up to one autosave (~10 s). The bury loop waits
  `verify_seconds` for the save to confirm and otherwise stops that bone type
  instead of clicking repeatedly.
- Bank placeholders (0-quantity stacks) are not counted; burying removes normal
  stacks entirely, so the search grid stays aligned.
- If a duplicate stack shifts the search grid, the pass scans the visible
  results for the next panel that shows Bury Item instead of trusting the
  computed index.
- Prayer points are read from the wallet, not the skill panel. The game may
  still display a stale point value for a frame after a bury.
- An active Prayer drains points during combat; the bot will top up again as
  soon as a new bone drops while points are below 100. That is the configured
  low-prayer rule, not a loop bug.

