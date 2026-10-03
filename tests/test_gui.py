"""GUI tests for main/Nodeon.py (runs headless, no window appears).

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
    import Nodeon as app_module
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


if __name__ == "__main__":
    unittest.main()