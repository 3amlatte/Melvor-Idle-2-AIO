"""Locate, snapshot, decompress, and parse Melvor Idle 2 save files.

The save is a raw Brotli stream containing a little-endian binary object graph.
This module decodes the fixed-size header that precedes the game state and the
per-skill ``Experience`` components (double XP + int32 level), which give exact
skill levels without relying on the UI's "current / demo max" display.
See docs/save-format.md for the layout and caveats.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile
import threading
import uuid as uuidlib
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import Settings, load_settings
from .paths import (
    DEFAULT_SAVE_ROOT,
    FROZEN,
    SAVETOOL_EXE,
    SAVETOOL_PROJECT,
)

# SaveVersion enum values that change the header layout.
VERSION_LOCALIZATION = 9
VERSION_ALPHA_0_11_0 = 24
# BaseExperience.ReadFrom reads an extra int32 before the level in older saves.
VERSION_ALPHA_0_11_1 = 25
EXPERIENCE_MARKER = b"Experience"
EXPERIENCE_SEARCH_WINDOW = 128

# Save reads are expensive (snapshot + SaveTool process per autosave). Cache the
# decoded results by path/mtime/size; the game autosaves every ~10 s, so nearly
# all UI/runner polls are served from memory.
_CACHE_LOCK = threading.RLock()
_CACHE_MAX = 16
_HEADER_CACHE: OrderedDict[tuple[str, int, int], SaveHeader] = OrderedDict()
_SKILLS_CACHE: OrderedDict[tuple[str, int, int], SkillLevels] = OrderedDict()


def _hidden_process_kwargs() -> dict:
    """Keep console-app helpers (SaveTool/dotnet) from flashing a cmd window."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def _cache_key(path: Path) -> tuple[str, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _cache_get(cache, key):
    if key is None:
        return None
    with _CACHE_LOCK:
        value = cache.get(key)
        if value is not None:
            cache.move_to_end(key)
        return value


def _cache_put(cache, key, value) -> None:
    if key is None:
        return
    with _CACHE_LOCK:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > _CACHE_MAX:
            cache.popitem(last=False)

# The equipment component stores one length-prefixed slot entry per gear slot.
EQUIPMENT_MARKER = b"\x09Equipment"
EQUIPMENT_SLOT_NAMES: Mapping[str, str] = {
    "MelvorBase:Helmet": "Helmet",
    "MelvorBase:Cape": "Cape",
    "MelvorBase:Amulet": "Amulet",
    "MelvorBase:Ammo": "Ammo",
    "MelvorBase:Weapon": "Weapon",
    "MelvorBase:Torso": "Torso",
    "MelvorBase:Offhand": "Offhand",
    "MelvorBase:Legs": "Legs",
    "MelvorBase:Gloves": "Gloves",
    "MelvorBase:Boots": "Boots",
    "MelvorBase:RingSlot1": "Ring",
}
# Enemy attack stances stored in the active-enemy object, as length-prefixed
# strings. The active enemy id sits immediately before its stance.
ENEMY_STANCE_NAMES = (
    "Offensive",
    "Defensive",
    "Accurate",
    "Powerful",
    "LongRange",
    "Slash",
    "Block",
    "Crush",
    "Stab",
)
ENEMY_STANCE_TOKENS = tuple(
    bytes([len("MelvorBase:") + len(name)])
    + b"MelvorBase:"
    + name.encode("ascii")
    for name in ENEMY_STANCE_NAMES
)

# Display names of the skills stored in the save. The game uses
# "MelvorBase:<Skill>" entity ids.
SKILL_NAMES: tuple[str, ...] = (
    "Attack",
    "Strength",
    "Defence",
    "Hitpoints",
    "Ranged",
    "Magic",
    "Prayer",
    "Slayer",
    "Woodcutting",
    "Firemaking",
    "Fishing",
    "Cooking",
    "Mining",
    "Smithing",
    "Fletching",
    "Crafting",
    "Runecrafting",
    "Thieving",
    "Hunting",
    "Beastcrafting",
    "Herblore",
    "Farming",
    "Ranching",
    "Agility",
    "Summoning",
    "Astrology",
)

# These skills exist in newer/full saves but are not playable in the current
# demo yet, so they must not count toward the demo's Total Level maximum.
UNAVAILABLE_SKILLS = frozenset({"Astrology", "Summoning", "Herblore", "Agility"})
MAX_SKILL_LEVEL = 60
MAX_TOTAL_LEVEL = (len(SKILL_NAMES) - len(UNAVAILABLE_SKILLS)) * MAX_SKILL_LEVEL
# Base maximum hitpoints per Hitpoints level.
HITPOINTS_PER_LEVEL = 10

DATETIME_KIND_UNSPECIFIED = 0
DATETIME_KIND_UTC = 1
DATETIME_KIND_LOCAL = 2


class SaveFileError(RuntimeError):
    """Raised when a save cannot be located, read, or decoded."""


