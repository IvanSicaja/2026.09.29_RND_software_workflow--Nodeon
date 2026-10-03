#!/usr/bin/env python3
"""
Nodeon - a plain-.txt editor for box-drawing structure trees.

    python main/main.py [file.txt]

main.py (this file) is the Nodeon application; it needs treemodel.py next to it.

The file on disk is always pure UTF-8 text in this format:

    project-name/
    │
    ├── assets/                       # explanation
    │   ├── 01_media/                 # explanation
    │   └── 02_3d-modeling/           # explanation
    └── README.md                     # explanation
"""
from __future__ import annotations

import os
import re
import sys
import traceback
from typing import Callable, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import (QByteArray, QEvent, QIODevice, QPointF, QRect, QRectF,
                            QSaveFile, QSettings, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (QAction, QColor, QFont, QFontDatabase, QFontMetrics, QFontMetricsF,
                           QIcon, QPainterPath, QPen, QPixmap,
                           QKeySequence, QPainter, QPalette, QPolygonF,
                           QSyntaxHighlighter, QTextCharFormat, QTextCursor,
                           QTextFormat)
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox,
                               QStyle, QStyleOptionToolButton, QStylePainter,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
                               QSpinBox, QTextEdit, QToolBar, QToolButton,
                               QVBoxLayout, QWidget)

import treemodel as tm

APP_NAME = "Nodeon"
APP_VERSION = "1.0.0"
COLLAPSED = 1                      # QTextBlock.userState() flag of a folded branch
NEW_DOCUMENT = "new-project/\n│\n└── "
# Shortcut for "Edit name & explanation". Change it here if you prefer another one.
EDIT_SHORTCUT = "Ctrl+Shift+E"
DEFAULT_FONT_SIZE = 12.0           # editor font size (pt)
UI_VERSION = 2                     # bump to re-apply first-start layout defaults


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def u16len(s: str) -> int:
    """Qt positions count UTF-16 code units, Python counts code points."""
    return len(s.encode("utf-16-le")) // 2


def u16_to_cp(s: str, u: int) -> int:
    return len(s.encode("utf-16-le")[: 2 * u].decode("utf-16-le", errors="ignore"))


def monospace_font(size: float) -> QFont:
    families = set(QFontDatabase.families())
    for fam in ("JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono",
                "Menlo", "SF Mono", "Liberation Mono", "Courier New"):
        if fam in families:
            font = QFont(fam)
            break
    else:
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setPointSizeF(size)
    return font


class Theme:
    def __init__(self, dark: bool) -> None:
        self.dark = dark
        if dark:
            self.bg, self.fg = "#1e1f22", "#c9ccd3"
            self.gutter_bg, self.gutter_fg, self.gutter_cur = "#1e1f22", "#4e525a", "#a9acb4"
            self.guide, self.comment = "#5a5e66", "#7fa864"
            self.folder, self.file = "#6aaef0", "#c9ccd3"
            self.current_line, self.fold = "#26282e", "#9da0a8"
            self.badge_bg, self.badge_fg = "#3a3d44", "#c9ccd3"
            self.selection = "#214283"
        else:
            self.bg, self.fg = "#ffffff", "#1f2328"
            self.gutter_bg, self.gutter_fg, self.gutter_cur = "#f6f7f9", "#a4a9b1", "#3b4048"
            self.guide, self.comment = "#9ca2ab", "#3f7f45"
            self.folder, self.file = "#1d5fbf", "#1f2328"
            self.current_line, self.fold = "#f3f6fb", "#6c717a"
            self.badge_bg, self.badge_fg = "#e5e9f0", "#3b4048"
            self.selection = "#bcd4f5"


def apply_app_palette(app: QApplication, dark: bool) -> None:
    app.setStyle("Fusion")
    if not dark:
        app.setPalette(app.style().standardPalette())
        return
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: "#2b2d30", QPalette.ColorRole.WindowText: "#dfe1e5",
        QPalette.ColorRole.Base: "#1e1f22", QPalette.ColorRole.AlternateBase: "#2b2d30",
        QPalette.ColorRole.ToolTipBase: "#2b2d30", QPalette.ColorRole.ToolTipText: "#dfe1e5",
        QPalette.ColorRole.Text: "#dfe1e5", QPalette.ColorRole.Button: "#2b2d30",
        QPalette.ColorRole.ButtonText: "#dfe1e5", QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Highlight: "#2f65ca", QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#7b7e85", QPalette.ColorRole.Link: "#6aaef0",
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor("#6f737a"))
    app.setPalette(p)


# --------------------------------------------------------------------------- #
# Syntax highlighting
# --------------------------------------------------------------------------- #
class TreeHighlighter(QSyntaxHighlighter):
    _CONN = re.compile(r"├──|└──|\|--|`--|\+--")
    _HASH = re.compile(r"\s#")

    def __init__(self, document, theme: Theme) -> None:
        super().__init__(document)
        self.set_theme(theme, rehighlight=False)

    def set_theme(self, theme: Theme, rehighlight: bool = True) -> None:
        def fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Weight.DemiBold)
            f.setFontItalic(italic)
            return f
        self.f_guide = fmt(theme.guide)
        self.f_comment = fmt(theme.comment)
        self.f_folder = fmt(theme.folder, bold=True)
        self.f_file = fmt(theme.file)
        if rehighlight:
            self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        # Keep the fold flag that the editor stores in the block state.
        self.setCurrentBlockState(self.currentBlock().userState())
        n = len(text)
        i = 0
        while i < n and text[i] in "│| \t\xa0" and not self._CONN.match(text, i):
            i += 1
        m = self._CONN.match(text, i)
        if m:
            i = m.end()
        if i:
            self.setFormat(0, i, self.f_guide)
        rest = text[i:]
        stripped = rest.lstrip()
        if stripped.startswith("#"):
            self.setFormat(i + len(rest) - len(stripped), n, self.f_comment)
            return
        hm = self._HASH.search(rest)
        c = i + hm.start() + 1 if hm else n
        name = text[i:c].strip()
        if name:
            start = text.index(name, i)
            self.setFormat(start, len(name),
                           self.f_folder if name.endswith(("/", "\\")) else self.f_file)
        if hm:
            self.setFormat(c, n - c, self.f_comment)


# --------------------------------------------------------------------------- #
# Editor with fold gutter
# --------------------------------------------------------------------------- #
class FoldGutter(QWidget):
    def __init__(self, editor: "TreeEditor") -> None:
        super().__init__(editor)
        self.editor = editor
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.paint_gutter(event)

    def mousePressEvent(self, event) -> None:
        self.editor.gutter_clicked(event)


