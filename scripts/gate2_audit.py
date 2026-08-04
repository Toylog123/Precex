#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex Gate-2 dataset audit: completeness / meta consistency / evidence keys /
uniqueness (buggy hash + inject key) / verify_repair prove mode.
Output uses ASCII to avoid Windows console encoding issues.
Usage: python scripts/gate2_audit.py
"""
import json
import os
import re
import sys
import hashlib
import collections

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUGS = os.path.join(REPO_ROOT, "samples", "bugs")

REQUIRED = ["buggy.v", "golden.v", "tb_weak.sv", "verify.sby", "verify_golden.sby",
            "verify_repair.sby", "cex.vcd", "cex.log", "meta.json", "evidence.json",
            "semantics.json", "notes.md"]
EXTRA_UART_RX = "uart_tx.sv"
ALLOWED_EXTRA = {EXTRA_UART_RX, "sby_work", "sby_golden", "sby_repair"}


def audit():
    issues = []
    samples = sorted([d for d in os.listdir(BUGS) if re.match(r"^s\d{2}$", d) and os.path.isdir(os.path.join(BUGS, d))])
    print("[gate2-audit] samples:", len(samples))
    if len(samples) != 34:
        issues.append("sample count != 34: %d" % len(samples))

    # 1) file completeness
    for s in samples:
        d = os.path.join(BUGS, s)
        files = set(os.listdir(d))
        missing = [f for f in REQUIRED if f not in files]
        if missing:
            issues.append("%s missing: %s" % (s, ",".join(missing)))
        meta_p = os.path.join(d, "meta.json")
        if os.path.isfile(meta_p):
            try:
                meta = json.load(open(meta_p, encoding="utf-8"))
            except Exception as e:
                issues.append("%s meta.json unreadable: %s" % (s, e))
                meta = {}
            if meta.get("module") == "uart_rx" and EXTRA_UART_RX not in files:
                issues.append("%s uart_rx missing %s" % (s, EXTRA_UART_RX))
        unexpected = files - set(REQUIRED) - ALLOWED_EXTRA - {"uart_tx.sv"}
        if unexpected:
            issues.append("%s unexpected files: %s" % (s, ",".join(sorted(unexpected))))

    # 2) meta consistency
    for s in samples:
        meta_p = os.path.join(BUGS, s, "meta.json")
        try:
            meta = json.load(open(meta_p, encoding="utf-8"))
        except Exception as e:
            issues.append("%s meta.json unreadable: %s" % (s, e))
            continue
        sid = meta.get("sample_id")
        if sid != s:
            issues.append("%s meta.sample_id=%s mismatch" % (s, sid))
        for fld in ("module", "error_type", "inject_line"):
            if not meta.get(fld):
                issues.append("%s meta missing %s" % (s, fld))
        if "buggy_inject_line" not in meta:
            issues.append("%s meta missing buggy_inject_line" % s)
        v = meta.get("verification") or {}
        if v.get("golden_formal_result") not in ("pass", "PASS", True):
            issues.append("%s verification.golden_formal_result=%s" % (s, v.get("golden_formal_result")))
        if v.get("formal_result") != "fail":
            issues.append("%s verification.formal_result=%s" % (s, v.get("formal_result")))
        if v.get("verdict") not in ("L3_VALID", "valid", "PASS"):
            issues.append("%s verification.verdict=%s" % (s, v.get("verdict")))

    # 3) evidence/semantics keys + sample_id
    for s in samples:
        for fname, keys in (("evidence.json", ["sample_id", "module", "error_type", "fail_step", "file", "line"]),
                            ("semantics.json", ["sample_id", "module", "error_type", "text_summary"])):
            p = os.path.join(BUGS, s, fname)
            try:
                data = json.load(open(p, encoding="utf-8"))
            except Exception as e:
                issues.append("%s %s unreadable: %s" % (s, fname, e))
                continue
            for k in keys:
                if k not in data:
                    issues.append("%s %s missing %s" % (s, fname, k))
            if data.get("sample_id") and data["sample_id"] != s:
                issues.append("%s %s sample_id=%s mismatch" % (s, fname, data["sample_id"]))

    # 4) uniqueness: buggy.v hash + (module,error_type,inject_line) key
    hashes = collections.defaultdict(list)
    inject_keys = collections.defaultdict(list)
    for s in samples:
        d = os.path.join(BUGS, s)
        try:
            buggy = open(os.path.join(d, "buggy.v"), encoding="utf-8").read()
        except Exception as e:
            issues.append("%s buggy.v unreadable: %s" % (s, e))
            continue
        hashes[hashlib.md5(buggy.encode("utf-8")).hexdigest()].append(s)
        try:
            meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
        except Exception:
            meta = {}
        k = (meta.get("module"), meta.get("error_type"), meta.get("inject_line"))
        inject_keys[k].append(s)
    for h, ss in hashes.items():
        if len(ss) > 1:
            issues.append("buggy.v duplicate hash: %s" % ",".join(ss))
    for k, ss in inject_keys.items():
        if len(ss) > 1:
            issues.append("(module,type,line) duplicate: %s <- %s" % (str(k), ",".join(ss)))

    # 5) verify_repair.sby must be prove/k-induction mode
    for s in samples:
        p = os.path.join(BUGS, s, "verify_repair.sby")
        if os.path.isfile(p):
            content = open(p, encoding="utf-8", errors="replace").read().lower()
            if "prove" not in content and "k-induction" not in content:
                issues.append("%s verify_repair.sby not prove mode" % s)

    # 6) module x error_type matrix
    matrix = collections.Counter()
    for s in samples:
        try:
            meta = json.load(open(os.path.join(BUGS, s, "meta.json"), encoding="utf-8"))
        except Exception:
            continue
        matrix[(meta.get("module"), meta.get("error_type"))] += 1
    print("\n=== module x error_type matrix ===")
    for k in sorted(matrix):
        print("  %-20s %-20s %d" % (k[0], k[1], matrix[k]))

    print("\n=== audit result ===")
    if issues:
        print("ISSUES %d:" % len(issues))
        for it in issues:
            print("  [%s]" % it)
        return 1
    print("PASS: 34 samples complete, meta/evidence consistent, unique, prove mode ok")
    return 0


if __name__ == "__main__":
    sys.exit(audit())