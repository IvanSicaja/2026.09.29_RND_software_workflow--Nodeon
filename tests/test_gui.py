"""GUI tests for main/main.py (the Nodeon app) (runs headless, no window appears).

Run from the project root:
    python -m unittest discover tests
Uses a temporary settings file, so your real Nodeon preferences are untouched.
"""
import json
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

MK = "\u27a1\ufe0f"                       # explanation marker ➡️


def u16(text):
    """Length in Qt (UTF-16) units - the arrow counts as 2."""
    return len(text.encode("utf-16-le")) // 2


SAMPLE = ("project/\n"
          "│\n"
          "├── src/                          # Source code\n"
          "│   ├── main.py                   # Entry point\n"
          "│   └── a_really_long_module_name.py  # Long one\n"
          "├── docs/                         # Documentation\n"
          "│                                 # second line\n"
          "└── README.md                     # Overview").replace("#", MK)


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
        return [l.index(MK) for l in self.lines() if MK in l]

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
        self.assertEqual(labels[-3:], ["Format", "Delete line", "Delete branch"])

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
            if MK in line:
                text = line[:line.index(MK)]
                self.assertTrue(text.endswith("   "), repr(line))
                self.assertFalse(text.endswith("    ") and text.strip("│ "), repr(line))
        # explanation lines of one branch stay together
        docs = [l for l in self.lines() if "Documentation" in l or "second line" in l]
        self.assertEqual(docs[0].index(MK), docs[1].index(MK))

    def test_selection_only_moves_selected_and_is_kept(self):
        before = self.lines()
        cur = QTextCursor(self.ed.document().findBlockByNumber(2))
        end = self.ed.document().findBlockByNumber(3)
        cur.setPosition(end.position() + 5, QTextCursor.MoveMode.KeepAnchor)
        self.ed.setTextCursor(cur)
        self.key(K.Key_Right, M.AltModifier)
        self.key(K.Key_Right, M.AltModifier)
        after = self.lines()
        self.assertEqual(after[2].index(MK), before[2].index(MK) + 2)
        self.assertEqual(after[3].index(MK), before[3].index(MK) + 2)
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
    SPACER_SRC = "r/\n├── a/\n│   ├── a1      " + MK + " one\n│   └── a2\n├── b\n└── c"

    def _spacer_doc(self):
        self.ed.set_document_text(self.SPACER_SRC)

    def test_alt_enter_between_siblings(self):
        self._spacer_doc()
        self.goto(2)                                     # a1
        self.key(K.Key_Return, M.AltModifier)
        self.assertEqual(self.lines()[:5], ["r/", "├── a/", "│   ├── a1      " + MK + " one", "│   │", "│   └── a2"])
        self.assertEqual(self.ed.textCursor().blockNumber(), 3)   # cursor on the new line
        self.key(K.Key_Return, M.AltModifier)            # again: one more empty line
        self.assertEqual(self.lines()[3:6], ["│   │", "│   │", "│   └── a2"])

    def test_alt_enter_on_open_branch_and_last_child(self):
        self._spacer_doc()
        self.goto(1)                                     # a/ (open) -> before a1
        self.key(K.Key_Return, M.AltModifier)
        self.assertEqual(self.lines()[1:4], ["├── a/", "│   │", "│   ├── a1      " + MK + " one"])
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
        self.assertEqual(self.color_at(2, MK + " Source"), QColor(theme.comment).name())
        self.assertEqual(self.color_at(2, "├──"), QColor(theme.guide).name())
        self.assertEqual(self.ed.toPlainText(), text_before)       # text unchanged
        self.assertFalse(self.ed.document().isModified())
        self.mark(3, K.Key_O)
        self.assertEqual(self.color_at(3, "main.py"), QColor(theme.mark_explore).name())
        self.mark(7, K.Key_R)
        self.assertEqual(self.color_at(7, "README.md"), QColor(theme.mark_problem).name())

    def test_comment_colour_is_not_text_or_mark_colour(self):
        t = self.ed.theme
        self.assertEqual(self.color_at(2, MK + " Source"), QColor(t.comment).name())
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
        self.assertIn("Mark line", labels)
        self.assertIn("Mark words", labels)
        self.assertEqual(labels["Mark line"]._keys(), "Alt+G/O/R/C")
        self.assertEqual(labels["Mark words"]._keys(), "Alt+Shift+G/O/R/C")
        self.assertEqual(labels["Mark line"].menu().actions(), self.win.mark_actions)
        self.assertEqual(labels["Mark words"].menu().actions(), self.win.word_actions)
        self.assertEqual([app_module.shortcut_text(a) for a in self.win.word_actions],
                         ["Alt+Shift+G", "Alt+Shift+O", "Alt+Shift+R", "Alt+Shift+C"])
        # two different icons
        img1 = labels["Mark line"].defaultAction().icon().pixmap(24, 24).toImage()
        img2 = labels["Mark words"].defaultAction().icon().pixmap(24, 24).toImage()
        self.assertFalse(img1.isNull())
        self.assertFalse(img2.isNull())
        self.assertNotEqual(img1, img2)
        self.assertEqual([app_module.shortcut_text(a) for a in self.win.mark_actions],
                         ["Alt+G", "Alt+O", "Alt+R", "Alt+C"])

    # coloured words (names only) --------------------------------------------
    def select(self, line, start_text, end_text=None, end_line=None):
        """Select from start_text in `line` to the end of end_text (in end_line)."""
        doc = self.ed.document()
        b1 = doc.findBlockByNumber(line)
        b2 = doc.findBlockByNumber(line if end_line is None else end_line)
        end_text = end_text or start_text
        cur = QTextCursor(doc)
        cur.setPosition(b1.position() + u16(b1.text()[:b1.text().index(start_text)]))
        e = b2.text().index(end_text) + len(end_text)
        cur.setPosition(b2.position() + u16(b2.text()[:e]), QTextCursor.MoveMode.KeepAnchor)
        self.ed.setTextCursor(cur)

    def colors_of(self, line, text):
        """Colour of every character of `text` in `line`."""
        block = self.ed.document().findBlockByNumber(line)
        t = block.text()
        start = u16(t[:t.index(text)])
        out = []
        for pos in range(start, start + u16(text)):
            col = None
            for r in block.layout().formats():
                if r.start <= pos < r.start + r.length:
                    col = r.format.foreground().color().name()
            out.append(col)
        return out

    def c(self, attr):
        return QColor(getattr(self.ed.theme, attr)).name()

    def cursor_at(self, line, text, offset):
        b = self.ed.document().findBlockByNumber(line)
        cur = QTextCursor(b)
        cur.setPosition(b.position() + u16(b.text()[:b.text().index(text) + offset]))
        self.ed.setTextCursor(cur)

    W = (M.AltModifier | M.ShiftModifier) if M is not None else None

    def test_word_colour_only_selection_in_name(self):
        before = self.ed.toPlainText()
        self.select(4, "really")                              # part of a name
        self.key(K.Key_G, self.W)
        self.assertEqual(set(self.colors_of(4, "really")), {self.c("mark_checked")})
        self.assertEqual(set(self.colors_of(4, "a_")), {self.c("file")})
        self.assertEqual(set(self.colors_of(4, "_long_module_name.py")), {self.c("file")})
        self.assertEqual(self.ed.toPlainText(), before)
        self.assertTrue(self.ed.textCursor().hasSelection())    # selection kept

    def test_word_all_colours(self):
        for key, attr, line, word in ((K.Key_G, "mark_checked", 2, "src/"),
                                      (K.Key_O, "mark_explore", 3, "main.py"),
                                      (K.Key_R, "mark_problem", 7, "README.md")):
            self.select(line, word)
            self.key(key, self.W)
            self.assertEqual(set(self.colors_of(line, word)), {self.c(attr)})

    # explanations can never be coloured ---------------------------------------
    def test_explanation_selection_is_never_coloured(self):
        for key in (K.Key_G, K.Key_O, K.Key_R, K.Key_C):
            self.select(2, "Source code")
            self.key(key, self.W)
            self.assertEqual(set(self.colors_of(2, "Source code")), {self.c("comment")})
        self.assertIn("explanations always keep", self.win.statusBar().currentMessage())
        self.assertEqual(self.ed.export_spans(), [])
        self.assertFalse(os.path.exists(self.path + ".marks.json"))

    def test_explanation_word_at_cursor_is_never_coloured(self):
        for line, word in ((2, "Source"), (6, "second"), (7, "Overview")):
            self.cursor_at(line, word, 2)
            self.key(K.Key_G, self.W)
            self.assertEqual(set(self.colors_of(line, word)), {self.c("comment")})
        self.assertIn("No word at the cursor", self.win.statusBar().currentMessage())
        self.assertEqual(self.ed.export_spans(), [])

    def test_selection_over_name_and_explanation_colours_only_name(self):
        self.select(2, "├──", "code")                          # lines + name + explanation
        self.key(K.Key_G, self.W)
        self.assertEqual(set(self.colors_of(2, "├──")), {self.c("guide")})
        self.assertEqual(set(self.colors_of(2, "src/")), {self.c("mark_checked")})
        self.assertEqual(set(self.colors_of(2, MK + " Source code")), {self.c("comment")})

    def test_selection_over_several_lines(self):
        self.select(3, "main.py", "Overview", end_line=7)
        self.key(K.Key_R, self.W)
        for line, name in ((3, "main.py"), (4, "a_really_long_module_name.py"),
                           (5, "docs/"), (7, "README.md")):
            self.assertEqual(set(self.colors_of(line, name)), {self.c("mark_problem")})
        for line, text in ((3, "Entry point"), (6, "second line"), (7, "Overview")):
            self.assertEqual(set(self.colors_of(line, text)), {self.c("comment")})

    def test_line_mark_never_colours_explanation(self):
        for key in (K.Key_G, K.Key_O, K.Key_R):
            self.mark(2, key)
            self.assertEqual(set(self.colors_of(2, "Source code")), {self.c("comment")})
            self.mark(2, K.Key_C)

    def test_old_explanation_colours_in_marks_file_are_ignored(self):
        self.win.close()
        data = {"app": "Nodeon", "version": 1, "marks": [],
                "words": [{"path": [["project/", 0], ["src/", 0]], "part": "c0", "start": 0,
                           "end": 6, "text": "Source", "mark": "checked"},
                          {"path": [["project/", 0], ["src/", 0]], "part": "name", "start": 0,
                           "end": 3, "text": "src", "mark": "problem"}]}
        with open(self.path + ".marks.json", "w", encoding="utf-8") as f:
            json.dump(data, f)
        win2 = app_module.MainWindow(self.path)
        old = self.ed
        try:
            self.ed = win2.editor
            self.assertEqual(set(self.colors_of(2, "Source")), {self.c("comment")})
            self.assertEqual(set(self.colors_of(2, "src")), {self.c("mark_problem")})
            self.assertEqual([sp[0] for _k, sp in win2.editor.export_spans()], ["name"])
        finally:
            self.ed = old
            win2.editor.document().setModified(False)
            win2.close()

    def test_comment_colour_comes_from_theme(self):
        for dark in (True, False):
            self.win._set_dark(dark)
            self.assertEqual(set(self.colors_of(2, "Source code")), {self.c("comment")})

    # word at the cursor (names) ------------------------------------------------
    def test_cursor_inside_name_word(self):
        self.cursor_at(4, "a_really_long_module_name.py", 6)
        pos = self.ed.textCursor().position()
        self.key(K.Key_G, self.W)
        self.assertEqual(set(self.colors_of(4, "a_really_long_module_name.py")),
                         {self.c("mark_checked")})
        self.assertEqual(self.ed.textCursor().position(), pos)    # cursor not moved
        self.assertFalse(self.ed.textCursor().hasSelection())
        self.assertIn("Word at cursor", self.win.statusBar().currentMessage())

    def test_cursor_at_name_borders(self):
        self.cursor_at(7, "README.md", 0)                       # |README.md
        self.key(K.Key_O, self.W)
        self.assertEqual(set(self.colors_of(7, "README.md")), {self.c("mark_explore")})
        self.cursor_at(3, "main.py", 7)                         # main.py|
        self.key(K.Key_R, self.W)
        self.assertEqual(set(self.colors_of(3, "main.py")), {self.c("mark_problem")})

    def test_word_nothing_on_tree_lines_or_spaces(self):
        self.goto(2)                                            # column 0: "├──"
        self.key(K.Key_G, self.W)
        self.assertIn("No word at the cursor", self.win.statusBar().currentMessage())
        self.cursor_at(2, "src/", 6)                            # spaces after the name
        self.key(K.Key_G, self.W)
        self.goto(1)                                            # spacer line "│"
        self.key(K.Key_G, self.W)
        self.assertEqual(self.ed.export_spans(), [])

    def test_cursor_toggle_recolour_and_default(self):
        self.cursor_at(7, "README.md", 3)
        self.key(K.Key_G, self.W)
        self.key(K.Key_G, self.W)                               # same again = remove
        self.assertEqual(set(self.colors_of(7, "README.md")), {self.c("file")})
        self.key(K.Key_O, self.W)
        self.key(K.Key_R, self.W)                               # recolour
        self.assertEqual(set(self.colors_of(7, "README.md")), {self.c("mark_problem")})
        self.key(K.Key_C, self.W)                               # default colour
        self.assertEqual(set(self.colors_of(7, "README.md")), {self.c("file")})
        self.assertEqual(self.ed.export_spans(), [])

    def test_partial_remove_and_recolour_partly_coloured_word(self):
        self.select(4, "a_really_long")
        self.key(K.Key_G, self.W)
        self.select(4, "long")
        self.key(K.Key_C, self.W)
        self.assertEqual(set(self.colors_of(4, "a_really_")), {self.c("mark_checked")})
        self.assertEqual(set(self.colors_of(4, "long_module")), {self.c("file")})
        self.cursor_at(4, "module", 2)
        self.key(K.Key_O, self.W)                               # whole word recoloured
        self.assertEqual(set(self.colors_of(4, "a_really_long_module_name.py")),
                         {self.c("mark_explore")})

    def test_selection_still_wins_over_word(self):
        self.select(4, "really_lo")
        self.key(K.Key_G, self.W)
        self.assertEqual(set(self.colors_of(4, "really_lo")), {self.c("mark_checked")})
        self.assertEqual(set(self.colors_of(4, "ng_module")), {self.c("file")})

    # default colour ----------------------------------------------------------
    def test_default_colour_in_both_menus(self):
        self.assertIn("Default colour", self.win.a_mark_clear.text())
        self.assertIn("Default colour", self.win.a_word_clear.text())
        self.assertIn(self.win.a_mark_clear, self.win.mark_menu.actions())
        self.assertIn(self.win.a_word_clear, self.win.words_menu.actions())
        self.assertNotIn(self.win.a_word_clear, self.win.mark_menu.actions())
        self.assertNotIn(self.win.a_mark_clear, self.win.words_menu.actions())
        self.assertEqual(app_module.shortcut_text(self.win.a_mark_clear), "Alt+C")
        self.assertEqual(app_module.shortcut_text(self.win.a_word_clear), "Alt+Shift+C")

    def test_line_default_colour(self):
        for key in (K.Key_G, K.Key_O, K.Key_R):
            self.mark(7, key)
            self.key(K.Key_C, M.AltModifier)
            self.assertEqual(set(self.colors_of(7, "README.md")), {self.c("file")})
            self.mark(2, key)
            self.key(K.Key_C, M.AltModifier)
            self.assertEqual(set(self.colors_of(2, "src/")), {self.c("folder")})
        self.assertEqual(self.ed.export_marks(), [])
        self.assertIn("default colour", self.win.statusBar().currentMessage())

    def test_word_default_inside_line_coloured_name(self):
        self.mark(4, K.Key_R)                                   # whole name red
        self.select(4, "really")
        self.key(K.Key_C, self.W)                               # just "really" default
        self.assertEqual(set(self.colors_of(4, "really")), {self.c("file")})
        self.assertEqual(set(self.colors_of(4, "a_")), {self.c("mark_problem")})
        self.assertEqual(set(self.colors_of(4, "_long_module_name.py")), {self.c("mark_problem")})
        self.mark(2, K.Key_G)
        self.cursor_at(2, "src/", 1)
        self.key(K.Key_C, self.W)
        self.assertEqual(set(self.colors_of(2, "src/")), {self.c("folder")})

    def test_word_default_saved_and_reloaded(self):
        self.mark(4, K.Key_R)
        self.select(4, "really")
        self.key(K.Key_C, self.W)
        with open(self.path + ".marks.json", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual([(w["text"], w["mark"]) for w in data["words"]], [("really", "default")])
        self.win.close()
        win2 = app_module.MainWindow(self.path)
        old = self.ed
        try:
            self.ed = win2.editor
            self.assertEqual(set(self.colors_of(4, "really")), {self.c("file")})
            self.assertEqual(set(self.colors_of(4, "a_")), {self.c("mark_problem")})
        finally:
            self.ed = old
            win2.editor.document().setModified(False)
            win2.close()

    def test_line_command_overrides_word_defaults(self):
        self.mark(4, K.Key_R)
        self.select(4, "really")
        self.key(K.Key_C, self.W)
        self.mark(4, K.Key_G)
        self.assertEqual(set(self.colors_of(4, "a_really_long_module_name.py")),
                         {self.c("mark_checked")})
        self.assertEqual(self.ed.export_spans(), [])
        self.mark(4, K.Key_C)
        self.assertEqual(set(self.colors_of(4, "a_really_long_module_name.py")), {self.c("file")})
        self.assertEqual(self.ed.export_marks(), [])

    def test_word_default_when_already_default(self):
        self.cursor_at(7, "README.md", 2)
        self.key(K.Key_C, self.W)
        self.assertIn("already in the default colour", self.win.statusBar().currentMessage())
        self.assertFalse(os.path.exists(self.path + ".marks.json"))
        self.mark(4, K.Key_R)
        self.select(4, "really")
        self.key(K.Key_C, self.W)
        self.select(4, "really")
        self.key(K.Key_C, self.W)
        self.assertIn("already in the default colour", self.win.statusBar().currentMessage())
        self.assertEqual(len(self.ed.export_spans()), 1)

    def test_word_and_line_mark_together(self):
        self.mark(4, K.Key_R)
        self.select(4, "module")
        self.key(K.Key_G, self.W)
        self.assertEqual(set(self.colors_of(4, "a_really")), {self.c("mark_problem")})
        self.assertEqual(set(self.colors_of(4, "module")), {self.c("mark_checked")})

    def test_word_follows_alignment_moves_and_edits(self):
        self.select(5, "docs")
        self.key(K.Key_O, self.W)
        self.goto(0)
        for _ in range(3):
            self.key(K.Key_Right, M.AltModifier)                # explanations move
        self.assertEqual(set(self.colors_of(5, "docs")), {self.c("mark_explore")})
        self.goto(5)
        self.key(K.Key_Up, M.AltModifier | M.ShiftModifier)     # move branch up
        line = [i for i, l in enumerate(self.lines()) if "docs/" in l][0]
        self.assertEqual(set(self.colors_of(line, "docs")), {self.c("mark_explore")})
        b = self.ed.document().findBlockByNumber(line)
        cur = QTextCursor(b)
        cur.setPosition(b.position() + b.text().index("docs/") + 4)
        self.ed.setTextCursor(cur)
        QTest.keyClicks(self.ed, "_v2")                         # typing after the word
        QTest.qWait(300)
        self.assertIn("docs_v2/", self.lines()[line])
        self.assertEqual(set(self.colors_of(line, "docs")), {self.c("mark_explore")})

    def test_word_gone_when_edited_back_with_undo(self):
        self.select(7, "README")
        self.key(K.Key_R, self.W)
        self.cursor_at(7, "README", 3)
        QTest.keyClicks(self.ed, "X")                            # "REAXDME"
        QTest.qWait(300)
        self.assertEqual(set(self.colors_of(7, "REAXDME")), {self.c("file")})
        self.key(K.Key_Z, M.ControlModifier)
        QTest.qWait(300)
        self.assertEqual(set(self.colors_of(7, "README")), {self.c("mark_problem")})

    def test_word_colours_saved_and_reloaded(self):
        self.select(2, "src")
        self.key(K.Key_G, self.W)
        self.select(4, "module")
        self.key(K.Key_O, self.W)
        marks_file = self.path + ".marks.json"
        with open(marks_file, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(sorted(w["text"] for w in data["words"]), ["module", "src"])
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), SAMPLE + "\n")             # .txt untouched
        self.win.close()
        win2 = app_module.MainWindow(self.path)
        old = self.ed
        try:
            self.ed = win2.editor
            self.assertEqual(set(self.colors_of(2, "src")), {self.c("mark_checked")})
            self.assertEqual(set(self.colors_of(4, "module")), {self.c("mark_explore")})
            for line, word in ((2, "src"), (4, "module")):
                self.select(line, word)
                win2.editor.mark_words(app_module.MARK_NONE)
            self.assertFalse(os.path.exists(marks_file))
        finally:
            self.ed = old
            win2.editor.document().setModified(False)
            win2.close()

    def test_word_colour_hidden_lines_and_folding(self):
        self.select(3, "main")
        self.key(K.Key_G, self.W)
        self.ed.toggle_fold(2)
        self.ed.toggle_fold(2)
        self.assertEqual(set(self.colors_of(3, "main")), {self.c("mark_checked")})

    # delete one line (Ctrl+Q) ---------------------------------------------------
    def test_ctrl_q_deletes_leaf_line_only(self):
        self.goto(3)                                             # main.py
        self.key(K.Key_Q, M.ControlModifier)
        self.assertEqual(self.lines(), [
            "project/", "│",
            "├── src/                          " + MK + " Source code",
            "│   └── a_really_long_module_name.py   " + MK + " Long one",   # 3-space minimum
            "├── docs/                         " + MK + " Documentation",
            "│                                 " + MK + " second line",
            "└── README.md                     " + MK + " Overview"])
        self.assertTrue(self.win.isVisible())                      # Ctrl+Q no longer quits
        self.assertEqual(self.ed.textCursor().blockNumber(), 3)

    def test_ctrl_q_on_branch_keeps_sub_items(self):
        self.goto(2)                                             # src/ with 2 sub-items
        self.key(K.Key_Q, M.ControlModifier)
        lines = self.lines()
        self.assertNotIn("src/", "\n".join(lines))
        self.assertTrue(any(l.startswith("├── main.py") for l in lines))
        self.assertTrue(any(l.startswith("├── a_really_long_module_name.py") for l in lines))
        self.assertEqual(len(lines), 7)
        self.assertIn("sub-items kept", self.win.statusBar().currentMessage())
        self.key(K.Key_Z, M.ControlModifier)                     # one undo step
        self.assertEqual(self.ed.toPlainText(), SAMPLE)

    def test_ctrl_q_on_explanation_and_empty_lines(self):
        self.goto(6)                                             # 2nd explanation line of docs/
        self.key(K.Key_Q, M.ControlModifier)
        self.assertNotIn("second line", self.ed.toPlainText())
        self.assertIn("Documentation", self.ed.toPlainText())
        self.goto(1)                                             # empty spacer line
        self.key(K.Key_Q, M.ControlModifier)
        self.assertEqual(self.lines()[:2], ["project/", "├── src/                          "
                                            + MK + " Source code"])

    def test_ctrl_q_last_line_and_collapsed_branch(self):
        self.goto(7)
        self.key(K.Key_Q, M.ControlModifier)
        self.assertNotIn("README", self.ed.toPlainText())
        # docs/ is now the last branch, so no vertical line continues below it
        self.assertEqual(self.lines()[-1], " " * 34 + MK + " second line")
        self.ed.toggle_fold(2)                                   # fold src/
        self.goto(2)
        self.key(K.Key_Q, M.ControlModifier)
        self.assertIn("main.py", self.ed.toPlainText())
        visible = [self.ed.document().findBlockByNumber(i).isVisible()
                   for i in range(self.ed.document().blockCount())]
        self.assertTrue(all(visible))                             # lifted items are visible

    def test_ctrl_q_marks_follow_lifted_items(self):
        self.mark(3, K.Key_G)                                    # main.py green
        self.goto(2)
        self.key(K.Key_Q, M.ControlModifier)
        line = [i for i, l in enumerate(self.lines()) if "main.py" in l][0]
        self.assertEqual(set(self.colors_of(line, "main.py")), {self.c("mark_checked")})

    def test_ctrl_q_root_and_toolbar(self):
        self.goto(0)                                             # project/ (top level)
        self.key(K.Key_Q, M.ControlModifier)
        top = [l for l in self.lines() if l and l[0] not in "│├└ "]
        self.assertEqual(top, ["src/                              " + MK + " Source code",
                               "docs/                             " + MK + " Documentation",
                               "README.md                         " + MK + " Overview"])
        labels = [b._label for b in self.win.findChildren(app_module.ActionButton)]
        self.assertEqual(labels[-3:], ["Format", "Delete line", "Delete branch"])
        self.assertEqual(app_module.shortcut_text(self.win.a_delete_line), "Ctrl+Q")
        self.assertEqual(self.win.a_quit.shortcuts(), [])
        self.assertFalse(self.win.a_delete_line.icon().isNull())

    # the ➡️ marker -------------------------------------------------------------
    def test_saves_with_arrow_and_reads_old_hash_files(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(SAMPLE.replace(MK, "#") + "\n")              # file from an older version
        self.win.load_file(self.path)
        self.assertEqual(set(self.colors_of(2, "# Source code")), {self.c("comment")})
        self.assertTrue(self.win.save())
        with open(self.path, encoding="utf-8") as f:
            text = f.read()
        expected = SAMPLE.replace(".py  " + MK, ".py   " + MK)    # 3-space minimum applied
        self.assertEqual(text, expected + "\n")
        self.assertNotIn(" # ", text)

    def test_new_explanation_written_with_arrow(self):
        self.ed.set_document_text("root/\n└── a")
        self.goto(1)
        node = self.ed._map.node_at(1)

        def op(n):
            node.comment = ["new one"]
            return node, "end"
        self.ed.run_op(op, require_node=False)
        self.assertTrue(self.lines()[1].endswith(MK + " new one"))
        self.assertEqual(set(self.colors_of(1, MK + " new one")), {self.c("comment")})

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