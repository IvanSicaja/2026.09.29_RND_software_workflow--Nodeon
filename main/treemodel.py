"""
treemodel.py - pure-Python model for box-drawing tree text files (no GUI).

The file format (4 columns per level):

    project-name/
    │
    ├── assets/                       # explanation
    │   │
    │   ├── 01_media/                 # explanation
    │   └── 02_3d-modeling/           # explanation
    │                                 # explanation continues on a new line
    │
    └── README.md                     # explanation

* A line without a connector at column 0 is a top-level (root) node.
* "├── " / "└── " lines are branches; depth = column / 4 + 1.
* Lines containing only "│" / spaces are blank spacer lines ("gaps").
* A line that contains only guides followed by "#" continues the
  explanation of the branch above it.
* "name   # text" splits into the branch name and its explanation.

parse() is tolerant (accepts ASCII "|--", "`--", "+--", tabs, NBSP from
the `tree` command, indented text without connectors, uneven spacing).
render() always writes the canonical, perfectly aligned format.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

INDENT = 4
VERT = "│"
TEE = "├── "
ELBOW = "└── "
PIPE_PREFIX = VERT + " " * (INDENT - 1)
BLANK_PREFIX = " " * INDENT

KIND_NODE = "node"
KIND_COMMENT = "comment"
KIND_GAP = "gap"
KIND_PREAMBLE = "preamble"

_GUIDES = "│| "
_CONNECTOR_RE = re.compile(r"├──|└──|\|--|`--|\+--")
_COMMENT_SPLIT_RE = re.compile(r"\s#")


class TreeError(Exception):
    """Raised when a structural operation is not possible."""


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #
class Node:
    __slots__ = ("name", "comment", "children", "parent", "gap_before")

    def __init__(self, name: str = "", comment: Optional[List[str]] = None,
                 gap_before: int = 0) -> None:
        self.name: str = name
        self.comment: List[str] = list(comment) if comment else []
        self.children: List["Node"] = []
        self.parent: Optional["Node"] = None
        self.gap_before: int = gap_before

    def __repr__(self) -> str:
        return f"Node({self.name!r}, children={len(self.children)})"

    # -- relations ---------------------------------------------------------
    @property
    def depth(self) -> int:
        """Top-level nodes have depth 0; the invisible document root is -1."""
        d, n = -1, self.parent
        while n is not None:
            d += 1
            n = n.parent
        return d

    @property
    def index(self) -> int:
        if self.parent is None:
            return 0
        for i, c in enumerate(self.parent.children):
            if c is self:
                return i
        raise TreeError("Corrupted tree: node not found in its parent")

    def is_last(self) -> bool:
        return self.parent is None or self.parent.children[-1] is self

    def insert_child(self, index: int, child: "Node") -> None:
        child.parent = self
        self.children.insert(index, child)

    def append_child(self, child: "Node") -> None:
        self.insert_child(len(self.children), child)

    def detach(self) -> None:
        if self.parent is not None:
            del self.parent.children[self.index]
            self.parent = None

    def iter_preorder(self) -> Iterator["Node"]:
        stack = [self]
        while stack:
            n = stack.pop()
            yield n
            stack.extend(reversed(n.children))

    def descendant_count(self) -> int:
        return sum(1 for _ in self.iter_preorder()) - 1

    def is_ancestor_of(self, other: "Node") -> bool:
        n = other.parent
        while n is not None:
            if n is self:
                return True
            n = n.parent
        return False

    def clone(self) -> "Node":
        new = Node(self.name, self.comment, self.gap_before)
        stack = [(self, new)]
        while stack:
            src, dst = stack.pop()
            for c in src.children:
                cc = Node(c.name, c.comment, c.gap_before)
                dst.append_child(cc)
                stack.append((c, cc))
        return new

    def path(self) -> List[str]:
        out, n = [], self
        while n is not None and n.parent is not None:
            out.append(n.name)
            n = n.parent
        return list(reversed(out))


class TreeDocument:
    def __init__(self) -> None:
        self.root = Node("")          # invisible container, depth -1
        self.preamble: List[str] = []  # "#" lines before the first node
        self.trailing_blank = 0

    def iter_nodes(self) -> Iterator[Node]:
        it = self.root.iter_preorder()
        next(it)
        yield from it

    def is_empty(self) -> bool:
        return not self.root.children


@dataclass
class FormatOptions:
    min_comment_column: int = 34   # "#" never starts left of this column
    comment_gap: int = 3           # min spaces between longest name and "#"


# --------------------------------------------------------------------------- #
# Line map: which text line belongs to which node
# --------------------------------------------------------------------------- #
class LineMap:
    def __init__(self, doc: TreeDocument, kinds: List[str],
                 nodes: List[Optional[Node]], header: Dict[int, int],
                 name_col: Dict[int, int]) -> None:
        self.doc = doc
        self.kinds = kinds
        self.nodes = nodes
        self.header = header        # id(node) -> line of the node
        self.name_col = name_col    # id(node) -> column where its name starts
        self._ranges: Optional[Dict[int, Tuple[int, int]]] = None

    def __len__(self) -> int:
        return len(self.kinds)

    def node_at(self, line: int) -> Optional[Node]:
        """Node owning a branch line or explanation line (None for gaps)."""
        if 0 <= line < len(self.kinds) and self.kinds[line] in (KIND_NODE, KIND_COMMENT):
            return self.nodes[line]
        return None

    def node_near(self, line: int) -> Optional[Node]:
        """Like node_at, but a spacer line resolves to the branch below it."""
        if 0 <= line < len(self.kinds):
            return self.nodes[line]
        return None

    def line_of(self, node: Node) -> Optional[int]:
        return self.header.get(id(node))

    def fold_ranges(self) -> Dict[int, Tuple[int, int]]:
        """header line -> (first hidden line, last hidden line).

        Only branches with children are foldable. The branch line itself and
        its own explanation lines stay visible when folded."""
        if self._ranges is not None:
            return self._ranges
        own_end: Dict[int, int] = {}
        for i, (k, n) in enumerate(zip(self.kinds, self.nodes)):
            if n is not None and k in (KIND_NODE, KIND_COMMENT):
                own_end[id(n)] = i
        order = list(self.doc.iter_nodes())
        sub_end: Dict[int, int] = {}
        for n in reversed(order):
            e = own_end.get(id(n), -1)
            for c in n.children:
                e = max(e, sub_end.get(id(c), -1))
            sub_end[id(n)] = e
        ranges: Dict[int, Tuple[int, int]] = {}
        for n in order:
            if not n.children:
                continue
            h = self.header.get(id(n))
            if h is None:
                continue
            s, e = own_end[id(n)] + 1, sub_end[id(n)]
            if e >= s:
                ranges[h] = (s, e)
        self._ranges = ranges
        return ranges


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _lead(line: str) -> int:
    """Index of the first character after the vertical guides ("│", "|", " ")."""
    i, n = 0, len(line)
    while i < n and line[i] in _GUIDES and not _CONNECTOR_RE.match(line, i):
        i += 1
    return i


def _split_name(content: str) -> Tuple[str, List[str]]:
    content = content.strip()
    if content.startswith("#"):
        return "", [content[1:].strip()]
    m = _COMMENT_SPLIT_RE.search(content)
    if m:
        return content[:m.start()].rstrip(), [content[m.end():].strip()]
    return content, []


def parse(text: str) -> Tuple[TreeDocument, LineMap]:
    doc = TreeDocument()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    n_lines = len(lines)
    kinds = [KIND_GAP] * n_lines
    nodes: List[Optional[Node]] = [None] * n_lines
    header: Dict[int, int] = {}
    name_col: Dict[int, int] = {}

    stack: List[Node] = [doc.root]   # stack[k] = latest node at depth k-1
    last: Optional[Node] = None
    pending: List[int] = []

    for i, raw in enumerate(lines):
        line = raw.replace("\xa0", " ").expandtabs(INDENT).rstrip()
        if all(c in _GUIDES for c in line):
            pending.append(i)
            continue
        lead = _lead(line)
        m = _CONNECTOR_RE.match(line, lead)
        if m is not None:
            depth = (lead + INDENT // 2) // INDENT + 1
            content = line[m.end():]
            ncol = m.end() + (len(content) - len(content.lstrip(" ")))
        else:
            rest = line[lead:]
            if rest.startswith("#"):
                if last is not None:
                    for j in pending:
                        nodes[j] = last
                    pending = []
                    last.comment.append(rest[1:].strip())
                    kinds[i], nodes[i] = KIND_COMMENT, last
                else:
                    doc.preamble.append(line.strip())
                    kinds[i] = KIND_PREAMBLE
                continue
            depth = 0 if lead == 0 else max(1, (lead + INDENT // 2) // INDENT)
            content, ncol = rest, lead

        depth = min(depth, len(stack) - 1)
        name, comment = _split_name(content)
        node = Node(name, comment, gap_before=len(pending))
        for j in pending:
            nodes[j] = node
        pending = []
        stack[depth].append_child(node)
        del stack[depth + 1:]
        stack.append(node)
        kinds[i], nodes[i] = KIND_NODE, node
        header[id(node)] = i
        name_col[id(node)] = ncol
        last = node

    doc.trailing_blank = len(pending)
    return doc, LineMap(doc, kinds, nodes, header, name_col)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _with_comment(first: str, col: int, text: str) -> str:
    pad = max(1, col - len(first))
    return first + " " * pad + ("# " + text if text else "#")


def render(doc: TreeDocument, opts: Optional[FormatOptions] = None) -> Tuple[str, LineMap]:
    opts = opts or FormatOptions()
    out: List[str] = []
    kinds: List[str] = []
    nodes: List[Optional[Node]] = []
    header: Dict[int, int] = {}
    name_col: Dict[int, int] = {}

    def emit(text: str, kind: str, node: Optional[Node]) -> None:
        out.append(text)
        kinds.append(kind)
        nodes.append(node)

    for p in doc.preamble:
        emit(p, KIND_PREAMBLE, None)

    stack: List[Tuple[Node, str, int]] = []

    def push_children(parent: Node, prefix: str) -> None:
        kids = parent.children
        if not kids:
            return
        top = parent is doc.root
        lens = [len(k.name) if top else len(prefix) + INDENT + len(k.name) for k in kids]
        cols = [0] * len(kids)
        start = 0
        # Explanations of consecutive siblings (no spacer between) share a column.
        for i in range(1, len(kids) + 1):
            if i == len(kids) or kids[i].gap_before > 0:
                col = max(opts.min_comment_column, max(lens[start:i]) + opts.comment_gap)
                for j in range(start, i):
                    cols[j] = col
                start = i
        for k, col in reversed(list(zip(kids, cols))):
            stack.append((k, prefix, col))

    push_children(doc.root, "")
    while stack:
        node, prefix, col = stack.pop()
        top = node.parent is doc.root
        for _ in range(node.gap_before):
            emit("" if top else prefix + VERT, KIND_GAP, node)
        if top:
            first, child_prefix, ncol = node.name, "", 0
        else:
            last = node.is_last()
            first = prefix + (ELBOW if last else TEE) + node.name
            child_prefix = prefix + (BLANK_PREFIX if last else PIPE_PREFIX)
            ncol = len(prefix) + INDENT
        header[id(node)] = len(out)
        name_col[id(node)] = ncol
        emit(_with_comment(first, col, node.comment[0]) if node.comment else first,
             KIND_NODE, node)
        if len(node.comment) > 1:
            base = child_prefix + (VERT if node.children else "")
            for c in node.comment[1:]:
                emit(_with_comment(base, col, c), KIND_COMMENT, node)
        push_children(node, child_prefix)

    for _ in range(doc.trailing_blank):
        emit("", KIND_GAP, None)
    return "\n".join(out), LineMap(doc, kinds, nodes, header, name_col)


def format_text(text: str, opts: Optional[FormatOptions] = None) -> str:
    return render(parse(text)[0], opts)[0]


# --------------------------------------------------------------------------- #
# Structural operations
# --------------------------------------------------------------------------- #
def _require_parent(node: Node) -> Node:
    if node.parent is None:
        raise TreeError("This item has no parent")
    return node.parent


def add_sibling_after(node: Node, new: Node) -> Node:
    parent = _require_parent(node)
    parent.insert_child(node.index + 1, new)
    if parent.parent is None:            # new top-level item: keep a blank line
        new.gap_before = max(new.gap_before, 1)
    return new


def add_sibling_before(node: Node, new: Node) -> Node:
    parent = _require_parent(node)
    idx = node.index
    new.gap_before = node.gap_before
    if parent.parent is not None:        # blank line stays above the pair
        node.gap_before = 0
    parent.insert_child(idx, new)
    return new


def add_child(node: Node, new: Node, first: bool = False) -> Node:
    node.insert_child(0 if first else len(node.children), new)
    return new


def delete(node: Node) -> None:
    parent = _require_parent(node)
    idx = node.index
    if idx + 1 < len(parent.children):
        nxt = parent.children[idx + 1]
        nxt.gap_before = max(nxt.gap_before, node.gap_before)
    node.detach()


def move_up(node: Node) -> None:
    parent = _require_parent(node)
    i = node.index
    if i == 0:
        raise TreeError("Already the first item in its branch")
    sib = parent.children[i - 1]
    parent.children[i - 1], parent.children[i] = node, sib
    node.gap_before, sib.gap_before = sib.gap_before, node.gap_before


def move_down(node: Node) -> None:
    parent = _require_parent(node)
    i = node.index
    if i == len(parent.children) - 1:
        raise TreeError("Already the last item in its branch")
    move_up(parent.children[i + 1])


def indent(node: Node) -> None:
    """Make the node the last child of its previous sibling (move right)."""
    parent = _require_parent(node)
    i = node.index
    if i == 0:
        raise TreeError("Can't move right: there is no item above it on the same level")
    prev = parent.children[i - 1]
    node.detach()
    if not prev.children:
        node.gap_before = 0
    prev.append_child(node)


def outdent(node: Node) -> None:
    """Move the node one level left, right after its parent."""
    parent = _require_parent(node)
    grand = parent.parent
    if grand is None:
        raise TreeError("Can't move left: already a top-level item")
    idx = parent.index
    node.detach()
    grand.insert_child(idx + 1, node)
    if grand.parent is None:
        node.gap_before = max(node.gap_before, 1)


def duplicate(node: Node) -> Node:
    parent = _require_parent(node)
    c = node.clone()
    parent.insert_child(node.index + 1, c)
    return c


def previous_in_order(doc: TreeDocument, node: Node) -> Optional[Node]:
    prev = None
    for n in doc.iter_nodes():
        if n is node:
            return prev
        prev = n
    return None
