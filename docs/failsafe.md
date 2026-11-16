# Idle failsafe

The bot should never leave the character standing still. When the save header
reports no active action (`active_action` empty), the bot starts the configured
fallback action. Farming runs first each loop, then prayer upkeep, so ready
plots are serviced before the fallback or the main task.

## How it works

1. The runner decodes the save header every `[save].poll_seconds` (default 5 s).
2. Farming maintenance is checked first; if a plot needs attention it runs and
   returns to the task page.
3. If `active_action` is empty, the failsafe clicks the configured skill page
   icon, waits, then clicks the action's **Start/Cut** button.
4. The next save poll confirms the action and logs
   `Fallback action is running: <name>`.
5. A cooldown prevents repeated clicks if the action fails to start.
6. When a run ends, the restore step resumes the previous action; if it cannot,
   `ensure_active` starts the fallback so the character is not left idle.

## Configuration

```toml
[failsafe]
enabled = true
action = "Spikemoss Shrub"
page = [39, 303]        # Woodcutting sidebar icon
button = [1082, 1096]   # Spikemoss Shrub Cut button
cooldown_seconds = 60
```

- `page` is the sidebar icon of the skill page, in reference client
  coordinates (2560x1369).
- `button` is the action's Start/Cut button on that page.
- `action` is only used in logs.

The default is **Woodcutting → Spikemoss Shrub**. The desktop app's
**Settings → Learn fallback…** wizard records a different page icon and action
button with two real clicks, then writes these values.

## Verified against the demo build

- With the character idle, a run logged
  `Character is not running an action; starting the fallback 'Spikemoss Shrub'.`
  and the save header changed to `Woodcutting / Spikemoss Shrub`.
- The farming maintenance no longer mistakes the woodcutting page for the farm:
  `farming_page_open` now also requires the green farming category tabs.
- The fallback runs after restore when the previous action was combat and could
  not be re-entered.
- The 3-task Slayer run stopped at 3 completions, restored **Spikemoss Shrub**,
  and `ensure_active` saw the running action and did not click again.

## Caveats

- The button coordinate assumes the default (unscrolled) action list. If the
  list is scrolled, the fallback can click the wrong card; keep the page at the
  top (the bot does not scroll it yet).
- The failsafe only acts while the runner is running; it is not a separate
  service.
- Nothing happens while the game is minimized.
