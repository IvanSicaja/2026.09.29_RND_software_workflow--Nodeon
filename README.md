# Tree Editor

A PyCharm-style editor for plain-text structure trees. Files stay **pure UTF-8 `.txt`**
in exactly this format (4 columns per level, explanations after `#`):

```
project-name/
│
├── assets/                       # Additional project resources
│   ├── 01_media/                 # Organized media resources
│   └── 02_3d-modeling/           # 3D objects
│                                 # CAD files, simulation models, renders
└── README.md                     # Project overview
```

## Run

```
pip install -r requirements.txt
python tree_editor.py                          # new tree
python tree_editor.py example_project_tree.txt # open a file
```
You can also drag a .txt file onto the window.

## Folding

| Action | How |
|---|---|
| Collapse all / Expand all | `Alt+1` / `Alt+4` (toolbar: ⊟ / ⊞) |
| Collapse one level / Expand one level (whole document) | `Alt+2` / `Alt+3` (toolbar: − Level / + Level) |
| Show exactly N levels | `Ctrl+1` … `Ctrl+9`, or the **Levels** box |
| Toggle one branch | click ▼/▶ next to the line number, or `Ctrl+.` |
| Collapse / expand a branch with everything inside | `Alt`+click the arrow, or `Ctrl+Shift+.` / `Ctrl+Shift+,` |
| Open a folded branch | click its `⋯ N items` badge |

"One level" is document-wide and standardizing: every branch ends up showing the
same number of levels, so a mixed state becomes a clean overview.

## Editing

| Action | How |
|---|---|
| New item on the same level | `Enter` at the end of a name, or `Ctrl+Enter` |
| New sub-item | `Ctrl+Shift+Enter` (Enter on an open branch also adds a first sub-item) |
| Move right / left one level | `Tab` / `Shift+Tab` (or `Alt+Shift+→ / ←`) |
| Move up / down (with all sub-items) | `Alt+Shift+↑ / ↓` |
| Edit name & explanation | `F2` (explanation only: `Ctrl+E`); each explanation line becomes a `#` line |
| Duplicate / delete a branch | `Ctrl+D` / `Ctrl+Shift+Delete` |
| Finish a list | `Enter` on an empty item moves it one level left; `Backspace` removes it |
| Split a name | `Enter` in the middle of a name |
| Plain newline | `Shift+Enter` |
| Format document | `Ctrl+Alt+L` (also automatic on save; can be turned off in Settings) |
| Find | `Ctrl+F`, `F3`, `Shift+F3` (folded branches open automatically) |

Every structural action redraws all `│ ├── └──` lines and re-aligns explanations,
and is a single `Ctrl+Z` undo step. You can also type freely like in any text
editor; indented names without connectors (or ASCII `|--`, `` `-- ``) are
understood and fixed by **Format**.

Explanation alignment: `#` starts at column 34 at minimum; siblings written
together (no blank `│` line between them) share one column so long names never
break alignment. Both numbers are in **View → Settings**.

## Files
* `tree_editor.py` – the application
* `treemodel.py` – parser/formatter/tree operations (no GUI, reusable)
* `test_treemodel.py` – `python -m unittest test_treemodel.py`
* `example_project_tree.txt` – your project structure

Saving is atomic (temp file + rename), keeps the file's line endings (LF/CRLF),
and asks before discarding unsaved changes.