class TreeEditor(QPlainTextEdit):
    statusMessage = Signal(str)
    foldsChanged = Signal()
    openFileRequested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.options = tm.FormatOptions()
        self.theme = Theme(False)
        self._model, self._map = tm.parse("")
        self._ranges: dict = {}
        self._parsed_rev = -1
        self._last_block = 0
        self._reserved_keys: Set[int] = set()
        self.context_actions: List[Optional[QAction]] = []

        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.gutter = FoldGutter(self)
        self.highlighter = TreeHighlighter(self.document(), self.theme)
        self.set_font_size(DEFAULT_FONT_SIZE)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.refresh)

        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self.document().contentsChanged.connect(self._timer.start)
        self._update_gutter_width()
        self._highlight_current_line()

    # ---- appearance ------------------------------------------------------
    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(theme.bg))
        pal.setColor(QPalette.ColorRole.Text, QColor(theme.fg))
        pal.setColor(QPalette.ColorRole.Highlight, QColor(theme.selection))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.fg))
        self.setPalette(pal)
        self.highlighter.set_theme(theme)
        self._highlight_current_line()
        self.gutter.update()
        self.viewport().update()

    def set_font_size(self, size: float) -> None:
        size = max(6.0, min(48.0, size))
        font = monospace_font(size)
        self.setFont(font)
        self.gutter.setFont(font)
        self.setTabStopDistance(QFontMetricsF(font).horizontalAdvance(" ") * tm.INDENT)
        self._update_gutter_width()

    def font_size(self) -> float:
        return self.font().pointSizeF()

    def wheelEvent(self, e) -> None:
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step = 1 if e.angleDelta().y() > 0 else -1
            self.set_font_size(self.font_size() + step)
            e.accept()
            return
        super().wheelEvent(e)

    # ---- document ----------------------------------------------------------
    def set_document_text(self, text: str) -> None:
        self.setPlainText(text)
        self.document().clearUndoRedoStacks()
        self.refresh(force=True)
        self.moveCursor(QTextCursor.MoveOperation.Start)
        self.document().setModified(False)

    def reserve_shortcuts(self, actions) -> None:
        """Make sure our shortcuts win over QPlainTextEdit's built-in keys."""
        for a in actions:
            for seq in a.shortcuts():
                if not seq.isEmpty():
                    self._reserved_keys.add(seq[0].toCombined())

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.ShortcutOverride:
            if e.keyCombination().toCombined() in self._reserved_keys:
                e.ignore()
                return True
        return super().event(e)

    # ---- parsing and folding ---------------------------------------------
    def _rev_ok(self) -> bool:
        return self.document().revision() == self._parsed_rev

    def refresh(self, force: bool = False) -> None:
        if force or not self._rev_ok():
            self._model, self._map = tm.parse(self.toPlainText())
            self._ranges = self._map.fold_ranges()
            self._parsed_rev = self.document().revision()
        self._apply_folds()

    def ensure_parsed(self) -> None:
        if not self._rev_ok():
            self._timer.stop()
            self.refresh()

    def _block(self, line: int):
        return self.document().findBlockByNumber(line)

    def collapsed_headers(self) -> Set[int]:
        return {h for h in self._ranges if self._block(h).userState() == COLLAPSED}

    def _apply_folds(self, collapsed: Optional[Set[int]] = None) -> None:
        doc = self.document()
        n = doc.blockCount()
        if collapsed is None:
            collapsed = self.collapsed_headers()
        collapsed = {h for h in collapsed if h in self._ranges and h < n}
        hidden = bytearray(n)
        for h in collapsed:
            s, e = self._ranges[h]
            e = min(e, n - 1)
            if s <= e:
                hidden[s:e + 1] = b"\x01" * (e - s + 1)
        dirty_from, dirty_to = -1, -1
        block, i = doc.begin(), 0
        while block.isValid():
            if i in collapsed:
                if block.userState() != COLLAPSED:
                    block.setUserState(COLLAPSED)
            elif block.userState() == COLLAPSED:
                block.setUserState(-1)
            visible = not hidden[i]
            if block.isVisible() != visible:
                block.setVisible(visible)
                if dirty_from < 0:
                    dirty_from = block.position()
                dirty_to = block.position() + block.length()
            block = block.next()
            i += 1
        if dirty_from >= 0:
            doc.markContentsDirty(dirty_from, dirty_to - dirty_from)
        cur = self.textCursor()
        if not cur.block().isVisible():
            b = cur.block()
            while b.isValid() and not b.isVisible():
                b = b.previous()
            if b.isValid():
                c = QTextCursor(b)
                c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                self.setTextCursor(c)
        self.viewport().update()
        self.gutter.update()
        self.foldsChanged.emit()

    def toggle_fold(self, header: int) -> None:
        self.ensure_parsed()
        if header not in self._ranges:
            return
        cur = self.collapsed_headers()
        cur.symmetric_difference_update({header})
        self._apply_folds(cur)

    def set_branch_recursive(self, header: int, collapse: bool) -> None:
        self.ensure_parsed()
        node = self._map.node_at(header)
        if node is None:
            return
        subtree = {self._map.line_of(n) for n in node.iter_preorder()}
        subtree = {h for h in subtree if h in self._ranges}
        cur = self.collapsed_headers()
        cur = cur | subtree if collapse else cur - subtree
        self._apply_folds(cur)

    def _depth_of(self, header: int) -> int:
        node = self._map.nodes[header]
        return node.depth if node is not None else 0

    def max_level(self) -> int:
        self.ensure_parsed()
        return max((self._depth_of(h) + 1 for h in self._ranges), default=0)

    def current_level(self) -> int:
        """Levels fully shown below the top-level items."""
        vis_collapsed = [self._depth_of(h) for h in self.collapsed_headers()
                         if self._block(h).isVisible()]
        return min(vis_collapsed) if vis_collapsed else self.max_level()

    def show_to_level(self, level: int) -> None:
        self.ensure_parsed()
        self._apply_folds({h for h in self._ranges if self._depth_of(h) >= level})
        self.statusMessage.emit(f"Showing {level} level(s)")

    def collapse_all(self) -> None:
        self.show_to_level(0)
        self.statusMessage.emit("Collapsed everything")

    def expand_all(self) -> None:
        self.ensure_parsed()
        self._apply_folds(set())
        self.statusMessage.emit("Expanded everything")

    def expand_one_level(self) -> None:
        self.ensure_parsed()
        depths = [self._depth_of(h) for h in self.collapsed_headers()
                  if self._block(h).isVisible()]
        if not depths:
            self.statusMessage.emit("Everything is already expanded")
            return
        self.show_to_level(min(depths) + 1)

    def collapse_one_level(self) -> None:
        self.ensure_parsed()
        collapsed = self.collapsed_headers()
        depths = [self._depth_of(h) for h in self._ranges
                  if h not in collapsed and self._block(h).isVisible()]
        if not depths:
            self.statusMessage.emit("Everything is already collapsed")
            return
        self.show_to_level(max(depths))

    def toggle_current(self) -> None:
        self.ensure_parsed()
        node = self._map.node_near(self.textCursor().blockNumber())
        while node is not None and node.parent is not None:
            h = self._map.line_of(node)
            if h in self._ranges:
                self.toggle_fold(h)
                return
            node = node.parent
        self.statusMessage.emit("Nothing to collapse here")

    def _current_header(self) -> Optional[int]:
        self.ensure_parsed()
        node = self._map.node_near(self.textCursor().blockNumber())
        while node is not None and node.parent is not None:
            h = self._map.line_of(node)
            if h in self._ranges:
                return h
            node = node.parent
        return None

    def collapse_branch_fully(self) -> None:
        h = self._current_header()
        if h is not None:
            self.set_branch_recursive(h, True)

    def expand_branch_fully(self) -> None:
        h = self._current_header()
        if h is not None:
            self.set_branch_recursive(h, False)

    def reveal_line(self, line: int) -> bool:
        self.ensure_parsed()
        cur = self.collapsed_headers()
        keep = {h for h in cur if not (self._ranges[h][0] <= line <= self._ranges[h][1])}
        if keep != cur:
            self._apply_folds(keep)
            return True
        return False

    # ---- structural editing ----------------------------------------------
    def _replace_text(self, new: str) -> None:
        old = self.toPlainText()
        if old == new:
            return
        p = len(os.path.commonprefix([old, new]))
        max_s = min(len(old), len(new)) - p
        s = len(os.path.commonprefix([old[::-1], new[::-1]]))
        s = min(s, max_s)
        cur = self.textCursor()        # editor cursor, so Undo returns here
        cur.beginEditBlock()
        cur.setPosition(u16len(old[:p]))
        cur.setPosition(u16len(old[:len(old) - s]), QTextCursor.MoveMode.KeepAnchor)
        cur.insertText(new[p:len(new) - s])
        cur.endEditBlock()
        self.setTextCursor(cur)

    def _cursor_context(self) -> Tuple[int, Optional[tm.Node], Optional[int]]:
        """(line, node, cursor offset inside the node's name)"""
        cur = self.textCursor()
        line = cur.blockNumber()
        node = self._map.node_near(line)
        offset = None
        if node is not None and self._map.kinds[line] == tm.KIND_NODE:
            col = u16_to_cp(cur.block().text(), cur.positionInBlock())
            offset = col - self._map.name_col.get(id(node), 0)
        return line, node, offset

    def run_op(self, op: Callable[[Optional[tm.Node]], Tuple[Optional[tm.Node], str]],
               require_node: bool = True, message: str = "",
               canonical: bool = False) -> bool:
        """Apply a model operation, re-render the text (one undo step) and
        keep folds, scroll position and cursor where the user expects them.

        op(node) returns (focus_node, mode) where mode is
        'keep' | 'start' | 'end' | 'select'.

        canonical=True re-aligns all explanations automatically (Format
        document); otherwise explanations keep the columns the user chose."""
        self.ensure_parsed()
        _, node, offset = self._cursor_context()
        if require_node and node is None:
            self.statusMessage.emit("Put the cursor on a branch line first")
            return False
        collapsed_nodes = [self._map.nodes[h] for h in self.collapsed_headers()]
        vscroll = self.verticalScrollBar().value()
        try:
            focus, mode = op(node)
        except tm.TreeError as ex:
            self.statusMessage.emit(str(ex))
            return False

        text, lm = tm.render(self._model, self.options, preserve_columns=not canonical)
        self._replace_text(text)
        self._model, self._map = lm.doc, lm
        self._ranges = lm.fold_ranges()
        self._parsed_rev = self.document().revision()
        self._timer.stop()

        collapsed = {lm.line_of(n) for n in collapsed_nodes if n is not None}
        collapsed.discard(None)
        if focus is not None:
            a = focus.parent
            while a is not None:
                collapsed.discard(lm.line_of(a))
                a = a.parent
        self._apply_folds(collapsed)
        self.verticalScrollBar().setValue(vscroll)
        if focus is not None and lm.line_of(focus) is not None:
            self._place_cursor(focus, mode, offset)
        self.ensureCursorVisible()
        if message:
            self.statusMessage.emit(message)
        return True

    def _place_cursor(self, node: tm.Node, mode: str, offset: Optional[int]) -> None:
        block = self._block(self._map.line_of(node))
        text = block.text()
        ncol = min(self._map.name_col.get(id(node), 0), len(text))
        end = min(ncol + len(node.name), len(text))
        if mode == "start":
            col = ncol
        elif mode == "keep" and offset is not None:
            col = ncol + max(0, min(offset, len(node.name)))
        else:
            col = end
        cur = QTextCursor(block)
        if mode == "select" and node.name:
            cur.setPosition(block.position() + u16len(text[:ncol]))
            cur.setPosition(block.position() + u16len(text[:end]), QTextCursor.MoveMode.KeepAnchor)
        else:
            cur.setPosition(block.position() + u16len(text[:col]))
        self.setTextCursor(cur)

    # individual operations
    def add_sibling(self) -> None:
        def op(node):
            if node is None:
                return self._new_root()
            return tm.add_sibling_after(node, tm.Node("")), "start"
        self.run_op(op, require_node=not self._model.is_empty(),
                    message="New item added - type its name")

    def add_child(self) -> None:
        def op(node):
            if node is None:
                return self._new_root()
            return tm.add_child(node, tm.Node("")), "start"
        self.run_op(op, require_node=not self._model.is_empty(),
                    message="New sub-item added - type its name")

    def _new_root(self) -> Tuple[tm.Node, str]:
        n = tm.Node("")
        self._model.root.append_child(n)
        return n, "start"

    def delete_branch(self) -> None:
        def op(node):
            parent = node.parent
            idx = node.index
            count = node.descendant_count()
            tm.delete(node)
            if idx < len(parent.children):
                focus = parent.children[idx]
            elif idx > 0:
                focus = parent.children[idx - 1]
            else:
                focus = parent if parent.parent is not None else None
            op.count = count
            return focus, "end"
        op.count = 0
        if self.run_op(op):
            extra = f" and {op.count} sub-item(s)" if op.count else ""
            self.statusMessage.emit(f"Deleted branch{extra} - Ctrl+Z to undo")

    def move_up(self) -> None:
        self.run_op(lambda n: (tm.move_up(n), (n, "keep"))[1])

    def move_down(self) -> None:
        self.run_op(lambda n: (tm.move_down(n), (n, "keep"))[1])

    def indent(self) -> None:
        self.run_op(lambda n: (tm.indent(n), (n, "keep"))[1])

    def outdent(self) -> None:
        self.run_op(lambda n: (tm.outdent(n), (n, "keep"))[1])

    def duplicate(self) -> None:
        self.run_op(lambda n: (tm.duplicate(n), "end"), message="Branch duplicated")

    def format_document(self, quiet: bool = False, canonical: bool = True) -> None:
        """canonical=True: full auto-alignment (Ctrl+Alt+L).
        canonical=False: tidy the tree lines but keep the explanation columns
        (used when saving, so manual alignment is not lost)."""
        self.run_op(lambda n: (n, "keep"), require_node=False,
                    message="" if quiet else "Document formatted", canonical=canonical)

    def shift_explanations(self, direction: int) -> None:
        """Move explanations left (-1) / right (+1): the selected lines, or the
        whole document when nothing is selected. The selection is kept so the
        shortcut can be pressed repeatedly."""
        self.ensure_parsed()
        doc = self.document()
        cur = self.textCursor()
        anchor_b = doc.findBlock(cur.anchor())
        pos_b = doc.findBlock(cur.position())
        anchor = (anchor_b.blockNumber(), cur.anchor() - anchor_b.position())
        pos = (pos_b.blockNumber(), cur.position() - pos_b.position())
        whole = not cur.hasSelection()
        if whole:
            nodes = [n for n in self._model.iter_nodes() if n.comment]
        else:
            first, last = sorted((anchor[0], pos[0]))
            # A selection ending at column 0 of a line does not include that line.
            if last > first and (pos if pos[0] == last else anchor)[1] == 0:
                last -= 1
            seen: Set[int] = set()
            nodes = []
            for line in range(first, last + 1):
                n = self._map.node_at(line)
                if n is not None and n.comment and id(n) not in seen:
                    seen.add(id(n))
                    nodes.append(n)
        gap = self.options.comment_gap
        result = {}

        def op(_node):
            result["col"] = tm.shift_comments(nodes, direction, gap)
            return None, "keep"

        if not self.run_op(op, require_node=False):
            return
        # Restore the cursor/selection on the same lines.
        new = QTextCursor(doc)

        def to_pos(line_col: Tuple[int, int]) -> int:
            b = doc.findBlockByNumber(min(line_col[0], doc.blockCount() - 1))
            return b.position() + min(line_col[1], b.length() - 1)
        new.setPosition(to_pos(anchor))
        new.setPosition(to_pos(pos), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(new)
        scope = "whole document" if whole else f"{len(nodes)} explanation(s)"
        side = "right" if direction > 0 else "left"
        self.statusMessage.emit(f"Explanations moved {side} ({scope}) - column {result['col'] + 1}")

    def edit_current(self, focus_explanation: bool = False) -> None:
        self.ensure_parsed()
        _, node, _ = self._cursor_context()
        if node is None:
            self.statusMessage.emit("Put the cursor on a branch line first")
            return
        dlg = EditNodeDialog(self, node, self.font(), focus_explanation or not node.children)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, comment = dlg.values()
        target = node

        def op(n):
            target.name, target.comment = name, comment
            return target, "end"
        self.run_op(op, require_node=False, message="Branch updated")

    # ---- keyboard ---------------------------------------------------------
    def keyPressEvent(self, e) -> None:
        key = e.key()
        mods = e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        plain = mods == Qt.KeyboardModifier.NoModifier
        has_sel = self.textCursor().hasSelection()
        if plain and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not has_sel:
            if self._smart_enter():
                return
        elif plain and key == Qt.Key.Key_Tab:
            if self._on_branch_line():
                self.indent()
            else:
                self.insertPlainText(" " * tm.INDENT)
            return
        elif key == Qt.Key.Key_Backtab:
            if self._on_branch_line():
                self.outdent()
            return
        elif plain and key == Qt.Key.Key_Backspace and not has_sel:
            if self._smart_backspace():
                return
        elif plain and key == Qt.Key.Key_Delete and not has_sel:
            cur = self.textCursor()
            nxt = cur.block().next()
            if cur.atBlockEnd() and nxt.isValid() and not nxt.isVisible():
                self.reveal_line(nxt.blockNumber())
                self.statusMessage.emit("Expanded the folded branch first")
                return
        super().keyPressEvent(e)

    def _on_branch_line(self) -> bool:
        self.ensure_parsed()
        return self._map.node_at(self.textCursor().blockNumber()) is not None

    def _smart_enter(self) -> bool:
        self.ensure_parsed()
        line, node, offset = self._cursor_context()
        if node is None or offset is None or self._map.kinds[line] != tm.KIND_NODE:
            return False
        name_len = len(node.name)
        header = self._map.line_of(node)

        if not node.name and not node.children and not node.comment:
            if node.parent is not None and node.parent.parent is not None:
                self.run_op(lambda n: (tm.outdent(n), (n, "start"))[1])
                return True
        if offset <= 0 and node.name:
            self.run_op(lambda n: (tm.add_sibling_before(n, tm.Node("")), (n, "start"))[1])
            return True
        if 0 < offset < name_len:
            left, right = node.name[:offset].rstrip(), node.name[offset:].lstrip()

            def split(n):
                n.name = left
                return tm.add_sibling_after(n, tm.Node(right)), "start"
            self.run_op(split)
            return True
        expanded_with_kids = node.children and header not in self.collapsed_headers()
        if node.depth == 0 or expanded_with_kids:
            self.run_op(lambda n: (tm.add_child(n, tm.Node(""), first=True), "start"))
        else:
            self.run_op(lambda n: (tm.add_sibling_after(n, tm.Node("")), "start"))
        return True

    def _smart_backspace(self) -> bool:
        self.ensure_parsed()
        cur = self.textCursor()
        prev = cur.block().previous()
        if cur.atBlockStart() and prev.isValid() and not prev.isVisible():
            self.reveal_line(prev.blockNumber())
            self.statusMessage.emit("Expanded the folded branch first")
            return True
        line, node, offset = self._cursor_context()
        if (node is not None and offset is not None and offset <= 0
                and not node.name and not node.children and not node.comment
                and node.parent is not None):
            def op(n):
                focus = tm.previous_in_order(self._model, n)
                tm.delete(n)
                return focus, "end"
            self.run_op(op)
            return True
        return False

    # ---- navigation over hidden lines --------------------------------------
    def _on_cursor_moved(self) -> None:
        cur = self.textCursor()
        b = cur.block()
        if not b.isVisible():
            forward = b.blockNumber() > self._last_block
            nb = b
            if forward:
                while nb.isValid() and not nb.isVisible():
                    nb = nb.next()
            if not forward or not nb.isValid():
                nb = b
                while nb.isValid() and not nb.isVisible():
                    nb = nb.previous()
            if nb.isValid():
                mode = (QTextCursor.MoveMode.KeepAnchor if cur.hasSelection()
                        else QTextCursor.MoveMode.MoveAnchor)
                cur.setPosition(nb.position(), mode)
                self.setTextCursor(cur)
                return
        self._last_block = b.blockNumber()
        self._highlight_current_line()
        self.gutter.update()

    def _highlight_current_line(self) -> None:
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(self.theme.current_line))
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel])

    # ---- gutter -------------------------------------------------------------
    def _fold_w(self) -> int:
        return max(14, int(self.fontMetrics().height() * 0.95))

    def gutter_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return 10 + self.fontMetrics().horizontalAdvance("9") * digits + 6 + self._fold_w()

    def _update_gutter_width(self, *_args) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def _on_update_request(self, rect, dy) -> None:
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._update_gutter_width()

    def _painted_blocks(self, top: float, bottom: float):
        block = self.firstVisibleBlock()
        offset = self.contentOffset()
        can_skip = self._rev_ok()
        while block.isValid():
            if block.isVisible():
                geo = self.blockBoundingGeometry(block).translated(offset)
                if geo.top() > bottom:
                    break
                if geo.bottom() >= top:
                    yield block, geo
                n = block.blockNumber()
                if can_skip and n in self._ranges and block.userState() == COLLAPSED:
                    block = self._block(self._ranges[n][1] + 1)
                    continue
            block = block.next()

    def paint_gutter(self, event) -> None:
        p = QPainter(self.gutter)
        p.fillRect(event.rect(), QColor(self.theme.gutter_bg))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fm = self.fontMetrics()
        line_h = fm.height()
        fw = self._fold_w()
        w = self.gutter.width()
        cur_line = self.textCursor().blockNumber()
        ranges = self._ranges if self._rev_ok() else {}
        for block, geo in self._painted_blocks(event.rect().top(), event.rect().bottom()):
            n = block.blockNumber()
            top = int(geo.top())
            p.setPen(QColor(self.theme.gutter_cur if n == cur_line else self.theme.gutter_fg))
            p.drawText(0, top, w - fw - 8, line_h,
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(n + 1))
            if n in ranges:
                self._draw_arrow(p, QRectF(w - fw - 2, top, fw, line_h),
                                 block.userState() == COLLAPSED)
        p.end()

    def _draw_arrow(self, p: QPainter, r: QRectF, collapsed: bool) -> None:
        s = min(r.width(), r.height()) * 0.28
        c = r.center()
        if collapsed:
            pts = [QPointF(c.x() - s * 0.6, c.y() - s), QPointF(c.x() - s * 0.6, c.y() + s),
                   QPointF(c.x() + s * 0.8, c.y())]
        else:
            pts = [QPointF(c.x() - s, c.y() - s * 0.6), QPointF(c.x() + s, c.y() - s * 0.6),
                   QPointF(c.x(), c.y() + s * 0.8)]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.theme.fold))
        p.drawPolygon(QPolygonF(pts))

    def gutter_clicked(self, e) -> None:
        self.ensure_parsed()
        y = e.position().y()
        for block, geo in self._painted_blocks(y, y):
            if geo.top() <= y <= geo.bottom():
                n = block.blockNumber()
                if n in self._ranges:
                    if e.modifiers() & Qt.KeyboardModifier.AltModifier:
                        self.set_branch_recursive(n, block.userState() != COLLAPSED)
                    else:
                        self.toggle_fold(n)
                else:
                    self.setTextCursor(QTextCursor(block))
                return

    # ---- "⋯ N items" badge after folded branches ---------------------------
    def _badge(self, block, geo: QRectF) -> Tuple[QRectF, str]:
        node = self._map.nodes[block.blockNumber()]
        count = node.descendant_count() if node is not None else 0
        label = f"⋯ {count} item{'s' if count != 1 else ''}"
        fm = QFontMetricsF(self.font())
        x = (geo.left() + self.document().documentMargin()
             + fm.horizontalAdvance(block.text()) + fm.horizontalAdvance("  "))
        rect = QRectF(x, geo.top() + 1, fm.horizontalAdvance(label) + 12, fm.height() - 2)
        return rect, label

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        if not self._ranges or not self._rev_ok():
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for block, geo in self._painted_blocks(e.rect().top(), e.rect().bottom()):
            n = block.blockNumber()
            if n in self._ranges and block.userState() == COLLAPSED:
                rect, label = self._badge(block, geo)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(self.theme.badge_bg))
                p.drawRoundedRect(rect, 4, 4)
                p.setPen(QColor(self.theme.badge_fg))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        p.end()

    def _badge_hit(self, pos: QPointF) -> Optional[int]:
        if not self._rev_ok():
            return None
        block = self.cursorForPosition(pos.toPoint()).block()
        n = block.blockNumber()
        if n in self._ranges and block.userState() == COLLAPSED:
            geo = self.blockBoundingGeometry(block).translated(self.contentOffset())
            if self._badge(block, geo)[0].contains(pos):
                return n
        return None

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            hit = self._badge_hit(e.position())
            if hit is not None:
                self.toggle_fold(hit)
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        super().mouseMoveEvent(e)
        if not e.buttons():
            shape = (Qt.CursorShape.PointingHandCursor if self._badge_hit(e.position()) is not None
                     else Qt.CursorShape.IBeamCursor)
            self.viewport().setCursor(shape)

    # ---- context menu, drag & drop ----------------------------------------
    def contextMenuEvent(self, e) -> None:
        if not self.textCursor().hasSelection():
            self.setTextCursor(self.cursorForPosition(e.pos()))
        menu = self.createStandardContextMenu()
        first = menu.actions()[0] if menu.actions() else None
        for a in self.context_actions:
            if a is None:
                menu.insertSeparator(first)
            else:
                menu.insertAction(first, a)
        menu.insertSeparator(first)
        menu.exec(e.globalPos())

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            for url in e.mimeData().urls():
                if url.isLocalFile():
                    self.openFileRequested.emit(url.toLocalFile())
                    break
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


