"""Objects list: include checkbox, color, name, [Edit], [···], and bulk Merge/Duplicate/Delete."""

from __future__ import annotations

from typing import List, Optional, Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.project import MaskObject

ID_ROLE = Qt.ItemDataRole.UserRole


def color_icon(rgb, size: int = 12) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(*rgb))
    return QIcon(pm)


class ObjectsPanel(QWidget):
    include_toggled = pyqtSignal(int, bool)
    renamed = pyqtSignal(int, str)
    edit_requested = pyqtSignal(int)  # obj id; the Object already in Edit means "finish"
    new_requested = pyqtSignal()
    merge_requested = pyqtSignal(list)
    duplicate_requested = pyqtSignal(list)
    delete_requested = pyqtSignal(list)
    remove_frame_requested = pyqtSignal(int)
    selection_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._objects: List[MaskObject] = []
        self._editing: Optional[int] = None
        self._updating = False

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemSelectionChanged.connect(self._on_selection)

        self.new_btn = QPushButton("+ New Object from Points")
        self.new_btn.setToolTip("Then click (or drag a box) on the image — N")
        self.new_btn.clicked.connect(self.new_requested)
        self.merge_btn = QPushButton("Merge")
        self.merge_btn.setToolTip("Fuse the selected rows into one Object (Ctrl/Shift-click rows to select)")
        self.merge_btn.clicked.connect(lambda: self.merge_requested.emit(self.selected_ids()))
        self.dup_btn = QPushButton("Duplicate")
        self.dup_btn.clicked.connect(lambda: self.duplicate_requested.emit(self.selected_ids()))
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(lambda: self.delete_requested.emit(self.selected_ids()))

        ops = QHBoxLayout()
        for b in (self.merge_btn, self.dup_btn, self.del_btn):
            ops.addWidget(b)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.new_btn)
        lay.addWidget(self.tree, 1)
        lay.addLayout(ops)
        self._update_buttons()

    # ------------------------------------------------------------------

    def set_objects(self, objects: Sequence[MaskObject], key: Optional[str], editing: Optional[int]) -> None:
        """Rebuild the rows, keeping the row selection."""
        keep = set(self.selected_ids())
        self._objects = list(objects)
        self._editing = editing
        self._updating = True
        self.tree.blockSignals(True)
        self.tree.clear()
        for o in objects:
            item = QTreeWidgetItem()
            item.setData(0, ID_ROLE, o.id)
            item.setText(0, o.name)
            item.setIcon(0, color_icon(o.color))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
            item.setCheckState(0, Qt.CheckState.Checked if o.included else Qt.CheckState.Unchecked)
            has = key is not None and o.mask(key) is not None
            n = sum(1 for fs in o.frames.values() if fs.mask is not None)
            item.setToolTip(0, f"{o.source.value} · masks on {n} image(s)" + ("" if has else " · none on this image"))
            if not has:
                item.setForeground(0, QBrush(QColor(140, 140, 140)))
            if o.id == editing:
                f = QFont()
                f.setBold(True)
                item.setFont(0, f)
            self.tree.addTopLevelItem(item)
            item.setSelected(o.id in keep)
            self.tree.setItemWidget(item, 1, self._edit_button(o.id, o.id == editing))
            self.tree.setItemWidget(item, 2, self._more_button(o.id))
        self.tree.blockSignals(False)
        self._updating = False
        self._update_buttons()

    def _edit_button(self, oid: int, editing: bool) -> QPushButton:
        b = QPushButton("Done" if editing else "Edit")
        b.setCheckable(True)
        b.setChecked(editing)
        b.setToolTip("Finish Editing (Esc)" if editing else "Edit this Object with SAM2 points (E)")
        b.setFixedWidth(52)
        b.clicked.connect(lambda _=False, i=oid: self.edit_requested.emit(i))
        b.setObjectName(f"edit_{oid}")
        return b

    def _more_button(self, oid: int) -> QPushButton:
        b = QPushButton("···")
        b.setFixedWidth(32)
        b.setObjectName(f"more_{oid}")
        menu = QMenu(b)
        menu.addAction("Rename", lambda i=oid: self._start_rename(i))
        menu.addAction("Duplicate", lambda i=oid: self.duplicate_requested.emit([i]))
        menu.addAction("Remove mask on this image", lambda i=oid: self.remove_frame_requested.emit(i))
        menu.addSeparator()
        menu.addAction("Delete", lambda i=oid: self.delete_requested.emit([i]))
        b.setMenu(menu)
        return b

    def _item(self, oid: int) -> Optional[QTreeWidgetItem]:
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, ID_ROLE) == oid:
                return it
        return None

    def _start_rename(self, oid: int) -> None:
        it = self._item(oid)
        if it is not None:
            self.tree.editItem(it, 0)

    def selected_ids(self) -> List[int]:
        return [it.data(0, ID_ROLE) for it in self.tree.selectedItems()]

    def select_ids(self, ids: Sequence[int]) -> None:
        wanted = set(ids)
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            it.setSelected(it.data(0, ID_ROLE) in wanted)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 0:
            return
        oid = item.data(0, ID_ROLE)
        obj = next((o for o in self._objects if o.id == oid), None)
        if obj is None:
            return
        checked = item.checkState(0) == Qt.CheckState.Checked
        if checked != obj.included:
            self.include_toggled.emit(oid, checked)
        elif item.text(0) != obj.name:  # empty names are rejected by the project and the row resets
            self.renamed.emit(oid, item.text(0))

    def _on_selection(self) -> None:
        self._update_buttons()
        self.selection_changed.emit(self.selected_ids())

    def _update_buttons(self) -> None:
        n = len(self.selected_ids())
        self.merge_btn.setEnabled(n >= 2)
        self.dup_btn.setEnabled(n >= 1)
        self.del_btn.setEnabled(n >= 1)
