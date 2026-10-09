"""Small widget helpers shared by the panels."""

from __future__ import annotations

from typing import Sequence

from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
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
        shrinkable(button)


class ColumnScroll(QScrollArea):
    """Scrolls its page vertically only; the page's minimum width still holds for the dock.

    A plain QScrollArea reports a tiny minimum width, so with the horizontal bar off a narrow
    dock cut the page's right side off (Properties › Edit Layer, U3 p133).
    """

    def __init__(self, page: QWidget, parent=None):
        super().__init__(parent)
        self.setWidget(page)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        page.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.widget() and event.type() == QEvent.Type.LayoutRequest:
            self.updateGeometry()  # the page's minimum width may have changed
        return super().eventFilter(obj, event)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        page = self.widget()
        if page is None:
            return hint
        bar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        return QSize(max(hint.width(), page.minimumSizeHint().width() + bar), hint.height())


def scroll_column(panel: QWidget) -> QVBoxLayout:
    """Lay *panel* out as one column that scrolls vertically: the layout to fill is returned.

    What the column holds then never sets the panel's minimum height, so a tab that grows
    (the propagation lists) scrolls inside instead of making the main window taller.
    """
    body = QWidget()
    area = ColumnScroll(body)
    outer = QVBoxLayout(panel)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(area)
    return QVBoxLayout(body)


class ButtonRow(QWidget):
    """Buttons in one row while they fit, else two a row (U4, p133: four were cut off at 1280 px)."""

    def __init__(self, buttons: Sequence[QWidget], parent=None):
        super().__init__(parent)
        self._buttons = list(buttons)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._cols = 0
        self._place(len(self._buttons))

    def _needed(self) -> int:
        gap = self._grid.horizontalSpacing() if self._grid.horizontalSpacing() >= 0 else 6
        n = len(self._buttons)  # the columns share the width equally: the widest label decides
        return max(b.sizeHint().width() for b in self._buttons) * n + gap * (n - 1)

    def _place(self, cols: int) -> None:
        if cols == self._cols:
            return
        self._cols = cols
        for b in self._buttons:
            self._grid.removeWidget(b)
        for i, b in enumerate(self._buttons):
            self._grid.addWidget(b, i // cols, i % cols)
        for c in range(len(self._buttons)):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)

    def resizeEvent(self, event) -> None:
        n = len(self._buttons)
        self._place(n if event.size().width() >= self._needed() else (n + 1) // 2)
        super().resizeEvent(event)


def shrinkable(button: QWidget) -> None:
    """Full width while there is room, clipped (never below a stub) when the column is narrow.

    (``Ignored`` would let a layout squeeze it to nothing next to a stretching field.)
    """
    button.setMinimumWidth(24)
    button.setSizePolicy(QSizePolicy.Policy.Preferred, button.sizePolicy().verticalPolicy())



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
        self.title = QLabel(dock.windowTitle())
        self.title.setMinimumWidth(0)  # the title may be clipped so the dock can get narrow
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.title, 1)
        for w in extra:  # their natural size: a fixed width clipped them with larger fonts / display scaling
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
            if tip == "Float":
                self.float_btn = b

    def set_compact(self, on: bool) -> None:
        """A narrow dock: drop the title and the float button, so the other buttons fit unclipped."""
        self.title.setVisible(not on)
        self.float_btn.setVisible(not on)
