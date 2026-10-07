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

MK = "\u27a1\ufe0f"                       # explanation marker ➡️

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
            "├── a/                            " + MK + " A",
            "│   └── b",
            "└── c                             " + MK + " C",
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
        return [line.index(MK) for line in text.split("\n")[1:]]

    def test_parse_records_column(self):
        self.assertEqual([n.comment_col for n in self.nodes], [34, 34, 34])

    def test_move_left_until_text_then_others_stay_aligned(self):
        for _ in range(6):                        # 34 -> 28: all together
            tm.shift_comments(self.nodes, -1, 3)
        self.assertEqual(self.cols(), [28, 28, 28])
        tm.shift_comments(self.nodes, -1, 3)      # long name blocks at 28 (3 spaces)
        self.assertEqual(self.cols(), [27, 28, 27])
        text = tm.render(self.doc, preserve_columns=True)[0].split("\n")
        self.assertTrue(text[2].startswith("├── a_very_long_name_here   " + MK))
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
        self.assertEqual(lines[1].index(MK), lines[2].index(MK))
        self.assertEqual(lines[1].index(MK), 27)

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
        self.assertEqual(tm.render(self.doc)[0], self.SRC.replace("#", MK))



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



class NodeKeys(unittest.TestCase):
    def test_keys_are_paths_with_duplicate_numbers(self):
        doc, _ = tm.parse("r/\n├── a/\n│   └── x\n├── a/\n│   └── x\n└── b")
        keys = tm.node_keys(doc)
        nodes = list(doc.iter_nodes())
        self.assertEqual(keys[id(nodes[1])], (("r/", 0), ("a/", 0)))
        self.assertEqual(keys[id(nodes[3])], (("r/", 0), ("a/", 1)))
        self.assertEqual(keys[id(nodes[4])], (("r/", 0), ("a/", 1), ("x", 0)))
        self.assertEqual(len(set(keys.values())), len(nodes))

    def test_keys_stable_after_moving_siblings(self):
        doc, _ = tm.parse("r/\n├── a\n└── b")
        a = doc.root.children[0].children[0]
        before = tm.node_keys(doc)[id(a)]
        tm.move_down(a)
        self.assertEqual(tm.node_keys(doc)[id(a)], before)



class WordSpans(unittest.TestCase):
    def test_line_segments(self):
        t = "│   ├── 01_media/                 # Organized media resources"
        segs = {k: t[s:e] for k, s, e in tm.line_segments(t)}
        self.assertEqual(segs, {"name": "01_media/", "comment": "Organized media resources"})
        t = "│                                 # second line  "
        self.assertEqual([t[s:e] for _, s, e in tm.line_segments(t)], ["second line"])
        self.assertEqual(tm.line_segments("│   │"), [])
        self.assertEqual(tm.line_segments("├── "), [])
        t = "|-- a b   # c"
        self.assertEqual([t[s:e] for _, s, e in tm.line_segments(t)], ["a b", "c"])

    def test_add_merge_subtract(self):
        text = "Organized media resources"
        sp = tm.add_span([], "c0", 0, 9, 1, text)                 # Organized
        sp = tm.add_span(sp, "c0", 9, 15, 1, text)                # touching, same colour
        self.assertEqual(sp, [("c0", 0, 15, 1, "Organized media")])
        sp = tm.add_span(sp, "c0", 10, 15, 3, text)               # recolour "media"
        self.assertEqual(sorted(sp), [("c0", 0, 10, 1, "Organized "), ("c0", 10, 15, 3, "media")])
        sp = tm.subtract_range(sp, "c0", 2, 12)
        self.assertEqual(sorted(sp), [("c0", 0, 2, 1, "Or"), ("c0", 12, 15, 3, "dia")])
        sp = tm.add_span(sp, "name", 0, 3, 2, "abcdef")           # other segment untouched
        self.assertEqual(len(sp), 3)

    def test_is_covered(self):
        sp = [("c0", 0, 5, 1, "aaaaa"), ("c0", 5, 9, 1, "bbbb"), ("c0", 9, 12, 2, "ccc")]
        self.assertTrue(tm.is_covered(sp, "c0", 1, 9, 1))
        self.assertFalse(tm.is_covered(sp, "c0", 1, 10, 1))
        self.assertFalse(tm.is_covered(sp, "name", 0, 1, 1))

    def test_resolve_follows_text(self):
        sp = ("c0", 4, 9, 2, "media")
        self.assertEqual(tm.resolve_span(sp, "the media x"), sp)
        self.assertEqual(tm.resolve_span(sp, "new: the media x"), ("c0", 9, 14, 2, "media"))
        self.assertEqual(tm.resolve_span(sp, "media x media"), ("c0", 0, 5, 2, "media"))
        self.assertIsNone(tm.resolve_span(sp, "the medi_a x"))



