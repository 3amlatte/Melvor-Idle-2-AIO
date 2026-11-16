# Restore the previous action

When a run ends, the bot puts the game back the way it found it. If the
character was cutting a Willow Tree and a dungeon test took over, Woodcutting
resumes when the test stops.

```
before the run          during the run          after the run
Woodcutting / Willow -> Dungeon / Harvest Farm -> Woodcutting / Willow
```

This is automatic for every run (including `--duration` tests and `Ctrl+C`) and
can be disabled with `[restore].enabled = false`.

## How it works

There is no OCR and no hardcoded action registry. The bot reads the action name
from the save header, then learns how to return to it from the rendered UI at
startup:

1. **Open the action's page.** Click the sidebar's "return to this page" button
   (the button under the action timer). This navigates without changing the
   action.
2. **Remember the page button.** The skill page header draws the same artwork as
   the sidebar icon. The bot crops the header icon and matches it against the
   page icons in the sidebar at several scales, skipping the active-action
   button at the top (it shows the same skill icon but points at the current
   action's page). It remembers the matching page point.
3. **Remember the action name.** The active action's name is white text in a
   teal banner on the right. The bot extracts that text as a binary mask (the
   category label on the right, such as "Tree", is ignored).

At the end of the run:

4. **Check whether it is still running.** The save header is only written every
   10 seconds, so a short test can end before the save reflects the change. The
   bot therefore trusts the **screen** first: it opens the action's page, and if
   the active panel shows the same name, the action is still running and nothing
   is clicked. The save header is only a fallback shortcut, because it can be up
   to 10 seconds stale.
5. **Leave combat.** If the character is still in combat or a dungeon, the bot
   clicks **Run from Combat** first.
6. **Find the action card.** It opens the remembered page and matches the name
   mask against the card grid across font scales (the banner name is larger than
   the card name).
7. **Click the card's start button.** Every skilling start button is the same
   tight dark-green rectangle. The bot detects those buttons and picks the one
   below the matched name, then clicks it.
8. **Verify.** It checks the active panel name immediately and falls back to
   polling the save header for up to `verify_seconds`.

All coordinates and readers live in `src/mi2_aio/ui.py` in reference space, so
the feature follows the [display independence rules](display.md).

## Configuration

```toml
[restore]
enabled = true
# How long to wait for the save header to confirm the restored action.
verify_seconds = 25
poll_seconds = 1.5
```

## Behaviour by pre-run state

| Before the run | After the run |
|---|---|
| Idle | Nothing to restore; the run ends as it started. |
| Skilling action (Woodcutting, Mining, ...) | The same action is restarted. |
| Fishing | Not restorable automatically: the save header names the spot but not the location and the fishing page is not a card grid. Restore logs a warning and leaves the game alone. |
| Combat or a dungeon | The Combat page is reopened; the exact enemy/dungeon is **not** re-entered automatically. |
| Observe task | The action is unchanged, so the restore is not captured or run. |
| Dry run | No input is sent; the log says what would be remembered/restored. |
| `[restore].enabled = false` | No capture and no restore. |

## Failure behaviour

Restore is deliberately conservative. If it cannot identify the page icon, the
action name, the card, or the start button, it logs a warning and leaves the game
alone. It never clicks a guessed coordinate: a wrong click could stop the very
action it is trying to resume. A screenshot of the failed page is written to
`logs/errors/restore_failed.png` for diagnosis.

## Verified against the demo build

- Woodcutting / Willow Tree → Harvest Farm dungeon test → bot left combat,
  matched the Willow card at 0.88 confidence, clicked its Cut button and
  confirmed "Willow Tree is running again".
- Woodcutting / Ambervine Bush (right-hand card column) → dungeon test → bot
  matched the card at 0.89 confidence and restored it.
- A short run that ended before the dungeon started correctly logged "already
  running" and left the action untouched.
- Dry run: restore logged that it would remember the action and sent no input.
- `Ctrl+C`/`--duration` both run the restore in the runner's shutdown path.

## Caveats

- Restoring **combat** to the exact enemy or dungeon is not implemented; only
  the Combat page is reopened. Skilling actions on the standard card grid are
  fully restored. **Fishing** is not restored: the header has the spot name but
  not the location, and the page uses a dropdown instead of cards. Pick the
  location/spot with the `fishing` task instead.
- The page must use the standard card grid with the green start button. If a
  future build changes the skill page layout, re-capture the regions in
  `ui.py` and re-run the live check.
- A process that is killed (not stopped with `Ctrl+C`, `STOP`, or a runtime
  limit) cannot run the shutdown path, so the restore will not happen.
- The action name must be readable in the active panel banner. Skills whose
  active view does not show that banner are skipped with a warning.
