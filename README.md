# Nodeon

A PyCharm-style editor for plain-text structure trees. Files stay **pure UTF-8 `.txt`**
with `│ ├── └──` lines and `➡️` explanations. Only `➡️` starts an explanation;
`#` is ordinary text like every other character.

## Run

From the project root:

```
pip install -r requirements.txt
python main/main.py                                   # new tree
python main/main.py data/example_project_tree.txt     # open a file
```
In PyCharm: open `main/main.py` and press Run. You can also drag a .txt file onto the window.

Every toolbar button shows its keyboard shortcut underneath (hover for a longer description).

## Project files

| File | Purpose |
|---|---|
| `main/main.py` | The Nodeon application (window, toolbar, folding, shortcuts). **Start this.** |
| `main/treemodel.py` | Required by main.py: reads, formats and edits the tree. Must stay next to main.py. |
| `data/example_project_tree.txt` | Example tree to open in Nodeon. |
| `tests/test_treemodel.py` | Tests for the tree logic and explanation alignment |
| `<name>.txt.marks.json` | Created next to a tree when you use colour marks. |
| `tests/test_gui.py` | Tests that drive the real app with keystrokes (headless, settings untouched) |
| `requirements.txt` | Python dependencies (PySide6). |

## Folding

| Action | How |
|---|---|
| Collapse all / Expand all | `Alt+1` / `Alt+4` |
| Collapse one level / Expand one level (whole document) | `Alt+2` / `Alt+3` |
| Show exactly N levels | `Ctrl+1` … `Ctrl+9`, or the **Levels** box |
| Toggle one branch | click ▼/▶ next to the line number, or `Ctrl+.` |
| Collapse / expand a branch with everything inside | `Alt`+click the arrow, or `Ctrl+Shift+.` / `Ctrl+Shift+,` |
| Open a folded branch | click its `⋯ N items` badge |

## Editing

| Action | How |
|---|---|
| New item on the same level | `Enter` at the end of a name, or `Ctrl+Enter` |
| New sub-item | `Ctrl+Shift+Enter` (Enter on an open branch also adds a first sub-item) |
| Insert empty line (vertical branch lines kept) | `Alt+Enter` (press again for more; `Ctrl+Z` to undo) |
| Move right / left one level | `Tab` / `Shift+Tab` (or `Alt+Shift+→ / ←`) |
| Move up / down (with all sub-items) | `Alt+Shift+↑ / ↓` |
| Explanation: add or edit (and the name) | `Ctrl+Shift+E` (explanation only: `Ctrl+E`) |
| Duplicate / delete a branch | `Ctrl+D` / `Ctrl+Shift+Delete` |
| Paste several lines (from PDF, Word, web) | `Ctrl+V` – the first line goes where the cursor is, every further line becomes its own branch on the **same level** right below (inside an explanation: further explanation lines). Empty lines are skipped; the tree below stays intact; one `Ctrl+Z` undoes it |
| Column selection on / off (like PyCharm) | `Alt+Shift+Insert` or the **Column select** button. Then `Shift+arrows` or drag with the mouse to select a rectangle over several lines; typing, `Tab` / `Shift+Tab`, `Backspace`, `Delete`, copy, cut and paste work on every row at once. `Esc` ends the rectangle; the status bar shows **COLUMN** while the mode is on |
| Delete only the line at the cursor | `Ctrl+Q` – sub-items stay and move up one level; on an explanation or empty line only that line is deleted |
| Finish a list | `Enter` on an empty item moves it one level left; `Backspace` removes it |
| Split a name | `Enter` in the middle of a name |
| Plain newline | `Shift+Enter` |
| Move explanations left / right | `Alt+←` / `Alt+→` (selected lines, or the whole document if nothing is selected) |
| Format document (auto-align all explanations) | `Ctrl+Alt+L` |
| Find | `Ctrl+F`, `F3`, `Shift+F3` (folded branches open automatically) |

Press `F1` in the app for the full shortcut list.

## Colour marks (track what you explored)

Colour only the **name** of a branch (tree lines and explanations stay as they are):

| Mark | Shortcut |
|---|---|
| Checked / OK (green) | `Alt+G` |
| To explore (orange) | `Alt+O` |
| Problem (red) | `Alt+R` |
| Default colour (remove mark) | `Alt+C` (or press the same key again) |

Works on the line at the cursor or on every branch in a selection.
Toolbar: **Mark line** (whole name, `Alt+G/O/R/C`) and **Mark words** (word at the cursor or
selection, `Alt+Shift+G/O/R/C`); `C` = back to the default text colour. With the cursor on a space or a tree line nothing is coloured.

**Colour only words** – put the cursor on a word (no selection needed), or select exact
characters with the mouse or Shift+arrows, and add **Shift**: `Alt+Shift+G` (green), `Alt+Shift+O` (orange), `Alt+Shift+R` (red),
`Alt+Shift+C` (default colour – also works on a word inside a name that has a whole-line colour). Same colours as above; works in names and explanations, over
several lines, and never colours the tree lines. The colour stays on the words when you
move branches, move explanations or edit other parts of the line; if you change the
coloured word itself, its colour disappears (`Ctrl+Z` brings it back). Also in the toolbar
(**Mark**), the Tree menu and the right-click menu. Marks follow a branch when you move it.

The `.txt` stays pure text: marks are saved automatically in a small file next to it,
`<name>.txt.marks.json`. Keep it with the `.txt` when you copy or share the tree.
Explanations (`➡️`) are always shown in their own violet colour; they can never be
coloured – the colour marks work on branch names only.

## Explanation alignment

`Alt+→` / `Alt+←` move the `➡️` explanations of the selected lines (or the whole document):

* Every explanation always keeps **at least 3 spaces** after the text of its line.
* **Moving left:** all explanations move together in one column; one that reaches its
  text stops there (3 spaces after it), the others stay aligned and keep moving.
* **Moving right:** explanations held back by their text are picked up as the column
  reaches them, so everything ends up in one vertical column, then moves together.
* A multi-line explanation always moves as one block.
* Your columns are kept when you save and when you add, move or edit branches.
  `Ctrl+Alt+L` (Format document) re-aligns everything automatically, as before.

## Tests

```
python -m unittest discover tests
```

## Troubleshooting

**"treemodel.py was not found / is empty / is not Nodeon's file"** – `main.py` always loads
the `treemodel.py` that sits in the **same folder** (`main/`). Make sure:

* `main/treemodel.py` exists, is not empty, and starts with
  `"""treemodel.py - pure-Python model for box-drawing tree text files`.
* It is not a copy of `main.py` (both files are needed, with different content).
* `main.py` and `treemodel.py` come from the same version (replace both together).

`__pycache__/` folders can always be deleted safely; Python recreates them.