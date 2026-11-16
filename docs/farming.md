# Farming maintenance

Farming runs **alongside** the main task. By default it has **priority**:
every runner loop checks the farm before starting the main task step. The main
task keeps its action going (combat, woodcutting, ...) while the bot occasionally
checks the farm, harvests grown plots, applies the selected compost, replants
the selected crop and waters it. Set `[farming].prioritise = false` to let the
task step run first and check farming afterwards. Prayer upkeep and the idle
fallback run only after farming.

```powershell
python -m mi2_aio run --task slayer          # slayer + farming maintenance
python -m mi2_aio farm                       # one farming pass now
python -m mi2_aio farm --inspect             # print plot states, change nothing
python -m mi2_aio farm --restore combat      # pass, then reopen Combat
```

## Manual pass during a run

In the desktop app, **Farm Run** behaves differently depending on the bot:

- **Idle:** runs a standalone farming pass in a worker.
- **Task active:** queues a manual pass. The runner services it between task
  steps, restores the current action page, then continues the same task. This
  avoids a second clicking thread and a race for the game window.

If the remaining runtime is under 60 seconds, the queued pass is skipped so the
run can stop on time.

## Trigger

Farming sets the game's attention flag when a plot is harvestable
(`ActiveFarmingCategory.RequiresAttention`), and the skill sidebar shows a red
badge on the Farming icon for that flag. The badge is visible from every page,
so the normal poll costs one screenshot and no page switch:

1. every `badge_poll_seconds`, check the badge on the Farming icon
2. **only if the badge is set**, run a full pass (before the main task step when
   `prioritise` is on, or after the step when it is off). `check_minutes` can
   add an optional safety pass; it defaults to `0` (badge-only).
3. the pass switches to Farming, services every configured category, then
   returns to **the page of the action currently being performed** (combat,
   woodcutting, mining, ...) by pressing the sidebar's current-action button
   (tooltip "Click to return to this page"). If that button is unavailable it
   falls back to the main task's declared page (`Task.page`).

Most polls therefore cost one screenshot and no page switch. The optional
`check_minutes` fallback exists only for users who want a periodic pass in case
the badge is missed; the default is badge-only.

## What a pass does

For every plot card in the first row of each category (Allotments, Herbs,
Compost Bins, Trees, Flowers, Orchard and Mill Farm by default):

| Card state | Detection | Action |
|---|---|---|
| growing (crops) | red **Clear** button | water only when the "Hold to Water" button is shown and the plot is not already watered |
| growing (compost bin) | red **Clear** button | nothing (bins are not watered) |
| ready | teal **Ready to Harvest** title in the lower panel (checked before the red Clear button, because red crop art can look like Clear) | click **Harvest** (or collect the bin) |
| empty | white **Waiting...** body title and a green **Plant** button | select the configured compost in the header picker (Fertiliser by default), click **Apply Compost**, then **Plant** |
| blocked empty | empty, but the Plant button is dark (**Not enough Seeds.** / **No Product selected.**) | counted and skipped as information, no compost is wasted |
| locked / purchasable | no product header, an orange **Locked** title, or the **Purchase to Unlock** card (white label + gold price) | skipped |

The second plot row is deliberately **not** touched: in the demo it holds
locked/purchasable cards whose "Hold to Buy Plot" button must never be clicked
by the bot.

Plots that are **locked by Farming level**, demo content restrictions, or not
purchased yet are counted and skipped. The pass logs them as information
("skipped N locked/unpurchased plot(s) ... not an error") and never treats a low
level or an unowned plot as a failure. The bot never clicks **Hold to Buy Plot**.

After harvesting, the plot is empty. If the body shows **Apply Compost**, the bot
first selects the configured compost type in the header picker (slot 1 is
**Fertiliser**, slot 2 is **Compost**), then presses **Apply Compost** and
verifies the body changed to **Applied**. Then it plants the already-selected
crop and immediately waters it (a 2.5 s hold) and verifies the **Watered** badge.
Compost is applied before planting, as the game requires.

Plots that are empty but cannot be planted (the Plant button is dark because no
seed/product is selected) are counted and skipped as information. The bot does
not waste compost on them.

Compost bins get one action per pass (collect when ready, otherwise
begin/restart), at most two actions per card.

