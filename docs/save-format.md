# Melvor Idle 2 save format (verified against v0.11.4-alpha)

Derived by decompiling the game's .NET assembly (`GamesByMalcs.Melvor2.dll`) for the sole purpose of reading save data. The project does not ship or modify game code.

## Location

```
%APPDATA%\Games By Malcs\Melvor Idle 2\
├─ device_settings\deviceSettings.json
├─ logs\godot*.log
└─ steam\<SteamID64>\
   ├─ userSettings.json
   ├─ saves\
   │  ├─ save_<uuid>.sav     ← current save
   │  ├─ save_<uuid>.bak     ← previous save
   │  └─ save_<uuid>.tmp     ← transient write target
   └─ save_backups\
      └─ <uuid>_0.bak … <uuid>_10.bak
```

`<uuid>` is the save slot id, not the character name.

## Write behavior

- Autosave interval is **10 seconds** (`Constants.AutoSaveInterval`).
- Writes go to a `.tmp` file, then the old `.sav` is moved to `.bak`, then `.tmp` is renamed to `.sav`.
- The 10 files in `save_backups` are rotating long-term backups (newest seen: `_10`).
- Because the rename is atomic, copying `.sav` is generally safe, but retry on a Brotli failure in case you catch a transitional state.

## Encoding

The whole file is a raw **Brotli** stream (no magic bytes, no header). Decoded content is a little-endian binary object graph:

```
int32   saveVersion
SaveHeader
Game object
```

Important: Python's `brotli` / `brotlicffi` reject these streams (they appear to use a window size/feature the bindings won't accept). .NET `System.IO.Compression.BrotliStream` decodes them correctly, so `tools/SaveTool` is used instead.

### SaveHeader layout

Field order and types, matching `SaveHeader.ReadFrom` in the game:

| Field | Type | Notes |
|---|---|---|
| `version` | int32 | version of this save |
| `UUID` | 16 bytes | .NET `Guid.ToByteArray()` (mixed-endian) |
| `CharacterName` | string | BinaryWriter 7-bit-length-prefixed UTF-8 |
| `Gamemode` | string | e.g. `Test` |
| `Timestamp` | int64 | `DateTime.ToBinary()` |
| `ActiveEntityName` | string | e.g. `Fishing` |
| `ActiveEntityIcon` | string | `res://...` path |
| `ActiveActionName` | string | e.g. `Quiet Bend` |
| `ActiveActionIcon` | string | `res://...` path |
| `TotalLevel` | int32 | sum of skill levels |
| `GP` | int64 | |
| `SlayerCoins` | int64 | |
| `IsDemo` | bool | 1 byte |

Version thresholds that change layout:
- `< 9` (`Localization`): an extra legacy string is read instead of the four active-entity/action strings.
- `< 24` (`Alpha0_11_0`): no `IsDemo` byte.

### Combat state (beyond the header)

`parse_header(data)` also reads the following combat fields and exposes them on
`SaveHeader`:

