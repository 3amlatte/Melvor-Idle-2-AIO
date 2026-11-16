# Fishing task

The `fishing` task opens the Fishing page, chooses a location and fishing spot,
and starts the action. It is available from the desktop app under
**Features → Fishing** and from the CLI with `--task fishing`.

## Database

`data/fishing.json` is generated from the `FishingLocation` and `FishingRecipe`
arrays in `Melvor2.exe` (demo build `v0.11.4-alpha`):

- 7 locations in client order: Shallow Shores, Shrapnel River, Lemvor Pier,
  Windy Coastline, Glowing Depths, Coral Reef, Open Ocean.
- 23 spots total. `FishingRecipe` entries are the spots; `RandomProducts` are
  the fish.
- Each fish keeps the client's `Weight`, with `chance = weight / sum(weights)`
  pre-computed. The right-hand output panel shows the same fractions as
  percentages (for example Raw Herring 44.44% / Raw Trout 55.56% at Pebble Bank).
- `fish_chance` is the spot's `FishChance` (the rest is junk), `experience` is
  `BaseExperience`, and the intervals come from `BaseMinInterval` /
  `BaseMaxInterval`.
- `special` holds the `SpecialProducts` rolls.
- `demo_locked` is set when a location or spot has a `DemoLocked` requirement.
  Coral Reef and Open Ocean are locked whole; Shrapnel River (Moonlit Stream),
  Windy Coastline (Windy Bay, Gusty Cliffside, Midnight Cove) and Glowing Depths
  (Glowing Rift, Luminous Abyss) have locked spots.
- `level` is the spot/location `Level` requirement.

Loader: `src/mi2_aio/fishing_db.py`. The dataclasses expose
`FishingSpot.fish_names`, `FishingSpot.interval_label`,
`FishingSpot.junk_chance`, `FishingLocation.available_spots`, and lookups by id
or display name.

## Options

`RunRequest.options`, `TaskContext.options`, and `QueuedTask.options` carry
`location` and `spot`:

```python
{"location": "ShrapnelRiver", "spot": "PebbleBank"}
```

Both ids and display names are accepted. Missing, unknown or demo-locked values
fall back to the first available location/spot, so a bare run still works. The
CLI passes the same options:

```text
python -m mi2_aio run --task fishing --location "Shrapnel River" --spot "Pebble Bank" --duration 60
```

Queue rows keep their own options; the Task column shows
`Fishing · Shrapnel River / Pebble Bank`.

## Page layout and readers

All coordinates are reference-space (2560×1369) and are scaled at click time by
`ui.to_client`. Captures always go through `ui.normalize(capture_client(...))`.

| Element | Reference point / box | Reader |
| --- | --- | --- |
| Skill sidebar icon | `(35, 425)` | page is navigated with a click |
| Select Location bar (card toggle) | `(1300, 119)` | `fishing_cards_visible` |
| Location cards | `y = 240`, `x = 438 + 296·index` | `fishing_cards_visible` |
| Select Spot dropdown | `(2220, 431)` | `fishing_page_open` |
| Spot rows | `x = 2070`, `y = 486 + 76·row` | `fishing_spot_menu_open` |
| Start Fishing | `(2070, 878)` | `fishing_start_visible` |

- `fishing_page_open` requires both the teal **Select Spot** bar and the solid
  beige value box below it. The panel body alone is not enough: bank and other
  dark pages share its brown tone.
- `fishing_cards_visible` measures the dark card row under the location bar.
  The bar toggles the row; only use this while `fishing_page_open` is true.
- `fishing_start_visible` counts green pixels in the button box. Green means the
  selected spot is not running; the gold **Stop Fishing** state means it is.
- `fishing_spot_menu_open` counts the wide green highlight the dropdown draws on
  the current spot. Closed panels stay below the threshold.

## Navigation sequence

1. If the page is not showing, click the sidebar icon.
2. If the location cards are collapsed, click the Select Location bar.
3. Click the location card twice. Selecting a location makes the game resume
   that location's remembered spot, and an open Select Spot menu swallows the
   first click, so the second click is required to land the selection.
4. Click the Select Spot arrow, then confirm `fishing_spot_menu_open`. Up to
   three attempts are made because the first click can be swallowed while the
   location switch settles.
5. Click the target row. If the menu is still open, click it once more.
6. If `fishing_start_visible`, click Start. The retry loop allows two clicks.

## Verification

The save header's `active_action` is the spot's display name (`Pebble Bank`,
`Shimmering Depths`, ...). The task treats that as the success signal and logs
`Fishing active: <spot> at <location>`. It waits up to 22 seconds (the autosave
is delayed) before retrying. After three attempts it stops with an error that
names the spot's level requirement.

A wrong active spot is treated the same as no spot: the task re-selects the
location and spot and clicks Start again.

## Start Fishing needs a real click

The green **Start Fishing** button does not react to posted window messages
(`WM_MOUSEMOVE`/`WM_LBUTTONDOWN`), unlike the location cards and dropdown. The
task therefore uses `input.click_client` for that button only: it focuses the
game, spends one click on open water to absorb the activation click, then clicks
the button. If focusing fails it falls back to the background click and logs a
warning. Every other click stays on the background path.

## Limitations

- Bait and priority-fish selection are left as configured in the game.
- Fishing keeps running until the duration/Stop ends the task; it does not stop
  when inventory space runs out.
- Demo-locked content is reported, not bypassed.
- A spot above the character's Fishing level cannot be selected by the game; the
  task retries and then stops with a clear message (the UI still shows the level).
- **Restore previous action** cannot re-enter a fishing action by itself: the
  save header carries the spot name but not the location, so restore logs a
  warning and leaves the game alone. Running the `fishing` task with the desired
  location/spot is the supported way to choose it.