The bot selects the **compost type**, but it never selects a crop/seed and never
buys a plot.

## The Mill

The **Mill Farm** category grows the storage items (Wheat, Sugarcane, Corn,
Flax) that The Mill consumes. After the plot pass, the bot services The Mill
building:

1. read the mill status from the Farm Buildings panel (green "Running: Grain"
   vs orange-red "Stopped");
2. open The Mill panel (it replaces the plot area) if it is closed;
3. press **Deposit** on all four storage rows, moving the bank's Wheat /
   Sugarcane / Corn / Flax into the mill (the quantity defaults to the mill's
   6,000 stack cap);
4. if the mill is stopped **and** any storage bar shows stock, press
   **Toggle Grain Mill** to start it;
5. close the panel again if the bot opened it.

So farmed items flow: Mill Farm plot → bank on harvest → deposited into The
Mill → mill produces Grain/Flour/Sugar while running. The mill is never stopped
by the bot; a stopped mill with stock is restarted.

## Reading the page (no OCR)

| Signal | How |
|---|---|
| Attention badge | red pixels at the top-right of the Farming sidebar icon |
| Farming page open | green category bar across the top **and** the bright "Farm Buildings / The Mill" panel at the top right |
| Card grid | detected from the header bars (two dark runs per card) each pass, so the layout can move |
| Growing | red Clear button, growth timer, or Watered/Hold-to-Water badge |
| Ready | teal **Ready to Harvest** title (teal text in the lower panel) |
| Ready regrow crops | the title is checked before the red Clear button; strawberry/red crop art can otherwise look like Clear |
| Empty | white **Waiting...** title on the dark empty panel, with no plant art in the upper body (white flowers are not enough) |
| Compost needed | white **Apply Compost** label plus the tan bag icon in the body (the header's "Compost: Select" row is always there) |
| Compost applied | green **Applied** label in the body |
| Compost picker | white hint text in the picker overlay; slots are 1 Fertiliser, 2 Compost, 3 third |
| Plant available | green **Plant** button in the body |
| Plant blocked | dark Plant button and "Not enough Seeds." / "No Product selected." |
| Watered | teal "Watered" badge text (RGB ~98,192,137) |
| Not watered | white "Hold to Water" button text |
| Buttons | connected green regions inside the card (the game's primary buttons) |
| Mill status | green vs orange-red "Running/Stopped" label in the Farm Buildings panel |
| Mill open | the white "Toggle Grain Mill" label |
| Mill stock | contiguous grey fill (RGB ~143) in the four storage bars |

Card geometry is detected from the plot header bars each pass (the grid moved
after extra plots were purchased). The mill panel's button positions live in
`src/mi2_aio/ui.py`.

## Configuration

```toml
[farming]
enabled = true
# True: service a needed farm pass before the main task step.
prioritise = true
badge_poll_seconds = 5.0
# 0 = only when the red attention badge appears.
check_minutes = 0.0
categories = ["allotments", "herbs", "compost", "trees", "flowers", "orchard", "mill"]
harvest = true
compost = true
# Select the compost type before applying it. Slot 1 is Fertiliser in the demo
# picker; slot 2 is Compost; slot 3 is the third compost.
select_compost = true
compost_slot = 1
plant = true
water = true
mill = true
restore_page = true
```

Set `enabled = false` to disable farming entirely. `mill = false` skips The Mill
building while still servicing the Mill Farm plots. `restore_page` returns to the
**current action's page** after each pass (via the sidebar action button); with
no active action it leaves Farming open.

## Verified against the demo build

- The Farming sidebar icon shows the red attention badge when the game flags a
  harvestable plot.
- `farm --inspect` classified live plots correctly across Allotments, Herbs,
  Compost Bins, Trees and Mill Farm, including ready, empty, growing, blocked
  and locked plots. In particular, ready herbs are no longer misread as empty.
- The new **Flowers** and **Orchard** tabs were captured live: every card (the
  purchase card, level locks and demo locks) classified as locked, so the pass
  will skip them until the plots are bought and planted.
- A full live pass with 3 ready herbs + 1 ready Mill Farm plot produced:
  **4 harvested, 4 composted, 4 planted, 4 watered, 1 blocked, mill handled**.
  Each plot followed harvest → select **Fertiliser** → Apply Compost → Plant →
  hold-to-water.
- A ready **regrowing Strawberry** plot (red fruit plus a red Clear button) was
  previously misread as growing. The teal "Ready to Harvest" check now runs
  first; a live pass harvested it and it is regrowing again
  (`1 harvested, 1 composted, 2 planted, 2 watered, 1 blocked`).
- White **strawberry flowers** were later misread as the empty "Waiting..."
  title, causing false "planted" clicks on growing plots. The empty check now
  requires the dark panel and no upper-body plant art; a follow-up pass
  produced **0 harvested, 0 composted, 0 planted, 0 watered, 1 blocked, mill
  handled** (the blocked plot is the seedless tree).
- After replanting, the herb cards show "Compost: Fertiliser" and the teal
  **Watered** badge; the bot's readers report `state=growing`, `watered=True`,
  `compost=False`.
- A second pass produced **0 harvested, 0 composted, 0 planted, 0 watered**,
  confirming it does not re-apply compost or re-water an already-watered crop.
- The blocked Tree plot ("Not enough Seeds.") was counted and skipped without
  wasting compost; the mill was restarted when stopped and left running.
- Compost picker: slot 1 is **Fertiliser**, slot 2 is **Compost**; selecting the
  slot enables the body's Apply Compost button, and applying it changes the body
  to "Applied" with the Fertiliser label.
- **Farming priority during the 3-task Slayer run:** passes ran before the
  combat step. One pass harvested, composted, planted and watered **2** plots;
  the other passes were clean (or mill-only) and combat resumed automatically.
  Total run: **2 harvested, 2 composted, 2 planted, 2 watered, 1 blocked, mill
  handled**, alongside 3 completed Slayer tasks.

## Caveats

- The harvest/plant button is located as the card's green action button. If a
  future build styles it differently, `farm --inspect` will report the card as
  `unknown` and the bot will leave it alone rather than guess.
- **Red crop art can look like the red Clear button** (strawberries are the
  live example). Ready cards are therefore detected first from the teal "Ready
  to Harvest" title. If a future crop uses a different ready title colour or
  position, update `FARM_READY_TITLE_BOX` and `card_ready()` in `ui.py`.
- Only the first plot row is serviced. The second row holds locked/purchasable
  cards in the demo; skipping it guarantees the bot never presses
  "Hold to Buy Plot".
- **Compost selection is slot-based.** The picker has three items; slot 1 is
  Fertiliser and slot 2 is Compost in the demo. If a future build reorders them,
  change `compost_slot` (or the `FARM_COMPOST_PICKER_SLOTS` points in `ui.py`).
  The bot selects the configured type before every Apply Compost press, then
  verifies the body shows "Applied". If the selection fails it plants without
  compost and logs that.
- **Watering uses a 2.5 s hold** on the "Hold to Water" button. 1.4 s already
  fires it on this build; the longer press is for slow frames. The bot verifies
  the Watered badge before counting the action.
- **White crop art can look like the "Waiting..." title** (strawberry flowers
  are the live example). The empty check therefore also requires a dark panel
  and no plant art in the upper body; if a future crop has white flowers with
  almost no green, re-check `FARM_PLANT_ART_BOX` / `card_empty()`.
- **Empty plots with no seed/product** show a dark Plant button and an orange
  error. They are counted as blocked and skipped, so compost is not wasted.
- **The Mill** deposits use the quantity spinbox's current value, which defaults
  to the mill's 6,000 stack cap when the panel is opened. If you set a quantity
  of 0 the bot's Deposit press does nothing. The bot does not change the mill's
  selected product (Flour / Sugar / Basic Grain).
- **Flowers and Orchard** are full categories in the same pass: their owned
  plots follow the same harvest → compost → plant → water sequence. The tabs are
  in `FARM_CATEGORY_TABS` (`flowers`, `orchard`). Unowned or level/demo-locked
  cards are recognized and skipped, so they can stay in the category list before
  the plots are purchased. If a future build adds/removes category tabs, update
  those reference points.
- The bot selects the compost type but does not buy plots, seeds or compost; it
  uses the already-selected crop/seed.
- Keep the game unminimized. The maintenance skips passes while minimized.
- Growth is not tracked: the game owns the timers, and the bot reacts to the
  harvestable state instead.
