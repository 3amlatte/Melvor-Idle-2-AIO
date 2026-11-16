"""Read, validate and write ``settings.toml`` without destroying comments.

``tomllib`` is read-only. The app uses ``tomlkit`` so the carefully documented
configuration file survives a settings save. Every value is validated against
``settings_schema`` before the file is replaced atomically.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tomlkit

from .config import Settings, load_settings
from .paths import CONFIG_FILE
from .settings_schema import (
    BOOL,
    CHOICE,
    FIELDS,
    FLOAT,
    INT,
    LIST_STR,
    PAIR_INT,
    POINT,
    STR,
    FieldSpec,
)


class SettingsError(ValueError):
    """Raised when a setting is unknown or invalid."""


def load_document(path: Path | None = None):
    path = path or CONFIG_FILE
    if not path.exists():
        return tomlkit.document()
    return tomlkit.parse(path.read_text(encoding="utf-8"))


def values_from_document(document) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for path, spec in FIELDS.items():
        raw = _get(document, path.split("."))
        values[path] = spec.default if raw is None else _coerce(spec, raw)
    return values


def read_values(path: Path | None = None) -> dict[str, Any]:
    return values_from_document(load_document(path))


def validate_value(spec: FieldSpec, value: Any) -> Any:
    label = spec.label
    try:
        if spec.kind == BOOL:
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "1", "yes", "on"}:
                    return True
                if lowered in {"false", "0", "no", "off"}:
                    return False
                raise SettingsError(f"{label}: expected true or false.")
            return bool(value)

        if spec.kind == INT:
            number = int(value)
            return _in_range(spec, number)

        if spec.kind == FLOAT:
            number = float(value)
            return _in_range(spec, number)

        if spec.kind == CHOICE:
            text = str(value).strip()
            if spec.choices and text not in spec.choices:
                raise SettingsError(
                    f"{label}: choose one of {', '.join(spec.choices)}."
                )
            return text

        if spec.kind == STR:
            return str(value)

        if spec.kind == LIST_STR:
            if isinstance(value, str):
                items = [part.strip() for part in value.split(",")]
            else:
                items = [str(part).strip() for part in value]
            items = [item for item in items if item]
            if not items:
                raise SettingsError(f"{label}: at least one value is required.")
            return items

        if spec.kind in {POINT, PAIR_INT}:
            if isinstance(value, str):
                parts = [part.strip() for part in value.split(",")]
            else:
                parts = list(value)
            if len(parts) != 2:
                raise SettingsError(f"{label}: enter two values.")
            numbers = []
            for part in parts:
                number = float(part)
                number = _in_range(spec, number)
                numbers.append(int(number) if spec.kind == POINT else number)
            return numbers

        return value
    except SettingsError:
        raise
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{label}: {exc}") from exc


def save_values(
    values: Mapping[str, Any],
    path: Path | None = None,
) -> Settings:
    """Validate and persist a partial settings update; returns the reloaded Settings."""
    path = path or CONFIG_FILE
    document = load_document(path)
    for dotted, raw in values.items():
        spec = FIELDS.get(dotted)
        if spec is None:
            raise SettingsError(f"Unknown setting {dotted!r}.")
        normalized = validate_value(spec, raw)
        _set_path(document, dotted.split("."), normalized)

    path.parent.mkdir(parents=True, exist_ok=True)
    text = tomlkit.dumps(document)
    fd, temp_name = tempfile.mkstemp(
        prefix="settings_", suffix=".toml", dir=str(path.parent)
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        # Parse the temp file first; a broken update must never replace the
        # working configuration.
        load_settings(temp_path)
        os.replace(temp_path, path)
        return load_settings(path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _in_range(spec: FieldSpec, number: float) -> float:
    if spec.minimum is not None and number < spec.minimum:
        raise SettingsError(f"{spec.label}: minimum is {spec.minimum}.")
    if spec.maximum is not None and number > spec.maximum:
        raise SettingsError(f"{spec.label}: maximum is {spec.maximum}.")
    return number


def _coerce(spec: FieldSpec, raw: Any) -> Any:
    value = raw
    if hasattr(raw, "unwrap"):
        try:
            value = raw.unwrap()
        except Exception:
            value = raw
    if spec.kind == BOOL:
        return bool(value)
    if spec.kind == INT:
        return int(value)
    if spec.kind == FLOAT:
        return float(value)
    if spec.kind in {STR, CHOICE}:
        return str(value)
    if spec.kind == LIST_STR:
        return [str(item) for item in value]
    if spec.kind in {POINT, PAIR_INT}:
        return [int(item) for item in value]
    return value


def _get(node: Any, parts: list[str]) -> Any:
    current = node
    for part in parts:
        if not hasattr(current, "get"):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def _set_path(document: Any, parts: list[str], value: Any) -> None:
    node = document
    for part in parts[:-1]:
        child = node.get(part) if hasattr(node, "get") else None
        if child is None:
            child = tomlkit.table()
            node[part] = child
        node = child
    key = parts[-1]
    existing = node.get(key) if hasattr(node, "get") else None
    if existing is not None and not hasattr(existing, "get"):
        # Preserve the key's comment/trivia by replacing only its value.
        try:
            existing.value = value
            return
        except Exception:
            pass
    node[key] = value
