#!/usr/bin/env python3
"""
Compare files between two directories and produce an interactive HTML report.

Usage:
    python dir_diff.py [dir1] [dir2] [-o output.html]

If dir1 / dir2 are omitted, the hardcoded defaults (DEFAULT_DIR1 / DEFAULT_DIR2
near the top of this file) are used.

The report lists every file found in either directory. Clicking a file opens a
popup showing:
  * a side-by-side / unified diff when the file exists in both directories,
  * a "missing in ..." message when the file is present in only one directory,
  * an "identical" note when the contents match.
"""

import argparse
import difflib
import html
import json
import os
import sys
from pathlib import Path


# --------------------------------------------------------------------------- #
# Hardcoded defaults (used when the corresponding argument is not provided)
# --------------------------------------------------------------------------- #
DEFAULT_DIR1 = "config"
DEFAULT_DIR2 = "config_1"
DEFAULT_OUTPUT = "compare_report.html"


# --------------------------------------------------------------------------- #
# File collection helpers
# --------------------------------------------------------------------------- #
def collect_files(root: Path) -> set:
    """Return a set of file paths relative to *root* (recursively)."""
    files = set()
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = Path(dirpath) / name
            files.add(full.relative_to(root).as_posix())
    return files


def read_lines(path: Path):
    """Read a file as text lines. Returns (lines, is_binary)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.readlines(), False
    except UnicodeDecodeError:
        # Treat undecodable files as binary.
        return [], True
    except OSError as exc:
        return [f"<could not read file: {exc}>"], False


# --------------------------------------------------------------------------- #
# Diff computation
# --------------------------------------------------------------------------- #
def compare_file(rel: str, dir1: Path, dir2: Path) -> dict:
    """Build a result dict describing the comparison of one relative path."""
    p1 = dir1 / rel
    p2 = dir2 / rel
    in1 = p1.is_file()
    in2 = p2.is_file()

    result = {
        "name": rel,
        "in1": in1,
        "in2": in2,
        "status": "",
        "diff_html": "",
    }

    if in1 and not in2:
        result["status"] = "only-left"
        result["diff_html"] = _missing_block(rel, dir1.name, dir2.name, p1)
        return result

    if in2 and not in1:
        result["status"] = "only-right"
        result["diff_html"] = _missing_block(rel, dir2.name, dir1.name, p2, missing_side="left")
        return result

    # Present in both -> compute diff.
    lines1, bin1 = read_lines(p1)
    lines2, bin2 = read_lines(p2)

    if bin1 or bin2:
        same = _files_equal_bytes(p1, p2)
        result["status"] = "same" if same else "modified"
        if same:
            result["diff_html"] = _note_block(
                f"Binary file identical in both directories: {html.escape(rel)}"
            )
        else:
            result["diff_html"] = _note_block(
                f"Binary files differ (byte comparison): {html.escape(rel)}"
            )
        return result

    if lines1 == lines2:
        result["status"] = "same"
        result["diff_html"] = _note_block(
            f"Files are identical: {html.escape(rel)}"
        )
        return result

    result["status"] = "modified"
    result["diff_html"] = _diff_block(rel, dir1.name, dir2.name, lines1, lines2)
    return result


def _files_equal_bytes(p1: Path, p2: Path) -> bool:
    try:
        return p1.read_bytes() == p2.read_bytes()
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# HTML fragment builders
# --------------------------------------------------------------------------- #
def _note_block(message: str) -> str:
    return f'<div class="note">{message}</div>'


def _missing_block(rel, present_dir, missing_dir, path, missing_side="right") -> str:
    lines, is_bin = read_lines(path)
    header = (
        f'<div class="note warn">File <b>{html.escape(rel)}</b> exists in '
        f'<b>{html.escape(present_dir)}</b> but is <b>missing</b> in '
        f'<b>{html.escape(missing_dir)}</b>.</div>'
    )
    if is_bin:
        return header + _note_block("(binary content not shown)")

    body_rows = []
    for i, line in enumerate(lines, 1):
        body_rows.append(
            f'<tr><td class="ln">{i}</td>'
            f'<td class="add">{html.escape(line.rstrip(chr(10)))}</td></tr>'
        )
    table = (
        '<table class="difftable"><thead><tr><th>#</th>'
        f'<th>Content ({html.escape(present_dir)})</th></tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody></table>'
    )
    return header + table


def _plain(text):
    """Escape one line for a diff cell (empty -> non-breaking space)."""
    escaped = html.escape(text.rstrip("\n"))
    return escaped if escaped else "&nbsp;"


def _inline_pair(left_line, right_line):
    """
    Character-level diff of two lines. Returns (left_html, right_html) where the
    exact changed segments are wrapped in a highlight span, so only the real
    differences stand out (VSCode-style).
    """
    left_raw = left_line.rstrip("\n")
    right_raw = right_line.rstrip("\n")
    sm = difflib.SequenceMatcher(a=left_raw, b=right_raw, autojunk=False)

    left_parts, right_parts = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        lseg = html.escape(left_raw[i1:i2])
        rseg = html.escape(right_raw[j1:j2])
        if tag == "equal":
            left_parts.append(lseg)
            right_parts.append(rseg)
        else:
            if lseg:
                left_parts.append(f'<span class="hl-del">{lseg}</span>')
            if rseg:
                right_parts.append(f'<span class="hl-add">{rseg}</span>')

    lhtml = "".join(left_parts) or "&nbsp;"
    rhtml = "".join(right_parts) or "&nbsp;"
    return lhtml, rhtml


# Unchanged runs longer than this get collapsed; a few context lines are kept
# visible on each side of the fold.
_FOLD_MIN = 8
_FOLD_CONTEXT = 3
_fold_counter = [0]


def _diff_block(rel, name1, name2, lines1, lines2) -> str:
    """Return an HTML side-by-side diff table (left = name1, right = name2)."""
    sm = difflib.SequenceMatcher(a=lines1, b=lines2, autojunk=False)
    rows = []

    def add_row(ln, lcls, ltext, rn, rcls, rtext, tr_class=""):
        lno = str(ln) if ln is not None else ""
        rno = str(rn) if rn is not None else ""
        lmark = "-" if lcls == "del" else ""
        rmark = "+" if rcls == "add" else ""
        cls_attr = f' class="{tr_class}"' if tr_class else ""
        rows.append(
            f'<tr{cls_attr}>'
            f'<td class="ln">{lno}</td>'
            f'<td class="side {lcls}"><span class="marker">{lmark}</span>{ltext}</td>'
            f'<td class="ln">{rno}</td>'
            f'<td class="side {rcls}"><span class="marker">{rmark}</span>{rtext}</td>'
            f'</tr>'
        )

    def add_equal(li, ri, tr_class=""):
        add_row(li + 1, "ctx", _plain(lines1[li]),
                ri + 1, "ctx", _plain(lines2[ri]), tr_class=tr_class)

    def emit_equal(i1, i2, j1, j2, is_first, is_last):
        n = i2 - i1
        if n <= _FOLD_MIN:
            for k in range(n):
                add_equal(i1 + k, j1 + k)
            return

        # Keep context lines next to real changes; fold the middle.
        top = 0 if is_first else _FOLD_CONTEXT
        bottom = 0 if is_last else _FOLD_CONTEXT
        hidden_count = n - top - bottom
        if hidden_count < 2:  # not worth folding
            for k in range(n):
                add_equal(i1 + k, j1 + k)
            return

        for k in range(top):
            add_equal(i1 + k, j1 + k)

        _fold_counter[0] += 1
        fid = f"fold-{_fold_counter[0]}"
        rows.append(
            f'<tr class="fold-divider" data-count="{hidden_count}" '
            f'onclick="toggleFold(this)" data-target="{fid}">'
            f'<td colspan="4"><span class="fold-icon">⋯</span>'
            f'<span class="fold-label">Show {hidden_count} unchanged lines</span>'
            f'</td></tr>'
        )
        for k in range(top, n - bottom):
            add_equal(i1 + k, j1 + k, tr_class=f"fold-row {fid}")
        for k in range(n - bottom, n):
            add_equal(i1 + k, j1 + k)

    opcodes = sm.get_opcodes()
    for idx, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == "equal":
            emit_equal(i1, i2, j1, j2,
                       is_first=(idx == 0), is_last=(idx == len(opcodes) - 1))
        elif tag == "replace":
            left = list(range(i1, i2))
            right = list(range(j1, j2))
            for k in range(max(len(left), len(right))):
                paired = k < len(left) and k < len(right)
                if paired:
                    lt, rt = _inline_pair(lines1[left[k]], lines2[right[k]])
                    add_row(i1 + k + 1, "del", lt, j1 + k + 1, "add", rt)
                elif k < len(left):
                    add_row(i1 + k + 1, "del", _plain(lines1[left[k]]),
                            None, "empty", "&nbsp;")
                else:
                    add_row(None, "empty", "&nbsp;",
                            j1 + k + 1, "add", _plain(lines2[right[k]]))
        elif tag == "delete":
            for k in range(i1, i2):
                add_row(k + 1, "del", _plain(lines1[k]), None, "empty", "&nbsp;")
        elif tag == "insert":
            for k in range(j1, j2):
                add_row(None, "empty", "&nbsp;", k + 1, "add", _plain(lines2[k]))

    header = (
        '<div class="diff-legend">'
        f'<span class="leg leg-del"></span> {html.escape(name1)} (old)'
        f'<span class="leg leg-add"></span> {html.escape(name2)} (new)'
        '</div>'
    )
    table = (
        '<table class="difftable sidebyside">'
        '<colgroup>'
        '<col class="c-ln"><col class="c-side">'
        '<col class="c-ln"><col class="c-side">'
        '</colgroup>'
        '<thead><tr>'
        f'<th class="ln">#</th><th>{html.escape(name1)}</th>'
        f'<th class="ln">#</th><th>{html.escape(name2)}</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )
    return header + table


# --------------------------------------------------------------------------- #
# Full page rendering
# --------------------------------------------------------------------------- #
def render_html(dir1: Path, dir2: Path, results: list) -> str:
    counts = {
        "same": sum(1 for r in results if r["status"] == "same"),
        "modified": sum(1 for r in results if r["status"] == "modified"),
        "only-left": sum(1 for r in results if r["status"] == "only-left"),
        "only-right": sum(1 for r in results if r["status"] == "only-right"),
    }

    # Store diff HTML in a JS object keyed by index to keep the list clean.
    diff_map = {str(i): r["diff_html"] for i, r in enumerate(results)}
    diff_json = json.dumps(diff_map)

    status_label = {
        "same": "Identical",
        "modified": "Modified",
        "only-left": f"Only in {dir1.name}",
        "only-right": f"Only in {dir2.name}",
    }
    status_badge = {
        "same": "badge-same",
        "modified": "badge-mod",
        "only-left": "badge-left",
        "only-right": "badge-right",
    }

    rows = []
    for i, r in enumerate(results):
        rows.append(
            f'<li class="file-item {r["status"]}" data-idx="{i}" '
            f'data-name="{html.escape(r["name"]).lower()}" onclick="showDiff({i})">'
            f'<span class="fname">{html.escape(r["name"])}</span>'
            f'<span class="badge {status_badge[r["status"]]}">'
            f'{html.escape(status_label[r["status"]])}</span></li>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Directory Diff Report</title>
<style>
  :root {{
    --bg: #0d1117; --panel: #161b22; --border: #30363d; --text: #c9d1d9;
    --muted: #8b949e; --accent: #58a6ff;
    /* subtle whole-line tint */
    --add-bg: rgba(46,160,67,.15); --del-bg: rgba(248,81,73,.15);
    --add-fg: #aff5b4; --del-fg: #ffdcd7;
    /* bright inline highlight for the exact changed chars */
    --add-hl: rgba(46,160,67,.45); --del-hl: rgba(248,81,73,.45);
    --empty-bg: #0b0e13;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
    Helvetica, Arial, sans-serif; background: var(--bg); color: var(--text);
  }}
  header {{
    padding: 20px 28px; border-bottom: 1px solid var(--border);
    background: var(--panel);
  }}
  header h1 {{ margin: 0 0 6px; font-size: 20px; }}
  header .paths {{ font-size: 13px; color: var(--muted); }}
  header .paths code {{ color: var(--accent); }}
  .summary {{ display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; }}
  .summary .chip {{
    font-size: 12px; padding: 4px 10px; border-radius: 20px;
    border: 1px solid var(--border); background: #21262d;
  }}
  .toolbar {{ padding: 14px 28px; }}
  .toolbar input {{
    width: 100%; max-width: 420px; padding: 8px 12px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--panel);
    color: var(--text); font-size: 14px;
  }}
  ul.filelist {{ list-style: none; margin: 0; padding: 0 28px 40px; }}
  li.file-item {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 14px; margin-bottom: 6px; border: 1px solid var(--border);
    border-radius: 6px; background: var(--panel); cursor: pointer;
    transition: background .12s;
  }}
  li.file-item:hover {{ background: #1c2333; border-color: var(--accent); }}
  .fname {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }}
  .badge {{ font-size: 11px; padding: 3px 9px; border-radius: 20px; white-space: nowrap; }}
  .badge-same {{ background: #21262d; color: var(--muted); }}
  .badge-mod  {{ background: #3d2c00; color: #e3b341; }}
  .badge-left {{ background: #67060c; color: var(--del-fg); }}
  .badge-right{{ background: #033a16; color: var(--add-fg); }}

  /* Modal */
  .overlay {{
    display: none; position: fixed; inset: 0; background: rgba(1,4,9,.75);
    z-index: 50; align-items: center; justify-content: center; padding: 24px;
  }}
  .overlay.open {{ display: flex; }}
  .modal {{
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; width: 100%; max-width: 1000px; max-height: 85vh;
    display: flex; flex-direction: column; overflow: hidden;
  }}
  .modal-head {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 14px 18px; border-bottom: 1px solid var(--border);
  }}
  .modal-head h3 {{
    margin: 0; font-size: 14px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }}
  .modal-head button {{
    background: none; border: none; color: var(--muted); font-size: 22px;
    cursor: pointer; line-height: 1;
  }}
  .modal-head button:hover {{ color: var(--text); }}
  .modal-body {{ padding: 16px 18px; overflow: auto; }}
  .note {{
    padding: 10px 12px; margin-bottom: 12px; border-radius: 6px;
    background: #1c2333; font-size: 13px;
  }}
  .note.warn {{ background: #3d2c00; color: #e3b341; }}
  table.difftable {{
    width: 100%; border-collapse: collapse;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px;
  }}
  table.difftable td, table.difftable th {{
    padding: 2px 8px; text-align: left; vertical-align: top;
    white-space: pre-wrap; word-break: break-word;
  }}
  td.ln {{
    color: var(--muted); text-align: right;
    user-select: none; padding: 1px 8px 1px 4px;
    background: rgba(255,255,255,.02); font-size: 11.5px;
    overflow: hidden;
  }}
  /* Side-by-side diff */
  table.sidebyside {{ table-layout: fixed; width: 100%; }}
  col.c-ln {{ width: 52px; }}
  col.c-side {{ width: auto; }}
  table.sidebyside th {{
    color: var(--muted); font-weight: 600; font-size: 12px;
    letter-spacing: .3px; text-transform: uppercase;
    border-bottom: 1px solid var(--border);
    position: sticky; top: 0; background: var(--panel); z-index: 1;
    padding: 8px 10px;
  }}
  table.sidebyside tbody tr:hover td.side {{ filter: brightness(1.15); }}
  td.side {{
    line-height: 1.55; padding: 1px 10px 1px 4px;
    border-left: 1px solid var(--border);
  }}
  td.side .marker {{
    display: inline-block; width: 12px; color: var(--muted);
    user-select: none; opacity: .8;
  }}
  td.side.add {{ background: var(--add-bg); color: var(--add-fg); }}
  td.side.del {{ background: var(--del-bg); color: var(--del-fg); }}
  td.side.ctx {{ color: var(--text); }}
  td.side.empty {{
    background: var(--empty-bg);
    background-image: repeating-linear-gradient(
      45deg, transparent, transparent 6px,
      rgba(255,255,255,.02) 6px, rgba(255,255,255,.02) 12px);
  }}
  /* bright inline highlight of the exact changed characters */
  .hl-add {{ background: var(--add-hl); border-radius: 2px; color: #fff; }}
  .hl-del {{ background: var(--del-hl); border-radius: 2px; color: #fff;
             text-decoration: line-through; text-decoration-color: rgba(255,255,255,.35); }}
  /* legend */
  .diff-legend {{
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    font-size: 12.5px; color: var(--muted); margin-bottom: 12px;
  }}
  .diff-legend .leg {{
    display: inline-block; width: 12px; height: 12px; border-radius: 3px;
    margin-left: 12px;
  }}
  .diff-legend .leg:first-child {{ margin-left: 0; }}
  .leg-del {{ background: var(--del-hl); }}
  .leg-add {{ background: var(--add-hl); }}
  /* collapsible unchanged region */
  tr.fold-divider td {{
    background: #12171f; color: var(--accent); cursor: pointer;
    padding: 4px 12px; border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border); font-size: 12px; user-select: none;
  }}
  tr.fold-divider:hover td {{ background: #1a2330; }}
  tr.fold-divider .fold-icon {{
    display: inline-block; margin-right: 8px; font-weight: 700; letter-spacing: 1px;
  }}
  tr.fold-divider.open .fold-label::after {{ content: ""; }}
  tr.fold-row {{ display: none; }}
  tr.fold-row.show {{ display: table-row; }}
  /* single-column "added" table for missing-file view */
  .line.add, td.add {{ background: var(--add-bg); color: var(--add-fg); }}
</style>
</head>
<body>
<header>
  <h1>Directory Diff Report</h1>
  <div class="paths">
    Left: <code>{html.escape(str(dir1))}</code> &nbsp;|&nbsp;
    Right: <code>{html.escape(str(dir2))}</code>
  </div>
  <div class="summary">
    <span class="chip">Total: {len(results)}</span>
    <span class="chip">Identical: {counts["same"]}</span>
    <span class="chip">Modified: {counts["modified"]}</span>
    <span class="chip">Only in {html.escape(dir1.name)}: {counts["only-left"]}</span>
    <span class="chip">Only in {html.escape(dir2.name)}: {counts["only-right"]}</span>
  </div>
</header>

<div class="toolbar">
  <input id="filter" type="text" placeholder="Filter files..." oninput="filterList()">
</div>

<ul class="filelist" id="filelist">
  {"".join(rows)}
</ul>

<div class="overlay" id="overlay" onclick="if(event.target===this)closeDiff()">
  <div class="modal">
    <div class="modal-head">
      <h3 id="modal-title"></h3>
      <button onclick="closeDiff()" title="Close">&times;</button>
    </div>
    <div class="modal-body" id="modal-body"></div>
  </div>
</div>

<script>
  const DIFFS = {diff_json};
  const NAMES = {json.dumps([r["name"] for r in results])};

  function showDiff(idx) {{
    document.getElementById('modal-title').textContent = NAMES[idx];
    document.getElementById('modal-body').innerHTML = DIFFS[idx] || '<div class="note">No content.</div>';
    document.getElementById('overlay').classList.add('open');
  }}
  function closeDiff() {{
    document.getElementById('overlay').classList.remove('open');
  }}
  function toggleFold(divider) {{
    const fid = divider.dataset.target;
    const count = divider.dataset.count;
    const isOpen = divider.classList.toggle('open');
    document.querySelectorAll('#modal-body tr.' + fid).forEach(tr => {{
      tr.classList.toggle('show', isOpen);
    }});
    const label = divider.querySelector('.fold-label');
    const icon = divider.querySelector('.fold-icon');
    if (isOpen) {{
      label.textContent = 'Hide ' + count + ' unchanged lines';
      icon.textContent = '⌄';
    }} else {{
      label.textContent = 'Show ' + count + ' unchanged lines';
      icon.textContent = '⋯';
    }}
  }}
  function filterList() {{
    const q = document.getElementById('filter').value.toLowerCase();
    document.querySelectorAll('#filelist .file-item').forEach(li => {{
      li.style.display = li.dataset.name.includes(q) ? '' : 'none';
    }});
  }}
  document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeDiff(); }});
</script>
</body>
</html>"""


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare two directories and produce an interactive HTML diff report."
    )
    parser.add_argument(
        "dir1", nargs="?", default=DEFAULT_DIR1,
        help=f"First (left) directory (default: {DEFAULT_DIR1})",
    )
    parser.add_argument(
        "dir2", nargs="?", default=DEFAULT_DIR2,
        help=f"Second (right) directory (default: {DEFAULT_DIR2})",
    )
    parser.add_argument(
        "-o", "--output", default=DEFAULT_OUTPUT,
        help=f"Output HTML file (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)

    dir1 = Path(args.dir1).resolve()
    dir2 = Path(args.dir2).resolve()

    for d in (dir1, dir2):
        if not d.is_dir():
            print(f"Error: '{d}' is not a directory.", file=sys.stderr)
            return 1

    all_files = sorted(collect_files(dir1) | collect_files(dir2))
    results = [compare_file(rel, dir1, dir2) for rel in all_files]

    html_out = render_html(dir1, dir2, results)
    Path(args.output).write_text(html_out, encoding="utf-8")

    summary = {
        "total": len(results),
        "identical": sum(1 for r in results if r["status"] == "same"),
        "modified": sum(1 for r in results if r["status"] == "modified"),
        "only_left": sum(1 for r in results if r["status"] == "only-left"),
        "only_right": sum(1 for r in results if r["status"] == "only-right"),
    }
    print(f"Report written to: {args.output}")
    print(
        "Summary: {total} files | {identical} identical | {modified} modified | "
        "{only_left} only in left | {only_right} only in right".format(**summary)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
