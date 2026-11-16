"""Command-line entry point: doctor / status / levels / capture / gear / melee / tasks / features."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import Settings, load_settings
from .modes import resolve_mode
from .paths import LOGS_DIR, ensure_runtime_dirs
from .savefile import (
    SaveFileError,
    discover_saves,
    format_header,
    format_skills,
    read_header,
    read_skills,
    select_save,
)
from .tasks import DEFAULT_TASK, list_tasks
from .ui import REFERENCE_SIZE
from .window import capture as capture_window
from .window import (
    capture_client,
    ensure_reference_size,
    find_game_window,
    layout_ready,
)


def _load(args: argparse.Namespace) -> Settings:
    return load_settings(Path(args.config) if args.config else None)


def _add_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to settings.toml (default: config/settings.toml)",
    )


def cmd_doctor(args: argparse.Namespace) -> int:
    from .diagnostics import collect_diagnostics, format_diagnostics

    settings = _load(args)
    data = collect_diagnostics(settings)
    print(format_diagnostics(data))
    return 0 if data["ok"] else 1


def cmd_status(args: argparse.Namespace) -> int:
    settings = _load(args)

    if args.all:
        saves = discover_saves(settings)
        if not saves:
            print("error: no saves found", file=sys.stderr)
            return 1
        selected = saves[0]
        if settings.save.character:
            try:
                selected = select_save(settings)
            except SaveFileError as exc:
                print(f"warning: {exc}", file=sys.stderr)
        print(
            f"{'':1} {'character':<16} {'mode':<16} {'lvl':>4}  "
            f"{'action':<20} uuid"
        )
        for path in saves:
            marker = "*" if path == selected else " "
            try:
                header = read_header(path, settings=settings)
                mode = resolve_mode(header.gamemode, settings.gamemodes)
                action = (header.active_action or "idle")[:20]
                print(
                    f"{marker} {header.character_name:<16} "
                    f"{mode.profile.display_name:<16} {header.total_level:>4}  "
                    f"{action:<20} {header.uuid[:8]}"
                )
            except SaveFileError as exc:
                print(f"{marker} {'?':<16} {'unreadable':<16}    -  {exc}")
        print(
            "\n* selected save (newest unless [save].character pins another character)"
        )
        return 0

    try:
        header = read_header(
            Path(args.save) if args.save else None, settings=settings
        )
    except SaveFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    mode = resolve_mode(header.gamemode, settings.gamemodes)

    if args.json:
        payload = header.to_dict()
        payload["age_seconds"] = header.age_seconds
        payload["mode"] = {
            "raw": mode.raw,
            "matched": mode.matched,
            "key": mode.profile.key,
            "display_name": mode.profile.display_name,
            "permanent_death": mode.profile.permanent_death,
            "allow_risky_tasks": mode.profile.allow_risky_tasks,
            "min_hp_ratio": mode.profile.min_hp_ratio,
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(format_header(header))
    print(f"mode profile   {mode.profile.display_name} (key={mode.profile.key})")
    print(f"permanent death {mode.profile.permanent_death}")
    print(f"risky tasks     {'allowed' if mode.profile.allow_risky_tasks else 'blocked'}")
    print(f"min hp ratio    {mode.profile.min_hp_ratio:.2f}")
    if not mode.matched:
        print(f"warning         unrecognized gamemode {mode.raw!r}; using 'unknown'")
    age = header.age_seconds
    if age is not None:
        print(f"header age     {age:,.0f}s")
    return 0


def cmd_levels(args: argparse.Namespace) -> int:
    try:
        levels = read_skills(settings=_load(args))
    except SaveFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        import json

        print(json.dumps(levels.to_dict(), indent=2))
        return 0
    print(format_skills(levels))
    return 0


def cmd_modes(args: argparse.Namespace) -> int:
    settings = _load(args)
    entries = []
    for key in sorted(settings.gamemodes):
        profile = settings.gamemodes[key]
        entries.append(
            {
                "key": profile.key,
                "display_name": profile.display_name,
                "aliases": list(profile.aliases),
                "permanent_death": profile.permanent_death,
                "allow_risky_tasks": profile.allow_risky_tasks,
                "min_hp_ratio": profile.min_hp_ratio,
                "blocked_tasks": sorted(profile.blocked_tasks),
                "builtin": profile.builtin,
                "description": profile.description,
            }
        )

    if args.json:
        print(json.dumps(entries, indent=2))
        return 0

    print(f"{'key':<10} {'display':<16} {'death':<6} {'risky':<6} {'minhp':>5}  aliases")
    for entry in entries:
        death = "perm" if entry["permanent_death"] else "no"
        risky = "yes" if entry["allow_risky_tasks"] else "no"
        aliases = ", ".join(entry["aliases"]) or "-"
        print(
            f"{entry['key']:<10} {entry['display_name']:<16} {death:<6} "
            f"{risky:<6} {entry['min_hp_ratio']:>5.2f}  {aliases}"
        )
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    settings = _load(args)
    ensure_runtime_dirs()
    try:
        window = find_game_window(settings.game.window_title)
        image = capture_client(window) if args.client else capture_window(window)
    except (LookupError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    destination = (
        Path(args.output)
        if args.output
        else LOGS_DIR / f"capture_{datetime.now():%Y%m%d_%H%M%S}.png"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)
    print(f"saved {destination} ({image.width}x{image.height})")
    return 0


def cmd_tasks(_args: argparse.Namespace) -> int:
    from .features import CATEGORIES, by_category

    print(f"default task: {DEFAULT_TASK}\n")
    grouped = by_category()
    for category_key, label in CATEGORIES.items():
        features = grouped.get(category_key, [])
        if not features:
            continue
        print(f"{label}")
        for feature in features:
            print(f"  {feature.key:<12} {feature.description}")
            modes = "runnable" if feature.task else "maintenance"
            print(f"  {'':<12} {feature.config_section}  ({modes})")
        print()
    print("Runnable tasks: " + ", ".join(t.name for t in list_tasks()))
    return 0


def cmd_gear(args: argparse.Namespace) -> int:
    from dataclasses import asdict

    from .equipment_db import load_database

    db = load_database()

    attack = args.attack
    defence = args.defence
    smithing = args.smithing
    level_source = (
        "arguments"
        if all(value is not None for value in (attack, defence, smithing))
        else "save"
    )
    if args.compare and (
        attack is None or defence is None or smithing is None
    ):
        try:
            levels = read_skills(settings=_load(args))
            attack = attack if attack is not None else (levels.level("Attack") or 1)
            defence = (
                defence if defence is not None else (levels.level("Defence") or 1)
            )
            smithing = (
                smithing
                if smithing is not None
                else (levels.level("Smithing") or 1)
            )
            level_source = (
                "save"
                if args.attack is None
                and args.defence is None
                and args.smithing is None
                else "save + overrides"
            )
        except SaveFileError as exc:
            print(
                f"warning: could not read save levels ({exc}); pass "
                "--attack/--defence/--smithing to override",
                file=sys.stderr,
            )
            attack = attack if attack is not None else 1
            defence = defence if defence is not None else 1
            smithing = smithing if smithing is not None else 1
            level_source = "fallback"

    if args.compare:
        baseline = db.weapon_by_name(args.compare)
        if baseline is None:
            print(f"unknown weapon: {args.compare}", file=sys.stderr)
            return 1
        print(
            f"{baseline.name} ({baseline.weapon_type or baseline.type}"
            f"{', 2H' if baseline.two_handed else ''}): "
            f"power {baseline.power_rating:.0f} | "
            f"slash {baseline.slash_attack:.0f} | "
            f"str {baseline.melee_strength:.0f} | "
            f"interval {baseline.turn_interval_s:.1f}s | "
            f"slots {'+'.join(baseline.occupied_slots)}"
        )
        variants = [
            ("Best available", {}),
            ("Best craftable", {"craftable_only": True}),
        ]
        for label, options in variants:
            loadout = db.best_loadout(
                attack,
                defence,
                smithing_level=smithing,
                **options,
            )
            if loadout is None:
                print(f"\n{label}: no equippable scimitar/defender pair")
                continue
            diff = db.compare_to_two_handed(baseline, loadout)
            print(
                f"\n{label} at Attack {attack} / Defence {defence} "
                f"/ Smithing {smithing} ({level_source}):"
            )
            print(
                f"  {loadout.name}: power {loadout.power_rating:.0f} | "
                f"slash {loadout.slash_attack:.0f} | "
                f"str {loadout.melee_strength:.0f} | "
                f"interval {loadout.turn_interval_s:.1f}s | "
                f"slash def {loadout.slash_defence:.0f}"
            )
            print(
                f"  power {diff['power_rating_delta']:+.0f} | "
                f"slash {diff['slash_attack_delta']:+.0f} | "
                f"strength {diff['melee_strength_delta']:+.0f} | "
                f"interval {diff['interval_delta_s']:+.2f}s (positive = faster)"
            )
            print(
                "  per second: "
                f"slash {diff['baseline_slash_per_s']:.1f} -> "
                f"{diff['loadout_slash_per_s']:.1f}, "
                f"strength {diff['baseline_strength_per_s']:.1f} -> "
                f"{diff['loadout_strength_per_s']:.1f}"
            )
        return 0

    groups: list[tuple[str, tuple, str]] = []
    if args.slot in ("all", "scimitar"):
        groups.append(("Scimitars", db.scimitars, "weapon"))
    if args.slot in ("all", "sword"):
        groups.append(("Swords (1H + 2H)", db.swords, "weapon"))
    if args.slot in ("all", "mallet"):
        groups.append(("Mallets", db.mallets, "weapon"))
    if args.slot in ("all", "defender"):
        groups.append(("Defenders (armour)", db.defenders, "armour"))
    if args.slot in ("all", "other"):
        groups.append(("Other weapons (comparison)", db.other_weapons, "weapon"))
    armour_slots = (
        "helmet",
        "torso",
        "legs",
        "boots",
        "gloves",
        "cape",
        "amulet",
        "ring",
        "offhand",
    )
    if args.slot in ("all", "armour"):
        groups.append(("Armour", db.armour, "armour"))
    elif args.slot in armour_slots:
        groups.append(
            (args.slot.title(), db.armour_for_slot(args.slot), "armour")
        )

    if args.json:
        import json

        payload = {
            "game": db.game,
            "build": db.build,
            "data_version": db.data_version,
            "source": db.source,
            "generated": db.generated,
            "future_tiers": {
                key: list(names) for key, names in db.future_tiers.items()
            },
            "scimitars": [asdict(item) for item in db.scimitars],
            "swords": [asdict(item) for item in db.swords],
            "mallets": [asdict(item) for item in db.mallets],
            "defenders": [asdict(item) for item in db.defenders],
            "armour": [asdict(item) for item in db.armour],
            "other_weapons": [asdict(item) for item in db.other_weapons],
        }
        print(json.dumps(payload, indent=2))
        return 0

    def requirements_text(item) -> str:
        if item.requirements:
            return " / ".join(
                f"{requirement.skill} {requirement.level}"
                for requirement in item.requirements
            )
        return "none"

    def source_text(item) -> str:
        parts: list[str] = []
        if item.smithing is not None:
            materials = ", ".join(
                f"{quantity}x {name}"
                for name, quantity in item.smithing.ingredients
            )
            parts.append(f"Smithing {item.smithing.level} ({materials})")
        if item.drops:
            detail_parts: list[str] = []
            if item.drop_area:
                detail_parts.append(item.drop_area)
            if item.drop_chance is not None:
                detail_parts.append(f"{item.drop_chance * 100:.2f}%")
            detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
            parts.append("drop: " + ", ".join(item.drops) + detail)
        if item.obtained_from and not (
            item.smithing is not None
            and item.obtained_from.strip().lower() == "smithing"
        ):
            parts.append(item.obtained_from)
        if item.two_handed:
            parts.append("2H (occupies offhand)")
        return " / ".join(parts) or "unknown"

    for title, items, kind in groups:
        print(f"{title}")
        if kind == "armour":
            print(
                f"  {'Name':<28} {'Slot':<8} {'Req':<22} {'S.Def':>5} "
                f"{'C.Def':>5} {'T.Def':>5} {'Str':>4} {'Prot':>5}  Source"
            )
        else:
            print(
                f"  {'Name':<26} {'Req':<20} {'Slash':>5} {'Crush':>5} "
                f"{'Block':>5} {'Str':>4} {'Def':>4}  Source"
            )
        for item in items:
            requirement = requirements_text(item)
            source = source_text(item)
            if kind == "armour":
                print(
                    f"  {item.name:<28} {item.slot:<8} {requirement:<22} "
                    f"{float(item.stats.get('slash_defence', 0)):>5.0f} "
                    f"{float(item.stats.get('crush_defence', 0)):>5.0f} "
                    f"{item.total_defence:>5.0f} {item.melee_strength:>4.0f} "
                    f"{item.protection:>5.0f}  {source}"
                )
            else:
                print(
                    f"  {item.name:<26} {requirement:<20} "
                    f"{item.slash_attack:>5.0f} {item.style_bonus('crush'):>5.0f} "
                    f"{item.style_bonus('block'):>5.0f} "
                    f"{item.melee_strength:>4.0f} {item.slash_defence:>4.0f}  {source}"
                )
        print()

    if args.slot in ("all", "scimitar", "defender"):
        print("Future tiers (client artwork, not in the demo item database):")
        for key, names in db.future_tiers.items():
            print(f"  {key}: {', '.join(names)}")
    return 0


def cmd_melee(args: argparse.Namespace) -> int:
    import difflib

    from .enemy_db import load_enemies
    from .equipment_db import load_database
    from .melee import choose_melee_style, format_decision

    settings = _load(args)
    enemies = load_enemies()
    name = args.enemy
    if not name:
        try:
            header = read_header(settings=settings)
        except SaveFileError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if (
            header.active_entity.strip().lower() != "combat"
            or not header.active_action.strip()
        ):
            print(
                "error: the character is not fighting; pass --enemy NAME "
                "(for example --enemy \"Blue Slime\")",
                file=sys.stderr,
            )
            return 1
        name = header.active_enemy_id or header.active_action

    enemy = enemies.find(name)
    if enemy is None:
        suggestions = difflib.get_close_matches(
            name, list(enemies.names()), n=5, cutoff=0.4
        )
        detail = (
            "\nDid you mean: " + ", ".join(suggestions) if suggestions else ""
        )
        print(f"error: unknown enemy {name!r}{detail}", file=sys.stderr)
        return 1

    attack = args.attack
    defence = args.defence
    smithing = args.smithing
    level_source = "arguments"
    if attack is None or defence is None or smithing is None:
        try:
            skills = read_skills(settings=settings)
            attack = attack if attack is not None else (skills.level("Attack") or 1)
            defence = (
                defence if defence is not None else (skills.level("Defence") or 1)
            )
            smithing = (
                smithing
                if smithing is not None
                else (skills.level("Smithing") or 1)
            )
            level_source = "save"
        except SaveFileError as exc:
            print(
                f"warning: could not read save levels ({exc}); using 1 for "
                "missing values",
                file=sys.stderr,
            )
            attack = attack if attack is not None else 1
            defence = defence if defence is not None else 1
            smithing = smithing if smithing is not None else 1
            level_source = "fallback"

    decision = choose_melee_style(
        load_database(),
        enemy,
        attack_level=attack,
        defence_level=defence,
        smithing_level=smithing,
        craftable_only=args.craftable,
        include_special=not args.no_special,
    )
    if args.json:
        import json

        print(json.dumps(decision.to_dict(), indent=2))
        return 0
    print(format_decision(decision))
    print(f"Levels: Attack {attack}, Defence {defence}, Smithing {smithing} ({level_source})")
    try:
        header = read_header(settings=settings)
        weapon = header.equipment.get("Weapon", "")
        offhand = header.equipment.get("Offhand", "")
        if weapon:
            print(
                "Equipped: "
                + weapon
                + (f" + {offhand}" if offhand and offhand != weapon else "")
            )
    except SaveFileError:
        pass
    if args.craftable:
        print("Weapons: craftable only (Smithing recipes)")
    elif args.no_special:
        print("Weapons: standard tiers only (special drops excluded)")
    return 0


def cmd_slayer_masters(args: argparse.Namespace) -> int:
    from dataclasses import asdict

    from .slayer_master_db import load_slayer_masters

    db = load_slayer_masters()
    if args.json:
        import json

        payload = {
            "game": db.game,
            "build": db.build,
            "source": db.source,
            "generated": db.generated,
            "masters": [asdict(master) for master in db.masters],
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(
        f"{'Master':<12} {'Len':>3}  {'Areas':<44} "
        f"{'Reroll':>8} {'Block':>8}  Unlock"
    )
    for master in db.masters:
        areas = ", ".join(area.name for area in master.areas)
        unlock_parts = []
        for requirement in master.unlock_requirements:
            if requirement.type == "Level":
                unlock_parts.append(
                    f"{requirement.skill} {requirement.level}"
                )
            else:
                unlock_parts.append(requirement.type)
        unlock = " / ".join(unlock_parts) or "none"
        reroll = (
            f"{master.reroll_cost.quantity:,}"
            if master.reroll_cost
            else "-"
        )
        block = (
            f"{master.block_cost.quantity:,}" if master.block_cost else "-"
        )
        print(
            f"{master.name:<12} {master.base_task_length:>3}  {areas:<44} "
            f"{reroll:>8} {block:>8}  {unlock}"
        )
    return 0


def cmd_features(args: argparse.Namespace) -> int:
    from .features import CATEGORIES, FEATURES

    if args.json:
        import json

        print(
            json.dumps(
                [
                    {
                        "key": feature.key,
                        "category": feature.category,
                        "name": feature.name,
                        "description": feature.description,
                        "config_section": feature.config_section,
                        "task": feature.task,
                    }
                    for feature in FEATURES
                ],
                indent=2,
            )
        )
        return 0

    for feature in FEATURES:
        print(
            f"{CATEGORIES.get(feature.category, feature.category):<8} "
            f"{feature.key:<10} {feature.name:<14} {feature.config_section}"
        )
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from .app import main as app_main

    config = Path(args.config) if args.config else None
    return app_main([], config_path=config)


def cmd_run(args: argparse.Namespace) -> int:
    from .instance import SingleInstance
    from .runner import run

    settings = _load(args)
    lock = SingleInstance("MI2_AIO_Bot")
    if not lock.acquire():
        print(
            "error: another MI2 AIO bot run is already active.",
            file=sys.stderr,
        )
        return 5
    try:
        return run(
            task_name=args.task,
            settings=settings,
            duration_minutes=args.duration,
            dry_run=args.dry_run,
            max_tasks=args.max_tasks,
            options={
                key: value
                for key, value in (
                    ("location", args.location),
                    ("spot", args.spot),
                    ("recipe", args.recipe),
                    ("amount", str(args.amount) if args.amount else ""),
                )
                if value
            },
        )
    finally:
        lock.release()


def cmd_farm(args: argparse.Namespace) -> int:
    from .instance import SingleInstance

    lock = SingleInstance("MI2_AIO_Bot")
    if not lock.acquire():
        print(
            "error: another MI2 AIO bot run is already active.",
            file=sys.stderr,
        )
        return 5
    try:
        return _cmd_farm(args)
    finally:
        lock.release()


def _cmd_farm(args: argparse.Namespace) -> int:
    import threading

    from . import ui
    from .farming import FarmingMaintenance
    from .log import configure
    from .tasks.base import TaskContext

    settings = _load(args)
    logger = configure(settings.logging.level)
    try:
        window = find_game_window(settings.game.window_title)
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    ctx = TaskContext(
        settings=settings,
        window=window,
        logger=logger,
        stop=threading.Event(),
        page=None if args.restore == "none" else args.restore,
    )
    maintenance = FarmingMaintenance(settings)

    layout_ok, layout_reason = layout_ready(window)
    if not layout_ok:
        window = ensure_reference_size(window)
        layout_ok, layout_reason = layout_ready(window)
    if not layout_ok:
        print(
            f"error: {layout_reason}. Keep the game unminimized; the farming "
            f"readers are calibrated for a {REFERENCE_SIZE[0]}x{REFERENCE_SIZE[1]} "
            "client.",
            file=sys.stderr,
        )
        return 4

    if not args.inspect:
        counts = maintenance.run_pass(
            ctx, reason="manual", restore=args.restore != "none"
        )
        if args.restore in ("combat", "bank"):
            target = ui.PAGE_TARGETS[args.restore]
            maintenance._click(ctx, target)
            import time

            time.sleep(0.9)
        print(
            "farming pass: "
            + ", ".join(f"{key}={value}" for key, value in counts.items())
        )
        return 0

    image = maintenance._capture(ctx)
    print(f"attention badge  {ui.farming_badge(image)}")
    print(f"farming page     {ui.farming_page_open(image)}")
    if not ui.farming_page_open(image):
        maintenance._click(ctx, ui.FARM_ICON)
        import time

        time.sleep(1.3)
        image = maintenance._capture(ctx)
        print(f"farming page     {ui.farming_page_open(image)}")
    if not ui.farming_page_open(image):
        print("error: could not open the farming page", file=sys.stderr)
        return 1

    for category, point in ui.FARM_CATEGORY_TABS.items():
        maintenance._click(ctx, point)
        import time

        time.sleep(1.0)
        image = maintenance._capture(ctx)
        cards = ui.farm_cards(image)
        states = [ui.card_state(image, card) for card in cards]
        print(f"{category:<12} {states}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mi2",
        description="Local automation toolkit for Melvor Idle 2 (Steam).",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check environment, game, save, capture")
    _add_config(doctor)
    doctor.set_defaults(func=cmd_doctor)

    status = sub.add_parser("status", help="Decode save header(s) and mode")
    _add_config(status)
    status.add_argument("--save", type=str, default=None, help="Specific .sav file")
    status.add_argument(
        "--all", action="store_true", help="List every character/save slot"
    )
    status.add_argument("--json", action="store_true", help="Print JSON")
    status.set_defaults(func=cmd_status)

    levels = sub.add_parser(
        "levels", help="Read exact skill levels from the save"
    )
    _add_config(levels)
    levels.add_argument("--json", action="store_true", help="Print JSON")
    levels.set_defaults(func=cmd_levels)

    modes = sub.add_parser("modes", help="List game-mode profiles and policies")
    _add_config(modes)
    modes.add_argument("--json", action="store_true", help="Print JSON")
    modes.set_defaults(func=cmd_modes)

    capture = sub.add_parser("capture", help="Screenshot the game window")
    _add_config(capture)
    capture.add_argument("-o", "--output", type=str, default=None)
    capture.add_argument(
        "--client", action="store_true", help="Crop to the client area"
    )
    capture.set_defaults(func=cmd_capture)

    tasks = sub.add_parser("tasks", help="List tasks grouped by category")
    tasks.set_defaults(func=cmd_tasks)

    features = sub.add_parser(
        "features", help="List features by category (for the settings UI)"
    )
    features.add_argument("--json", action="store_true", help="Print JSON")
    features.set_defaults(func=cmd_features)

    gear = sub.add_parser(
        "gear",
        help="List melee weapons and armour with requirements and recipes",
    )
    _add_config(gear)
    gear.add_argument(
        "--slot",
        choices=(
            "all",
            "scimitar",
            "sword",
            "mallet",
            "defender",
            "other",
            "armour",
            "helmet",
            "torso",
            "legs",
            "boots",
            "gloves",
            "cape",
            "amulet",
            "ring",
            "offhand",
        ),
        default="all",
        help="Show only one equipment type",
    )
    gear.add_argument(
        "--compare",
        metavar="WEAPON",
        default=None,
        help="Compare a two-handed weapon (e.g. 'Bone Scythe') to the best pair",
    )
    gear.add_argument(
        "--attack",
        type=int,
        default=None,
        help="Override Attack level (default: read the save)",
    )
    gear.add_argument(
        "--defence",
        type=int,
        default=None,
        help="Override Defence level (default: read the save)",
    )
    gear.add_argument(
        "--smithing",
        type=int,
        default=None,
        help="Override Smithing level (default: read the save)",
    )
    gear.add_argument("--json", action="store_true", help="Print JSON")
    gear.set_defaults(func=cmd_gear)

    melee = sub.add_parser(
        "melee",
        help="Choose the best melee style (slash/block/crush) for an enemy",
    )
    _add_config(melee)
    melee.add_argument(
        "--enemy",
        default=None,
        help="Enemy name (default: the current save header action)",
    )
    melee.add_argument("--attack", type=int, default=None)
    melee.add_argument("--defence", type=int, default=None)
    melee.add_argument("--smithing", type=int, default=None)
    melee.add_argument(
        "--craftable",
        action="store_true",
        help="Only consider Smithing recipes",
    )
    melee.add_argument(
        "--no-special",
        action="store_true",
        help="Exclude special/drop-only weapons",
    )
    melee.add_argument("--json", action="store_true", help="Print JSON")
    melee.set_defaults(func=cmd_melee)

    masters = sub.add_parser(
        "slayer-masters",
        help="List Slayer masters, areas, lengths and costs",
    )
    _add_config(masters)
    masters.add_argument("--json", action="store_true", help="Print JSON")
    masters.set_defaults(func=cmd_slayer_masters)

    farm = sub.add_parser(
        "farm", help="Run one farming pass now, or inspect plot states"
    )
    _add_config(farm)
    farm.add_argument(
        "--inspect",
        action="store_true",
        help="Print the farming page state without harvesting anything",
    )
    farm.add_argument(
        "--restore",
        choices=("none", "action", "combat", "bank"),
        default="action",
        help="Page to open after the pass (default: the current action's page)",
    )
    farm.set_defaults(func=cmd_farm)

    gui = sub.add_parser("gui", help="Launch the desktop app")
    _add_config(gui)
    gui.set_defaults(func=cmd_gui)

    run = sub.add_parser("run", help="Run an automation task")
    _add_config(run)
    run.add_argument("--task", type=str, default=DEFAULT_TASK)
    run.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Stop after N minutes (capped by max_runtime_minutes)",
    )
    run.add_argument(
        "--dry-run", action="store_true", help="Log intended actions, send none"
    )
    run.add_argument(
        "--tasks",
        dest="max_tasks",
        type=int,
        default=None,
        help="Stop after N completed Slayer tasks",
    )
    run.add_argument(
        "--location",
        type=str,
        default="",
        help="Fishing location id or name (for --task fishing)",
    )
    run.add_argument(
        "--spot",
        type=str,
        default="",
        help="Fishing spot id or name inside the location",
    )
    run.add_argument(
        "--recipe",
        type=str,
        default="",
        help="Cooking recipe id or name (for --task cooking)",
    )
    run.add_argument(
        "--amount",
        type=int,
        default=0,
        help="Cooking products to make (0 = until stopped)",
    )
    run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
