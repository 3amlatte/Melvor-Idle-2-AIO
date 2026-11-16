from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from mi2_aio.app import NumberInput


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_duration_input_keeps_its_unit(app) -> None:
    field = NumberInput(unit="Minutes", maximum=1440)
    assert field.value() == 0
    assert field.text() == "0"
    assert field.unit_label is not None
    assert field.unit_label.text() == "Minutes"

    field.setValue(10)
    assert field.value() == 10
    assert field.text() == "10"
    # The unit label is a separate, permanent part of the field.
    assert field.unit_label.text() == "Minutes"


def test_amount_input_is_unitless_and_empty_means_zero(app) -> None:
    field = NumberInput(maximum=1_000_000)
    assert field.unit_label is None
    assert field.value() == 0
    field.edit.setText("")
    assert field.value() == 0
    field.setValue(250)
    assert field.value() == 250
    field.setValue(2_000_000)
    assert field.value() == 1_000_000


def test_typed_value_updates_and_emits(app) -> None:
    field = NumberInput(maximum=1440)
    seen: list[int] = []
    field.valueChanged.connect(seen.append)
    field.edit.setText("12")
    assert field.value() == 12
    assert seen[-1] == 12
