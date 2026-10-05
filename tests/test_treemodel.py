"""Unit tests for main/treemodel.py.

Run from the project root:
    python -m unittest discover tests
or directly:
    python tests/test_treemodel.py
"""
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "main"))

import treemodel as tm  # noqa: E402

# The example tree may live in main/ or data/ - use whichever exists.
EXAMPLE_CANDIDATES = [
    os.path.join(PROJECT_ROOT, "data", "example_project_tree.txt"),
    os.path.join(PROJECT_ROOT, "main", "example_project_tree.txt"),
]
EXAMPLE = next((p for p in EXAMPLE_CANDIDATES if os.path.isfile(p)), None)


class ParseRender(unittest.TestCase):
    @unittest.skipIf(EXAMPLE is None, "example_project_tree.txt not found in data/ or main/")
    def test_example_is_stable(self):
        with open(EXAMPLE, encoding="utf-8") as f:
            src = f.read()
        once = tm.format_text(src)
        self.assertEqual(once, tm.format_text(once))
        doc, _ = tm.parse(once)
        root = doc.root.children[0]
        self.assertEqual(root.name, "project-name/")
        self.assertEqual(root.children[0].name, "assets/")
        self.assertEqual(root.children[1].comment[1], "Invoices, receipts, subscriptions, tools paid,")

    def test_canonical_output(self):
        doc, _ = tm.parse("r/\n    a/  # A\n        b\n    c # C\n")
        text, _ = tm.render(doc)
        self.assertEqual(text.split("\n"), [
            "r/",
            "├── a/                            # A",
            "│   └── b",
            "└── c                             # C",
            "",
        ])

    def test_ascii_and_tabs(self):
        doc, _ = tm.parse("p\n|-- a\n|   `-- b\n`-- c")
        self.assertEqual([n.name for n in doc.iter_nodes()], ["p", "a", "b", "c"])
        self.assertEqual(doc.root.children[0].children[0].children[0].name, "b")

    def test_multiline_comment_and_gaps(self):
        src = "r/\n│\n├── a/     # one\n│          # two\n│\n└── b"
        doc, lm = tm.parse(src)
        a = doc.root.children[0].children[0]
        self.assertEqual(a.comment, ["one", "two"])
        self.assertEqual(a.gap_before, 1)
        self.assertEqual(doc.root.children[0].children[1].gap_before, 1)

    def test_fold_ranges(self):
        doc, lm = tm.parse("r/\n├── a/   # x\n│        # y\n│   └── f\n│\n└── b")
        self.assertEqual(lm.fold_ranges(), {0: (1, 5), 1: (3, 3)})


class Operations(unittest.TestCase):
    def setUp(self):
        self.doc, _ = tm.parse("r/\n├── a/\n│   └── a1\n├── b\n└── c")
        r = self.doc.root.children[0]
        self.a, self.b, self.c = r.children

    def names(self):
        return tm.render(self.doc)[0]

    def test_move(self):
        tm.move_up(self.b)
        self.assertEqual(self.names(), "r/\n├── b\n├── a/\n│   └── a1\n└── c")
        with self.assertRaises(tm.TreeError):
            tm.move_up(self.b)

    def test_indent_outdent(self):
        tm.indent(self.b)
        self.assertEqual(self.names(), "r/\n├── a/\n│   ├── a1\n│   └── b\n└── c")
        tm.outdent(self.b)
        self.assertEqual(self.names(), "r/\n├── a/\n│   └── a1\n├── b\n└── c")
        with self.assertRaises(tm.TreeError):
            tm.indent(self.a)

    def test_delete_duplicate(self):
        tm.duplicate(self.a)
        tm.delete(self.c)
        self.assertEqual(self.names(), "r/\n├── a/\n│   └── a1\n├── a/\n│   └── a1\n└── b")