class SaveToolMissing(SaveFileError):
    """Raised when the .NET Brotli helper is not built and cannot be built."""


@dataclass(frozen=True)
class SlayerTaskState:
    """The active Slayer master's current task, read from the save."""

    master: str
    enemy_id: str
    length: int
    progress: int
    extended: bool = False

    @property
    def key(self) -> tuple[str, str, int]:
        """Task identity; a new length means a new task."""
        return (self.master, self.enemy_id, self.length)

    @property
    def complete(self) -> bool:
        return self.length > 0 and self.progress >= self.length


@dataclass(frozen=True)
class SaveHeader:
    save_version: int
    uuid: str
    character_name: str
    gamemode: str
    timestamp: datetime | None
    active_entity: str
    active_entity_icon: str
    active_action: str
    active_action_icon: str
    total_level: int
    gp: int
    slayer_coins: int
    is_demo: bool
    # Active combat enemy id (e.g. "BlueSlime"), empty outside combat.
    active_enemy_id: str = ""
    # Equipped items keyed by slot (Weapon/Offhand/...), game ids without the
    # "MelvorBase:" namespace. Empty when the equipment block is unavailable.
    equipment: Mapping[str, str] = field(default_factory=dict)
    # Item ids present in the bank/inventory list (game ids, no namespace).
    bank_items: frozenset[str] = frozenset()
    # Same items in bank display order (used to locate a search result cell).
    bank_order: tuple[str, ...] = ()
    # Item id → quantity for the bank tab stack list.
    bank_stacks: Mapping[str, int] = field(default_factory=dict)
    # Currency balances from the player wallet (PrayerPoints, GoldPieces, ...).
    wallet: Mapping[str, int] = field(default_factory=dict)
    prayer_points: int = 0
    slayer_task: SlayerTaskState | None = None
    # Current hitpoints from the Combat.Player component, and the base maximum
    # derived from the Hitpoints skill level. None/zero when unavailable.
    current_hp: int | None = None
    max_hp: int = 0
    source: Path | None = None
    source_mtime: datetime | None = None

    @property
    def age_seconds(self) -> float | None:
        """Seconds between the header timestamp and now, if a timestamp exists."""
        if self.timestamp is None:
            return None
        now = datetime.now(UTC)
        stamp = self.timestamp
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        return (now - stamp).total_seconds()

    @property
    def hp_ratio(self) -> float | None:
        """Current/max hitpoints from the save, or None when unavailable."""
        if self.current_hp is None or self.max_hp <= 0:
            return None
        return max(0.0, min(1.0, self.current_hp / self.max_hp))

    def to_dict(self) -> dict[str, object]:
        return {
            "save_version": self.save_version,
            "uuid": self.uuid,
            "character_name": self.character_name,
            "gamemode": self.gamemode,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "active_entity": self.active_entity,
            "active_entity_icon": self.active_entity_icon,
            "active_action": self.active_action,
            "active_action_icon": self.active_action_icon,
            "total_level": self.total_level,
            "gp": self.gp,
            "slayer_coins": self.slayer_coins,
            "is_demo": self.is_demo,
            "current_hp": self.current_hp,
            "max_hp": self.max_hp,
            "active_enemy_id": self.active_enemy_id,
            "equipment": dict(self.equipment),
            "bank_item_count": len(self.bank_items),
            "prayer_points": self.prayer_points,
            "slayer_task": (
                {
                    "master": self.slayer_task.master,
                    "enemy_id": self.slayer_task.enemy_id,
                    "length": self.slayer_task.length,
                    "progress": self.slayer_task.progress,
                    "extended": self.slayer_task.extended,
                }
                if self.slayer_task is not None
                else None
            ),
            "source": str(self.source) if self.source else None,
            "source_mtime": self.source_mtime.isoformat() if self.source_mtime else None,
        }


@dataclass(frozen=True)
class SkillLevel:
    name: str
    level: int
    xp: float


@dataclass(frozen=True)
class SkillLevels:
    character_name: str
    gamemode: str
    save_version: int
    total_level: int
    skills: Mapping[str, SkillLevel]
    source: Path | None = None
    source_mtime: datetime | None = None

    @property
    def parsed_total(self) -> int:
        return sum(skill.level for skill in self.skills.values())

    def level(self, name: str) -> int | None:
        skill = self.skills.get(name)
        return skill.level if skill else None

    def xp(self, name: str) -> float | None:
        skill = self.skills.get(name)
        return skill.xp if skill else None

    def to_dict(self) -> dict[str, object]:
        return {
            "character_name": self.character_name,
            "gamemode": self.gamemode,
            "save_version": self.save_version,
            "total_level": self.total_level,
            "parsed_total": self.parsed_total,
            "source": str(self.source) if self.source else None,
            "source_mtime": (
                self.source_mtime.isoformat() if self.source_mtime else None
            ),
            "skills": {
                name: {"level": skill.level, "xp": skill.xp}
                for name, skill in self.skills.items()
            },
        }


