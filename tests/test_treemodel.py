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


if __name__ == "__main__":
    unittest.main()
