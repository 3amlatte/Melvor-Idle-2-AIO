# Melee gear database (weapons + armour)

The melee database covers every demo-available weapon for the three melee
styles — **scimitars** (slash), **swords** (slash/block, or slash/crush/block
for 2H), **mallets** (crush) — and every armour slot: helmets, torsos, legs,
boots, gloves, capes, amulets, rings and off-hand items. Defenders live in the
armour list because they use the **Defence** skill. Each item has its equip
requirements, full combat stats, Smithing recipe and drop sources; it is the
data foundation for the auto-upgrade feature.

A scimitar or 1H sword can pair with a defender. A two-handed sword, scythe or
mallet occupies both the weapon and off-hand slots, so it cannot use a defender.

- Data file: `data/scimitars_defenders.json`
- Loader: `src/mi2_aio/equipment_db.py`
- Enemy data: `data/enemies.json` (levels + Slash/Block/Crush defence)
- Style engine: `src/mi2_aio/melee.py` (`choose_melee_style()`)
- CLI: `python -m mi2_aio gear`, `python -m mi2_aio melee`

## Demo items

### Scimitars (weapon, slash)

| Item | Equip | Slash Atk | Str | Smithing | Materials | Other source |
|---|---|---:|---:|---|---|---|
| Copper Scimitar | Attack 10 | 34 | 16 | 6 | 2x Copper Bar | |
| Iron Scimitar | Attack 20 | 44 | 20 | 11 | 2x Iron Bar | |
| Steel Scimitar | Attack 30 | 56 | 24 | 27 | 2x Steel Bar | |
| Mithril Scimitar | Attack 40 | 69 | 28 | 37 | 2x Mithril Bar | Mangrove Mantis |
| Toxic Razors Scimitar | Attack 42 | 74 | 29 | — | drop only | Toxic Razorfish (Toxic Bog, 0.68%) |
| Adamant Scimitar | Attack 50 | 82 | 32 | 47 | 2x Adamantite Bar | Mangrove Mantis, Wolf |

### Defenders (offhand)

| Item | Equip | Slash Atk | Str | Slash Def | Smithing | Materials | Other source |
|---|---|---:|---:|---:|---|---|---|
| Copper Defender | Defence 10 | 5 | 0 | 6 | 5 | 1x Copper Bar | |
| Iron Defender | Defence 20 | 8 | 0 | 12 | 10 | 1x Iron Bar | |
| Steel Defender | Defence 30 | 11 | 1 | 17 | 25 | 1x Steel Bar | |
| Mithril Defender | Defence 40 | 14 | 2 | 22 | 35 | 1x Mithril Bar | Mangrove Mantis |
| Mantis Defender | Defence 45 | 17 | 3 | 26 | — | drop only | Mangrove Mantis |
| Adamant Defender | Defence 50 | 20 | 4 | 27 | 45 | 1x Adamantite Bar | Mangrove Mantis, Spirit Stag |

Defenders are stored in the **armour** list (`slot: "offhand"`,
`type: "defender"`), not a separate top-level array, because they use the
Defence skill and compete for the off-hand slot. `db.defenders` and
`gear --slot defender` remain as convenient views.

The JSON also stores the full stat block (power rating, turn interval, stab /
crush / block / accurate / powerful / long-range / empowered / focused bonuses),
sell price and the exact Smithing category. `gear --json` prints everything.

### Toxic Razors Scimitar is a Melvor 2 item

It is not an MI1 item. Evidence:

- The installed `Melvor2.exe` contains the item object `ToxicRazorsScimitar`
  ("Toxic Razors Scimitar", sells 1,332) and the `ToxicRazorfish` monster drop
  table includes it with weight 1 in the 40% table (0.678% per kill).
