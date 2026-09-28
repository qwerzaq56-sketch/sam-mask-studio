"""Small widget helpers shared by the panels."""

from __future__ import annotations

from typing import Sequence

from PyQt6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolButton,
    QWidget,
)


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


class DockTitleBar(QWidget):
    """A dock title bar with extra buttons left of the usual float / close buttons."""

    def __init__(self, dock: QDockWidget, extra: Sequence[QWidget] = ()):
        super().__init__(dock)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 2, 2)
        lay.setSpacing(2)
        title = QLabel(dock.windowTitle())
        title.setMinimumWidth(0)  # the title may be clipped so the dock can get narrow
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(title, 1)
        for w in extra:
            lay.addWidget(w)
        style = self.style()
        for icon, tip, slot in (
            (QStyle.StandardPixmap.SP_TitleBarNormalButton, "Float", lambda: dock.setFloating(not dock.isFloating())),
            (QStyle.StandardPixmap.SP_TitleBarCloseButton, "Close (View menu brings it back)", dock.close),
        ):
            b = QToolButton()
            b.setIcon(style.standardIcon(icon))
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(slot)
            lay.addWidget(b)