# --------------------------------------------------------------------------- #
# Toolbar icons (drawn as vectors, so they are sharp at any size and theme)
# --------------------------------------------------------------------------- #
def _draw_icon(p: QPainter, kind: str) -> None:
    """Draw a minimal line icon in a 24x24 coordinate space."""
    def line(*pts) -> None:
        path = QPainterPath(QPointF(*pts[0]))
        for pt in pts[1:]:
            path.lineTo(QPointF(*pt))
        p.drawPath(path)

    def chevron(y: float, up: bool) -> None:
        d = -2.5 if up else 2.5
        line((7, y - d), (12, y + d), (17, y - d))

    def plus(cx: float, cy: float, r: float) -> None:
        line((cx - r, cy), (cx + r, cy))
        line((cx, cy - r), (cx, cy + r))

    if kind == "open":
        line((3, 18.5), (3, 5.5), (9.5, 5.5), (11.5, 7.5), (19, 7.5), (19, 10))
        line((3, 18.5), (6, 11), (21.5, 11), (18.5, 18.5), (3, 18.5))
    elif kind == "save":
        line((12, 3.5), (12, 14.5))
        line((7.5, 10), (12, 14.5), (16.5, 10))
        line((4, 15), (4, 20), (20, 20), (20, 15))
    elif kind in ("collapse_all", "collapse_level", "expand_all", "expand_level"):
        line((5, 4.5), (19, 4.5))                       # the level we fold into
        up = kind.startswith("collapse")
        if kind.endswith("_all"):
            chevron(11.5, up)
            chevron(17.5, up)
        else:
            chevron(14, up)
    elif kind == "add_item":
        line((5, 3), (5, 21))
        line((5, 12), (10, 12))
        plus(16.5, 12, 4)
    elif kind == "add_child":
        p.drawEllipse(QPointF(6, 5), 2.2, 2.2)          # parent item
        line((6, 7.5), (6, 15), (11, 15))               # branch into it
        plus(17, 15, 3.5)
    elif kind == "edit":
        line((15, 4), (20, 9), (9, 20), (4, 20), (4, 15), (15, 4))
        line((12.5, 6.5), (17.5, 11.5))
    elif kind == "delete":
        line((4, 6.5), (20, 6.5))
        line((9, 6.5), (9, 3.5), (15, 3.5), (15, 6.5))
        line((6, 6.5), (7, 20.5), (17, 20.5), (18, 6.5))
        line((10, 10), (10, 17))
        line((14, 10), (14, 17))
    elif kind in ("up", "down", "left", "right"):
        tail, head, wing1, wing2 = {
            "up": ((12, 20), (12, 4), (6, 10), (18, 10)),
            "down": ((12, 4), (12, 20), (6, 14), (18, 14)),
            "left": ((20, 12), (4, 12), (10, 6), (10, 18)),
            "right": ((4, 12), (20, 12), (14, 6), (14, 18)),
        }[kind]
        line(tail, head)
        line(wing1, head, wing2)
    elif kind in ("expl_left", "expl_right"):           # explanation column + arrow
        x0 = 13 if kind == "expl_left" else 3
        for y in (6, 12, 18):
            line((x0, y), (x0 + 8, y))
        if kind == "expl_left":
            line((10, 12), (3, 12))
            line((6, 8.5), (2.5, 12), (6, 15.5))
        else:
            line((14, 12), (21, 12))
            line((18, 8.5), (21.5, 12), (18, 15.5))
    elif kind == "format":                              # names + aligned explanations
        for y, x_end in ((6, 9), (12, 12), (18, 7)):
            line((4, y), (x_end, y))
            line((15, y), (20, y))


