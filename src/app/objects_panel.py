"""Objects list (spec 01 §7, 03 §3).

Each row: include checkbox (Final Mask), color, name (double-click to rename),
[🔒] lock, [Edit], [×] delete, [···] menu. When an Object has several Variants on the
current image they are listed under it as ● / ○ rows; clicking one selects it.
Merge / Move / Duplicate / Delete act on the selected rows (Ctrl/Shift-click),
so they never conflict with the include checkboxes. Duplicate copies the mask on
the current image only; Duplicate All copies every linked mask. Merge (Add) and
Move (Add, this image) run at once; their small ⚙ buttons open the options
(Move's ⚙ also has Copy). Roles: docs/specs/05-merge-copy-move.md.
A locked Object is never deleted (no confirmation: Delete is undoable).
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QToolButton,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.special import LENS_EDGE, SKY
from src.core.project import MaskObject

ID_ROLE = Qt.ItemDataRole.UserRole
COLUMNS = 7  # name · linked (🔗 n) · 👁 · 🔒 · Edit · × · ···
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


class LockButton(QPushButton):
    """🔒 when locked; unlocked it is an empty cell that shows a faint lock under the mouse."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFlat(True)
        self.setFixedWidth(22)
        self._fade = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fade)
        self._hover = False
        self.toggled.connect(lambda _on: self.update_look())
        self.update_look()

    def update_look(self) -> None:
        locked = self.isChecked()
        self.setText("🔒" if locked or self._hover else "")
        self._fade.setOpacity(1.0 if locked else 0.35)
        self.setToolTip("Locked: cannot be deleted (click to unlock)" if locked
                        else "Lock: a locked Object cannot be deleted")

    def enterEvent(self, event):
        self._hover = True
        self.update_look()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update_look()
        super().leaveEvent(event)


