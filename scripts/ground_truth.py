# -*- coding: utf-8 -*-
"""Ground-truth resolver for PreCex localization scoring.

Primary criterion: defect statement line numbers in buggy.v, derived from
diffing golden.v vs buggy.v (difflib), keeping only NON-header edit regions
(the 4-line sample header insert at the top of buggy.v is excluded).

Cross-check: content match of meta.diff '+' side lines inside buggy.v.
For pure deletions (line removed), the anchor is the buggy insertion point
j1 (1-based), i.e. the last existing buggy line before the gap.

Usage:
    from scripts.ground_truth import ground_truth_lines, update_meta_ground_truth
"""
import os
import re
import json
import difflib

DEFAULT_SKIP_HEADER = 4  # buggy.v ?????????


def normalize(s):
    return re.sub(r"\s+", " ", s).strip()


def parse_meta_diff(dt):
    plus, minus = [], []
    for ln in (dt or "").splitlines():
        s = ln.strip()
        if s.startswith("+"):
            plus.append(s[1:].strip())
        elif s.startswith("-"):
            minus.append(s[1:].strip())
    return plus, minus


def content_match_lines(plus, buggy_lines):
    """meta.diff '+' side lines matched inside buggy.v (1-based line numbers)."""
    hits = []
    for p in plus:
        key = normalize(p)
        if len(key) < 6:
            continue
        for i, bl in enumerate(buggy_lines):
            if key and key in normalize(bl):
                hits.append(i + 1)
    return sorted(set(hits))


def difflib_regions(golden_lines, buggy_lines):
    sm = difflib.SequenceMatcher(None, golden_lines, buggy_lines)
    return [o for o in sm.get_opcodes() if o[0] != "equal"]


def ground_truth_lines(sample_dir, skip_header=DEFAULT_SKIP_HEADER, with_content=True):
    """Return dict with primary ('lines') and cross-check ('content_lines') truth."""
    with open(os.path.join(sample_dir, "golden.v"), encoding="utf-8", errors="replace") as f:
        g = f.read().splitlines()
    with open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8", errors="replace") as f:
        b = f.read().splitlines()

    ops = difflib_regions(g, b)
    lines, regions = [], []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "insert" and j2 <= skip_header:
            continue  # header insert
        if tag in ("replace", "insert") and j2 > j1:
            for j in range(j1, j2):
                if j + 1 > skip_header:
                    lines.append(j + 1)
            regions.append({"tag": tag,
                            "g": [i + 1 for i in range(i1, i2)],
                            "b": [j + 1 for j in range(j1, j2)]})
        elif tag == "delete" and i2 > i1:
            pos = j1 if j1 >= 1 else 1          # insertion point (1-based)
            if pos <= len(b) and pos > skip_header:
                lines.append(pos)
            regions.append({"tag": tag,
                            "g": [i + 1 for i in range(i1, i2)],
                            "b": [pos]})
    lines = sorted(set(lines))

    content = []
    if with_content:
        meta_path = os.path.join(sample_dir, "meta.json")
        plus = []
        if os.path.isfile(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            plus, _ = parse_meta_diff(meta.get("diff"))
        content = content_match_lines(plus, b)

    return {"lines": lines, "regions": regions,
            "content_lines": content,
            "n_lines": len(lines), "n_content": len(content),
            "method": "difflib(golden vs buggy), non-header edit regions; "
                      "delete anchor = insertion point"}


def update_meta_ground_truth(sample_dir, skip_header=DEFAULT_SKIP_HEADER):
    """Write corrected defect line numbers into meta.json:
       buggy_inject_line  -> min true line (backward compat, single-line)
       buggy_inject_lines -> full list (authoritative for scoring)
    """
    gt = ground_truth_lines(sample_dir, skip_header=skip_header)
    meta_path = os.path.join(sample_dir, "meta.json")
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    meta["buggy_inject_line"] = gt["lines"][0] if gt["lines"] else None
    meta["buggy_inject_lines"] = gt["lines"]
    meta["gt_method"] = gt["method"]
    meta["gt_content_lines"] = gt["content_lines"]
    import datetime
    meta["gt_updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return gt


if __name__ == "__main__":
    import sys
    REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for base in ["bugs", "deep"]:
        d = os.path.join(REPO, "samples", base)
        for sid in sorted(os.listdir(d)):
            sd = os.path.join(d, sid)
            if not os.path.isdir(sd):
                continue
            gt = ground_truth_lines(sd)
            with open(os.path.join(sd, "meta.json"), encoding="utf-8") as f:
                meta = json.load(f)
            print("%-5s inj=%3s meta_buggy=%3s TRUE=%s content=%s" % (
                sid, meta.get("inject_line"), meta.get("buggy_inject_line"),
                gt["lines"], gt["content_lines"]))