def make_icon(kind: str, color: str) -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size / 24.0, size / 24.0)
        pen = QPen(QColor(color), 1.8 if size >= 24 else 2.1)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        _draw_icon(p, kind)
        p.end()
        icon.addPixmap(pm)
    return icon


def shortcut_text(action: QAction) -> str:
    seqs = action.shortcuts()
    if not seqs:
        return ""
    text = seqs[0].toString(QKeySequence.SequenceFormat.NativeText)
    for a, b in (("Return", "Enter"), ("Delete", "Del"), ("Up", "↑"),
                 ("Down", "↓"), ("Left", "←"), ("Right", "→")):
        text = text.replace(a, b)
    return text


def _caption_font(base: QFont) -> QFont:
    f = QFont(base)
    f.setPointSizeF(max(6.5, base.pointSizeF() - 1.5))
    return f


def _captioned(widget: QWidget, caption: str) -> QWidget:
    """A toolbar widget with a small shortcut caption underneath."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(6, 2, 6, 2)
    lay.setSpacing(3)
    lay.addStretch()
    lay.addWidget(widget)
    label = QLabel(caption)
    label.setFont(_caption_font(label.font()))
    label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
    lay.addWidget(label)
    return box


class ActionButton(QToolButton):
    """Toolbar button: icon, name, and its keyboard shortcut underneath."""
    ICON = 24

    def __init__(self, action: QAction, label: str) -> None:
        super().__init__()
        self._label = label
        self.setDefaultAction(action)
        self.setText(label)
        self.setAutoRaise(True)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        action.changed.connect(self._on_action_changed)

    def _on_action_changed(self) -> None:
        self.setText(self._label)        # keep our short label, not the menu text
        self.updateGeometry()
        self.update()

    def _keys(self) -> str:
        return shortcut_text(self.defaultAction())

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        sm = QFontMetrics(_caption_font(self.font()))
        w = max(fm.horizontalAdvance(self._label), sm.horizontalAdvance(self._keys()),
                self.ICON) + 18
        h = 5 + self.ICON + 4 + fm.height() + 1 + sm.height() + 5
        return QSize(max(w, 58), h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event) -> None:
        p = QStylePainter(self)
        opt = QStyleOptionToolButton()
        self.initStyleOption(opt)
        opt.text = ""
        opt.icon = QIcon()
        p.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, opt)  # hover/press panel

        enabled = self.isEnabled()
        group = QPalette.ColorGroup.Active if enabled else QPalette.ColorGroup.Disabled
        pal = self.palette()
        r = self.rect()
        y = 5
        self.defaultAction().icon().paint(
            p, QRect((r.width() - self.ICON) // 2, y, self.ICON, self.ICON),
            Qt.AlignmentFlag.AlignCenter,
            QIcon.Mode.Normal if enabled else QIcon.Mode.Disabled)
        y += self.ICON + 4
        fm = QFontMetrics(self.font())
        p.setFont(self.font())
        p.setPen(pal.color(group, QPalette.ColorRole.ButtonText))
        p.drawText(QRect(0, y, r.width(), fm.height()), Qt.AlignmentFlag.AlignHCenter, self._label)
        y += fm.height() + 1
        small = _caption_font(self.font())
        p.setFont(small)
        p.setPen(pal.color(group, QPalette.ColorRole.PlaceholderText))
        p.drawText(QRect(0, y, r.width(), QFontMetrics(small).height()),
                   Qt.AlignmentFlag.AlignHCenter, self._keys())


# --------------------------------------------------------------------------- #
# Dialogs and find bar
# --------------------------------------------------------------------------- #
class EditNodeDialog(QDialog):
    def __init__(self, parent: QWidget, node: tm.Node, font: QFont,
                 focus_explanation: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit branch")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        path = QLabel(" › ".join(p or "(empty)" for p in node.path()))
        path.setWordWrap(True)
        path.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(path)
        form = QFormLayout()
        self.name = QLineEdit(node.name)
        self.name.setFont(font)
        self.name.setPlaceholderText("folder/ or file.ext")
        self.explanation = QPlainTextEdit("\n".join(node.comment))
        self.explanation.setFont(font)
        self.explanation.setPlaceholderText(
            "What is this for? Each line becomes a '#' line in the file.")
        self.explanation.setMinimumHeight(140)
        form.addRow("Name", self.name)
        form.addRow("Explanation", self.explanation)
        lay.addLayout(form)
        hint = QLabel("Ctrl+Enter to save")
        hint.setStyleSheet("color: palette(placeholder-text);")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(hint)
        row.addStretch()
        row.addWidget(buttons)
        lay.addLayout(row)
        save = QAction(self)
        save.setShortcuts([QKeySequence("Ctrl+Return"), QKeySequence("Ctrl+Enter")])
        save.triggered.connect(self.accept)
        self.addAction(save)
        if focus_explanation:
            self.explanation.setFocus()
            self.explanation.moveCursor(QTextCursor.MoveOperation.End)
        else:
            self.name.setFocus()
            self.name.selectAll()

    def values(self) -> Tuple[str, List[str]]:
        name = " ".join(self.name.text().split())
        lines = [l.rstrip() for l in self.explanation.toPlainText().split("\n")]
        while lines and not lines[-1]:
            lines.pop()
        while lines and not lines[0]:
            lines.pop(0)
        return name, lines

    def accept(self) -> None:
        name, _ = self.values()
        if name.startswith("#") or re.search(r"\s#", name):
            QMessageBox.warning(self, "Invalid name",
                                "A name can't start with '#' or contain ' #' - "
                                "that marks the start of the explanation.\n"
                                "Put that text in the Explanation box instead.")
            return
        super().accept()


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget, opts: tm.FormatOptions, format_on_save: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        form = QFormLayout(self)
        self.min_col = QSpinBox()
        self.min_col.setRange(0, 300)
        self.min_col.setValue(opts.min_comment_column)
        self.gap = QSpinBox()
        self.gap.setRange(1, 40)
        self.gap.setValue(opts.comment_gap)
        self.on_save = QCheckBox("Tidy the tree lines every time it is saved (explanation columns are kept)")
        self.on_save.setChecked(format_on_save)
        form.addRow("Explanation '#' column (minimum)", self.min_col)
        form.addRow("Spaces between longest name and '#'", self.gap)
        form.addRow(self.on_save)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class FindBar(QWidget):
    def __init__(self, editor: TreeEditor) -> None:
        super().__init__()
        self.editor = editor
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        self.field = QLineEdit()
        self.field.setPlaceholderText("Find in tree (folded branches open automatically)")
        self.field.returnPressed.connect(self.find_next)
        self.case = QCheckBox("Match case")
        self.info = QLabel()
        prev_btn, next_btn, close_btn = QToolButton(), QToolButton(), QToolButton()
        prev_btn.setText("▲")
        prev_btn.setToolTip("Previous (Shift+F3)")
        next_btn.setText("▼")
        next_btn.setToolTip("Next (F3)")
        close_btn.setText("✕")
        close_btn.setToolTip("Close (Esc)")
        prev_btn.clicked.connect(self.find_prev)
        next_btn.clicked.connect(self.find_next)
        close_btn.clicked.connect(self.close_bar)
        for w in (self.field, prev_btn, next_btn, self.case, self.info):
            lay.addWidget(w)
        lay.addStretch()
        lay.addWidget(close_btn)
        self.hide()

    def open_bar(self) -> None:
        sel = self.editor.textCursor().selectedText()
        if sel and "\u2029" not in sel:
            self.field.setText(sel)
        self.show()
        self.field.setFocus()
        self.field.selectAll()

    def close_bar(self) -> None:
        self.hide()
        self.editor.setFocus()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.close_bar()
        else:
            super().keyPressEvent(e)

    def find_next(self) -> None:
        self._find(backward=False)

    def find_prev(self) -> None:
        self._find(backward=True)

    def _find(self, backward: bool) -> None:
        text = self.field.text()
        if not text:
            if self.isHidden():
                self.open_bar()
            return
        from PySide6.QtGui import QTextDocument
        flags = QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        if self.case.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        doc = self.editor.document()
        found = doc.find(text, self.editor.textCursor(), flags)
        if found.isNull():
            start = QTextCursor(doc)
            if backward:
                start.movePosition(QTextCursor.MoveOperation.End)
            found = doc.find(text, start, flags)
            self.info.setText("Wrapped around" if not found.isNull() else "")
        else:
            self.info.setText("")
        if found.isNull():
            self.info.setText("Not found")
            return
        self.editor.reveal_line(found.blockNumber())
        self.editor.setTextCursor(found)
        self.editor.centerCursor()


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    MAX_RECENT = 10

    def __init__(self, path: Optional[str] = None) -> None:
        super().__init__()
        self.settings = QSettings("Nodeon", "Nodeon")
        _migrate_old_settings(self.settings)
        self.path: Optional[str] = None
        self.newline = "\n"

        self.editor = TreeEditor()
        self.findbar = FindBar(self.editor)
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.editor)
        lay.addWidget(self.findbar)
        self.setCentralWidget(central)

        self.editor.options = tm.FormatOptions(
            int(self.settings.value("min_comment_column", 34)),
            int(self.settings.value("comment_gap", 3)))
        self.format_on_save = self.settings.value("format_on_save", True, type=bool)
        ui_version = int(self.settings.value("ui_version", 0) or 0)
        font_size = float(self.settings.value("font_size", DEFAULT_FONT_SIZE))
        if ui_version < UI_VERSION and font_size < DEFAULT_FONT_SIZE:
            font_size = DEFAULT_FONT_SIZE          # one-time upgrade to the larger default
        self.editor.set_font_size(font_size)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()

        self.editor.statusMessage.connect(lambda m: self.statusBar().showMessage(m, 4000))
        self.editor.foldsChanged.connect(self._update_level_display)
        self.editor.cursorPositionChanged.connect(self._update_position)
        self.editor.openFileRequested.connect(self._open_dropped)
        self.editor.document().modificationChanged.connect(self.setWindowModified)

        dark = self.settings.value("dark", None)
        if dark is None:
            dark = QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        self._set_dark(dark in (True, "true"), save=False)

        geo = self.settings.value("geometry")
        self._needs_default_geometry = geo is None or ui_version < UI_VERSION
        if not self._needs_default_geometry:
            self.restoreGeometry(geo)
        else:
            avail = QApplication.primaryScreen().availableGeometry()
            self.resize(max(avail.width() // 2, 400), avail.height())
        self.settings.setValue("ui_version", UI_VERSION)

        if not (path and self.load_file(path)):
            self.new_file(ask=False)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self._needs_default_geometry:
            self._needs_default_geometry = False
            QTimer.singleShot(0, self._apply_default_geometry)

    def _apply_default_geometry(self) -> None:
        """First start: full screen height, half the screen width, centered."""
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry()
        frame = self.frameGeometry()
        extra_w = max(0, frame.width() - self.width())
        extra_h = max(0, frame.height() - self.height())
        w = avail.width() // 2
        self.resize(max(w - extra_w, self.minimumSizeHint().width()), avail.height() - extra_h)
        self.move(avail.x() + (avail.width() - self.frameGeometry().width()) // 2, avail.y())

    # ---- actions ---------------------------------------------------------
    def _act(self, text: str, slot, shortcut=None, tip: str = "") -> QAction:
        a = QAction(text, self)
        if shortcut:
            seqs = shortcut if isinstance(shortcut, (list, tuple)) else [shortcut]
            unique: List[QKeySequence] = []
            for s in seqs:
                for k in QKeySequence.keyBindings(s) if isinstance(s, QKeySequence.StandardKey) \
                        else [QKeySequence(s)]:
                    if k not in unique:
                        unique.append(k)
            a.setShortcuts(unique)
        keys = ", ".join(s.toString(QKeySequence.SequenceFormat.NativeText) for s in a.shortcuts())
        a.setToolTip(f"{tip or text.replace('&', '')}" + (f"  ({keys})" if keys else ""))
        a.setStatusTip(tip or text.replace("&", ""))
        a.triggered.connect(slot)
        self.addAction(a)
        return a

    def _build_actions(self) -> None:
        e = self.editor
        A = self._act
        self.a_new = A("&New", lambda: self.new_file(), QKeySequence.StandardKey.New)
        self.a_open = A("&Open…", self.open_dialog, QKeySequence.StandardKey.Open)
        self.a_save = A("&Save", self.save, QKeySequence.StandardKey.Save)
        self.a_save_as = A("Save &As…", self.save_as, "Ctrl+Shift+S")
        self.a_quit = A("E&xit", self.close, "Ctrl+Q")

        self.a_undo = A("&Undo", e.undo, QKeySequence.StandardKey.Undo)
        self.a_redo = A("&Redo", e.redo, [QKeySequence.StandardKey.Redo, "Ctrl+Y"])
        self.a_find = A("&Find…", self.findbar.open_bar, QKeySequence.StandardKey.Find)
        self.a_find_next = A("Find &next", self.findbar.find_next, "F3")
        self.a_find_prev = A("Find &previous", self.findbar.find_prev, "Shift+F3")

        self.a_collapse_all = A("Collapse all", e.collapse_all, "Alt+1",
                                "Collapse every branch")
        self.a_collapse_level = A("Collapse one level", e.collapse_one_level, "Alt+2",
                                  "Hide the deepest visible level in the whole document")
        self.a_expand_level = A("Expand one level", e.expand_one_level, "Alt+3",
                                "Show one more level in the whole document")
        self.a_expand_all = A("Expand all", e.expand_all, "Alt+4", "Expand every branch")
        self.a_toggle = A("Toggle branch", e.toggle_current, "Ctrl+.",
                          "Collapse / expand the branch at the cursor")
        self.a_collapse_branch = A("Collapse branch fully", e.collapse_branch_fully,
                                   "Ctrl+Shift+.", "Collapse this branch and everything inside it")
        self.a_expand_branch = A("Expand branch fully", e.expand_branch_fully, "Ctrl+Shift+,",
                                 "Expand this branch and everything inside it")
        self.level_actions = []
        for n in range(1, 10):
            self.level_actions.append(
                A(f"Show {n} level{'s' if n > 1 else ''}",
                  lambda _=False, n=n: e.show_to_level(n), f"Ctrl+{n}"))

        self.a_add_sibling = A("Add item below", e.add_sibling,
                               ["Ctrl+Return", "Ctrl+Enter"], "New item on the same level")
        self.a_add_child = A("Add sub-item", e.add_child,
                             ["Ctrl+Shift+Return", "Ctrl+Shift+Enter"], "New item inside this one")
        self.a_edit = A("Edit name && explanation…", lambda: e.edit_current(), EDIT_SHORTCUT,
                        "Explanation – add or edit the explanation (and the name)")
        self.a_explain = A("Edit explanation…", lambda: e.edit_current(True), "Ctrl+E")
        self.a_duplicate = A("Duplicate branch", e.duplicate, "Ctrl+D")
        self.a_delete = A("Delete branch", e.delete_branch, "Ctrl+Shift+Delete",
                          "Delete the item and everything inside it")
        self.a_up = A("Move up", e.move_up, "Alt+Shift+Up")
        self.a_down = A("Move down", e.move_down, "Alt+Shift+Down")
        self.a_left = A("Move left (outdent)", e.outdent, "Alt+Shift+Left",
                        "One level up in the tree (also Shift+Tab)")
        self.a_right = A("Move right (indent)", e.indent, "Alt+Shift+Right",
                         "Into the item above (also Tab)")
        self.a_format = A("Format document", lambda: e.format_document(), "Ctrl+Alt+L",
                          "Re-draw all lines and align every explanation")
        self.a_expl_left = A("Move explanations left", lambda: e.shift_explanations(-1),
                             "Alt+Left", "Move explanations (#) left - selected lines, or the "
                             "whole document if nothing is selected")
        self.a_expl_right = A("Move explanations right", lambda: e.shift_explanations(1),
                              "Alt+Right", "Move explanations (#) right - selected lines, or the "
                              "whole document if nothing is selected")

        self.a_zoom_in = A("Zoom in", lambda: self._zoom(1), ["Ctrl+=", "Ctrl++"])
        self.a_zoom_out = A("Zoom out", lambda: self._zoom(-1), "Ctrl+-")
        self.a_zoom_reset = A("Reset zoom", lambda: self._zoom(0), "Ctrl+0")
        self.a_dark = A("Dark theme", lambda c: self._set_dark(c))
        self.a_dark.setCheckable(True)
        self.a_settings = A("Settings…", self.open_settings)
        self.a_shortcuts = A("Keyboard shortcuts", self.show_shortcuts, "F1")
        self.a_about = A("About", self.show_about)

        e.reserve_shortcuts(self.actions())
        e.context_actions = [self.a_edit, self.a_explain, None, self.a_add_sibling,
                             self.a_add_child, self.a_duplicate, self.a_delete, None,
                             self.a_up, self.a_down, self.a_left, self.a_right, None,
                             self.a_toggle, self.a_collapse_branch, self.a_expand_branch]

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")
        m.addActions([self.a_new, self.a_open])
        self.recent_menu = m.addMenu("Open &recent")
        m.addSeparator()
        m.addActions([self.a_save, self.a_save_as])
        m.addSeparator()
        m.addAction(self.a_quit)
        self._rebuild_recent()

        m = mb.addMenu("&Edit")
        m.addActions([self.a_undo, self.a_redo])
        m.addSeparator()
        m.addActions([self.a_find, self.a_find_next, self.a_find_prev])

        m = mb.addMenu("&Tree")
        m.addActions([self.a_add_sibling, self.a_add_child, self.a_edit, self.a_explain,
                      self.a_duplicate, self.a_delete])
        m.addSeparator()
        m.addActions([self.a_up, self.a_down, self.a_left, self.a_right])
        m.addSeparator()
        m.addActions([self.a_expl_left, self.a_expl_right, self.a_format])

        m = mb.addMenu("&View")
        m.addActions([self.a_collapse_all, self.a_collapse_level, self.a_expand_level,
                      self.a_expand_all])
        lv = m.addMenu("Show levels")
        lv.addActions(self.level_actions)
        m.addSeparator()
        m.addActions([self.a_toggle, self.a_collapse_branch, self.a_expand_branch])
        m.addSeparator()
        m.addActions([self.a_zoom_in, self.a_zoom_out, self.a_zoom_reset])
        m.addSeparator()
        m.addActions([self.a_dark, self.a_settings])

        m = mb.addMenu("&Help")
        m.addActions([self.a_shortcuts, self.a_about])

    def _build_toolbar(self) -> None:
        # Row 1: file + folding of the whole document
        tb = QToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        self.addToolBar(tb)
        self._add_tool_buttons(tb, [
            (self.a_open, "Open"), (self.a_save, "Save"), None,
            (self.a_collapse_all, "Collapse all"), (self.a_collapse_level, "Collapse level"),
            (self.a_expand_level, "Expand level"), (self.a_expand_all, "Expand all"), None,
        ])
        self.level_spin = QSpinBox()
        self.level_spin.setPrefix("Levels: ")
        self.level_spin.setRange(0, 99)
        self.level_spin.setToolTip("How many levels of branches to show (Ctrl+1 … Ctrl+9)")
        self.level_spin.valueChanged.connect(self._level_spin_changed)
        tb.addWidget(_captioned(self.level_spin, "Ctrl+1 … 9"))
        tb.addSeparator()
        self._add_tool_buttons(tb, [
            (self.a_expl_left, "Explanations ←"), (self.a_expl_right, "Explanations →"),
        ])

        # Row 2: editing branches
        self.addToolBarBreak()
        tb2 = QToolBar("Tree")
        tb2.setObjectName("tree_toolbar")
        tb2.setMovable(False)
        self.addToolBar(tb2)
        self._add_tool_buttons(tb2, [
            (self.a_add_sibling, "Add item"), (self.a_add_child, "Add sub-item"),
            (self.a_edit, "Explanation"), None,
            (self.a_up, "Move up"), (self.a_down, "Move down"),
            (self.a_left, "Move left"), (self.a_right, "Move right"), None,
            (self.a_format, "Format"), (self.a_delete, "Delete"),
        ])

    def _add_tool_buttons(self, tb: QToolBar, items) -> None:
        for item in items:
            if item is None:
                tb.addSeparator()
                continue
            action, label = item
            tb.addWidget(ActionButton(action, label))

    def _refresh_icons(self, dark: bool) -> None:
        color = "#c9ccd3" if dark else "#3b4048"
        danger = "#e5737c" if dark else "#c0392b"
        for action, kind in (
                (self.a_open, "open"), (self.a_save, "save"),
                (self.a_collapse_all, "collapse_all"), (self.a_collapse_level, "collapse_level"),
                (self.a_expand_level, "expand_level"), (self.a_expand_all, "expand_all"),
                (self.a_add_sibling, "add_item"), (self.a_add_child, "add_child"),
                (self.a_edit, "edit"), (self.a_delete, "delete"),
                (self.a_up, "up"), (self.a_down, "down"), (self.a_left, "left"),
                (self.a_right, "right"), (self.a_format, "format"),
                (self.a_expl_left, "expl_left"), (self.a_expl_right, "expl_right")):
            action.setIcon(make_icon(kind, danger if kind == "delete" else color))

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.path_label = QLabel()
        self.pos_label = QLabel()
        self.pos_label.setMinimumWidth(self.pos_label.fontMetrics().horizontalAdvance("Ln 99999, Col 999") + 12)
        sb.addPermanentWidget(self.path_label, 1)
        sb.addPermanentWidget(self.pos_label)

    # ---- status ----------------------------------------------------------
    def _update_level_display(self) -> None:
        mx = self.editor.max_level()
        cur = self.editor.current_level()
        self.level_spin.blockSignals(True)
        self.level_spin.setMaximum(max(mx, 0))
        self.level_spin.setSuffix(f" / {mx}")
        self.level_spin.setValue(cur)
        self.level_spin.blockSignals(False)

    def _level_spin_changed(self, value: int) -> None:
        self.editor.show_to_level(value)

    def _update_position(self) -> None:
        cur = self.editor.textCursor()
        self.pos_label.setText(f"Ln {cur.blockNumber() + 1}, Col {cur.positionInBlock() + 1}")
        if self.editor._rev_ok():
            node = self.editor._map.node_near(cur.blockNumber())
            self.path_label.setText("  " + " › ".join(node.path()) if node else "")

    # ---- files -----------------------------------------------------------
    def _update_title(self) -> None:
        name = os.path.basename(self.path) if self.path else "Untitled"
        self.setWindowTitle(f"{name}[*] — {APP_NAME}")
        self.setWindowModified(self.editor.document().isModified())

    def maybe_save(self) -> bool:
        if not self.editor.document().isModified():
            return True
        name = os.path.basename(self.path) if self.path else "Untitled"
        r = QMessageBox.question(
            self, APP_NAME, f"Save changes to “{name}”?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        return r == QMessageBox.StandardButton.Discard

    def new_file(self, ask: bool = True) -> None:
        if ask and not self.maybe_save():
            return
        self.path = None
        self.newline = os.linesep if os.linesep in ("\n", "\r\n") else "\n"
        self.editor.set_document_text(NEW_DOCUMENT)
        self.editor.moveCursor(QTextCursor.MoveOperation.End)
        self._update_title()

    def open_dialog(self) -> None:
        if not self.maybe_save():
            return
        start = os.path.dirname(self.path) if self.path else str(self.settings.value("last_dir", ""))
        path, _ = QFileDialog.getOpenFileName(self, "Open tree", start,
                                              "Text files (*.txt);;All files (*)")
        if path:
            self.load_file(path)

    def _open_dropped(self, path: str) -> None:
        if self.maybe_save():
            self.load_file(path)

    def load_file(self, path: str) -> bool:
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as ex:
            QMessageBox.critical(self, APP_NAME, f"Could not open the file:\n{path}\n\n{ex}")
            self._remove_recent(path)
            return False
        if b"\x00" in data[:4096]:
            QMessageBox.critical(self, APP_NAME, f"This does not look like a text file:\n{path}")
            return False
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
            QMessageBox.warning(self, APP_NAME,
                                "The file is not valid UTF-8. Unreadable characters were "
                                "replaced with �. Saving will write UTF-8.")
        self.newline = "\r\n" if b"\r\n" in data else "\n"
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if text.endswith("\n"):
            text = text[:-1]
        self.editor.set_document_text(text)
        self.path = os.path.abspath(path)
        self.settings.setValue("last_dir", os.path.dirname(self.path))
        self._add_recent(self.path)
        self._update_title()
        self.statusBar().showMessage(f"Opened {self.path}", 4000)
        return True

    def save(self) -> bool:
        if not self.path:
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> bool:
        start = self.path or os.path.join(str(self.settings.value("last_dir", "")), "tree.txt")
        path, _ = QFileDialog.getSaveFileName(self, "Save tree", start,
                                              "Text files (*.txt);;All files (*)")
        if not path:
            return False
        if not os.path.splitext(path)[1]:
            path += ".txt"
        return self._write(path)

    def _write(self, path: str) -> bool:
        if self.format_on_save:
            self.editor.format_document(quiet=True, canonical=False)
        text = self.editor.toPlainText()
        data = (text.replace("\n", self.newline) + self.newline).encode("utf-8")
        f = QSaveFile(path)            # atomic: writes a temp file, then renames
        if not f.open(QIODevice.OpenModeFlag.WriteOnly):
            QMessageBox.critical(self, APP_NAME, f"Could not save:\n{path}\n\n{f.errorString()}")
            return False
        f.write(QByteArray(data))
        if not f.commit():
            QMessageBox.critical(self, APP_NAME, f"Could not save:\n{path}\n\n{f.errorString()}")
            return False
        self.path = os.path.abspath(path)
        self.settings.setValue("last_dir", os.path.dirname(self.path))
        self.editor.document().setModified(False)
        self._add_recent(self.path)
        self._update_title()
        self.statusBar().showMessage(f"Saved {self.path}", 4000)
        return True

    # ---- recent files ----------------------------------------------------
    def _recent(self) -> List[str]:
        v = self.settings.value("recent", [])
        if isinstance(v, str):
            v = [v]
        return [p for p in (v or []) if isinstance(p, str)]

    def _add_recent(self, path: str) -> None:
        items = [p for p in self._recent() if os.path.normcase(p) != os.path.normcase(path)]
        self.settings.setValue("recent", ([path] + items)[: self.MAX_RECENT])
        self._rebuild_recent()

    def _remove_recent(self, path: str) -> None:
        self.settings.setValue("recent", [p for p in self._recent() if p != path])
        self._rebuild_recent()

    def _rebuild_recent(self) -> None:
        self.recent_menu.clear()
        items = self._recent()
        for p in items:
            a = self.recent_menu.addAction(p)
            a.triggered.connect(lambda _=False, p=p: self._open_recent(p))
        self.recent_menu.setEnabled(bool(items))

    def _open_recent(self, path: str) -> None:
        if self.maybe_save():
            self.load_file(path)

    # ---- view ------------------------------------------------------------
    def _zoom(self, step: int) -> None:
        size = DEFAULT_FONT_SIZE if step == 0 else self.editor.font_size() + step
        self.editor.set_font_size(size)

    def _set_dark(self, dark: bool, save: bool = True) -> None:
        apply_app_palette(QApplication.instance(), dark)
        self.editor.set_theme(Theme(dark))
        self._refresh_icons(dark)
        self.a_dark.blockSignals(True)
        self.a_dark.setChecked(dark)
        self.a_dark.blockSignals(False)
        if save:
            self.settings.setValue("dark", dark)

    def open_settings(self) -> None:
        dlg = SettingsDialog(self, self.editor.options, self.format_on_save)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.editor.options = tm.FormatOptions(dlg.min_col.value(), dlg.gap.value())
        self.format_on_save = dlg.on_save.isChecked()
        self.settings.setValue("min_comment_column", dlg.min_col.value())
        self.settings.setValue("comment_gap", dlg.gap.value())
        self.settings.setValue("format_on_save", self.format_on_save)
        self.editor.format_document()

    def show_shortcuts(self) -> None:
        rows = [
            ("Whole document", ""),
            ("Collapse all / Expand all", "Alt+1 / Alt+4"),
            ("Collapse one level / Expand one level", "Alt+2 / Alt+3"),
            ("Show exactly N levels", "Ctrl+1 … Ctrl+9"),
            ("Single branch", ""),
            ("Toggle branch at cursor", "Ctrl+.  or click the ▼/▶ arrow"),
            ("Collapse / expand branch fully", "Ctrl+Shift+.  /  Ctrl+Shift+,  (or Alt+click arrow)"),
            ("Open a folded branch", "click its “⋯ N items” badge"),
            ("Editing", ""),
            ("New item (same level)", "Enter at end of name  or  Ctrl+Enter"),
            ("New sub-item", "Ctrl+Shift+Enter"),
            ("Move right / left one level", "Tab / Shift+Tab  (or Alt+Shift+→ / ←)"),
            ("Move up / down", "Alt+Shift+↑ / ↓"),
            ("Edit name & explanation", f"{EDIT_SHORTCUT}  (explanation only: Ctrl+E)"),
            ("Duplicate / delete branch", "Ctrl+D / Ctrl+Shift+Delete"),
            ("Remove an empty new item", "Backspace"),
            ("Move explanations left / right", "Alt+← / Alt+→  (selection, or whole document)"),
            ("Format document (auto-align all)", "Ctrl+Alt+L  (saving tidies lines, keeps # columns)"),
            ("Find", "Ctrl+F, F3, Shift+F3"),
            ("Raw newline (no auto item)", "Shift+Enter"),
        ]
        html = "<table cellspacing=6>"
        for a, b in rows:
            html += (f"<tr><td colspan=2><b>{a}</b></td></tr>" if not b
                     else f"<tr><td>{a}</td><td><code>{b}</code></td></tr>")
        html += "</table>"
        QMessageBox.information(self, "Keyboard shortcuts", html)

    def show_about(self) -> None:
        QMessageBox.about(self, APP_NAME,
                          f"<b>{APP_NAME}</b> {APP_VERSION}<br>"
                          "Plain-text structure trees with folding.<br>"
                          "Files stay pure UTF-8 .txt.")

    def closeEvent(self, e) -> None:
        if not self.maybe_save():
            e.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("font_size", self.editor.font_size())
        e.accept()


# --------------------------------------------------------------------------- #
def _migrate_old_settings(new: QSettings) -> None:
    """Carry over preferences saved under the app's previous name (Tree Editor)."""
    if new.allKeys():
        return
    old = QSettings("TreeEditor", "TreeEditor")
    for key in old.allKeys():
        new.setValue(key, old.value(key))
    new.sync()


def _install_excepthook() -> None:
    def hook(exc_type, exc, tb):
        msg = "".join(traceback.format_exception(exc_type, exc, tb))
        sys.stderr.write(msg)
        if QApplication.instance() is not None:
            QMessageBox.critical(None, f"{APP_NAME} - unexpected error",
                                 "Something went wrong. Your text is still in the editor; "
                                 "save it under a new name to be safe.\n\n" + msg[-2500:])
    sys.excepthook = hook


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Nodeon")
    ui_font = app.font()
    if ui_font.pointSizeF() > 0:
        ui_font.setPointSizeF(ui_font.pointSizeF() + 1)
        app.setFont(ui_font)
    _install_excepthook()
    path = sys.argv[1] if len(sys.argv) > 1 else None
    win = MainWindow(path)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())