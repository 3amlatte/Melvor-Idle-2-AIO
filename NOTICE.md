# Third-party notices

MI2 AIO is an unofficial, local automation tool. It is not affiliated with,
endorsed by, or sponsored by Games by Malcs or the developers of Melvor Idle.

## Game content and extracted data

- **Melvor Idle** and **Melvor Idle 2** are trademarks and copyrights of their
  respective owners.
- `data/*.json` contains reference data extracted from a locally installed demo
  build of the game (items, monsters, dungeons, fishing recipes, cooking
  recipes, gear and Slayer masters). It is included so the bot can recognise
  game UI and plan actions without OCR.
- `assets/templates/*` contains small UI reference crops captured from the same
  local installation (combat style and stance glyphs, dungeon name masks,
  cooking/fishing layout references).
- These files are **not** covered by the MIT license in `LICENSE`. They remain
  the property of their respective owners and are included only for local
  interoperability. Do not redistribute them separately from this project
  without checking the game's terms.
- The tool does not include game code, does not patch the game, and does not
  modify save files. It reads the save for status and sends ordinary mouse and
  keyboard input.

## Runtime libraries

The project depends on the following packages; see their own licenses:

| Package | Purpose |
| --- | --- |
| PySide6 / Qt | Desktop UI |
| Pillow | Image loading and scaling |
| NumPy | Array processing |
| OpenCV (`opencv-python`) | Template matching and connected components |
| pyautogui | Foreground mouse/keyboard fallback |
| tomlkit | Comment-preserving settings writes |
| pytest | Test suite (development) |
| PyInstaller | Standalone Windows build (development) |

`tools/SaveTool` is a small .NET helper built from the source in this
repository to decompress Brotli-compressed save files.

## Account and terms of service

Automation may violate the game's terms of service and can put an account at
risk. Use this software only in ways you are permitted to use it. The authors
accept no responsibility for account action, data loss, or other consequences.