class WordAtCursor(unittest.TestCase):
    T = "Additional project resources (non-code), etc. costs."

    def w(self, pos, text=None):
        text = self.T if text is None else text
        r = tm.word_at(text, pos)
        return text[r[0]:r[1]] if r else None

    def test_inside_and_borders(self):
        self.assertEqual(self.w(3), "Additional")           # inside
        self.assertEqual(self.w(0), "Additional")           # at the start
        self.assertEqual(self.w(10), "Additional")          # right after (left wins)
        self.assertEqual(self.w(11), "project")             # at the start of the next
        self.assertEqual(self.w(33), "non-code")            # inside brackets, with hyphen

    def test_punctuation_and_dots(self):
        self.assertEqual(self.w(43), "etc")                 # "etc." without the dot
        self.assertEqual(self.w(45), "etc")                 # cursor after the dot
        self.assertEqual(self.w(len(self.T)), "costs")      # end of line after "costs."
        self.assertEqual(self.w(4, "README.md"), "README.md")
        self.assertEqual(self.w(4, "01_media/"), "01_media/")

    def test_nothing_on_spaces_or_symbols(self):
        self.assertIsNone(self.w(2, "a    b"))
        self.assertIsNone(self.w(1, "   "))
        self.assertIsNone(self.w(0, ""))
        self.assertIsNone(self.w(1, "( )"))
        self.assertIsNone(self.w(99, "abc"))



class ArrowMarker(unittest.TestCase):
    def test_reads_arrow_plain_arrow_and_hash(self):
        for marker in (MK, "\u27a1", "#"):
            src = f"r/\n├── a/     {marker} one\n│          {marker} two\n└── b"
            doc, _ = tm.parse(src)
            a = doc.root.children[0].children[0]
            self.assertEqual((a.name, a.comment), ("a/", ["one", "two"]))
            self.assertEqual(a.comment_col, 11)

    def test_writes_arrow(self):
        out = tm.format_text("r/\n└── a  # x\n           # y")
        self.assertEqual(out.split("\n")[1:], ["└── a                             " + MK + " x",
                                              "                                  " + MK + " y"])
        self.assertNotIn("#", out)
        self.assertEqual(tm.format_text(out), out)                  # stable

    def test_explanation_alone_and_empty(self):
        doc, _ = tm.parse("r/\n└── " + MK + " only text")
        n = doc.root.children[0].children[0]
        self.assertEqual((n.name, n.comment), ("", ["only text"]))
        doc.root.children[0].children[0].comment = [""]
        self.assertTrue(tm.render(doc)[0].endswith(MK))

    def test_name_with_hash_inside_is_kept(self):
        doc, _ = tm.parse("r/\n└── C#-notes   " + MK + " x")
        n = doc.root.children[0].children[0]
        self.assertEqual((n.name, n.comment), ("C#-notes", ["x"]))

    def test_line_segments_with_arrow(self):
        t = "│   ├── 01_media/   " + MK + " Organized media"
        self.assertEqual({k: t[s:e] for k, s, e in tm.line_segments(t)},
                         {"name": "01_media/", "comment": "Organized media"})
        t = "│                   " + MK + " more text"
        self.assertEqual([t[s:e] for _, s, e in tm.line_segments(t)], ["more text"])


class DeleteRow(unittest.TestCase):
    SRC = "r/\n│\n├── a/   # x\n│        # y\n│   ├── a1\n│   └── a2\n├── b\n└── c"

    def setUp(self):
        self.doc, self.lm = tm.parse(self.SRC)
        self.r = self.doc.root.children[0]
        self.a, self.b, self.c = self.r.children

    def names(self):
        return [n.name for n in self.doc.iter_nodes()]

    def test_branch_row_keeps_sub_items(self):
        tm.delete_row(self.doc, tm.KIND_NODE, self.a)
        self.assertEqual(self.names(), ["r/", "a1", "a2", "b", "c"])
        self.assertEqual([n.parent for n in self.r.children], [self.r] * 4)
        self.assertEqual(self.r.children[0].gap_before, 1)          # spacer stays above

    def test_leaf_row(self):
        tm.delete_row(self.doc, tm.KIND_NODE, self.b)
        self.assertEqual(self.names(), ["r/", "a/", "a1", "a2", "c"])

    def test_explanation_row(self):
        tm.delete_row(self.doc, tm.KIND_COMMENT, self.a, comment_index=1)
        self.assertEqual(self.a.comment, ["x"])
        with self.assertRaises(tm.TreeError):
            tm.delete_row(self.doc, tm.KIND_COMMENT, self.a, comment_index=1)

    def test_spacer_and_trailing_rows(self):
        tm.delete_row(self.doc, tm.KIND_GAP, self.a)
        self.assertEqual(self.a.gap_before, 0)
        with self.assertRaises(tm.TreeError):
            tm.delete_row(self.doc, tm.KIND_GAP, self.a)
        self.doc.trailing_blank = 1
        tm.delete_row(self.doc, tm.KIND_GAP, None)
        self.assertEqual(self.doc.trailing_blank, 0)

    def test_text_is_exactly_one_row_shorter(self):
        before = tm.render(self.doc)[0].split("\n")
        tm.delete_row(self.doc, tm.KIND_NODE, self.c)
        after = tm.render(self.doc)[0].split("\n")
        self.assertEqual(len(after), len(before) - 1)


if __name__ == "__main__":
    unittest.main()