def discover_saves(settings: Settings | None = None) -> list[Path]:
    """Return save files, newest first.

    Looks under ``<root>/steam/<SteamID>/saves`` and ``<root>/saves``.
    """
    settings = settings or load_settings()
    root = Path(settings.save.root) if settings.save.root else DEFAULT_SAVE_ROOT

    candidates: list[Path] = []
    for pattern in ("steam/*/saves/save_*.sav", "saves/save_*.sav"):
        candidates.extend(root.glob(pattern))

    return sorted(
        (path for path in candidates if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def latest_save(settings: Settings | None = None) -> Path:
    saves = discover_saves(settings)
    if not saves:
        raise SaveFileError(
            "No Melvor Idle 2 saves found. Check [save].root in config/settings.toml."
        )
    return saves[0]


def select_save(settings: Settings | None = None) -> Path:
    """Pick the save to automate.

    Empty ``[save].character`` means "newest save". Otherwise the value may be a
    character name (case-insensitive) or a UUID / filename fragment, which lets
    multiple characters coexist without guessing.
    """
    settings = settings or load_settings()
    saves = discover_saves(settings)
    if not saves:
        raise SaveFileError(
            "No Melvor Idle 2 saves found. Check [save].root in config/settings.toml."
        )

    wanted = settings.save.character.strip()
    if not wanted:
        return saves[0]

    needle = wanted.lower()
    by_file = [path for path in saves if needle in path.stem.lower()]
    if len(by_file) == 1:
        return by_file[0]
    if len(by_file) > 1:
        listing = "\n".join(f"  {path.name}" for path in by_file)
        raise SaveFileError(
            f"Character selector {wanted!r} matches multiple saves:\n{listing}"
        )

    by_name: list[Path] = []
    for path in saves:
        try:
            header = read_header(path, settings=settings, retries=1)
        except SaveFileError:
            continue
        if header.character_name.strip().lower() == needle:
            by_name.append(path)

    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        listing = "\n".join(f"  {path.name}" for path in by_name)
        raise SaveFileError(
            f"Character name {wanted!r} matches multiple saves:\n{listing}"
        )

    available = []
    for path in saves:
        try:
            header = read_header(path, settings=settings, retries=1)
            available.append(f"{header.character_name} ({path.stem})")
        except SaveFileError:
            available.append(path.stem)
    raise SaveFileError(
        f"No save matched character {wanted!r}. Available:\n  "
        + "\n  ".join(available)
    )


def ensure_savetool(*, build: bool = True) -> Path:
    """Return the SaveTool executable, building it on first use if needed."""
    if SAVETOOL_EXE.exists():
        return SAVETOOL_EXE

    if not build:
        raise SaveToolMissing(
            f"{SAVETOOL_EXE} is missing. Run scripts/build_savetool.ps1 first."
        )

    if not SAVETOOL_PROJECT.exists() or FROZEN:
        raise SaveToolMissing(
            f"{SAVETOOL_EXE} is missing. Ship the prebuilt helper with the app "
            "or run scripts/build_savetool.ps1 in development."
        )

    result = subprocess.run(
        [
            "dotnet",
            "publish",
            str(SAVETOOL_PROJECT),
            "-c",
            "Release",
            "-o",
            str(SAVETOOL_EXE.parent),
        ],
        cwd=str(SAVETOOL_PROJECT.parent),
        capture_output=True,
        text=True,
        timeout=300,
        **_hidden_process_kwargs(),
    )
    if result.returncode != 0 or not SAVETOOL_EXE.exists():
        detail = (result.stderr or result.stdout or "").strip()[-2000:]
        raise SaveToolMissing(
            "Could not build tools/SaveTool. Install the .NET SDK or run "
            f"scripts/build_savetool.ps1 manually.\n{detail}"
        )
    return SAVETOOL_EXE


def decompress_save(save_path: Path, raw_path: Path) -> Path:
    """Decompress a Brotli save into ``raw_path`` using the .NET helper."""
    tool = ensure_savetool()
    result = subprocess.run(
        [str(tool), str(save_path), str(raw_path)],
        capture_output=True,
        text=True,
        timeout=120,
        **_hidden_process_kwargs(),
    )
    if result.returncode != 0 or not raw_path.exists() or raw_path.stat().st_size == 0:
        detail = (result.stderr or result.stdout or "").strip()[-500:]
        raise SaveFileError(f"SaveTool failed for {save_path.name}: {detail}")
    return raw_path


def _read_7bit_int(data: bytes, offset: int) -> tuple[int, int]:
    """Read a BinaryWriter 7-bit encoded length prefix."""
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise SaveFileError("Unexpected end of save header (length prefix).")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, offset
        shift += 7
        if shift > 35:
            raise SaveFileError("Invalid 7-bit length prefix in save header.")


def _read_string(data: bytes, offset: int) -> tuple[str, int]:
    length, offset = _read_7bit_int(data, offset)
    end = offset + length
    if end > len(data):
        raise SaveFileError("Unexpected end of save header (string payload).")
    return data[offset:end].decode("utf-8", errors="replace"), end


def _read_struct(data: bytes, offset: int, fmt: str) -> tuple[object, int]:
    size = struct.calcsize(fmt)
    if offset + size > len(data):
        raise SaveFileError("Unexpected end of save header (fixed field).")
    return struct.unpack_from(fmt, data, offset)[0], offset + size


def _datetime_from_binary(raw: int) -> tuple[datetime | None, int]:
    """Decode .NET DateTime.ToBinary(): 62 bits of ticks + 2 kind bits."""
    kind = (raw >> 62) & 0x3
    ticks = raw & 0x3FFF_FFFF_FFFF_FFFF
    if ticks <= 0:
        return None, kind
    # .NET ticks are 100 ns intervals since 0001-01-01. ToBinary stores ticks in
    # UTC for both Utc and Local kinds; the kind only controls display.
    value = datetime(1, 1, 1) + timedelta(microseconds=ticks // 10)
    if kind == DATETIME_KIND_UTC:
        return value.replace(tzinfo=UTC), kind
    if kind == DATETIME_KIND_LOCAL:
        return value.replace(tzinfo=UTC).astimezone(), kind
    return value, kind


def _item_id_from_segment(segment: bytes) -> str:
    """Return the last ``MelvorBase:<item>`` id in an equipment slot payload."""
    marker = segment.rfind(b"MelvorBase:")
    if marker < 0:
        return ""
    raw = segment[marker + len(b"MelvorBase:") :]
    end = 0
    while end < len(raw):
        byte = raw[end]
        if not (48 <= byte <= 57 or 65 <= byte <= 90 or 97 <= byte <= 122):
            break
        end += 1
    return raw[:end].decode("ascii", errors="ignore")


def parse_equipment(data: bytes) -> dict[str, str]:
    """Read the equipped items from the save object graph.

    The ``Equipment`` component is a count followed by length-prefixed slot
    entries; a non-empty slot payload ends with ``MelvorBase:<ItemId>``. A
    two-handed weapon appears in both the Weapon and Offhand slots.
    """
    start = data.find(EQUIPMENT_MARKER)
    if start < 0:
        return {}
    offset = start + len(EQUIPMENT_MARKER)
    if offset + 8 > len(data):
        return {}
    _block_length = struct.unpack_from("<i", data, offset)[0]
    offset += 4
    count = struct.unpack_from("<i", data, offset)[0]
    offset += 4
    if not 0 < count <= 20:
        return {}

    result: dict[str, str] = {}
    for _ in range(count):
        try:
            slot_name, offset = _read_string(data, offset)
        except SaveFileError:
            break
        if offset + 4 > len(data):
            break
        payload_length = struct.unpack_from("<i", data, offset)[0]
        offset += 4
        if payload_length < 0 or offset + payload_length > len(data):
            break
        payload = data[offset : offset + payload_length]
        offset += payload_length
        slot = EQUIPMENT_SLOT_NAMES.get(slot_name)
        if slot is None:
            continue
        item = _item_id_from_segment(payload)
        if item:
            result[slot] = item
    return result


def parse_active_enemy(data: bytes) -> str:
    """Return the id of the enemy currently being fought, or ``""``.

    The combat component stores two ``Enemy`` fields: the first is the
    component registry entry, the second is the active enemy object. The enemy
    id is the last ``MelvorBase:`` token before the object's attack stance, so
    the lookup never depends on the on-screen name.
    """
    equipment_start = data.find(EQUIPMENT_MARKER)
    search_from = max(equipment_start, 0)
    first = data.find(b"\x05Enemy", search_from)
    if first < 0:
        return ""
    second = data.find(b"\x05Enemy", first + 1)
    if second < 0:
        return ""
    limit = min(len(data), second + 8192)

    candidates: list[int] = []
    for token in ENEMY_STANCE_TOKENS:
        start = second
        while True:
            index = data.find(token, start, limit)
            if index < 0:
                break
            # The active enemy id is followed by a bool and then its stance.
            if index > 0 and data[index - 1] == 1:
                candidates.append(index)
            start = index + 1
    if not candidates:
        return ""

    for stance_index in sorted(candidates):
        end = stance_index - 1
        marker = data.rfind(b"MelvorBase:", second, end)
        if marker < 0:
            continue
        enemy_id = data[marker + len(b"MelvorBase:") : end].decode(
            "ascii", errors="ignore"
        )
        if not enemy_id or not enemy_id.isalnum():
            continue
        if data[marker - 1] != len(b"MelvorBase:") + len(enemy_id):
            continue
        return enemy_id
    return ""


def parse_bank_order(data: bytes) -> tuple[str, ...]:
    """Return the bank/inventory item ids in their bank display order."""
    start = data.find(b"MelvorBase:Bank")
    if start < 0:
        return ()
    end = data.find(b"Tab 1", start)
    if end < 0:
        end = min(len(data), start + 65536)

    marker = b"MelvorBase:"
    result: list[str] = []
    position = start
    while True:
        index = data.find(marker, position, end)
        if index < 0:
            break
        length = data[index - 1]
        id_length = length - len(marker)
        if 0 < id_length < 64:
            token = data[index + len(marker) : index + len(marker) + id_length]
            if token.isalnum():
                result.append(token.decode("ascii"))
        position = index + len(marker)
    return tuple(result)


def parse_bank_items(data: bytes) -> frozenset[str]:
    """Return the item ids in the bank/inventory list (game ids)."""
    return frozenset(parse_bank_order(data))


def _parse_slayer_task_entry(
    data: bytes, offset: int, length: int, master: str
) -> SlayerTaskState | None:
    end = offset + length
    if offset >= end or offset >= len(data):
        return None
    has_task = data[offset] != 0
    offset += 1
    if not has_task:
        return None
    if offset >= end:
        return None
    enemy_length = data[offset]
    offset += 1
    if enemy_length <= 0 or offset + enemy_length > end:
        return None
    enemy = data[offset : offset + enemy_length].decode("ascii", errors="replace")
    offset += enemy_length
    if not enemy.startswith("MelvorBase:") or offset + 9 > end:
        return None
    task_length = struct.unpack_from("<i", data, offset)[0]
    offset += 4
    task_progress = struct.unpack_from("<i", data, offset)[0]
    offset += 4
    extended = bool(data[offset]) if offset < end else False
    if task_length <= 0 or task_progress < 0:
        return None
    return SlayerTaskState(
        master=master,
        enemy_id=enemy.split(":")[-1],
        length=task_length,
        progress=task_progress,
        extended=extended,
    )


def parse_slayer_task(data: bytes) -> SlayerTaskState | None:
    """Read the active Slayer master's current task from the save.

    ``SlayerTasksComponent`` writes every master's state, then the recent
    (active) master reference, then the statistics component. The active
    reference is a bool + length-prefixed ``MelvorBase:<Master>`` immediately
    before ``Statistics``. The matching master entry holds the task enemy,
    length and progress.
    """
    marker = b"MelvorBase:"
    stats_mark = data.find(b"MelvorBase:SlayerMasterTasksCompleted")
    if stats_mark < 0:
        return None
    statistics = data.rfind(b"Statistics", 0, stats_mark)
    if statistics < 0:
        return None

    active_master = ""
    index = statistics
    while True:
        index = data.rfind(marker, 0, index)
        if index < 0:
            break
        if index < 2:
            continue
        length = data[index - 1]
        id_length = length - len(marker)
        if data[index - 2] != 1 or not 0 < id_length < 64:
            continue
        token = data[index + len(marker) : index + len(marker) + id_length]
        if token.isalnum():
            active_master = token.decode("ascii")
            break
    if not active_master:
        return None

    needle = marker + active_master.encode("ascii")
    position = 0
    found: SlayerTaskState | None = None
    while True:
        entry = data.find(needle, position, index)
        if entry < 0:
            break
        position = entry + 1
        if entry < 1 or data[entry - 1] != len(needle):
            continue
        length_offset = entry + len(needle)
        if length_offset + 4 > len(data):
            continue
        data_length = struct.unpack_from("<i", data, length_offset)[0]
        if not 0 < data_length < 1000:
            continue
        parsed = _parse_slayer_task_entry(
            data, length_offset + 4, data_length, active_master
        )
        if parsed is not None:
            found = parsed
    return found


def parse_bank_stacks(data: bytes) -> dict[str, int]:
    """Read bank item stacks (id → quantity) from the first bank tab list.

    The game writes each stack as ``quantity (int32)``, ``isPlaceholder
    (bool)``, ``isLocked (bool)`` and then the namespaced item id. The scan is
    bounded by the ``Tab 1`` label. Quantity is summed when the bank holds
    several stacks of the same item (the game allows duplicates while loot is
    being added), because the UI shows and buries every stack.
    """
    inventory = data.find(b"\tInventory")
    if inventory < 0:
        return {}
    start = inventory + len(b"\tInventory")
    end = data.find(b"Tab 1", start)
    if end < 0:
        return {}

    marker = b"MelvorBase:"
    result: dict[str, int] = {}

    # Find the first real stack record. Its item id is preceded by the length
    # byte and the six record bytes. Headers before the list contain no
    # namespaced item ids, so the first valid record is the first stack.
    position = data.find(marker, start, end)
    record_start = -1
    while position >= 0:
        candidate = position - 7
        if candidate >= start and _valid_bank_record(data, candidate, end):
            record_start = candidate
            break
        position = data.find(marker, position + 1, end)
    if record_start < 0:
        return {}

    offset = record_start
    while offset + 7 <= end:
        quantity = struct.unpack_from("<i", data, offset)[0]
        placeholder = data[offset + 4]
        locked = data[offset + 5]
        length = data[offset + 6]
        token_start = offset + 7
        if (
            quantity < 0
            or quantity > 1_000_000_000
            or placeholder not in (0, 1)
            or locked not in (0, 1)
            or length <= len(marker)
            or token_start + length > end + 1
        ):
            break
        if data[token_start : token_start + len(marker)] != marker:
            break
        item = data[token_start + len(marker) : token_start + length]
        if not item.isalnum():
            break
        key = item.decode("ascii")
        result[key] = result.get(key, 0) + quantity
        offset = token_start + length
    return result


def _valid_bank_record(data: bytes, offset: int, end: int) -> bool:
    """True when ``offset`` looks like the start of a bank stack record."""
    if offset + 7 > end:
        return False
    quantity = struct.unpack_from("<i", data, offset)[0]
    placeholder = data[offset + 4]
    locked = data[offset + 5]
    length = data[offset + 6]
    token_start = offset + 7
    marker_length = len(b"MelvorBase:")
    return (
        0 <= quantity <= 1_000_000_000
        and placeholder in (0, 1)
        and locked in (0, 1)
        and marker_length < length < 75
        and token_start + length <= end + 1
        and data[token_start : token_start + marker_length] == b"MelvorBase:"
    )



def parse_wallet(data: bytes) -> dict[str, int]:
    """Read the player's currency wallet (for example PrayerPoints)."""
    marker = b"MelvorBase:GoldPieces"
    position = 0
    while True:
        index = data.find(marker, position)
        if index < 0:
            return {}
        position = index + 1
        if index < 13:
            continue
        if data[index - 1] != len(marker):
            continue
        pair_start = index - 9
        count = struct.unpack_from("<i", data, pair_start - 4)[0]
        if not 0 < count <= 20:
            continue
        offset = pair_start
        pairs: dict[str, int] = {}
        valid = True
        for _ in range(count):
            if offset + 8 > len(data):
                valid = False
                break
            quantity = struct.unpack_from("<q", data, offset)[0]
            offset += 8
            try:
                currency, offset = _read_string(data, offset)
            except SaveFileError:
                valid = False
                break
            if not currency.startswith("MelvorBase:"):
                valid = False
                break
            pairs[currency.split(":")[-1]] = quantity
        if valid and "GoldPieces" in pairs:
            return pairs


def _parse_player_hp_from_region(
    data: bytes, offset: int, end: int
) -> int | None:
    """Read the first region of the Player component (GlobalHealth)."""
    try:
        count, offset = _read_struct(data, offset, "<i")
        if count <= 0 or count > 10_000:
            return None
        for _ in range(count):
            component_id, offset = _read_string(data, offset)
            length, offset = _read_struct(data, offset, "<i")
            if length < 0 or offset + length > end:
                return None
            if component_id == "Player":
                region_length, value_offset = _read_struct(data, offset, "<i")
                if (
                    region_length != 4
                    or value_offset + 4 > offset + length
                ):
                    return None
                hp = struct.unpack_from("<i", data, value_offset)[0]
                return hp if 0 <= hp <= 1_000_000 else None
            offset += length
    except SaveFileError:
        return None
    return None


def _parse_current_hp(data: bytes, offset: int) -> int | None:
    """Read current HP from the Combat entity's Player component.

    ``PlayerComponent.WriteTo`` starts with a region containing only
    ``CharacterHealth.Current`` as an int32, so this needs the top-level entity
    and component region walk, not the full object graph.
    """
    try:
        count, offset = _read_struct(data, offset, "<i")
        if count <= 0 or count > 10_000:
            return None
        for _ in range(count):
            entity_id, offset = _read_string(data, offset)
            length, offset = _read_struct(data, offset, "<i")
            if length < 0 or offset + length > len(data):
                return None
            if entity_id == "MelvorBase:Combat":
                return _parse_player_hp_from_region(
                    data, offset, offset + length
                )
            offset += length
    except SaveFileError:
        return None
    return None


def parse_header(data: bytes) -> SaveHeader:
    """Parse the fixed SaveHeader from decompressed save bytes."""
    offset = 0
    version, offset = _read_struct(data, offset, "<i")
    if offset + 16 > len(data):
        raise SaveFileError("Unexpected end of save header (uuid).")
    guid = uuidlib.UUID(bytes_le=data[offset : offset + 16])
    offset += 16

    character_name, offset = _read_string(data, offset)
    gamemode, offset = _read_string(data, offset)

    raw_timestamp, offset = _read_struct(data, offset, "<Q")
    timestamp, _kind = _datetime_from_binary(raw_timestamp)

    active_entity = active_entity_icon = ""
    active_action = active_action_icon = ""
    if version < VERSION_LOCALIZATION:
        # Legacy layout: one obsolete string instead of the four action fields.
        _, offset = _read_string(data, offset)
    else:
        active_entity, offset = _read_string(data, offset)
        active_entity_icon, offset = _read_string(data, offset)
        active_action, offset = _read_string(data, offset)
        active_action_icon, offset = _read_string(data, offset)

    total_level, offset = _read_struct(data, offset, "<i")
    gp, offset = _read_struct(data, offset, "<q")
    slayer_coins, offset = _read_struct(data, offset, "<q")

    is_demo = False
    if version >= VERSION_ALPHA_0_11_0:
        if offset >= len(data):
            raise SaveFileError("Unexpected end of save header (demo flag).")
        is_demo = data[offset] != 0
        offset += 1

    current_hp = _parse_current_hp(data, offset)
    max_hp = 0
    try:
        hitpoints = parse_skill_level(data, int(version), "Hitpoints")
        if hitpoints is not None:
            max_hp = hitpoints.level * HITPOINTS_PER_LEVEL
    except SaveFileError:
        pass

    bank_stacks = parse_bank_stacks(data)
    wallet = parse_wallet(data)
    owned_bank = {
        item: quantity
        for item, quantity in bank_stacks.items()
        if quantity > 0
    }
    return SaveHeader(
        save_version=int(version),
        uuid=str(guid).upper(),
        character_name=character_name,
        gamemode=gamemode,
        timestamp=timestamp,
        active_entity=active_entity,
        active_entity_icon=active_entity_icon,
        active_action=active_action,
        active_action_icon=active_action_icon,
        total_level=int(total_level),
        gp=int(gp),
        slayer_coins=int(slayer_coins),
        is_demo=is_demo,
        current_hp=current_hp,
        max_hp=max_hp,
        active_enemy_id=parse_active_enemy(data),
        equipment=parse_equipment(data),
        bank_items=frozenset(owned_bank),
        bank_order=tuple(owned_bank),
        bank_stacks=bank_stacks,
        wallet=wallet,
        prayer_points=wallet.get("PrayerPoints", 0),
        slayer_task=parse_slayer_task(data),
    )


def _parse_experience_level(
    data: bytes, start: int, save_version: int, name: str
) -> SkillLevel | None:
    """Read the Experience component that follows a skill entity name.

    BaseExperience.WriteTo writes a double Xp followed by an int32 Level. The
    component is length-prefixed (12 bytes on current saves; older saves have an
    extra int32 before the level, making it 16 bytes).
    """
    end = min(len(data), start + EXPERIENCE_SEARCH_WINDOW)
    marker = data.find(EXPERIENCE_MARKER, start, end)
    if marker < 0 or marker + 14 > len(data):
        return None
    payload_length = struct.unpack_from("<i", data, marker + 10)[0]
    expected = 12 if save_version >= VERSION_ALPHA_0_11_1 else 16
    if payload_length != expected:
        return None
    payload = marker + 14
    if payload + payload_length > len(data):
        return None
    xp = struct.unpack_from("<d", data, payload)[0]
    level_offset = payload + 8 if expected == 12 else payload + 12
    level = struct.unpack_from("<i", data, level_offset)[0]
    if not (1 <= level <= 200) or not (0 <= xp < 1e12):
        return None
    return SkillLevel(name=name, level=level, xp=xp)


def parse_skill_level(
    data: bytes, save_version: int, name: str
) -> SkillLevel | None:
    """Return one skill level from decompressed save bytes."""
    needle = f"MelvorBase:{name}".encode()
    position = 0
    while True:
        index = data.find(needle, position)
        if index < 0:
            return None
        end = index + len(needle)
        # The bytes after the name are a component length. A longer id
        # such as AttackTask3 / SmithingHelmet has an ASCII suffix there,
        # which decodes to an implausible length.
        if end + 4 > len(data):
            return None
        component_length = struct.unpack_from("<i", data, end)[0]
        if not (0 < component_length <= 10_000_000):
            position = index + 1
            continue
        parsed = _parse_experience_level(data, end, save_version, name)
        if parsed is not None:
            return parsed
        position = index + 1


def parse_skill_levels(
    data: bytes, save_version: int
) -> dict[str, SkillLevel]:
    """Extract current skill levels (and XP) from decompressed save bytes."""
    levels: dict[str, SkillLevel] = {}
    for name in SKILL_NAMES:
        parsed = parse_skill_level(data, save_version, name)
        if parsed is not None:
            levels[name] = parsed
    return levels


def read_skills(
    save_path: Path | None = None,
    *,
    settings: Settings | None = None,
    retries: int = 3,
) -> SkillLevels:
    """Snapshot a save and return exact per-skill levels from its XP components.

    The Skills page shows ``current / demo max`` (for example ``56/60``); this
    reads the stored level directly, so the max level cannot be mistaken for
    the character's level.
    """
    settings = settings or load_settings()
    save_path = save_path or select_save(settings)
    key = _cache_key(save_path)
    cached = _cache_get(_SKILLS_CACHE, key)
    if cached is not None:
        return cached
    with _CACHE_LOCK:
        key = _cache_key(save_path)
        cached = _cache_get(_SKILLS_CACHE, key)
        if cached is not None:
            return cached
        result = _read_skills_uncached(save_path, retries)
        _cache_put(_SKILLS_CACHE, key, result)
        return result


def _read_skills_uncached(save_path: Path, retries: int = 3) -> SkillLevels:
    last_error: Exception | None = None

    with tempfile.TemporaryDirectory(prefix="mi2_aio_skills_") as tmp:
        tmp_dir = Path(tmp)
        snapshot = tmp_dir / "snapshot.sav"
        raw = tmp_dir / "snapshot.raw"

        for attempt in range(1, retries + 1):
            try:
                shutil.copy2(save_path, snapshot)
                decompress_save(snapshot, raw)
                data = raw.read_bytes()
                header = parse_header(data)
                skills = parse_skill_levels(data, header.save_version)
                return SkillLevels(
                    character_name=header.character_name,
                    gamemode=header.gamemode,
                    save_version=header.save_version,
                    total_level=header.total_level,
                    skills=skills,
                    source=save_path,
                    source_mtime=datetime.fromtimestamp(
                        save_path.stat().st_mtime
                    ).astimezone(),
                )
            except (OSError, SaveFileError) as exc:
                last_error = exc
                if attempt < retries:
                    continue

    raise SaveFileError(
        f"Could not read skill levels from {save_path} after {retries} "
        f"attempts: {last_error}"
    )


def format_skills(levels: SkillLevels) -> str:
    """Human-readable skill-level listing."""
    lines = [
        f"{levels.character_name} ({levels.gamemode}, save v{levels.save_version})"
    ]
    for name in SKILL_NAMES:
        skill = levels.skills.get(name)
        if skill is not None:
            lines.append(
                f"  {name:<14} {skill.level:>3}  {skill.xp:,.0f} xp"
            )
    lines.append(
        f"  total level    {levels.total_level} "
        f"(parsed {levels.parsed_total})"
    )
    return "\n".join(lines)


def read_header(
    save_path: Path | None = None,
    *,
    settings: Settings | None = None,
    retries: int = 3,
) -> SaveHeader:
    """Snapshot a save (default: newest) and return its decoded header.

    Retries because the game may be replacing the file mid-read. Results are
    cached by path/mtime/size, so the UI and runner do not launch a new
    SaveTool process for every poll.
    """
    settings = settings or load_settings()
    save_path = save_path or select_save(settings)
    key = _cache_key(save_path)
    cached = _cache_get(_HEADER_CACHE, key)
    if cached is not None:
        return cached
    with _CACHE_LOCK:
        key = _cache_key(save_path)
        cached = _cache_get(_HEADER_CACHE, key)
        if cached is not None:
            return cached
        header = _read_header_uncached(save_path, retries)
        _cache_put(_HEADER_CACHE, key, header)
        return header


def _read_header_uncached(save_path: Path, retries: int = 3) -> SaveHeader:
    last_error: Exception | None = None

    with tempfile.TemporaryDirectory(prefix="mi2_aio_save_") as tmp:
        tmp_dir = Path(tmp)
        snapshot = tmp_dir / "snapshot.sav"
        raw = tmp_dir / "snapshot.raw"

        for attempt in range(1, retries + 1):
            try:
                shutil.copy2(save_path, snapshot)
                decompress_save(snapshot, raw)
                header = parse_header(raw.read_bytes())
                return replace(
                    header,
                    source=save_path,
                    source_mtime=datetime.fromtimestamp(
                        save_path.stat().st_mtime
                    ).astimezone(),
                )
            except (OSError, SaveFileError) as exc:
                last_error = exc
                if attempt < retries:
                    continue

    raise SaveFileError(
        f"Could not read {save_path} after {retries} attempts: {last_error}"
    )


def format_header(header: SaveHeader) -> str:
    """Human-readable multi-line summary."""
    stamp = header.timestamp.isoformat() if header.timestamp else "unknown"
    mtime = header.source_mtime.isoformat() if header.source_mtime else "unknown"
    demo = "demo" if header.is_demo else "full"
    lines = [
        f"character      {header.character_name} ({header.gamemode}, {demo})",
        f"save version   {header.save_version}",
        f"uuid           {header.uuid}",
        f"file           {header.source}",
        f"file modified  {mtime}",
        f"header time    {stamp}",
        f"total level    {header.total_level}",
        f"gp             {header.gp:,}",
        f"slayer coins   {header.slayer_coins:,}",
        f"active entity  {header.active_entity}",
        f"active action  {header.active_action}",
    ]
    if header.active_enemy_id:
        lines.append(f"active enemy   {header.active_enemy_id}")
    if header.slayer_task is not None:
        task = header.slayer_task
        lines.append(
            f"slayer task    {task.master}: {task.enemy_id} "
            f"{task.progress}/{task.length}"
            + (" (extended)" if task.extended else "")
        )
    weapon = header.equipment.get("Weapon", "")
    offhand = header.equipment.get("Offhand", "")
    if weapon:
        lines.append(
            f"equipped       {weapon}"
            + (f" + {offhand}" if offhand and offhand != weapon else "")
        )
    return "\n".join(lines)
