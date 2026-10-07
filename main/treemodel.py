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
* A line that contains only guides followed by "➡️" continues the
  explanation of the branch above it.
* "name   ➡️ text" splits into the branch name and its explanation
  ("#" is normal text).

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
# Explanations start with the arrow "➡️" (U+27A1 + U+FE0F) - the only marker.
# The same arrow without the invisible emoji selector ("➡") is accepted too.
# "#" is ordinary text like every other character.
MARKER = "\u27a1\ufe0f"
_MARKER_PAT = "\u27a1\ufe0f?"
_MARKER_START_RE = re.compile(_MARKER_PAT)
_COMMENT_SPLIT_RE = re.compile(r"\s" + _MARKER_PAT)


def marker_at(text: str, pos: int = 0) -> int:
    """Length of the explanation marker starting at text[pos] (0 if none)."""
    m = _MARKER_START_RE.match(text, pos)
    return m.end() - pos if m else 0


class TreeError(Exception):
    """Raised when a structural operation is not possible."""


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #
class Node:
    __slots__ = ("name", "comment", "children", "parent", "gap_before", "comment_col")

    def __init__(self, name: str = "", comment: Optional[List[str]] = None,
                 gap_before: int = 0) -> None:
        self.name: str = name
        self.comment: List[str] = list(comment) if comment else []
        self.children: List["Node"] = []
        self.parent: Optional["Node"] = None
        self.gap_before: int = gap_before
        # Column of the "#" as it appears in the text (None = not placed yet).
        self.comment_col: Optional[int] = None

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
        new.comment_col = self.comment_col
        stack = [(self, new)]
        while stack:
            src, dst = stack.pop()
            for c in src.children:
                cc = Node(c.name, c.comment, c.gap_before)
                cc.comment_col = c.comment_col
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
        self.preamble: List[str] = []  # "➡️" lines before the first node
        self.trailing_blank = 0

    def iter_nodes(self) -> Iterator[Node]:
        it = self.root.iter_preorder()
        next(it)
        yield from it

    def is_empty(self) -> bool:
        return not self.root.children


@dataclass
class FormatOptions:
    min_comment_column: int = 34   # "➡️" never starts left of this column
    comment_gap: int = 3           # min spaces between longest name and "➡️"


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


def _hash_index(content: str) -> int:
    """Index of the "➡️" that starts the explanation (-1 if none)."""
    stripped = content.lstrip()
    offset = len(content) - len(stripped)
    if marker_at(stripped):
        return offset
    m = _COMMENT_SPLIT_RE.search(stripped)
    return offset + m.start() + 1 if m else -1


