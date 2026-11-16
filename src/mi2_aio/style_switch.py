"""Pick and apply the best melee style for the enemy being fought.

The active enemy is read from the save (``SaveHeader.active_enemy_id``), which
works for both slayer and dungeon waves. The equipped weapon/off-hand are also
read from the save, so the switcher knows whether a bank trip is needed.

The decision comes from :mod:`mi2_aio.melee`; this module adds the live parts:

* walk the ranked candidates so an item the character does not own is skipped;
* equip the chosen weapon (and defender) through the bank;
* click the stance button for the weapon type's stance order;
* verify the stance from the UI;
* leave the current setup alone if nothing usable is owned.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PIL import Image

from . import equipment, ui
from .enemy_db import Enemy, load_enemies
from .equipment_db import EquipmentDatabase, load_database
from .melee import MeleeDecision, StyleChoice, choose_melee_style
from .savefile import SaveFileError, SkillLevels, read_header, read_skills
from .window import capture_client

if TYPE_CHECKING:
    from .equipment_db import EquipmentItem
    from .tasks.base import TaskContext


class StyleSwitcher:
    """Apply the best slash/block/crush setup for the active enemy."""

    def __init__(
        self,
        *,
        auto_style: bool = True,
        auto_armour: bool = True,
        armour_check_minutes: float = 10.0,
        switch_cooldown_seconds: float = 20.0,
        backoff_seconds: float = 600.0,
        stance_verify_seconds: float = 1.0,
    ) -> None:
        self.auto_style = auto_style
        self.auto_armour = auto_armour
        self.armour_check_minutes = max(1.0, armour_check_minutes)
        self.switch_cooldown_seconds = max(5.0, switch_cooldown_seconds)
        self.backoff_seconds = max(30.0, backoff_seconds)
        self.stance_verify_seconds = max(0.2, stance_verify_seconds)

        self._equipment_db: EquipmentDatabase | None = None
        self._enemies = None
        self._levels: SkillLevels | None = None
        self._levels_total: int | None = None

        self._enemy_id = ""
        self._decision: MeleeDecision | None = None
        self._blocked: set[tuple[str, str | None]] = set()
        self._blocked_until = 0.0
        self._last_switch_at = 0.0
        self._equipped_key: tuple[str, str | None] | None = None
        self._equipped_until = 0.0
        self._missing_defenders: set[str] = set()
        self._last_logged: dict[str, float] = {}
        self._last_armour_check = 0.0
        self._armour_logged = False

    # -- plumbing --------------------------------------------------------
    @property
    def db(self) -> EquipmentDatabase:
        if self._equipment_db is None:
            self._equipment_db = load_database()
        return self._equipment_db

    @property
    def enemies(self):
        if self._enemies is None:
            self._enemies = load_enemies()
        return self._enemies

    def _warn(
        self,
        ctx: TaskContext,
        key: str,
        message: str,
        *args: object,
        every: float = 300.0,
    ) -> None:
        now = time.monotonic()
        if now - self._last_logged.get(key, 0.0) < every:
            return
        self._last_logged[key] = now
        ctx.logger.warning(message, *args)

    def _info_once(
        self,
        ctx: TaskContext,
        key: str,
        message: str,
        *args: object,
    ) -> None:
        now = time.monotonic()
        if now - self._last_logged.get(key, 0.0) < 3600.0:
            return
        self._last_logged[key] = now
        ctx.logger.info(message, *args)

    def _click(self, ctx: TaskContext, point: tuple[int, int]) -> None:
        x, y = ui.to_client(*point, ctx.window.client_area)
        from .input import click_game

        click_game(ctx.window, x, y, ctx.settings.automation)

    def _capture(self, ctx: TaskContext) -> Image.Image:
        x, y = ui.to_client(*ui.CURSOR_PARK, ctx.window.client_area)
        try:
            from .input import background_move

            background_move(
                ctx.window,
                x,
                y,
                ctx.settings.automation,
                settle=False,
            )
        except Exception:
            pass
        time.sleep(0.25)
        return ui.normalize(capture_client(ctx.window))

    def _act(self, ctx: TaskContext, description: str) -> bool:
        if ctx.dry_run:
            ctx.logger.info("DRY RUN: %s", description)
            return False
        return True

    # -- save state ------------------------------------------------------
    def _read_levels(self, ctx: TaskContext) -> SkillLevels | None:
        total = ctx.header.total_level if ctx.header else None
        if self._levels is not None and total == self._levels_total:
            return self._levels
        try:
            levels = read_skills(settings=ctx.settings)
        except SaveFileError as exc:
            self._warn(
                ctx,
                "levels",
                "Could not read exact levels for the melee style choice (%s); "
                "leaving the current style alone.",
                exc,
            )
            return None
        self._levels = levels
        self._levels_total = total
        ctx.logger.info(
            "Melee style levels: Attack %s, Defence %s, Smithing %s.",
            levels.level("Attack"),
            levels.level("Defence"),
            levels.level("Smithing"),
        )
        return levels

    def _enemy(self, ctx: TaskContext) -> Enemy | None:
        header = ctx.header
        if header is None or header.active_entity.strip().lower() != "combat":
            return None
        if header.active_enemy_id:
            enemy = self.enemies.find_by_id(header.active_enemy_id)
            if enemy is not None:
                return enemy
        # Older saves or unusual states only expose the display name.
        if header.active_action.strip():
            return self.enemies.find(header.active_action)
        return None

    # -- current equipment ----------------------------------------------
    def _current_key(self, ctx: TaskContext) -> tuple[str, str | None] | None:
        now = time.monotonic()
        if self._equipped_key is not None and now < self._equipped_until:
            return self._equipped_key
        header = ctx.header
        if header is None:
            return None
        weapon = self.db.find_by_game_id(header.equipment.get("Weapon", ""))
        if weapon is None:
            return None
        offhand = self.db.find_by_game_id(header.equipment.get("Offhand", ""))
        defender_id = None
        if offhand is not None and offhand.id != weapon.id:
            defender_id = offhand.id
        return (weapon.id, defender_id)

    def _matches_current(
        self,
        choice: StyleChoice,
        current: tuple[str, str | None] | None,
    ) -> bool:
        if current is None:
            return False
        weapon_id, defender_id = current
        if choice.weapon.id != weapon_id:
            return False
        if choice.weapon.two_handed:
            return True
        expected = choice.defender.id if choice.defender else None
        if expected is None:
            return defender_id is None
        if defender_id == expected:
            return True
        return expected in self._missing_defenders and defender_id is None

    # -- public ----------------------------------------------------------
    def reset(self) -> None:
        """Forget the current enemy plan (for example on a new slayer task)."""
        self._enemy_id = ""
        self._decision = None
        self._blocked.clear()
        self._blocked_until = 0.0
        self._last_switch_at = 0.0
        # Keep _equipped_key until it expires; the save may not have caught up
        # with the last bank switch yet.
        self._missing_defenders.clear()

    def _read_equipment_slot(
        self, ctx: TaskContext, slot_key: str
    ) -> str | None:
        try:
            header = read_header(settings=ctx.settings)
        except SaveFileError:
            return None
        return header.equipment.get(slot_key)

    def _maybe_upgrade_armour(self, ctx: TaskContext) -> None:
        """Equip better owned armour pieces, respecting every level requirement."""
        if not self.auto_armour:
            return
        now = time.monotonic()
        if now - self._last_armour_check < self.armour_check_minutes * 60.0:
            return

        header = ctx.header
        if header is None or header.active_entity.strip().lower() != "combat":
            return
        self._last_armour_check = now
        levels = self._read_levels(ctx)
        if levels is None:
            return
        level_map = {
            name: skill.level for name, skill in levels.skills.items()
        }
        owned = self.db.owned_items(header)
        weapon = self.db.find_by_game_id(header.equipment.get("Weapon", ""))

        slots = (
            ("Helmet", "helmet"),
            ("Cape", "cape"),
            ("Amulet", "amulet"),
            ("Torso", "torso"),
            ("Legs", "legs"),
            ("Gloves", "gloves"),
            ("Boots", "boots"),
            ("Ring", "ring"),
        )
        upgrades: list[tuple[str, EquipmentItem, EquipmentItem | None]] = []
        for slot_key, slot in slots:
            best = self.db.best_armour(slot, level_map, owned=owned)
            if best is None:
                continue
            current = self.db.find_by_game_id(
                header.equipment.get(slot_key, "")
            )
            if current is not None and current.id == best.id:
                continue
            if (
                current is not None
                and best.armour_score <= current.armour_score
            ):
                continue
            upgrades.append((slot_key, best, current))

        # Defenders compete for the offhand, but only with a one-handed weapon.
        if weapon is not None and not weapon.two_handed:
            best_defender = self.db.best_armour(
                "offhand", level_map, owned=owned, subtype="defender"
            )
            if best_defender is not None:
                current_defender = self.db.find_by_game_id(
                    header.equipment.get("Offhand", "")
                )
                if (
                    current_defender is None
                    or best_defender.armour_score
                    > current_defender.armour_score
                ):
                    upgrades.append(
                        ("Offhand", best_defender, current_defender)
                    )

        if not upgrades:
            if not self._armour_logged:
                self._armour_logged = True
                ctx.logger.info(
                    "Armour check: already using the best owned pieces for "
                    "Defence %s.",
                    level_map.get("Defence"),
                )
            return
        if ctx.dry_run:
            ctx.logger.info(
                "DRY RUN: would upgrade armour: %s",
                ", ".join(
                    f"{slot} {best.name}" for slot, best, _current in upgrades
                ),
            )
            return

        for slot, best, current in upgrades:
            ctx.logger.info(
                "Armour upgrade: %s %s -> %s (protection %.0f, defence %.0f).",
                slot,
                current.name if current is not None else "empty",
                best.name,
                best.protection,
                best.total_defence,
            )
        for slot, best, current in upgrades:
            if self.db.bank_target(header, best) is None:
                ctx.logger.warning(
                    "%s was not found in the bank; keeping %s in the %s slot.",
                    best.name,
                    current.name if current is not None else "it empty",
                    slot,
                )
                continue
            search = self.db.bank_search(best)[0]
            ctx.logger.info(
                "Equipping armour candidate %s (%s) and verifying from the "
                "save.",
                best.name,
                slot,
            )
            ok = equipment.equip_verified_slot(
                ctx.window,
                ctx.settings.automation,
                search=search,
                slot_key=slot,
                desired_game_id=best.game_id,
                read_equipment=lambda key=slot: self._read_equipment_slot(
                    ctx, key
                ),
            )
            if ok:
                ctx.logger.info("Equipped armour: %s (%s).", best.name, slot)
                continue

            ctx.logger.warning(
                "Could not verify %s in the %s slot; reverting.",
                best.name,
                slot,
            )
            if current is not None:
                revert_search = self.db.bank_search(current)[0]
                reverted = equipment.equip_verified_slot(
                    ctx.window,
                    ctx.settings.automation,
                    search=revert_search,
                    slot_key=slot,
                    desired_game_id=current.game_id,
                    read_equipment=lambda key=slot: self._read_equipment_slot(
                        ctx, key
                    ),
                )
                if reverted:
                    ctx.logger.info(
                        "Reverted to %s in the %s slot.", current.name, slot
                    )
                else:
                    ctx.logger.warning(
                        "Could not revert the %s slot to %s; check the "
                        "equipment panel.",
                        slot,
                        current.name,
                    )
        self._armour_logged = False

    def maybe_apply(
        self,
        ctx: TaskContext,
        image: Image.Image,
        style: ui.CombatStyle | None = None,
    ) -> bool:
        """Apply the best melee style; return True when melee is handled.

        False means the caller may use the old melee/ranged/magic triangle
        logic instead (for example when auto style is disabled or the exact
        levels could not be read).
        """
        self._maybe_upgrade_armour(ctx)
        if not self.auto_style:
            return False
        if style is not None and style.word not in (None, "melee"):
            return False

        enemy = self._enemy(ctx)
        if enemy is None:
            self._warn(
                ctx,
                "enemy",
                "No active enemy in the save yet; the melee style choice is "
                "waiting for the next autosave.",
                every=120.0,
            )
            return False

        now = time.monotonic()
        if enemy.id != self._enemy_id:
            self._enemy_id = enemy.id
            self._decision = None
            self._blocked.clear()
            self._blocked_until = 0.0
            self._last_switch_at = 0.0
            # Keep _equipped_key: the save's equipment block can lag behind a
            # bank switch by an autosave, and the manager just equipped it.
            self._missing_defenders.clear()
            ctx.logger.info(
                "Melee style check: enemy %s (Defence %d).",
                enemy.name,
                enemy.defence_level,
            )

        if now < self._blocked_until:
            return True

        if self._decision is None:
            levels = self._read_levels(ctx)
            if levels is None:
                return False
            attack = levels.level("Attack") or 1
            defence = levels.level("Defence") or 1
            smithing = levels.level("Smithing") or 1
            decision = choose_melee_style(
                self.db,
                enemy,
                attack_level=attack,
                defence_level=defence,
                smithing_level=smithing,
                owned=(
                    self.db.owned_items(ctx.header)
                    if ctx.header is not None
                    else None
                ),
            )
            self._decision = decision
            if decision.best is None:
                self._warn(
                    ctx,
                    "no_style",
                    "No equippable melee weapon was found for %s; leaving the "
                    "current style alone.",
                    enemy.name,
                )
                self._blocked_until = now + self.backoff_seconds
                return True
            ctx.logger.info(
                "Enemy %s: best melee style is %s with %s (%.1f%% hit).",
                enemy.name,
                decision.best.style_label,
                decision.best.label,
                decision.best.hit_chance * 100.0,
            )

        if not self._decision.candidates:
            return True

        current = self._current_key(ctx)
        best = self._decision.candidates[0]

        if self._matches_current(best, current):
            self._ensure_stance(ctx, best)
            return True

        if now - self._last_switch_at < self.switch_cooldown_seconds:
            return True

        attempted = 0
        # Try the best setup for each style first, then the remaining ranked
        # candidates. This reaches every style quickly when the top crush or
        # block gear is not in the bank.
        ordered: list[StyleChoice] = sorted(
            self._decision.choices,
            key=lambda choice: (
                -choice.hit_chance,
                -choice.melee_strength,
                choice.interval_s,
            ),
        )
        seen = {choice.key for choice in ordered}
        ordered.extend(
            choice
            for choice in self._decision.candidates
            if choice.key not in seen
        )
        for choice in ordered:
            if choice.key in self._blocked:
                continue
            if attempted >= 6:
                break
            attempted += 1
            if self._matches_current(choice, current):
                self._ensure_stance(ctx, choice)
                return True
            if self._try_equip(ctx, choice):
                self._ensure_stance(ctx, choice)
                return True

        current_choice = next(
            (
                choice
                for choice in self._decision.candidates
                if self._matches_current(choice, current)
            ),
            None,
        )
        if current_choice is not None:
            self._ensure_stance(ctx, current_choice)
            self._info_once(
                ctx,
                f"fallback_{self._enemy_id}",
                "No better melee weapon is in the bank for %s; keeping %s.",
                self._decision.enemy.name,
                current_choice.label,
            )
            return True

        self._blocked_until = now + self.backoff_seconds
        self._warn(
            ctx,
            "no_owned",
            "None of the recommended melee weapons is in the bank for %s; "
            "leaving the current weapon alone for %.0f minutes.",
            self._decision.enemy.name,
            self.backoff_seconds / 60.0,
        )
        return True

    # -- equip / stance --------------------------------------------------
    def _try_equip(self, ctx: TaskContext, choice: StyleChoice) -> bool:
        if not self._act(
            ctx,
            f"equip {choice.label} for {choice.style_label}",
        ):
            # Dry runs still count as handled so the old triangle logic does
            # not fight the intended plan.
            return False

        header = ctx.header
        if header is None:
            return False
        weapon_target = self.db.bank_target(header, choice.weapon)
        if weapon_target is None:
            ctx.logger.info(
                "%s is not in the bank; trying the next best melee setup.",
                choice.weapon.name,
            )
            self._blocked.add(choice.key)
            return False

        targets = [
            equipment.BankTarget(
                choice.weapon.name, weapon_target[0], weapon_target[1]
            )
        ]
        if choice.defender is not None and not choice.weapon.two_handed:
            defender_target = self.db.bank_target(header, choice.defender)
            if defender_target is not None:
                targets.append(
                    equipment.BankTarget(
                        choice.defender.name,
                        defender_target[0],
                        defender_target[1],
                    )
                )
            else:
                self._missing_defenders.add(choice.defender.id)

        ctx.logger.info(
            "Equipping %s for %s (%.1f%% hit) against %s.",
            choice.label,
            choice.style_label,
            choice.hit_chance * 100.0,
            self._decision.enemy.name if self._decision else "the enemy",
        )
        try:
            equipped = equipment.equip_targets(
                ctx.window, ctx.settings.automation, targets
            )
        except Exception:
            ctx.logger.exception(
                "Could not equip %s; trying the next best melee setup.",
                choice.label,
            )
            self._blocked.add(choice.key)
            return False

        if choice.weapon.name not in equipped:
            ctx.logger.info(
                "%s is not in the bank; trying the next best melee setup.",
                choice.weapon.name,
            )
            self._blocked.add(choice.key)
            return False

        if (
            choice.defender is not None
            and choice.defender.name not in equipped
        ):
            self._missing_defenders.add(choice.defender.id)
            ctx.logger.warning(
                "%s is not in the bank; using %s alone.",
                choice.defender.name,
                choice.weapon.name,
            )
        defender_id = (
            choice.defender.id
            if choice.defender is not None
            and choice.defender.name in equipped
            else None
        )
        self._last_switch_at = time.monotonic()
        self._equipped_key = (choice.weapon.id, defender_id)
        self._equipped_until = time.monotonic() + 30.0
        ctx.logger.info(
            "Equipped %s (%s).", choice.label, choice.style_label
        )
        return True

    def _ensure_stance(self, ctx: TaskContext, choice: StyleChoice) -> bool:
        desired = choice.style
        index = choice.weapon.stance_index(desired)
        if index is None:
            self._warn(
                ctx,
                f"stance_{choice.weapon.id}_{desired}",
                "%s (%s) has no %s stance; leaving the stance alone.",
                choice.weapon.name,
                choice.weapon.weapon_type,
                choice.style_label,
            )
            return False

        image = self._capture(ctx)
        current = ui.read_attack_stance(image)
        if current is None:
            # The equipment panel can take a moment to redraw after a bank
            # switch.
            time.sleep(0.8)
            image = self._capture(ctx)
            current = ui.read_attack_stance(image)
        if current == desired:
            self._info_once(
                ctx,
                f"ready_{self._enemy_id}_{desired}",
                "Melee style ready: %s with %s (%.1f%% hit).",
                choice.style_label,
                choice.label,
                choice.hit_chance * 100.0,
            )
            return True

        point = ui.stance_button(index)
        if not self._act(
            ctx,
            f"select the {choice.style_label} stance at {point}",
        ):
            return False
        self._click(ctx, point)
        time.sleep(self.stance_verify_seconds)
        image = self._capture(ctx)
        verified = ui.read_attack_stance(image)
        if verified == desired:
            ctx.logger.info(
                "Stance set to %s for %s.",
                choice.style_label,
                choice.label,
            )
            return True

        self._warn(
            ctx,
            f"stance_failed_{self._enemy_id}_{desired}",
            "Could not verify the %s stance for %s (read %r); leaving it as is.",
            choice.style_label,
            choice.weapon.name,
            verified,
        )
        return False
