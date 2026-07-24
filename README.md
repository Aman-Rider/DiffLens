# DiffLens
file comparison of a directory
Directory Diff Report
Compare two directories file-by-file and produce a single, self-contained, interactive HTML report. Clicking any file opens a popup with a side-by-side diff — like the file compare view in VSCode or Notepad++.

Features
Recursive comparison of every file in both directories (including nested subfolders), using Python's standard-library difflib.
Side-by-side diff in a popup: left column = first directory (old, red), right column = second directory (new, green).
Character-level highlighting — only the exact changed characters are highlighted, so real differences stand out even on long lines.
Collapsible unchanged regions — long runs of identical lines fold into a clickable divider (Show N unchanged lines), with a few context lines kept visible next to each change.
Missing-file handling — files present in only one directory are flagged and their content is shown in the popup.
Binary-safe — non-text files are compared byte-for-byte instead of being rendered as garbled text.
Live filter to search the file list by name, plus summary counts.
Zero dependencies — pure Python standard library; the output HTML has no external assets.
Requirements
Python 3.6+ (no third-party packages required)
Usage
python3 dir_diff.py <dir1> <dir2> [-o output.html]
Examples
Compare two directories and write to a custom file:

python3 dir_diff.py ./old_config ./new_config -o result.html
Run with the built-in defaults (no arguments):

python3 dir_diff.py
When arguments are omitted, the hardcoded defaults near the top of dir_diff.py are used:

Constant	Default	Meaning
DEFAULT_DIR1	config	First (left) directory
DEFAULT_DIR2	config_1	Second (right) directory
DEFAULT_OUTPUT	compare_report.html	Output HTML file
Edit those constants in dir_diff.py to change the defaults.

Options
Option	Description
dir1	First (left) directory. Optional; uses default.
dir2	Second (right) directory. Optional; uses default.
-o, --output	Output HTML file path. Optional; uses default.
Output
The script prints a summary to the console and writes an HTML report:

Report written to: compare_report.html
Summary: 6 files | 1 identical | 3 modified | 1 only in left | 1 only in right
Open the generated .html file in any web browser. Each file is listed with a status badge:

Badge	Meaning
Identical	File contents match in both directories
Modified	File exists in both but contents differ
Only in <dir1>	File exists only in the first directory
Only in <dir2>	File exists only in the second directory
Click a file to open the diff popup. Use the filter box to narrow the list, and press Esc (or click outside) to close the popup.

How it works
Both directories are walked recursively and their file sets are merged.
Each file is classified: identical, modified, or present in only one side.
For modified text files, difflib.SequenceMatcher aligns the lines into two columns and computes character-level highlights for changed lines.
Long unchanged runs (more than _FOLD_MIN lines) are collapsed, keeping _FOLD_CONTEXT lines of context on each side.
Everything is rendered into one standalone HTML file with inline CSS and JS.
Tuning
Two constants in dir_diff.py control the folding behavior:

Constant	Default	Meaning
_FOLD_MIN	8	Unchanged runs longer than this get collapsed
_FOLD_CONTEXT	3	Context lines kept visible on each side of a fold
