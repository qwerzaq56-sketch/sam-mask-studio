"""Small widget helpers shared by the panels."""

from __future__ import annotations

from typing import Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
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



class CollapsibleBox(QGroupBox):
    """A group box whose title is a ▾ / ▸ button that folds its contents away.

    Put the contents in ``box.body`` (a plain widget; give it a layout).
    ``title()`` / ``setTitle()`` work on the button, so it stands in for a QGroupBox.
    """

    toggled_open = pyqtSignal(bool)

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.header = QToolButton()
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setAutoRaise(True)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.ArrowType.DownArrow)
        self.header.setStyleSheet("QToolButton { border: none; font-weight: 600; }")
        self.header.setToolTip("Fold / unfold this section")
        self.header.toggled.connect(self._toggled)
        self.body = QWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 6)
        lay.setSpacing(2)
        lay.addWidget(self.header, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.body)
        self.setTitle(title)

    def title(self) -> str:
        return self.header.text()

    def setTitle(self, title: str) -> None:
        self.header.setText(title)

    def is_open(self) -> bool:
        return self.header.isChecked()

    def set_open(self, on: bool) -> None:
        self.header.setChecked(bool(on))

    def _toggled(self, on: bool) -> None:
        self.header.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.body.setVisible(on)
        self.toggled_open.emit(on)


class DockTitleBar(QWidget):
    """A dock title bar with extra buttons left of the usual float / close buttons."""

    def __init__(self, dock: QDockWidget, extra: Sequence[QWidget] = ()):
        super().__init__(dock)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 2, 2)
        lay.setSpacing(1)
        title = QLabel(dock.windowTitle())
        title.setMinimumWidth(0)  # the title may be clipped so the dock can get narrow
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(title, 1)
        for w in extra:
            w.setFixedWidth(20)  # compact, so a folded Frame List stays narrow
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
            b.setFixedWidth(20)
            b.clicked.connect(slot)
            lay.addWidget(b)
