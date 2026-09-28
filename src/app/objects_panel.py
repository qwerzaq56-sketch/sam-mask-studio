"""Objects list (spec 01 §7, 03 §3).

Each row: include checkbox (Final Mask), color, name (double-click to rename),
[Edit], [×] delete, [···] menu. When an Object has several Variants on the
current image they are listed under it as ● / ○ rows; clicking one selects it.
Merge / Duplicate / Delete act on the selected rows (Ctrl/Shift-click), so they
never conflict with the include checkboxes.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.project import MaskObject

ID_ROLE = Qt.ItemDataRole.UserRole
COLUMNS = 5  # name · linked (🔗 n) · Edit · × · ···
VARIANT_ROLE = Qt.ItemDataRole.UserRole + 1


def later(owner: QObject, signal, *args) -> None:
    """Emit *signal* of *owner* on the next event-loop turn.

    Handlers rebuild this tree; doing that inside the tree's own signal (or a
    row button's ``clicked``) would delete the item or button still in use.
    The timer is a child of *owner*, so it dies with it and never emits from
    a deleted widget (that crashes rather than raising).
    """
    t = QTimer(owner)
    t.setSingleShot(True)
    t.timeout.connect(lambda: signal.emit(*args))
    t.timeout.connect(t.deleteLater)
    t.start(0)


def color_icon(rgb, size: int = 12) -> QIcon:
    """A color chip with a thin darker border, so light colors (lavender, pale yellow) still show."""
    pm = QPixmap(size, size)
    color = QColor(*rgb)
    pm.fill(color)
    p = QPainter(pm)
    p.setPen(color.darker(170))
    p.drawRect(0, 0, size - 1, size - 1)
    p.end()
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
    variant_selected = pyqtSignal(int, int)  # obj id, variant index (current image)
    selection_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._objects: List[MaskObject] = []
        self._editing: Optional[int] = None
        self._updating = False
        self._shape: tuple = ()
        self._key: Optional[str] = None
        self._order: List[int] = []  # selected ids, oldest first

        self.tree = QTreeWidget()
        self.tree.setColumnCount(COLUMNS)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(14)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, COLUMNS):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.viewport().installEventFilter(self)  # a click on empty space clears the selection

        self.new_btn = QPushButton("+ New Object from Points")
        self.new_btn.setToolTip("Then click (or drag a box) on the image — N")
        self.new_btn.clicked.connect(lambda: later(self, self.new_requested))
        self.merge_btn = QPushButton("Merge")
        self.merge_btn.setToolTip("Fuse the selected rows into one Object (Ctrl/Shift-click rows to select)")
        self.merge_btn.clicked.connect(lambda: later(self, self.merge_requested, self.selected_ids()))
        self.dup_btn = QPushButton("Duplicate")
        self.dup_btn.clicked.connect(lambda: later(self, self.duplicate_requested, self.selected_ids()))
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(lambda: later(self, self.delete_requested, self.selected_ids()))

        ops = QHBoxLayout()
        for b in (self.merge_btn, self.dup_btn, self.del_btn):
            ops.addWidget(b)
        # Only the Objects with a mask on this image by default; Show all lists every Object.
        self.show_all = QCheckBox("Show all Objects")
        self.show_all.setToolTip("Also list Objects that have no mask on this image")
        self.show_all.toggled.connect(lambda _on: self.set_objects(self._objects, self._key, self._editing))
        self.shown_label = QLabel("")
        self.shown_label.setStyleSheet("color: gray;")
        head = QHBoxLayout()
        head.addWidget(self.show_all)
        head.addStretch(1)
        head.addWidget(self.shown_label)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(head)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.new_btn)
        lay.addWidget(QLabel("Selected Objects"))
        lay.addLayout(ops)
        self._update_buttons()

    # ------------------------------------------------------------------

    def set_objects(self, objects: Sequence[MaskObject], key: Optional[str], editing: Optional[int]) -> None:
        """Show *objects*, keeping the row selection.

        Rows are updated in place while the list of Objects (and their Variant
        rows) stays the same. Rebuilding would delete the row buttons, and a
        click whose press selects a row would then lose its release.
        """
        self._objects = list(objects)
        self._key = key
        self._editing = editing
        shown = [o for o in objects if self._listed(o, key, editing)]
        hidden = len(objects) - len(shown)
        self.shown_label.setText(f"{len(shown)} of {len(objects)} shown" if hidden else "")
        shape = (
            tuple((o.id, self._variant_count(o, key)) for o in shown),
            editing,
        )
        self._updating = True
        self.tree.blockSignals(True)
        if shape != self._shape:
            self._rebuild(shown, key, editing)
            self._shape = shape
        for i, o in enumerate(shown):
            self._fill(self.tree.topLevelItem(i), o, key, editing)
        self.tree.blockSignals(False)
        self._updating = False
        self._update_buttons()

    def _listed(self, o: MaskObject, key: Optional[str], editing: Optional[int]) -> bool:
        """Listed: it has a mask on this image, it is being edited, or Show all is on."""
        return self.show_all.isChecked() or o.id == editing or (key is not None and o.mask(key) is not None)

    @staticmethod
    def _variant_count(o: MaskObject, key: Optional[str]) -> int:
        fs = o.frame(key) if key is not None else None
        return len(fs.variants) if fs is not None and len(fs.variants) > 1 else 0

    def _rebuild(self, objects: Sequence[MaskObject], key: Optional[str], editing: Optional[int]) -> None:
        keep = set(self.selected_ids())
        self.tree.clear()
        for o in objects:
            item = QTreeWidgetItem()
            item.setData(0, ID_ROLE, o.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
            self.tree.addTopLevelItem(item)
            item.setSelected(o.id in keep)
            self.tree.setItemWidget(item, 2, self._edit_button(o.id, o.id == editing))
            self.tree.setItemWidget(item, 3, self._delete_button(o.id))
            self.tree.setItemWidget(item, 4, self._more_button(o.id))
            for i in range(self._variant_count(o, key)):
                child = QTreeWidgetItem(item)
                child.setData(0, ID_ROLE, o.id)
                child.setData(0, VARIANT_ROLE, i)
                child.setFlags(Qt.ItemFlag.ItemIsEnabled)
                child.setFirstColumnSpanned(True)
            item.setExpanded(True)

    def _fill(self, item: QTreeWidgetItem, o: MaskObject, key: Optional[str], editing: Optional[int]) -> None:
        """Write *o*'s current state into its row (and Variant rows)."""
        if item.text(0) != o.name:
            item.setText(0, o.name)
        item.setIcon(0, color_icon(o.color))
        state = Qt.CheckState.Checked if o.included else Qt.CheckState.Unchecked
        if item.checkState(0) != state:
            item.setCheckState(0, state)
        has = key is not None and o.mask(key) is not None
        n = sum(1 for fs in o.frames.values() if fs.mask is not None)
        item.setToolTip(0, f"{o.source.value} · masks on {n} image(s)" + ("" if has else " · none on this image"))
        # linked: the same Object on several images (propagated, batch, ...)
        link = f"🔗 {n}" if n > 1 else ""
        if item.text(1) != link:
            item.setText(1, link)
            item.setToolTip(1, f"Linked: masks on {n} images" if link else "")
        item.setForeground(0, QBrush() if has else QBrush(QColor(140, 140, 140)))
        f = QFont()
        f.setBold(o.id == editing)
        item.setFont(0, f)
        fs = o.frame(key) if key is not None else None
        if fs is not None and item.childCount():
            sel = min(fs.selected, len(fs.variants) - 1)
            for i, v in enumerate(fs.variants[: item.childCount()]):
                item.child(i).setText(0, f"{'●' if i == sel else '○'}  Variant {i + 1}   {v.score:.3f}")

    def _edit_button(self, oid: int, editing: bool) -> QPushButton:
        b = QPushButton("Editing" if editing else "Points")
        b.setCheckable(True)
        b.setChecked(editing)
        b.setToolTip("Finish Editing (Esc)" if editing else "Edit this Object with SAM2 points (E)")
        b.setFixedWidth(60)
        b.clicked.connect(lambda _=False, i=oid: later(self, self.edit_requested, i))
        b.setObjectName(f"edit_{oid}")
        return b

    def _delete_button(self, oid: int) -> QPushButton:
        b = QPushButton("×")
        b.setFixedWidth(26)
        b.setToolTip("Delete this Object")
        b.setObjectName(f"delete_{oid}")
        b.clicked.connect(lambda _=False, i=oid: later(self, self.delete_requested, [i]))
        return b

    def _more_button(self, oid: int) -> QPushButton:
        b = QPushButton("···")
        b.setFixedWidth(32)
        b.setObjectName(f"more_{oid}")
        menu = QMenu(b)
        menu.addAction("Rename", lambda i=oid: self._start_rename(i))
        menu.addAction("Duplicate", lambda i=oid: later(self, self.duplicate_requested, [i]))
        menu.addAction("Remove mask on this image", lambda i=oid: later(self, self.remove_frame_requested, i))
        menu.addSeparator()
        menu.addAction("Delete", lambda i=oid: later(self, self.delete_requested, [i]))
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
        """Selected Object ids in the order they were selected (Merge keeps the first one's name)."""
        now = {it.data(0, ID_ROLE) for it in self.tree.selectedItems() if it.parent() is None}
        self._order = [i for i in self._order if i in now]
        self._order += [
            it.data(0, ID_ROLE)
            for i in range(self.tree.topLevelItemCount())
            if (it := self.tree.topLevelItem(i)).data(0, ID_ROLE) in now and it.data(0, ID_ROLE) not in self._order
        ]
        return list(self._order)

    def select_ids(self, ids: Sequence[int]) -> None:
        wanted = set(ids)
        self._order = list(dict.fromkeys(ids))
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            it.setSelected(it.data(0, ID_ROLE) in wanted)
        self.tree.blockSignals(False)
        self._update_buttons()

    def eventFilter(self, obj, event):
        if (
            obj is self.tree.viewport()
            and event.type() == QEvent.Type.MouseButtonPress
            and self.tree.itemAt(event.position().toPoint()) is None
        ):
            self.tree.clearSelection()
        return super().eventFilter(obj, event)

    def move_selection(self, ids: Sequence[int], delta: int) -> Optional[int]:
        """The id *delta* rows from the current one among *ids* (the Objects that can be stepped to)."""
        if not ids:
            return None
        sel = self.selected_ids()
        current = self._editing if self._editing is not None else (sel[0] if sel else None)
        if current not in ids:
            return ids[0] if delta > 0 else ids[-1]
        i = ids.index(current) + delta
        return ids[i] if 0 <= i < len(ids) else None

    def _on_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        idx = item.data(0, VARIANT_ROLE)
        if item.parent() is not None and idx is not None:
            later(self, self.variant_selected, item.data(0, ID_ROLE), idx)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 0 or item.parent() is not None:
            return
        oid = item.data(0, ID_ROLE)
        obj = next((o for o in self._objects if o.id == oid), None)
        if obj is None:
            return
        checked = item.checkState(0) == Qt.CheckState.Checked
        if checked != obj.included:
            later(self, self.include_toggled, oid, checked)
        elif item.text(0) != obj.name:  # empty names are rejected by the project and the row resets
            later(self, self.renamed, oid, item.text(0))

    def _on_selection(self) -> None:
        self._update_buttons()
        later(self, self.selection_changed, self.selected_ids())

    def _update_buttons(self) -> None:
        n = len(self.selected_ids())
        self.merge_btn.setEnabled(n >= 2)
        self.dup_btn.setEnabled(n >= 1)
        self.del_btn.setEnabled(n >= 1)
