#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Temporal dependency graph extractor (2b evidence)."""
import json
import os
import sys
NL = chr(10)


def extract(sample_dir):
    ta = json.load(open(os.path.join(sample_dir, "trace_analysis.json"), encoding="utf-8"))
    an = ta.get("analysis") or {}
    dd = an.get("diff_detail") or {}
    rows = []
    for reg in ("state", "state_d"):
        st = dd.get(reg)
        if not st:
            continue
        g, b = st.get("golden") or [], st.get("buggy") or []
        cycs = st.get("cycles") or []
        for i in range(1, len(g)):
            g0, g1 = g[i - 1], g[i]
            b0, b1 = b[i - 1], b[i]
            if g0 is None or g1 is None:
                continue
            if g0 != g1 and (b0 == b1 or (b1 is not None and b1 != g1)):
                cyc = cycs[i] if i < len(cycs) else i
                rows.append({"cycle": cyc, "golden_from": g0, "golden_to": g1,
                             "buggy_from": b0, "buggy_to": b1, "reg": reg})
    return rows


def render(sample_dir):
    rows = extract(sample_dir)
    if not rows:
        return ""
    lines = ["### \u65f6\u5e8f\u4f9d\u8d56\u56fe\uff1a\u72b6\u6001\u8f6c\u79fb\u5206\u6b67\u8fb9\uff08\u8be5\u8f6c\u79fb\u800c\u672a\u8f6c\u79fb\uff09"]
    for r in rows:
        lines.append("- [%s] cycle=%s: golden %s->%s, buggy %s->%s" % (
            r["reg"], r["cycle"], r["golden_from"], r["golden_to"],
            r["buggy_from"], r["buggy_to"]))
    return NL.join(lines)


if __name__ == "__main__":
    for d in sys.argv[1:]:
        print("=====", d, "=====")
        print(render(d))