class ExplanationColumns(unittest.TestCase):
    SRC = ("r/\n"
           "├── short                         # a\n"
           "├── a_very_long_name_here         # b\n"
           "└── mid                           # c")

    def setUp(self):
        self.doc, _ = tm.parse(self.SRC)
        self.nodes = list(self.doc.iter_nodes())[1:]

    def cols(self):
        text = tm.render(self.doc, preserve_columns=True)[0]
        return [line.index("#") for line in text.split("\n")[1:]]

    def test_parse_records_column(self):
        self.assertEqual([n.comment_col for n in self.nodes], [34, 34, 34])

    def test_move_left_until_text_then_others_stay_aligned(self):
        for _ in range(6):                        # 34 -> 28: all together
            tm.shift_comments(self.nodes, -1, 3)
        self.assertEqual(self.cols(), [28, 28, 28])
        tm.shift_comments(self.nodes, -1, 3)      # long name blocks at 28 (3 spaces)
        self.assertEqual(self.cols(), [27, 28, 27])
        text = tm.render(self.doc, preserve_columns=True)[0].split("\n")
        self.assertTrue(text[2].startswith("├── a_very_long_name_here   #"))
        while True:
            try:
                tm.shift_comments(self.nodes, -1, 3)
            except tm.TreeError:
                break
        self.assertEqual(self.cols(), [12, 28, 10])  # each 3 spaces after its text

    def test_move_right_realigns(self):
        while True:
            try:
                tm.shift_comments(self.nodes, -1, 3)
            except tm.TreeError:
                break
        tm.shift_comments(self.nodes, 1, 3)
        self.assertEqual(self.cols(), [12, 28, 11])
        tm.shift_comments(self.nodes, 1, 3)
        self.assertEqual(self.cols(), [12, 28, 12])  # unblocked lines aligned
        tm.shift_comments(self.nodes, 1, 3)
        self.assertEqual(self.cols(), [13, 28, 13])  # ...and move together
        for _ in range(15):
            tm.shift_comments(self.nodes, 1, 3)
        self.assertEqual(self.cols(), [28, 28, 28])
        tm.shift_comments(self.nodes, 1, 3)
        self.assertEqual(self.cols(), [29, 29, 29])  # then all move together

    def test_mixed_columns_converge(self):
        doc, _ = tm.parse("r/\n├── a     # x\n└── b                # y")
        nodes = list(doc.iter_nodes())[1:]
        tm.shift_comments(nodes, -1, 3)          # rightmost moves first
        self.assertEqual([n.comment_col for n in nodes], [10, 20])
        doc2, _ = tm.parse("r/\n├── a     # x\n└── b                # y")
        nodes2 = list(doc2.iter_nodes())[1:]
        tm.shift_comments(nodes2, 1, 3)          # leftmost moves first
        self.assertEqual([n.comment_col for n in nodes2], [11, 21])

    def test_multiline_explanation_moves_as_one(self):
        doc, _ = tm.parse("r/\n├── a/                    # one\n│                         # two\n└── b")
        a = doc.root.children[0].children[0]
        tm.shift_comments([a], 1, 3)
        lines = tm.render(doc, preserve_columns=True)[0].split("\n")
        self.assertEqual(lines[1].index("#"), lines[2].index("#"))
        self.assertEqual(lines[1].index("#"), 27)

    def test_no_explanations(self):
        doc, _ = tm.parse("r/\n└── a")
        with self.assertRaises(tm.TreeError):
            tm.shift_comments(list(doc.iter_nodes()), 1, 3)

    def test_preserve_is_stable_and_pushes_only_blocked_lines(self):
        text = tm.render(self.doc, preserve_columns=True)[0]
        self.assertEqual(tm.render(tm.parse(text)[0], preserve_columns=True)[0], text)
        self.nodes[0].name = "x" * 40               # name grows into its explanation
        cols = self.cols()
        self.assertEqual(cols, [4 + 40 + 3, 34, 34])

    def test_new_explanation_joins_sibling_column(self):
        for _ in range(4):
            tm.shift_comments(self.nodes, 1, 3)     # siblings now at 38
        new = tm.Node("new", ["fresh"])
        tm.add_sibling_after(self.nodes[2], new)
        self.assertEqual(self.cols(), [38, 38, 38, 38])

    def test_canonical_format_unchanged(self):
        for _ in range(4):
            tm.shift_comments(self.nodes, 1, 3)
        self.assertEqual(tm.render(self.doc)[0], self.SRC)



class Spacers(unittest.TestCase):
    SRC = "r/\n├── a/\n│   ├── a1\n│   └── a2\n├── b\n└── c"

    def setUp(self):
        self.doc, _ = tm.parse(self.SRC)
        self.r = self.doc.root.children[0]
        self.a, self.b, self.c = self.r.children

    def text(self):
        return tm.render(self.doc)[0]

    def test_between_siblings_keeps_vertical_line(self):
        tm.insert_spacer(self.doc, tm.node_after_subtree(self.a))      # before b
        self.assertEqual(self.text(), "r/\n├── a/\n│   ├── a1\n│   └── a2\n│\n├── b\n└── c")

    def test_inside_branch_keeps_both_lines(self):
        tm.insert_spacer(self.doc, self.a.children[1])                  # between a1 and a2
        self.assertEqual(self.text(), "r/\n├── a/\n│   ├── a1\n│   │\n│   └── a2\n├── b\n└── c")

    def test_after_last_child_goes_to_next_branch(self):
        self.assertIs(tm.node_after_subtree(self.a.children[1]), self.b)
        self.assertIsNone(tm.node_after_subtree(self.c))
        tm.insert_spacer(self.doc, None)
        self.assertEqual(self.text(), self.SRC + "\n")

    def test_spacers_round_trip(self):
        tm.insert_spacer(self.doc, self.a.children[0])
        tm.insert_spacer(self.doc, self.a.children[0])
        text = self.text()
        self.assertEqual(tm.format_text(text), text)
        self.assertIn("├── a/\n│   │\n│   │\n│   ├── a1", text)


if __name__ == "__main__":
    unittest.main()