"""Small widget helpers shared by the panels."""

from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QPushButton, QSizePolicy, QWidget


def allow_narrow(root: QWidget, min_chars: int = 10) -> None:
    """Let *root*'s combo boxes and buttons shrink with a narrow column.

    Combo boxes stop sizing to their longest entry, and buttons may shrink below
    their text width (the text is clipped rather than widening the whole dock).
    """
    for combo in root.findChildren(QComboBox):
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(min_chars)
    for button in root.findChildren(QPushButton):
        button.setMinimumWidth(0)
        button.setSizePolicy(QSizePolicy.Policy.Ignored, button.sizePolicy().verticalPolicy())