| Field | Notes |
|---|---|
| `current_hp` | Current hitpoints from the `MelvorBase:Combat` entity's `Player` component. The component starts with a 4-byte region containing `CharacterHealth.Current` as an int32. |
| `max_hp` | Hitpoints level × 10 (the demo's base maximum). |
| `active_enemy_id` | Active enemy id (e.g. `BlueSlime`) from the combat component. Empty outside combat. This is the **dungeon wave enemy** too, so style choice needs no OCR. |
| `equipment` | Slot → item id map (`Weapon`, `Offhand`, `Ammo`, ...). A two-handed weapon appears in both `Weapon` and `Offhand`. |
| `bank_items` | Item ids in the bank/inventory list (game ids). Used for ownership checks when equipping armour upgrades. Equipped items are not in the bank list, so combine it with `equipment`. |
| `bank_order` | The same ids in bank display order (duplicates removed). Used to compute a bank search result's grid index. |
| `bank_stacks` | Item id → quantity for the first bank tab. Duplicate stacks of one item are **summed**. |
| `wallet` | Currency balances (`GoldPieces`, `PrayerPoints`, `SlayerCoins`). |
| `prayer_points` | Convenience value: `wallet["PrayerPoints"]`. |
| `slayer_task` | Active Slayer master, enemy id, task length and progress. A new task is detected by a changed `(master, enemy, length)` key or a progress reset; the game immediately assigns the next task on completion. |

- The active enemy is the second `Enemy` field in the combat component; its id
  is the last `MelvorBase:` token before the enemy's attack stance.
- The `Equipment` component is a count and length-prefixed slot entries; each
  non-empty payload ends with `MelvorBase:<ItemId>`.
- Empty slots are omitted from `equipment`.

### Bank stacks and the wallet

The first bank tab's stack list starts at the `\tInventory` marker. Each stack
record is:

```
int32  quantity
bool   isPlaceholder
bool   isLocked
string item id ("MelvorBase:<Id>")
```

The list ends at the `Tab 1` label. The quantity is **before** the item id; the
game allows several stacks of one item (for example `Bone` from a loot batch
next to an older `Bone` stack), so the parser sums them. Reading the quantity
after the id shifts every value by one stack, which is easy to miss because the
numbers still look plausible.

The currency wallet is a count-prefixed list of `int64 quantity` +
`string currency id` pairs. The first `MelvorBase:GoldPieces` occurrence is the
player's wallet; later occurrences are statistics. `PrayerPoints` is read from
this wallet, not from the Prayer skill panel.


### Version enum (selected)

```
Unknown = -1, Initial = 0, Localization = 9,
Alpha0_10_4 = 23, Alpha0_11_0 = 24, Alpha0_11_1 = 25,
Alpha0_11_1_1 = 26, Alpha0_11_3 = 27, Alpha0_11_4 = 28
```

Observed live save: version `28`, character `Adventurer`, gamemode `Test`, demo build, total level 729, active action `Spikemoss Shrub` (Woodcutting) or a combat enemy/dungeon.

> The enum list was taken from the alpha build; a newer build may add versions. The header parser only relies on the `< 9` and `< 23` thresholds, so new versions remain readable.

## Decoding manually

```powershell
.\tools\bin\SaveTool.exe <save.sav> <out.raw>
```

Then parse the header with `mi2_aio.savefile.parse_header(bytes)`.

## Skill levels and XP

Each skill is stored as a `MelvorBase:<Skill>` entity whose **Experience**
component contains the exact current values:

```
Experience
int32   payload length   (12 on v28)
double  Xp
int32   Level
```

Older saves (`version < 25`) use a 16-byte payload with an extra int32 before
the level. The parser reads the skill level directly:

```powershell
python -m mi2_aio levels          # all skill levels and XP
python -m mi2_aio levels --json
```

`read_skills()` is the API for the auto-upgrade and other features. Do **not**
read the Skills page's `current / demo max` display (for example `56/60`) as a
single number: `56` is the level and `60` is the demo level cap. The save gives
the exact level, and the parsed total is checked against the header's
`TotalLevel` (currently 727/727).

The parser looks for the first exact `MelvorBase:<Skill>` whose next four bytes
are a plausible component length and whose `Experience` component is within 128
bytes. That skips longer ids such as `AttackTask3`, `StrengthHelmet` and
`SmithingTorso`, as well as the skill-name list near the header.

## Reading more of the save

The remainder is a custom binary object graph (`SaveWriter`/`SaveReader` with
region-length prefixes and a type registry). The top-level walk is implemented:
entity count → entity id + region → component count → component id + region.
That is enough to read `current_hp` from the Combat entity's `Player` component
(the first region is a single int32). Other inventory/action state still uses
the header and targeted component scans; fully decoding every component remains
out of scope.
