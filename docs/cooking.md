# Cooking task

The `cooking` task cooks a **Basic Food** recipe and can stop after a requested
number of products. It is available from **Features → Cooking** and from the CLI
with `--task cooking`.

## Database

`data/cooking.json` is generated from the `CookingRecipe` array in
`Melvor2.exe` (demo build `v0.11.4-alpha`). Only recipes with
`Category = BasicRecipes` are included:

- 26 recipes total; 13 are available in the demo.
- Each recipe lists its ingredients (item + quantity), product (item + quantity
  + chance), level, XP, cook interval (`BaseInterval`), difficulty and demo-lock
  state.
- `grid_slot` is the **row-major slot in the rendered recipe grid**. The demo
  inserts a locked card (Cod) after Pike, so the unlocked recipes are at slots
  0-8 and 10-13:

  | Slot | Recipe |
  | --- | --- |
  | 0-8 | Shrimp, Sardine, Beef, Herring, Chicken, Perch, Trout, Mackerel, Pike |
  | 9 | locked (Cod) |
  | 10-13 | Salmon, Lobster, Glowfin, Sea Bream |
  | 14-25 | locked demo recipes |

Loader: `src/mi2_aio/cooking_db.py`.

## Page layout and readers

All coordinates are reference-space (2560×1369) and are scaled at click time by
`ui.to_client`. Captures use `ui.normalize(capture_client(...))`.

| Element | Reference point / reader |
| --- | --- |
| Skill sidebar icon | `COOK_ICON = (35, 487)` |
| Page detector | beige **Choose Recipe** + **Selected** ribbons (`cooking_page_open`) |
| Basic Food category | `COOK_BASIC_FOOD = (419, 251)` |
| Recipe grid | `x = 800 / 1200`, first row `y = 280`, row step `107` (`cooking_recipe_point`) |
| Selected panel footer | `cooking_footer` finds the **Manage Stop Conditions** and **Create** text bands |
| Stop-condition foldable | `cooking_stop_panel_open` (beige condition combo) |
| Condition menu (Products Gained) | footer anchor offset |
| Quantity field | footer anchor offset |
| Red Stop (Creating panel) | `cooking_stop_point` (solid red button) |

The Selected panel scrolls independently. Instead of hard-coding the footer,
`cooking_footer` finds the last two bright text bands (Manage Stop Conditions,
Create) and derives all related points from the Manage row. This keeps working
after the panel scrolls.

## Task flow

1. Open Cooking from the skill sidebar.
2. Stop any active cooking action (red **Stop**) so the product count starts
   cleanly.
3. Click **Basic Food**, scroll the recipe grid to the top and click the
   recipe's grid slot.
4. Expand **Manage Stop Conditions** if it is collapsed.
5. Choose **Products Gained** and verify the **Item** row appeared (the item
   follows the selected recipe).
6. Click the quantity field, clear it, type the amount and press Enter.
7. Press **Create** and verify the Creating panel shows the red Stop button.
8. Wait for the game to stop the action.

### Amount handling

- The in-game **Products Gained** condition is the primary stop mechanism and
  gives exact counts. It is set to the requested amount before **Create**.
- The save header's bank stack is a safety net and a completion signal:
  - if the condition could not be set, the task clicks the red **Stop** when
    the bank gain reaches the amount;
  - if the condition was set, the task waits for the game to stop the action
    and only logs the bank delta.
- The save file lags behind the rendered action. After the action stops the
  task waits for the bank count to settle; with the stop condition set it trusts
  the game count and logs the bank delta as informational.

### Failure handling

- A wrong recipe (the save header names a different known cooking product) is
  stopped and logged.
- With **Products Gained** set, an action stop is treated as success: the game
  counted the products exactly, and the bank number is informational because the
  save file lags. The task only warns about an early stop when the ingredient
  stacks are also exhausted.
- If the condition could not be set, the bank delta is authoritative and an
  early stop is logged as a warning.
- A timeout (`amount × interval × 4`, at least 120 s) stops a run whose stop
  condition did not take effect.

## Options

```python
{"recipe": "Glowfin", "amount": "100"}
```

Ids and display names are accepted. A missing/unknown/demo-locked recipe falls
back to the first available recipe (Shrimp). `amount = 0` cooks until the run is
stopped.

The Amount field shows `0` by default and has no spin buttons. Duration is a
typed minutes value with no spin buttons; the field always keeps the "Minutes"
unit visible, and `0 Minutes` means no time limit. The bot passes the spelled
value as `duration_minutes`.

CLI:

```text
python -m mi2_aio run --task cooking --recipe Glowfin --amount 100
```

Queued rows keep their own options and show
`Cooking · Glowfin × 100` in the Task column.

## Verified against the demo build

- 5 Glowfin with **Products Gained = 5**: the game stopped the action exactly
  after 5 products; the bank went from 2,779 to 2,784.
- A second run of 5 Glowfin confirmed the stop condition and completion log.
- The recipe grid slots were checked live: slot 10 = Salmon, 11 = Lobster,
  12 = Glowfin, 13 = Sea Bream.
- Queue row verified: `Cooking · Glowfin × 5`.

## Limitations

- Only the **Basic Food** category is modelled. Intermediate Food and Bait are
  not supported yet.
- The recipe grid order and slots come from this demo build. If a future build
  changes the grid (or more recipes become available), regenerate
  `data/cooking.json` and re-check the slots.
- The **Products Gained** menu position assumes the condition list order used by
  this build (`None`, Recipe Creations, Products Gained, Products Owned,
  Ingredients Spent, Ingredients Remaining). If the list changes, update
  `COOK_STOP_MENU_DY` in `ui.py`.
- **Restore previous action** is not guaranteed for a cooking action; it treats
  the product name as an action name on the recipe grid. Use the cooking task to
  choose a recipe explicitly.
- The bot does not buy ingredients or change the player's selected recipe
  outside the task.
