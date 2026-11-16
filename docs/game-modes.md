# Game modes and multiple characters

The save header contains a `Gamemode` string. Supporting Regular, Hardcore, and
future character types means resolving that string to a **policy profile**, not
scattering `if mode == "hardcore"` checks through task code.

## What the demo build does

- `SaveHeader.Gamemode` reports **`Test`**.
- `Game.GetSaveHeader` in this build hardcodes `"Test"` when serialising the
  header.
- The new-save screen currently creates **one** gamemode panel (a loop with
  `i < 1`), and `NewSaveConfig` stores an integer `GamemodeId`. The full release
  is expected to expose more panels and write their names into the header.

Because the header is the authoritative source, this project can follow the
full release without a game update of its own: new strings resolve against
config, and anything unrecognised gets a conservative profile.

## Resolution

`resolve_mode(raw, profiles)` matches case- and punctuation-insensitively
against:

1. profile **key** (`hardcore`)
2. **display name** (`Hardcore`)
3. any **alias** (`hc`, `hardcore`)

Matching examples:

| Header value | Profile |
|---|---|
| `Regular`, `regular`, `Standard` | `regular` |
| `Hardcore`, `HC` | `hardcore` |
| `Test`, `demo`, `Test / Demo` | `test` |
| `Adventure`, `Ironman`, anything new | `unknown` |

`unknown` is deliberately safe:

```toml
permanent_death = true
allow_risky_tasks = false
min_hp_ratio = 0.75
```

So when the full release introduces a mode this project has never seen, the bot
will not start risky combat or other irreversible actions. Add the mode to
`config/settings.toml` to unlock it intentionally.

## Profiles are policy, not names

Each profile carries the rules a task needs:

| Field | Meaning |
|---|---|
| `permanent_death` | Death is irreversible (hardcore-style) |
| `allow_risky_tasks` | Tasks marked `risky = True` may run |
| `min_hp_ratio` | HP floor tasks should respect before acting |
| `blocked_tasks` | Task names refused in this mode |
| `aliases` | Extra header values that map here |

Tasks read `ctx.mode` / `ctx.min_hp_ratio`; they never inspect the raw string.
That also keeps a future mode with unusual rules configurable without code.

## Task compatibility

A task declares:

```python
class CombatTask(Task):
    name = "combat"
    risky = True
    supported_modes = frozenset({"regular", "test"})  # None = all modes
```

The runner enforces this before `start()` and again if the active save changes
mode while running. Refusals return exit code `3` and log the reason:

```
Refusing to run 'combat': task 'combat' is marked risky; mode 'hardcore'
does not allow risky tasks (set allow_risky_tasks = true to override)
```

## Multiple characters

Saves are stored per UUID. When more than one character exists:

```powershell
python -m mi2_aio status --all
```

```
  character        mode             lvl  action               uuid
* Adventurer       Test / Demo      671  Red Slime            A1B2C3D4
  AltCharacter     Hardcore          42  Mining               B2C3D4E5
```

By default the **newest** save is used. Pin one explicitly:

```toml
[save]
# character name or UUID/filename fragment (case-insensitive)
character = "HardcoreGuy"
```

Every command (`status`, `doctor`, `run`) then targets that save. An ambiguous
selector is an error, not a guess.

### Switching from the desktop app

The header shows a separate bubble for each saved character. Clicking a bubble
makes the app:

1. open the in-game hamburger menu and choose **Save and Exit to Main Menu**;
2. find the save's row on the character-selection screen and press **Load**;
3. wait for the save header to confirm the new character;
4. refresh the status, skills and character bubbles.

The **Queue** tab stores the character with each queued task, so a queue can mix
characters; the app switches automatically before each row starts. The bot does
not switch characters while a run is active. Character switching is also
available from **Diagnostics → Use selected character** for the save pin alone.

## Adding a mode in the full release

Usually config only:

```toml
[gamemodes.adventure]
display_name = "Adventure"
aliases = ["adventure", "adv"]
permanent_death = false
allow_risky_tasks = false
min_hp_ratio = 0.5
blocked_tasks = ["combat"]
```

No restart of the game is needed; restart the bot and check:

```powershell
python -m mi2_aio modes
python -m mi2_aio status
```
