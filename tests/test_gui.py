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
    from PySide6.QtGui import QTextCursor
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