class EyeButton(QPushButton):
    """👁 shown on the canvas; faint when hidden (the check box is the Final Mask, this is only the view)."""

    def __init__(self, parent=None):
        super().__init__("👁", parent)
        self.shown = True  # (not a checkable button: a checked flat button draws a pressed box)
        self.setFlat(True)
        self.setFixedWidth(22)
        self._fade = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fade)
        self.update_look()

    def set_shown(self, on: bool) -> None:
        if on != self.shown:
            self.shown = on
            self.update_look()

    def update_look(self) -> None:
        shown = self.shown
        self._fade.setOpacity(0.85 if shown else 0.2)
        self.setToolTip("Shown on the image (click to hide it there; the Final Mask is the check box)" if shown
                        else "Hidden on the image, except while it is edited (click to show it; "
                             "it still counts in the Final Mask if checked)")


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
    visibility_changed = pyqtSignal()  # 👁: which Objects the canvas shows (view only, not saved, no undo)
    special_requested = pyqtSignal(str)  # a special Object's kind (sky, lens_edge)
    merge_requested = pyqtSignal(list)  # Add, at once
    merge_options_requested = pyqtSignal(list)  # ⚙: Add / Override with A / B
    duplicate_requested = pyqtSignal(list)  # the current image's mask only
    duplicate_all_requested = pyqtSignal(list)  # every linked mask
    transfer_requested = pyqtSignal(list, bool)  # [source id, target id], move (else copy): Add, this image
    transfer_options_requested = pyqtSignal(list)  # ⚙: Move / Copy, Add / Replace, this image / every image
    lock_requested = pyqtSignal(list, bool)  # ids, locked
    delete_requested = pyqtSignal(list)
    remove_frame_requested = pyqtSignal(int)
    variant_selected = pyqtSignal(int, int)  # obj id, variant index (current image)
    selection_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        # the Objects selected last, kept when picking other frames takes their rows out of the list
        # (many-frame work: Copy Mask / Clear Masks on Picked Frames)
        self.hidden: set = set()  # 👁 off: not drawn on the image (this session only)
        self.last_selected: List[int] = []
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
        self.special_btn = QToolButton()
        self.special_btn.setText("+ Special ▾")
        self.special_btn.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.special_btn.setToolTip("An Object made from settings, not points: the sky, a fisheye's black edge")
        self.special_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.special_btn)
        for kind, text in ((SKY, "Sky Mask"), (LENS_EDGE, "Fisheye Lens Edge")):
            menu.addAction(text, lambda k=kind: later(self, self.special_requested, k))
        self.special_btn.setMenu(menu)
        self.merge_btn = QPushButton("Merge")
        self.merge_btn.setToolTip(
            "Fuse the selected rows into one Object (the union, named after the first selected)."
            " ⚙: other ways. Ctrl/Shift-click rows to select"
        )
        self.merge_btn.clicked.connect(lambda: later(self, self.merge_requested, self.selected_ids()))
        self.merge_opts_btn = self._options_button(
            "Merge options: Add, or Override with A / B",
            lambda: later(self, self.merge_options_requested, self.selected_ids()),
        )
        self.move_btn = QPushButton("Move A → B")
        self.move_btn.setToolTip(
            "Move the first selected Object's (A) mask on this image into the last selected (B), added to B's."
            " A stays. ⚙: Copy, Replace, or every image"
        )
        self.move_btn.clicked.connect(lambda: later(self, self.transfer_requested, self._pair(), True))
        self.move_opts_btn = self._options_button(
            "Move / Copy options: Move or Copy, Add / Replace, this image / every image where A has a mask",
            lambda: later(self, self.transfer_options_requested, self._pair()),
        )
        self.dup_btn = QPushButton("Duplicate")
        self.dup_btn.setToolTip("Copy the selected Objects' mask on this image only")
        self.dup_btn.clicked.connect(lambda: later(self, self.duplicate_requested, self.selected_ids()))
        self.dup_all_btn = QPushButton("Duplicate All")
        self.dup_all_btn.setToolTip("Copy the selected Objects with every linked mask (all images)")
        self.dup_all_btn.clicked.connect(lambda: later(self, self.duplicate_all_requested, self.selected_ids()))
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(lambda: later(self, self.delete_requested, self.selected_ids()))

        ops = QHBoxLayout()
        ops.setSpacing(2)
        for b, opts in ((self.merge_btn, self.merge_opts_btn), (self.move_btn, self.move_opts_btn)):
            ops.addWidget(b, 1)
            ops.addWidget(opts)
            ops.addSpacing(4)
        ops2 = QHBoxLayout()
        for b in (self.dup_btn, self.dup_all_btn, self.del_btn):
            ops2.addWidget(b)
        # Only the Objects with a mask on this image by default; Show all lists every Object.
        self.show_all = QCheckBox("Show all Objects")
        self.show_all.setToolTip("Also list Objects that have no mask on this image")
        self.show_all.toggled.connect(lambda _on: self.set_objects(self._objects, self._key, self._editing))
        self.shown_label = QLabel("")
        self.shown_label.setStyleSheet("color: gray;")
        self.lock_all_btn = QPushButton("Lock All")
        self.lock_all_btn.setToolTip("Lock every Object (locked ones cannot be deleted)")
        self.lock_all_btn.clicked.connect(lambda: later(self, self.lock_requested, self._all_ids(), True))
        self.unlock_all_btn = QPushButton("Unlock All")
        self.unlock_all_btn.setToolTip("Unlock every Object")
        self.unlock_all_btn.clicked.connect(lambda: later(self, self.lock_requested, self._all_ids(), False))
        head = QHBoxLayout()
        head.addWidget(self.show_all)
        head.addStretch(1)
        head.addWidget(self.shown_label)
        for b in (self.lock_all_btn, self.unlock_all_btn):
            b.setFixedWidth(b.fontMetrics().horizontalAdvance(b.text()) + 18)
            head.addWidget(b)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(head)
        lay.addWidget(self.tree, 1)
        new_row = QHBoxLayout()
        new_row.addWidget(self.new_btn, 1)
        new_row.addWidget(self.special_btn)
        lay.addLayout(new_row)
        lay.addWidget(QLabel("Selected Objects"))
        lay.addLayout(ops)
        lay.addLayout(ops2)
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
        return (self.show_all.isChecked() or o.id == editing or o.special is not None
                or (key is not None and o.mask(key) is not None))

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
            self.tree.setItemWidget(item, 2, self._eye_button(o.id))
            self.tree.setItemWidget(item, 3, self._lock_button(o.id))
            self.tree.setItemWidget(item, 4, self._edit_button(o.id, o.id == editing))
            self.tree.setItemWidget(item, 5, self._delete_button(o.id))
            self.tree.setItemWidget(item, 6, self._more_button(o.id))
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
        # a new row has no check state at all (it reads as Unchecked but draws no box): always set it once
        if item.data(0, Qt.ItemDataRole.CheckStateRole) is None or item.checkState(0) != state:
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
        eye = self.tree.itemWidget(item, 2)
        if isinstance(eye, EyeButton):
            eye.set_shown(o.id not in self.hidden)
        lock = self.tree.itemWidget(item, 3)
        if isinstance(lock, LockButton) and lock.isChecked() != o.locked:
            lock.setChecked(o.locked)
        delete = self.tree.itemWidget(item, 5)
        if isinstance(delete, QPushButton):
            delete.setEnabled(not o.locked)
            delete.setToolTip("Locked: unlock it to delete" if o.locked else "Delete this Object (Ctrl+Z undoes it)")
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

    def _options_button(self, tip: str, slot) -> QPushButton:
        b = QPushButton("⚙")
        b.setFixedWidth(26)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    def _eye_button(self, oid: int) -> QPushButton:
        b = EyeButton()
        b.setObjectName(f"eye_{oid}")
        b.set_shown(oid not in self.hidden)
        b.clicked.connect(lambda _=False, i=oid, eye=b: self._set_shown(i, not eye.shown))
        return b

    def _set_shown(self, oid: int, on: bool) -> None:
        (self.hidden.discard if on else self.hidden.add)(oid)
        eye = self.tree.findChild(EyeButton, f"eye_{oid}")
        if eye is not None:
            eye.set_shown(on)
        later(self, self.visibility_changed)

    def _lock_button(self, oid: int) -> QPushButton:
        b = LockButton()
        b.setObjectName(f"lock_{oid}")
        b.clicked.connect(lambda on, i=oid: later(self, self.lock_requested, [i], on))
        return b

    def _delete_button(self, oid: int) -> QPushButton:
        b = QPushButton("×")
        b.setFixedWidth(26)
        b.setToolTip("Delete this Object (Ctrl+Z undoes it)")
        b.setObjectName(f"delete_{oid}")
        b.clicked.connect(lambda _=False, i=oid: later(self, self.delete_requested, [i]))
        return b

    def _more_button(self, oid: int) -> QPushButton:
        b = QPushButton("···")
        b.setFixedWidth(32)
        b.setObjectName(f"more_{oid}")
        menu = QMenu(b)
        menu.addAction("Rename", lambda i=oid: self._start_rename(i))
        menu.addAction("Duplicate (this image)", lambda i=oid: later(self, self.duplicate_requested, [i]))
        menu.addAction("Duplicate All (every linked mask)",
                       lambda i=oid: later(self, self.duplicate_all_requested, [i]))
        menu.addAction("Lock / Unlock", lambda i=oid: self._toggle_lock(i))
        for label, move in (("Move into (Add, this image)", True), ("Copy into (Add, this image)", False)):
            into = menu.addMenu(label)
            into.aboutToShow.connect(lambda i=oid, m=into, mv=move: self._fill_into_menu(m, i, mv))
        menu.addAction("Remove mask on this image", lambda i=oid: later(self, self.remove_frame_requested, i))
        menu.addSeparator()
        menu.addAction("Delete", lambda i=oid: later(self, self.delete_requested, [i]))
        b.setMenu(menu)
        return b

    def _fill_into_menu(self, menu: QMenu, oid: int, move: bool) -> None:
        """Move / Copy into ▸ every other Object (built when opened, so names are current)."""
        menu.clear()
        others = [o for o in self._objects if o.id != oid]
        for o in others:
            menu.addAction(color_icon(o.color), o.name,
                           lambda i=oid, j=o.id, mv=move: later(self, self.transfer_requested, [i, j], mv))
        if not others:
            menu.addAction("(no other Object)").setEnabled(False)

    def _toggle_lock(self, oid: int) -> None:
        o = next((o for o in self._objects if o.id == oid), None)
        if o is not None:
            later(self, self.lock_requested, [oid], not o.locked)

    def _all_ids(self) -> List[int]:
        return [o.id for o in self._objects]

    def _pair(self) -> List[int]:
        """Copy's source and target: the first and the last selected row."""
        ids = self.selected_ids()
        return [ids[0], ids[-1]] if len(ids) >= 2 else ids

    def listed_ids(self) -> List[int]:
        """The Object rows in list order (what hovering the list steps through)."""
        return [self.tree.topLevelItem(i).data(0, ID_ROLE) for i in range(self.tree.topLevelItemCount())]

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

    def _remember(self, ids: Sequence[int]) -> None:
        if ids:  # an empty selection (the rows left the list) does not forget it
            self.last_selected = list(ids)

    def select_ids(self, ids: Sequence[int]) -> None:
        self._remember(ids)
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
            self.last_selected = []  # cleared on purpose: nothing is remembered
            self.tree.clearSelection()
        return super().eventFilter(obj, event)

    def move_selection(self, ids: Sequence[int], delta: int) -> Optional[int]:
        """The id *delta* rows from the current one among *ids*, wrapping (the top's previous is the bottom)."""
        if not ids:
            return None
        sel = self.selected_ids()
        current = self._editing if self._editing is not None else (sel[0] if sel else None)
        if current not in ids:
            return ids[0] if delta > 0 else ids[-1]
        return ids[(ids.index(current) + delta) % len(ids)]

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
        self._remember(self.selected_ids())
        self._update_buttons()
        later(self, self.selection_changed, self.selected_ids())

    def _update_buttons(self) -> None:
        n = len(self.selected_ids())
        self.merge_btn.setEnabled(n >= 2)
        self.merge_opts_btn.setEnabled(n >= 2)
        self.move_btn.setEnabled(n >= 2)
        self.move_opts_btn.setEnabled(n >= 2)
        self.lock_all_btn.setEnabled(any(not o.locked for o in self._objects))
        self.unlock_all_btn.setEnabled(any(o.locked for o in self._objects))
        self.dup_btn.setEnabled(n >= 1)
        self.dup_all_btn.setEnabled(n >= 1)
        self.del_btn.setEnabled(n >= 1)
