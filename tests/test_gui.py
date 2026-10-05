"""GUI tests for main/main.py (the Nodeon app) (runs headless, no window appears).

Run from the project root:
    python -m unittest discover tests
Uses a temporary settings file, so your real Nodeon preferences are untouched.
"""
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "main"))

try:
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtGui import QColor, QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog
except ImportError:                                     # pragma: no cover
    QApplication = None

if QApplication is not None:
    import importlib.util
    # Load main/main.py by its path: the name "main" alone could be confused
    # with the main/ folder itself.
    _spec = importlib.util.spec_from_file_location(
        "nodeon_app", os.path.join(PROJECT_ROOT, "main", "main.py"))
    app_module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(app_module)
    import treemodel as tm

M = Qt.KeyboardModifier if QApplication is not None else None
K = Qt.Key if QApplication is not None else None

SAMPLE = ("project/\n"
          "│\n"
          "├── src/                          # Source code\n"
          "│   ├── main.py                   # Entry point\n"
          "│   └── a_really_long_module_name.py  # Long one\n"
          "├── docs/                         # Documentation\n"
          "│                                 # second line\n"
          "└── README.md                     # Overview")


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp = tempfile.mkdtemp(prefix="nodeon-test-")
        ini = os.path.join(cls.tmp, "settings.ini")
        cls._orig_settings = app_module.QSettings
        app_module.QSettings = lambda *a: QSettings(ini, QSettings.Format.IniFormat)

    @classmethod
    def tearDownClass(cls):
        app_module.QSettings = cls._orig_settings
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.path = os.path.join(self.tmp, "tree.txt")
        marks = self.path + ".marks.json"
        if os.path.exists(marks):
            os.remove(marks)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(SAMPLE + "\n")
        self.win = app_module.MainWindow(self.path)
        self.win.show()
        QTest.qWait(20)
        self.ed = self.win.editor
        self.ed.setFocus()

    def tearDown(self):
        self.ed.document().setModified(False)
        self.win.close()
        self.win.deleteLater()
        QTest.qWait(10)

    # helpers --------------------------------------------------------------
    def lines(self):
        return self.ed.toPlainText().split("\n")

    def hash_cols(self):
        return [l.index("#") for l in self.lines() if "#" in l]

    def goto(self, line):
        self.ed.setTextCursor(QTextCursor(self.ed.document().findBlockByNumber(line)))

    def key(self, k, mods=None):
        QTest.keyClick(self.ed, k, mods if mods is not None else M.NoModifier)
        QTest.qWait(5)

    # toolbar --------------------------------------------------------------
    def test_explanation_button_label_and_tooltip(self):
        buttons = {b._label: b for b in self.win.findChildren(app_module.ActionButton)}
        self.assertIn("Explanation", buttons)
        self.assertNotIn("Edit", buttons)
        tip = buttons["Explanation"].defaultAction().toolTip()
        self.assertIn("Explanation", tip)
        self.assertIn("add or edit the explanation", tip)
        self.assertIn("Explanations ←", buttons)
        self.assertIn("Explanations →", buttons)
        self.assertEqual(buttons["Explanations ←"]._keys(), "Alt+←")
        self.assertEqual(buttons["Explanations →"]._keys(), "Alt+→")
        labels = [b._label for b in self.win.findChildren(app_module.ActionButton)]
        self.assertEqual(labels[-2:], ["Format", "Delete"])

    def test_edit_shortcut_opens_dialog(self):
        calls = []
        orig = app_module.EditNodeDialog.exec
        app_module.EditNodeDialog.exec = lambda d: (calls.append(1), QDialog.DialogCode.Rejected)[1]
        try:
            self.goto(2)
            self.key(K.Key_E, M.ControlModifier | M.ShiftModifier)
            self.key(K.Key_E, M.ControlModifier)
            self.key(K.Key_F2)
        finally:
            app_module.EditNodeDialog.exec = orig
        self.assertEqual(len(calls), 2)

    # explanation alignment ----------------------------------------------
    def test_alt_right_whole_document_aligns(self):
        before = self.hash_cols()
        self.assertEqual(len(set(before)), 2)            # the long line is out of line
        # The long line has only 2 spaces before "#", so it is held at 3 spaces
        # (column 39); the others reach that column after 5 presses.
        for _ in range(4):
            self.key(K.Key_Right, M.AltModifier)
        self.assertEqual(self.hash_cols(), [38, 38, 39, 38, 38, 38])
        self.key(K.Key_Right, M.AltModifier)
        self.assertEqual(self.hash_cols(), [39] * 6)       # everything in one column
        self.key(K.Key_Right, M.AltModifier)
        self.assertEqual(self.hash_cols(), [40] * 6)       # then all move together

    def test_alt_left_stops_three_spaces_after_text(self):
        for _ in range(60):
            self.key(K.Key_Left, M.AltModifier)
        for line in self.lines():
            if "#" in line:
                text = line[:line.index("#")]
                self.assertTrue(text.endswith("   "), repr(line))
                self.assertFalse(text.endswith("    ") and text.strip("│ "), repr(line))
        # explanation lines of one branch stay together
        docs = [l for l in self.lines() if "Documentation" in l or "second line" in l]
        self.assertEqual(docs[0].index("#"), docs[1].index("#"))

    def test_selection_only_moves_selected_and_is_kept(self):
        before = self.lines()
        cur = QTextCursor(self.ed.document().findBlockByNumber(2))
        end = self.ed.document().findBlockByNumber(3)
        cur.setPosition(end.position() + 5, QTextCursor.MoveMode.KeepAnchor)
        self.ed.setTextCursor(cur)
        self.key(K.Key_Right, M.AltModifier)
        self.key(K.Key_Right, M.AltModifier)
        after = self.lines()
        self.assertEqual(after[2].index("#"), before[2].index("#") + 2)
        self.assertEqual(after[3].index("#"), before[3].index("#") + 2)
        self.assertEqual(after[5:], before[5:])             # other lines untouched
        sel = self.ed.textCursor()
        self.assertTrue(sel.hasSelection())
        self.assertEqual(self.ed.document().findBlock(sel.anchor()).blockNumber(), 2)
        self.assertEqual(sel.blockNumber(), 3)

    def test_undo_restores(self):
        before = self.ed.toPlainText()
        self.key(K.Key_Right, M.AltModifier)
        self.assertNotEqual(self.ed.toPlainText(), before)
        self.key(K.Key_Z, M.ControlModifier)
        self.assertEqual(self.ed.toPlainText(), before)

    def test_save_keeps_manual_columns(self):
        for _ in range(5):
            self.key(K.Key_Right, M.AltModifier)
        expected = self.ed.toPlainText()
        self.assertTrue(self.win.save())
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), expected + "\n")

    def test_structural_edit_keeps_manual_columns(self):
        for _ in range(5):
            self.key(K.Key_Right, M.AltModifier)
        col = self.hash_cols()[0]
        self.goto(7)
        self.key(K.Key_Up, M.AltModifier | M.ShiftModifier)
        self.assertEqual(set(self.hash_cols()), {col})

    def test_format_document_still_auto_aligns(self):
        for _ in range(5):
            self.key(K.Key_Right, M.AltModifier)
        self.key(K.Key_L, M.ControlModifier | M.AltModifier)
        self.assertEqual(self.ed.toPlainText(), tm.format_text(SAMPLE))

    def test_folds_survive_alignment(self):
        self.ed.show_to_level(1)
        hidden = sum(1 for i in range(self.ed.document().blockCount())
                     if not self.ed.document().findBlockByNumber(i).isVisible())
        self.key(K.Key_Right, M.AltModifier)
        hidden2 = sum(1 for i in range(self.ed.document().blockCount())
                      if not self.ed.document().findBlockByNumber(i).isVisible())
        self.assertEqual(hidden, hidden2)
        self.assertGreater(hidden, 0)

    def test_no_explanations_message(self):
        self.ed.set_document_text("root/\n└── a")
        before = self.ed.toPlainText()
        self.key(K.Key_Right, M.AltModifier)
        self.assertEqual(self.ed.toPlainText(), before)

    # empty spacer lines (Alt+Enter) -----------------------------------------
    SPACER_SRC = "r/\n├── a/\n│   ├── a1      # one\n│   └── a2\n├── b\n└── c"

    def _spacer_doc(self):
        self.ed.set_document_text(self.SPACER_SRC)

    def test_alt_enter_between_siblings(self):
        self._spacer_doc()
        self.goto(2)                                     # a1
        self.key(K.Key_Return, M.AltModifier)
        self.assertEqual(self.lines()[:5], ["r/", "├── a/", "│   ├── a1      # one", "│   │", "│   └── a2"])
        self.assertEqual(self.ed.textCursor().blockNumber(), 3)   # cursor on the new line
        self.key(K.Key_Return, M.AltModifier)            # again: one more empty line
        self.assertEqual(self.lines()[3:6], ["│   │", "│   │", "│   └── a2"])

    def test_alt_enter_on_open_branch_and_last_child(self):
        self._spacer_doc()
        self.goto(1)                                     # a/ (open) -> before a1
        self.key(K.Key_Return, M.AltModifier)
        self.assertEqual(self.lines()[1:4], ["├── a/", "│   │", "│   ├── a1      # one"])
        self.assertEqual(self.lines()[4], "│   └── a2")
        self.goto(4)                                     # a2 (last child) -> before b
        self.key(K.Key_Return, M.AltModifier)
        self.assertEqual(self.lines()[4:7], ["│   └── a2", "│", "├── b"])

    def test_alt_enter_on_collapsed_branch_goes_below_it(self):
        self._spacer_doc()
        self.ed.toggle_fold(1)                           # fold a/
        self.goto(1)
        self.key(K.Key_Return, M.AltModifier)
        self.assertEqual(self.lines()[4:6], ["│", "├── b"])
        self.assertIn(1, self.ed.collapsed_headers())    # fold kept

    def test_alt_enter_last_line_undo_and_keys_kept(self):
        self._spacer_doc()
        self.goto(5)                                     # c, last line
        self.key(K.Key_Return, M.AltModifier)
        self.assertEqual(self.lines()[-1], "")
        self.key(K.Key_Z, M.ControlModifier)
        self.assertEqual(self.ed.toPlainText(), self.SPACER_SRC)
        # plain Enter still creates the next item, Shift+Enter a raw newline
        self.goto(4)
        self.ed.moveCursor(QTextCursor.MoveOperation.EndOfBlock)
        self.key(K.Key_Return)
        self.assertEqual(self.lines()[5], "├── ")
        self.assertIn("Empty line", [b._label for b in self.win.findChildren(app_module.ActionButton)])

    def test_alt_enter_save_round_trip(self):
        self._spacer_doc()
        self.goto(2)
        self.key(K.Key_Return, M.AltModifier)
        expected = self.ed.toPlainText()
        self.win.path = self.path
        self.assertTrue(self.win.save())
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), expected + "\n")

    # colour marks ------------------------------------------------------------
    def color_at(self, line, text):
        """Foreground colour (hex) of `text` in `line` as drawn on screen."""
        block = self.ed.document().findBlockByNumber(line)
        pos = block.text().index(text)
        for r in block.layout().formats():
            if r.start <= pos < r.start + r.length:
                return r.format.foreground().color().name()
        return None

    def mark(self, line, key):
        self.goto(line)
        self.key(key, M.AltModifier)

    def test_mark_colours_only_the_name(self):
        theme = self.ed.theme
        text_before = self.ed.toPlainText()
        self.mark(2, K.Key_G)                       # src/
        self.assertEqual(self.color_at(2, "src/"), QColor(theme.mark_checked).name())
        self.assertEqual(self.color_at(2, "# Source"), QColor(theme.comment).name())
        self.assertEqual(self.color_at(2, "├──"), QColor(theme.guide).name())
        self.assertEqual(self.ed.toPlainText(), text_before)       # text unchanged
        self.assertFalse(self.ed.document().isModified())
        self.mark(3, K.Key_O)
        self.assertEqual(self.color_at(3, "main.py"), QColor(theme.mark_explore).name())
        self.mark(7, K.Key_R)
        self.assertEqual(self.color_at(7, "README.md"), QColor(theme.mark_problem).name())

    def test_comment_colour_is_not_text_or_mark_colour(self):
        t = self.ed.theme
        self.assertEqual(self.color_at(2, "# Source"), QColor(t.comment).name())
        others = {QColor(c).name() for c in (t.fg, t.file, t.mark_checked,
                                                t.mark_explore, t.mark_problem)}
        self.assertNotIn(QColor(t.comment).name(), others)

    def test_same_key_again_and_alt_c_remove(self):
        self.mark(2, K.Key_G)
        self.mark(2, K.Key_G)
        self.assertEqual(self.color_at(2, "src/"), QColor(self.ed.theme.folder).name())
        self.mark(2, K.Key_R)
        self.mark(2, K.Key_C)
        self.assertEqual(self.color_at(2, "src/"), QColor(self.ed.theme.folder).name())
        self.assertEqual(self.ed.export_marks(), [])

    def test_mark_selection(self):
        cur = QTextCursor(self.ed.document().findBlockByNumber(2))
        cur.setPosition(self.ed.document().findBlockByNumber(4).position() + 3,
                        QTextCursor.MoveMode.KeepAnchor)
        self.ed.setTextCursor(cur)
        self.key(K.Key_O, M.AltModifier)
        self.assertEqual(len(self.ed.export_marks()), 3)
        self.assertTrue(self.ed.textCursor().hasSelection())

    def test_marks_follow_branches_and_undo(self):
        self.mark(7, K.Key_R)                       # README.md
        self.mark(5, K.Key_G)                       # docs/
        self.goto(7)
        self.key(K.Key_Up, M.AltModifier | M.ShiftModifier)   # README above docs
        readme = [i for i, l in enumerate(self.lines()) if "README" in l][0]
        docs = [i for i, l in enumerate(self.lines()) if "docs/" in l][0]
        self.assertEqual(self.color_at(readme, "README.md"), QColor(self.ed.theme.mark_problem).name())
        self.assertEqual(self.color_at(docs, "docs/"), QColor(self.ed.theme.mark_checked).name())
        self.key(K.Key_Z, M.ControlModifier)
        QTest.qWait(300)                            # let the editor re-read the text
        self.assertEqual(self.color_at(7, "README.md"), QColor(self.ed.theme.mark_problem).name())
        self.assertEqual(self.color_at(5, "docs/"), QColor(self.ed.theme.mark_checked).name())

    def test_mark_survives_typing_and_folding(self):
        self.mark(2, K.Key_G)
        self.ed.toggle_fold(2)
        self.assertIn(2, self.ed.collapsed_headers())
        self.assertEqual(self.color_at(2, "src/"), QColor(self.ed.theme.mark_checked).name())
        self.ed.toggle_fold(2)
        self.goto(2)
        self.ed.moveCursor(QTextCursor.MoveOperation.EndOfBlock)
        QTest.keyClicks(self.ed, " more")
        QTest.qWait(300)
        self.assertEqual(self.color_at(2, "src/"), QColor(self.ed.theme.mark_checked).name())
        self.assertNotIn(2, self.ed.collapsed_headers())

    def test_marks_saved_next_to_file_and_reloaded(self):
        self.mark(2, K.Key_G)
        self.mark(7, K.Key_O)
        marks_file = self.path + ".marks.json"
        self.assertTrue(os.path.isfile(marks_file))           # stored right away
        with open(self.path, encoding="utf-8") as f:
            self.assertNotIn("checked", f.read())              # .txt stays pure text
        self.win.close()
        win2 = app_module.MainWindow(self.path)
        try:
            marks = dict(win2.editor.export_marks())
            self.assertEqual(sorted(marks.values()), [app_module.MARK_CHECKED,
                                                      app_module.MARK_EXPLORE])
            # removing the last marks deletes the marks file
            for line in (2, 7):
                c = QTextCursor(win2.editor.document().findBlockByNumber(line))
                win2.editor.setTextCursor(c)
                win2.editor.mark_selection(app_module.MARK_NONE)
            self.assertFalse(os.path.exists(marks_file))
        finally:
            win2.editor.document().setModified(False)
            win2.close()

    def test_broken_marks_file_is_ignored(self):
        self.win.close()
        with open(self.path + ".marks.json", "w", encoding="utf-8") as f:
            f.write("{ not json")
        win2 = app_module.MainWindow(self.path)
        try:
            self.assertEqual(win2.editor.export_marks(), [])
            self.assertIn("could not be read", win2.statusBar().currentMessage())
        finally:
            win2.editor.document().setModified(False)
            win2.close()

    def test_mark_toolbar_and_shortcut_texts(self):
        labels = {b._label: b for b in self.win.findChildren(app_module.ActionButton)}
        self.assertIn("Mark", labels)
        self.assertEqual(labels["Mark"]._keys(), "Alt+G / O / R")
        menu = [a for a in labels["Mark"].menu().actions() if not a.isSeparator()]
        self.assertEqual(len(menu), 8)
        self.assertEqual([app_module.shortcut_text(a) for a in self.win.mark_actions],
                         ["Alt+G", "Alt+O", "Alt+R", "Alt+C"])

    # coloured words (selection only) -----------------------------------------
    def select(self, line, start_text, end_text=None, end_line=None):
        """Select from start_text in `line` to the end of end_text (in end_line)."""
        doc = self.ed.document()
        b1 = doc.findBlockByNumber(line)
        b2 = doc.findBlockByNumber(line if end_line is None else end_line)
        end_text = end_text or start_text
        cur = QTextCursor(doc)
        cur.setPosition(b1.position() + b1.text().index(start_text))
        cur.setPosition(b2.position() + b2.text().index(end_text) + len(end_text),
                        QTextCursor.MoveMode.KeepAnchor)
        self.ed.setTextCursor(cur)

    def colors_of(self, line, text):
        """Colour of every character of `text` in `line`."""
        block = self.ed.document().findBlockByNumber(line)
        start = block.text().index(text)
        out = []
        for pos in range(start, start + len(text)):
            col = None
            for r in block.layout().formats():
                if r.start <= pos < r.start + r.length:
                    col = r.format.foreground().color().name()
            out.append(col)
        return out

    def c(self, attr):
        return QColor(getattr(self.ed.theme, attr)).name()

    def test_word_colour_only_selection(self):
        before = self.ed.toPlainText()
        self.select(2, "Source")                              # "# Source code"
        self.key(K.Key_G, M.AltModifier | M.ShiftModifier)
        self.assertEqual(set(self.colors_of(2, "Source")), {self.c("mark_checked")})
        self.assertEqual(set(self.colors_of(2, " code")), {self.c("comment")})
        self.assertEqual(set(self.colors_of(2, "src/")), {self.c("folder")})
        self.assertEqual(self.ed.toPlainText(), before)
        self.assertTrue(self.ed.textCursor().hasSelection())    # selection kept

    def test_word_colour_part_of_name_and_all_colours(self):
        self.select(3, "main")                                 # part of "main.py"
        self.key(K.Key_O, M.AltModifier | M.ShiftModifier)
        self.assertEqual(set(self.colors_of(3, "main")), {self.c("mark_explore")})
        self.assertEqual(set(self.colors_of(3, ".py")), {self.c("file")})
        self.select(7, "Overview")
        self.key(K.Key_R, M.AltModifier | M.ShiftModifier)
        self.assertEqual(set(self.colors_of(7, "Overview")), {self.c("mark_problem")})

    def test_word_colour_never_touches_tree_lines(self):
        self.select(2, "├──", "Source")                        # lines + name + spaces + #
        self.key(K.Key_G, M.AltModifier | M.ShiftModifier)
        self.assertEqual(set(self.colors_of(2, "├──")), {self.c("guide")})
        self.assertEqual(set(self.colors_of(2, "src/")), {self.c("mark_checked")})
        self.assertEqual(set(self.colors_of(2, "Source")), {self.c("mark_checked")})
        self.assertEqual(self.colors_of(2, "#")[0], self.c("comment"))

    def test_word_colour_over_several_lines(self):
        self.select(5, "Documentation", "second", end_line=6)
        self.key(K.Key_R, M.AltModifier | M.ShiftModifier)
        self.assertEqual(set(self.colors_of(5, "Documentation")), {self.c("mark_problem")})
        self.assertEqual(set(self.colors_of(6, "second")), {self.c("mark_problem")})
        self.assertEqual(set(self.colors_of(6, " line")), {self.c("comment")})

    def test_word_toggle_and_partial_remove(self):
        self.select(2, "Source code")
        self.key(K.Key_G, M.AltModifier | M.ShiftModifier)
        self.select(2, "Source code")
        self.key(K.Key_G, M.AltModifier | M.ShiftModifier)     # same again = remove
        self.assertEqual(set(self.colors_of(2, "Source code")), {self.c("comment")})
        self.select(2, "Source code")
        self.key(K.Key_G, M.AltModifier | M.ShiftModifier)
        self.select(2, "code")
        self.key(K.Key_C, M.AltModifier | M.ShiftModifier)     # remove just "code"
        self.assertEqual(set(self.colors_of(2, "Source")), {self.c("mark_checked")})
        self.assertEqual(set(self.colors_of(2, "code")), {self.c("comment")})

    def test_word_needs_selection(self):
        self.goto(2)
        self.key(K.Key_G, M.AltModifier | M.ShiftModifier)
        self.assertIn("Select the words", self.win.statusBar().currentMessage())
        self.assertEqual(self.ed.export_spans(), [])

    def test_word_and_line_mark_together(self):
        self.mark(2, K.Key_R)                                  # whole name red
        self.select(2, "Source")
        self.key(K.Key_G, M.AltModifier | M.ShiftModifier)
        self.assertEqual(set(self.colors_of(2, "src/")), {self.c("mark_problem")})
        self.assertEqual(set(self.colors_of(2, "Source")), {self.c("mark_checked")})

    def test_word_follows_alignment_moves_and_edits(self):
        self.select(5, "Documentation")
        self.key(K.Key_O, M.AltModifier | M.ShiftModifier)
        self.goto(0)
        for _ in range(3):
            self.key(K.Key_Right, M.AltModifier)                # explanations move
        self.assertEqual(set(self.colors_of(5, "Documentation")), {self.c("mark_explore")})
        self.goto(5)
        self.key(K.Key_Up, M.AltModifier | M.ShiftModifier)    # move branch up
        line = [i for i, l in enumerate(self.lines()) if "Documentation" in l][0]
        self.assertEqual(set(self.colors_of(line, "Documentation")), {self.c("mark_explore")})
        # typing earlier in the line: colour stays on the word
        b = self.ed.document().findBlockByNumber(line)
        cur = QTextCursor(b)
        cur.setPosition(b.position() + b.text().index("docs/") + 4)
        self.ed.setTextCursor(cur)
        QTest.keyClicks(self.ed, "_v2")
        QTest.qWait(300)
        self.assertIn("docs_v2/", self.lines()[line])
        self.assertEqual(set(self.colors_of(line, "Documentation")), {self.c("mark_explore")})

    def test_word_gone_when_edited_back_with_undo(self):
        self.select(7, "Overview")
        self.key(K.Key_R, M.AltModifier | M.ShiftModifier)
        b = self.ed.document().findBlockByNumber(7)
        cur = QTextCursor(b)
        cur.setPosition(b.position() + b.text().index("Overview") + 4)
        self.ed.setTextCursor(cur)
        QTest.keyClicks(self.ed, "X")                           # "OverXview"
        QTest.qWait(300)
        self.assertEqual(set(self.colors_of(7, "OverXview")), {self.c("comment")})
        self.key(K.Key_Z, M.ControlModifier)
        QTest.qWait(300)
        self.assertEqual(set(self.colors_of(7, "Overview")), {self.c("mark_problem")})

    def test_word_colours_saved_and_reloaded(self):
        self.select(2, "Source")
        self.key(K.Key_G, M.AltModifier | M.ShiftModifier)
        self.select(6, "second")
        self.key(K.Key_O, M.AltModifier | M.ShiftModifier)
        marks_file = self.path + ".marks.json"
        with open(marks_file, encoding="utf-8") as f:
            data = __import__("json").load(f)
        self.assertEqual(sorted(w["text"] for w in data["words"]), ["Source", "second"])
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), SAMPLE + "\n")          # .txt untouched
        self.win.close()
        win2 = app_module.MainWindow(self.path)
        try:
            ed, old = win2.editor, self.ed
            self.ed = ed
            self.assertEqual(set(self.colors_of(2, "Source")), {self.c("mark_checked")})
            self.assertEqual(set(self.colors_of(6, "second")), {self.c("mark_explore")})
            # removing all colours deletes the marks file
            for line, word in ((2, "Source"), (6, "second")):
                self.select(line, word)
                ed.mark_words(app_module.MARK_NONE)
            self.assertFalse(os.path.exists(marks_file))
        finally:
            self.ed = old
            win2.editor.document().setModified(False)
            win2.close()

    def test_word_colour_hidden_lines_and_folding(self):
        self.select(3, "Entry")
        self.key(K.Key_G, M.AltModifier | M.ShiftModifier)
        self.ed.toggle_fold(2)
        self.ed.toggle_fold(2)
        self.assertEqual(set(self.colors_of(3, "Entry")), {self.c("mark_checked")})

    # existing behaviour still works ------------------------------------
    def test_folding_levels(self):
        self.ed.collapse_all()
        self.assertEqual(self.ed.current_level(), 0)
        self.ed.expand_one_level()
        self.assertEqual(self.ed.current_level(), 1)
        self.ed.expand_all()
        self.assertEqual(self.ed.current_level(), self.ed.max_level())

    def test_enter_tab_typing(self):
        self.ed.set_document_text("root/\n│\n└── ")
        self.ed.moveCursor(QTextCursor.MoveOperation.End)
        QTest.keyClicks(self.ed, "src/")
        self.key(K.Key_Return)
        QTest.keyClicks(self.ed, "main.py")
        self.key(K.Key_Tab)
        self.assertEqual(self.ed.toPlainText(), "root/\n│\n└── src/\n    └── main.py")


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class StartupTests(unittest.TestCase):
    """main.py must always load the treemodel.py next to it, and explain
    clearly (instead of crashing) when that file is missing or wrong."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nodeon-start-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(text)

    def assertLoadError(self, fragment):
        before = sys.modules.get("treemodel")
        with self.assertRaises(app_module.ModelLoadError) as ctx:
            app_module.load_treemodel(self.dir)
        self.assertIn(fragment, str(ctx.exception))
        self.assertIs(sys.modules.get("treemodel"), before)   # nothing left broken

    def test_correct_file_loads(self):
        src = os.path.join(PROJECT_ROOT, "main", "treemodel.py")
        shutil.copy(src, self.dir)
        before = sys.modules.get("treemodel")
        try:
            mod = app_module.load_treemodel(self.dir)
            self.assertTrue(hasattr(mod, "FormatOptions"))
            self.assertEqual(os.path.dirname(mod.__file__), self.dir)
        finally:
            sys.modules["treemodel"] = before

    def test_missing_file(self):
        os.mkdir(os.path.join(self.dir, "treemodel"))      # a folder with the same name
        self.assertLoadError("was not found")

    def test_empty_file(self):
        self._write("treemodel.py", "")
        self.assertLoadError("empty")

    def test_wrong_file(self):
        self._write("treemodel.py", "x = 1\n")
        self.assertLoadError("Missing: FormatOptions")

    def test_broken_file(self):
        self._write("treemodel.py", "def broken(:\n")
        self.assertLoadError("could not be loaded")

    def test_app_uses_file_next_to_main(self):
        self.assertIsNone(app_module.MODEL_ERROR)
        self.assertEqual(os.path.normcase(os.path.dirname(app_module.tm.__file__)),
                         os.path.normcase(os.path.join(PROJECT_ROOT, "main")))


if __name__ == "__main__":
    unittest.main()