def _split_name(content: str) -> Tuple[str, List[str]]:
    content = content.strip()
    k = marker_at(content)
    if k:
        return "", [content[k:].strip()]
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
            cstart = m.end()
            ncol = m.end() + (len(content) - len(content.lstrip(" ")))
        else:
            rest = line[lead:]
            k = marker_at(rest)
            if k:
                if last is not None:
                    for j in pending:
                        nodes[j] = last
                    pending = []
                    last.comment.append(rest[k:].strip())
                    kinds[i], nodes[i] = KIND_COMMENT, last
                else:
                    doc.preamble.append(line.strip())
                    kinds[i] = KIND_PREAMBLE
                continue
            depth = 0 if lead == 0 else max(1, (lead + INDENT // 2) // INDENT)
            content, ncol, cstart = rest, lead, lead

        depth = min(depth, len(stack) - 1)
        name, comment = _split_name(content)
        node = Node(name, comment, gap_before=len(pending))
        if comment:
            node.comment_col = cstart + _hash_index(content)
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
    return first + " " * pad + (MARKER + " " + text if text else MARKER)


def first_line_length(node: Node) -> int:
    """Length of "prefix + connector + name" of the node's line."""
    d = node.depth
    return len(node.name) if d <= 0 else INDENT * d + len(node.name)


def comment_min_col(node: Node, gap: int) -> int:
    """Leftmost allowed "➡️" column: `gap` spaces after the longest text on any
    line of the node's explanation (the name line or the continuation guides)."""
    d = node.depth
    longest = first_line_length(node)
    if len(node.comment) > 1:
        cont = (INDENT * d if d > 0 else 0) + (1 if node.children else 0)
        longest = max(longest, cont)
    return longest + gap


def _most_common(values: List[int]) -> int:
    counts: Dict[int, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts, key=lambda v: (counts[v], v))


def render(doc: TreeDocument, opts: Optional[FormatOptions] = None,
           preserve_columns: bool = False) -> Tuple[str, LineMap]:
    """Render the canonical text.

    preserve_columns=False: explanations of consecutive siblings are aligned
    automatically (Format document).
    preserve_columns=True: every explanation keeps its current column and is
    only pushed right when its own text would touch it; new explanations join
    the column used by their siblings."""
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
                if preserve_columns:
                    block = kids[start:i]
                    placed = [k.comment_col for k in block
                              if k.comment and k.comment_col is not None]
                    base = _most_common(placed) if placed else col
                    for j, k in enumerate(block, start):
                        own = k.comment_col if (k.comment and k.comment_col is not None) else base
                        cols[j] = max(own, comment_min_col(k, opts.comment_gap))
                else:
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
        if node.comment:
            node.comment_col = max(col, len(first) + 1)
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


def node_after_subtree(node: Node) -> Optional[Node]:
    """First node below the node and all of its sub-items (None at the end)."""
    n = node
    while n.parent is not None:
        p = n.parent
        i = n.index
        if i + 1 < len(p.children):
            return p.children[i + 1]
        n = p
    return None


def insert_spacer(doc: TreeDocument, before: Optional[Node]) -> None:
    """Insert one empty spacer line right above `before` (at its level, the
    vertical lines on the left are kept). None = at the end of the document."""
    if before is None:
        doc.trailing_blank += 1
    else:
        before.gap_before += 1


NodeKey = Tuple[Tuple[str, int], ...]


def node_keys(doc: TreeDocument) -> Dict[int, NodeKey]:
    """id(node) -> stable key: the names from the top down, each with its
    occurrence number among same-named siblings (so duplicates stay distinct)."""
    keys: Dict[int, NodeKey] = {}
    stack: List[Tuple[Node, NodeKey]] = [(doc.root, ())]
    while stack:
        parent, pkey = stack.pop()
        seen: Dict[str, int] = {}
        for c in parent.children:
            nth = seen.get(c.name, 0)
            seen[c.name] = nth + 1
            key = pkey + ((c.name, nth),)
            keys[id(c)] = key
            stack.append((c, key))
    return keys


def previous_in_order(doc: TreeDocument, node: Node) -> Optional[Node]:
    prev = None
    for n in doc.iter_nodes():
        if n is node:
            return prev
        prev = n
    return None


def shift_comments(nodes: List[Node], direction: int, gap: int) -> int:
    """Move the explanations of `nodes` one column left (-1) or right (+1).

    Rules:
    * Every explanation keeps at least `gap` spaces after the text of its line.
    * Moving right: the leftmost explanations move first until they reach the
      others, so explanations always end up in one vertical column; when all
      are aligned they move right together.
    * Moving left: the rightmost explanations that can still move go one
      column left; explanations that reach their text stop there, all the
      others stay aligned with each other.

    Returns the new alignment column. Raises TreeError if nothing can move.
    """
    units = [n for n in nodes if n.comment]
    if not units:
        raise TreeError("No explanations (➡️) in the selection")
    mins = {id(n): comment_min_col(n, gap) for n in units}
    cur = {id(n): max(n.comment_col if n.comment_col is not None else 0, mins[id(n)])
           for n in units}
    if direction > 0:
        target = min(cur.values()) + 1
        for n in units:
            n.comment_col = max(cur[id(n)], target)
        return target
    movable = [cur[id(n)] for n in units if cur[id(n)] > mins[id(n)]]
    if not movable:
        raise TreeError("Explanations are already as close to the text as possible")
    target = max(movable) - 1
    for n in units:
        n.comment_col = max(min(cur[id(n)], target), mins[id(n)])
    return target


# --------------------------------------------------------------------------- #
# Coloured character ranges ("spans") inside names and explanations
# --------------------------------------------------------------------------- #
# A span lives in one *segment* of a branch: "name" (the branch name) or
# "c0", "c1", ... (the 1st, 2nd, ... explanation line). start/end are relative
# to the segment text, and the marked text is remembered so the colour can
# follow the words if the text around them changes.
Span = Tuple[str, int, int, int, str]          # (segment, start, end, mark, text)

_LINE_GUIDES = "│| \t\xa0"


def line_segments(text: str) -> List[Tuple[str, int, int]]:
    """Positions of the name text and the explanation text in one line:
    [("name", start, end), ("comment", start, end)] (empty parts omitted)."""
    n = len(text)
    i = 0
    while i < n and text[i] in _LINE_GUIDES and not _CONNECTOR_RE.match(text, i):
        i += 1
    m = _CONNECTOR_RE.match(text, i)
    if m:
        i = m.end()
    out: List[Tuple[str, int, int]] = []
    rest = text[i:]
    stripped = rest.lstrip()
    if marker_at(stripped):
        hash_pos = i + len(rest) - len(stripped)
    else:
        hm = _COMMENT_SPLIT_RE.search(rest)
        hash_pos = i + hm.start() + 1 if hm else -1
        name_end = hash_pos if hash_pos >= 0 else n
        ns = i
        while ns < name_end and text[ns] in " \t":
            ns += 1
        ne = name_end
        while ne > ns and text[ne - 1] in " \t":
            ne -= 1
        if ne > ns:
            out.append(("name", ns, ne))
    if hash_pos >= 0:
        cs = hash_pos + max(1, marker_at(text, hash_pos))
        while cs < n and text[cs] in " \t":
            cs += 1
        ce = n
        while ce > cs and text[ce - 1] in " \t":
            ce -= 1
        if ce > cs:
            out.append(("comment", cs, ce))
    return out


def subtract_range(spans: List[Span], seg: str, a: int, b: int) -> List[Span]:
    """Remove the range [a, b) of segment `seg` from the spans (cutting spans
    that only partly overlap)."""
    out: List[Span] = []
    for sp in spans:
        sg, s, e, mark, text = sp
        if sg != seg or e <= a or s >= b:
            out.append(sp)
            continue
        if s < a:
            out.append((sg, s, a, mark, text[: a - s]))
        if e > b:
            out.append((sg, b, e, mark, text[b - s:]))
    return out


def add_span(spans: List[Span], seg: str, a: int, b: int, mark: int,
             seg_text: str) -> List[Span]:
    """Colour [a, b) of a segment (replacing whatever was there) and merge it
    with touching spans of the same colour."""
    a, b = max(0, a), min(len(seg_text), b)
    out = subtract_range(spans, seg, a, b)
    if b <= a:
        return out
    same = sorted([sp for sp in out if sp[0] == seg] + [(seg, a, b, mark, seg_text[a:b])],
                  key=lambda sp: sp[1])
    merged: List[Span] = []
    for sp in same:
        if merged and merged[-1][3] == sp[3] and sp[1] <= merged[-1][2]:
            _, s, e, m, _ = merged[-1]
            e = max(e, sp[2])
            merged[-1] = (seg, s, e, m, seg_text[s:e])
        else:
            merged.append(sp)
    return [sp for sp in out if sp[0] != seg] + merged


def is_covered(spans: List[Span], seg: str, a: int, b: int, mark: int) -> bool:
    """True if every character of [a, b) already has colour `mark`."""
    pos = a
    for _, s, e, _, _ in sorted((sp for sp in spans if sp[0] == seg and sp[3] == mark),
                                key=lambda sp: sp[1]):
        if s > pos:
            break
        pos = max(pos, e)
        if pos >= b:
            return True
    return pos >= b


def resolve_span(span: Span, seg_text: str) -> Optional[Span]:
    """Find the span's text in the (possibly edited) segment: at the same place,
    or else the nearest occurrence. None if the words are gone."""
    seg, s, e, mark, text = span
    if not text:
        return None
    if seg_text[s:e] == text:
        return span
    best, i = None, seg_text.find(text)
    while i >= 0:
        if best is None or abs(i - s) < abs(best - s):
            best = i
        i = seg_text.find(text, i + 1)
    if best is None:
        return None
    return (seg, best, best + len(text), mark, text)


# A "word" for colouring at the cursor: letters, digits and joined symbols such
# as 01_media/, README.md or non-code; spaces and brackets/punctuation split.
_WORD_RE = re.compile(r"[^\s,;:!?()\[\]{}<>\"“”‘’«»]+")


def word_at(text: str, pos: int) -> Optional[Tuple[int, int]]:
    """(start, end) of the word at cursor position `pos` in `text`, or None
    when the cursor is not touching a word. Inside a word wins; at a border
    the word on the left is preferred (like most editors)."""
    if not 0 <= pos <= len(text):
        return None
    left = right = None
    for m in _WORD_RE.finditer(text):
        s, e = m.start(), m.end()
        full_end = e
        while e > s + 1 and text[e - 1] == "." and "." not in text[s:e - 1]:
            e -= 1                                   # "etc." -> "etc", "costs." -> "costs"
        if s < pos < e:
            return s, e
        if pos in (e, full_end):
            left = (s, e)
        elif s == pos and right is None:
            right = (s, e)
        if s > pos:
            break
    return left or right



def delete_row(doc: TreeDocument, kind: str, node: Optional[Node],
               comment_index: int = 0, preamble_index: int = 0) -> None:
    """Delete exactly one row of the text.

    * branch row: the branch is removed; its sub-items stay and move up one
      level into its place (nothing below it is lost). Its explanation goes
      with it (it has nothing left to explain).
    * explanation row (2nd, 3rd ... line): only that explanation line.
    * empty spacer row: one spacer line.
    * text row above the tree: that row.
    """
    if kind == KIND_NODE and node is not None:
        parent = _require_parent(node)
        idx = node.index
        kids = list(node.children)
        node.detach()
        for offset, kid in enumerate(kids):
            parent.insert_child(idx + offset, kid)
        follower = parent.children[idx] if idx < len(parent.children) else None
        if follower is not None:
            follower.gap_before = max(follower.gap_before, node.gap_before)
        node.children = []
    elif kind == KIND_COMMENT and node is not None:
        if not 1 <= comment_index < len(node.comment):
            raise TreeError("This explanation line no longer exists")
        del node.comment[comment_index]
    elif kind == KIND_GAP:
        if node is not None:
            if node.gap_before <= 0:
                raise TreeError("Nothing to delete here")
            node.gap_before -= 1
        else:
            if doc.trailing_blank <= 0:
                raise TreeError("Nothing to delete here")
            doc.trailing_blank -= 1
    elif kind == KIND_PREAMBLE:
        if not 0 <= preamble_index < len(doc.preamble):
            raise TreeError("Nothing to delete here")
        del doc.preamble[preamble_index]
    else:
        raise TreeError("Nothing to delete here")