- MI2 wiki: [Toxic Razors
  Scimitar](https://melvoridle.wiki/melvor-idle-2/items/toxic-razors-scimitar)
  and [Toxic
  Razorfish](https://melvoridle.wiki/melvor-idle-2/enemies/toxic-razorfish),
  both labelled Demo 0.11.2.
- The MI2 item list (page 13) lists it with Attack 42 and a 1,332 sell price.
- The MI2 demo attack reference lists the `ToxicRazors` special attack.
- A search of the Melvor 1 wiki for "Toxic Razors" returns no such item.

The icon file is `ToxicRazorsDagger.png` (a legacy art filename), which can make
it look like an MI1 dagger; the item’s display name and type are Scimitar. It
drops from **Toxic Razorfish in Toxic Bog**, ~0.678% per kill (1 in 147).

## Swords

Swords are one-handed (**Slash + Block**, plus Stab on 1H swords) or
two-handed (**Slash + Crush + Block**). The 2H versions occupy the off-hand.

| Sword | Equip | Slash | Block | Str | Smithing |
|---|---|---:|---:|---:|---|
| Stone Sword | Attack 1 | 20 | 25 | 12 | 1 — 2x Stone |
| Copper Sword | Attack 10 | 27 | 34 | 16 | 6 — 2x Copper Bar |
| Iron Sword | Attack 20 | 33 | 42 | 20 | 11 — 2x Iron Bar |
| Steel Sword | Attack 30 | 43 | 55 | 24 | 26 — 2x Steel Bar |
| Mithril Sword | Attack 40 | 54 | 70 | 28 | 36 — 2x Mithril Bar |
| Adamant Sword | Attack 50 | 61 | 79 | 32 | 46 — 2x Adamantite Bar |

### Two-handed swords

| Sword | Equip | Slash | Crush | Block | Str | Smithing |
|---|---|---:|---:|---:|---:|---|
| Copper 2H Sword | Attack 10 | 47 | 49 | 61 | 42 | 9 — 4x Copper Bar |
| Iron 2H Sword | Attack 20 | 55 | 60 | 73 | 46 | 15 — 4x Iron Bar |
| Steel 2H Sword | Attack 30 | 67 | 72 | 89 | 48 | 31 — 4x Steel Bar |
| Mithril 2H Sword | Attack 40 | 83 | 87 | 108 | 50 | 41 — 4x Mithril Bar |
| Adamant 2H Sword | Attack 50 | 92 | 98 | 121 | 54 | 51 — 4x Adamantite Bar |
| Staggering Lash Greatsword | Attack 55 | 100 | 109 | 136 | 64 | drop: Wyvern |

The **Staggering Lash Greatsword** is a special drop-only 2H sword.

## Mallets

Mallets are two-handed **Crush** weapons. They occupy the off-hand slot, so
they cannot be paired with a defender (the game's item data lists
`MelvorBase:Offhand` under `OccupiesSlots`).

| Mallet | Equip | Crush | Str | Smithing |
|---|---|---:|---:|---|
| Stone Mallet | Attack 1 | 38 | 45 | 3 — 4x Stone |
| Copper Mallet | Attack 10 | 61 | 54 | 9 — 4x Copper Bar |
| Iron Mallet | Attack 20 | 73 | 56 | 15 — 4x Iron Bar |
| Steel Mallet | Attack 30 | 89 | 58 | 31 — 4x Steel Bar |
| Mithril Mallet | Attack 40 | 108 | 62 | 41 — 4x Mithril Bar |
| Adamant Mallet | Attack 50 | 121 | 66 | 51 — 4x Adamantite Bar |

The JSON also keeps the full Stab/Crush/Block attack bonuses and every defence
bonus for each item. `gear --slot sword|mallet` shows the key columns.

## Armour

`armour` contains every demo helmet, torso, legs, boots, gloves, cape, amulet,
ring and off-hand item (188 entries), including the six defenders. Full stats,
all level requirements, Smithing recipes and drop sources are stored. The
loader exposes:

- `db.armour_for_slot("torso")` / `"helmet"` / `"offhand"` / ...
- `db.owned_items(header)` — equipped + bank items from the save
- `db.best_armour(slot, levels, owned=..., subtype="defender")`

Ranking is `protection → total defence → melee strength → required level`.
Only items that meet **all** requirements are considered (some armour needs two
skills, e.g. chainmail needs Ranged + Defence). Magic/Ranged armour is never
selected for melee auto-upgrade.

At **Defence 40**, the best owned set is the Mithril set:

| Slot | Item | Prot | Total Def | Smithing |
|---|---|---:|---:|---|
| Helmet | Mithril Helmet | 93 | 135 | 37 |
| Torso | Mithril Platebody | 246 | 274 | 45 |
| Legs | Mithril Platelegs | 185 | 203 | 43 |
| Boots | Mithril Boots | 93 | 135 | 37 |
| Gloves | Mithril Gloves | 0 | 66 | 36 |
| Off-hand (1H) | Mithril Defender | 0 | 135 | 35 |

```powershell
python -m mi2_aio gear --slot armour
python -m mi2_aio gear --slot helmet
python -m mi2_aio gear --slot defender
python -m mi2_aio gear --json     # includes the armour array
```

The live auto-upgrade reads the bank and equipped slots from the save, compares
each slot against the best owned item, and equips upgrades. Bank search returns
several items for a slot word ("Helmet" lists every helmet), so the upgrader
tries candidates and **verifies the equipped slot from the save** before
accepting; if the desired item is not in the bank it reverts. It runs at task
start and every `armour_check_minutes` (default 10). A defender is only
considered for a one-handed weapon; two-handed weapons clear the offhand.

## Choosing a melee style for an enemy

The game computes melee accuracy from the player's **Attack level** and the
stance's attack bonus, and enemy evasion from the enemy's **Defence level** and
the matching Slash/Block/Crush defence bonus:

```text
accuracy = floor((Attack + 9) * (style attack bonus + 64))
evasion  = floor((enemy Defence + 9) * (enemy style defence bonus + 64))
hit      = 1 - evasion/(2*accuracy)   if accuracy >= evasion
         = accuracy/(2*evasion)       otherwise
```

`data/enemies.json` contains all 155 demo monsters with their levels and
Slash/Block/Crush defence values (extracted from the client). `melee.py` picks
the best weapon for each style (adding the best defender to one-handed weapons),
computes the hit chance, and returns the best of the three styles.

At **Attack 48 / Defence 40 / Smithing 59**:

| Enemy | Best style | Setup | Hit |
|---|---|---|---|
| Blue Slime | **Crush** | Mithril Mallet | 86.1% |
| Toxic Razorfish | **Block** | Mithril 2H Sword | 33.7% |
| Mangrove Mantis | **Block** | Mithril 2H Sword | 36.7% |
| Wyvern | **Slash** | Bone Scythe | 39.5% |
| Golbin | **Block** | Mithril 2H Sword | 97.0% |

```powershell
python -m mi2_aio melee --enemy "Blue Slime"
python -m mi2_aio melee                      # current save enemy (slayer/dungeon)
python -m mi2_aio melee --enemy "Blue Slime" --craftable
python -m mi2_aio melee --enemy "Blue Slime" --no-special
python -m mi2_aio melee --enemy "Blue Slime" --json
```

The scorer uses the weapon and defender only; other equipped gear contributes
constant bonuses and is not part of the weapon/style comparison yet. The live
slayer and dungeon tasks call `choose_melee_style()` for the active enemy (read
from the save), equip the best **owned** candidate through the bank and click
the matching stance. If no recommended weapon is in the bank they keep the
current setup and log it.

### Other weapons (comparison baselines)

| Item | Equip | Slash | Str | Interval | Type | Source |
|---|---|---:|---:|---:|---|---|
| Bone Scythe | Attack 23 | 95 | 47 | 3.3 s | 2H Sword (occupies weapon + offhand) | Harvest Farm Chest |

The Bone Scythe is **two-handed**: it blocks the off-hand slot, so it cannot be
paired with a defender. It is included in the database as the current melee
baseline.

## Bone Scythe vs scimitar + defender

Live character levels used for this comparison (read from the save): **Attack
48, Defence 40, Strength 56, Smithing 59**. The Skills page displays this as
`56/60` for Strength, where 60 is the demo cap; the save stores the exact level
(56).

```text
Bone Scythe (2H): power 672 | 95 slash | 47 str | 3.3 s

Best available (Attack 48 / Defence 40 / Smithing 59):
  Toxic Razors Scimitar + Mithril Defender
  power 1204 | 88 slash | 31 str | 2.6 s | 22 slash def
  power +532 | slash -7 | strength -16 | 0.70 s faster

Best craftable:
  Mithril Scimitar + Mithril Defender
  power 1148 | 83 slash | 30 str | 2.6 s | 22 slash def
  power +476 | slash -12 | strength -17 | 0.70 s faster
```

**Answer:** for this character, **Mithril Scimitar + Mithril Defender** is the
first clear standard upgrade over the Bone Scythe (both are craftable now at
Smithing 59 and equippable at Attack 40 / Defence 40). If the **Toxic Razors
Scimitar** drop is owned, use it with the Mithril Defender — that is the best
pair available at Attack 48 / Defence 40. At Attack 50 / Defence 50, upgrade to
**Adamant Scimitar + Adamant Defender** (craftable now at Smithing 59, equip
later).

The scythe has higher raw slash and strength per hit, but it is 27% slower
(3.3 s vs 2.6 s), cannot use a defender, and its game power rating is much
lower (672 vs 1,148/1,204). The faster pair also wins on slash accuracy per
second (31.9/33.8 vs 28.8), which matters against evasive enemies. Its
strength-per-second is lower (11.5/11.9 vs 14.2), so the scythe can still be
competitive against very low-evasion targets — but the scimitar + defender pair
is the better general-purpose slash setup.

Steel is **not** a clear replacement: Steel Scimitar + Steel Defender has only
67 slash / 25 strength, and although the scimitar's single-item power rating is
868, the pair's raw totals are below the scythe. Mithril is the first tier where
the pair clearly overtakes it.

```powershell
python -m mi2_aio gear --compare "Bone Scythe"
```

The client also contains artwork for additional tiers that are not in the
Demo 0.11.2 item database. They are listed under `future_tiers` in the JSON
(Bronze, Black, Rune, Dragon, Elder, Elderite, Dawnsteel, Meteorite, Titan,
Palace; Drowned, Shocking Nova defenders) and can be filled in when those items
become available.

## Using it

```powershell
python -m mi2_aio gear                    # every gear table
python -m mi2_aio gear --slot scimitar    # slash weapons
python -m mi2_aio gear --slot sword       # 1H + 2H swords
python -m mi2_aio gear --slot mallet      # crush weapons
python -m mi2_aio gear --slot defender    # off-hand defenders
python -m mi2_aio gear --slot armour      # every armour slot
python -m mi2_aio gear --slot helmet      # one slot (torso/legs/boots/...)
python -m mi2_aio gear --slot other       # two-handed comparison weapons
python -m mi2_aio gear --json             # full data for the UI
python -m mi2_aio gear --compare "Bone Scythe"
```

`gear --compare` reads Attack/Defence/Smithing from the save automatically. Pass
`--attack`, `--defence` or `--smithing` to override any of them for a
hypothetical comparison.

```python
from mi2_aio.equipment_db import load_database

db = load_database()
db.best_scimitar(43)                       # best equippable by slash attack
db.best_scimitar(43, include_special=False)  # standard tiers only
db.best_scimitar(43, craftable_only=True, smithing_level=37)
db.best_defender(45)
db.best_defender(50, craftable_only=True, smithing_level=45)
db.best_weapon_for_style("crush", 48)      # best mallet/2H by crush bonus
db.weapons_for_style("block", 48)          # every equippable block weapon
```

`best_weapon_for_style` / `weapons_for_style` rank by
`(style bonus, melee strength, -interval, power rating, required level)` so the
first entry is the strongest candidate for that style.

The ranking is deliberately simple and explicit:

- **Scimitar / sword / mallet**: `(style attack bonus, melee_strength,
  -turn_interval, power_rating, required_level)`.
- **Defender**: `(slash_defence, slash_attack, melee_strength, required_level)`.
- `include_special=False` excludes drop-only specials (Toxic Razors, Mantis,
  Staggering Lash Greatsword).
- `craftable_only=True` keeps only items whose Smithing recipe the player can
  make at `smithing_level`.

This means the future auto-upgrade can answer, without hardcoding item names:

- What is the best scimitar/defender I can equip now?
- What is the best one I can **make** now?
- What is the next tier, and what materials/levels does it need?
- Is the upgrade a Smithing recipe or a drop hunt?

## Data provenance

- Demo 0.11.2 item and recipe pages on `melvoridle.wiki` (the current demo
  content; the installed build is 0.11.4-alpha).
- The client executable's asset list confirms the tier names and the
  `future_tiers` entries. Its embedded item/monster data also confirms the
  Toxic Razors Scimitar and the Toxic Razorfish drop table.
- `data/enemies.json` is extracted from the embedded monster data in
  `Melvor2.exe` (objects with a `Sprite` under `res://Assets/Monsters/`).
- `data/dungeons.json` is extracted from the embedded standard-dungeon combat
  areas (waves, enemies, rewards).
- `data/weapon_types.json` is extracted from the embedded weapon-type objects;
  it gives the stance button order for each type (Sword, Sword2H, Mallet, ...).
- The hit-chance formula is ported from the decompiled
  `TargetCharacterStats.ComputeHitChance` and the accuracy/evasion rating
  formulas in `CharacterStats` (Melee accuracy uses the Attack level; evasion
  uses the enemy's Defence level).

Re-check the JSON after a game update: Smithing levels, materials and stats can
change between builds. `python -m mi2_aio gear` is the quickest way to see the
current data.

## Auto-upgrade notes for the next step

The database is reference data; it does not smith or buy anything. The live
style switcher already:

- reads the character's Attack, Defence and Smithing levels plus the current
  weapon, off-hand and armour from the save;
- chooses slash/block/crush from `data/enemies.json` for the active enemy,
  including dungeon waves;
- equips the best **owned** weapon candidate through the bank and selects the
  stance;
- equips the best owned armour per slot (Defence requirements, all level
  requirements checked) at task start and every `armour_check_minutes`;
- keeps the current setup when no recommended item is in the bank.

The remaining auto-upgrade work is:

1. Prefer a craftable upgrade when the bank has nothing better, using the
   Smithing recipe data and the current levels.
2. Report the next drop target when only a drop can upgrade the slot.
3. Use `compare_to_two_handed()` to weigh the current 2H weapon against the best
   scimitar + defender pair (raw stats, interval and the game's power rating)
   before spending bank visits.
4. Never pair a two-handed weapon (sword, scythe or mallet) with a defender.

## Caveats

- The special items are drop-only in the demo. Their drop rates are not part of
  the database yet; the auto-upgrade should treat them as "owned or not".
- Armour ranking uses `protection → total defence → melee strength → required
  level`. It does not yet choose a different set for a specific enemy's attack
  style; the highest-protection owned set is used.
- Armour verification waits for the game's autosave, so an upgrade can take
  several autosave intervals. This is deliberate: the bank search can list
  several items for a slot word, and only the save proves which one is equipped.
- The database is for the **demo** content. Future tiers are named but have no
  stats until the game exposes them.
