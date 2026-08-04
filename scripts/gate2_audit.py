#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex Gate-2 ?????????????? / meta ??? / ?????? / ??????
???python3 scripts/gate2_audit.py
"""
import json, os, re, sys, hashlib, collections

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
    print("???:", len(samples))
    if len(samples) != 34:
        issues.append("??? != 34: %d" % len(samples))

    # 1) ?????
    for s in samples:
        d = os.path.join(BUGS, s)
        files = set(os.listdir(d))
        missing = [f for f in REQUIRED if f not in files]
        if missing:
            issues.append("%s ??: %s" % (s, ",".join(missing)))
        # uart_rx ??? uart_tx.sv
        meta_p = os.path.join(d, "meta.json")
        if os.path.isfile(meta_p):
            meta = json.load(open(meta_p, encoding="utf-8"))
            if meta.get("module") == "uart_rx" and EXTRA_UART_RX not in files:
                issues.append("%s uart_rx ? %s" % (s, EXTRA_UART_RX))
        # ?????????????
        unexpected = files - set(REQUIRED) - ALLOWED_EXTRA - {"uart_tx.sv"}
        if unexpected:
            issues.append("%s ????: %s" % (s, ",".join(sorted(unexpected))))

    # 2) meta ???
    for s in samples:
        meta_p = os.path.join(BUGS, s, "meta.json")
        meta = json.load(open(meta_p, encoding="utf-8"))
        sid = meta.get("sample_id")
        if sid != s:
            issues.append("%s meta.sample_id=%s ???" % (s, sid))
        for fld in ("module", "error_type", "inject_line"):
            if not meta.get(fld):
                issues.append("%s meta ??? %s" % (s, fld))
        # buggy_inject_line ???loc_top1 ?????
        if "buggy_inject_line" not in meta:
            issues.append("%s meta ? buggy_inject_line" % s)
        # golden_formal_result 应在 verification 嵌套，且为 pass
        v = meta.get("verification") or {}
        if v.get("golden_formal_result") not in ("pass", "PASS", True):
            issues.append("%s verification.golden_formal_result=%s" % (s, v.get("golden_formal_result")))
        if v.get("formal_result") != "fail":
            issues.append("%s verification.formal_result=%s" % (s, v.get("formal_result")))
        if v.get("verdict") not in ("L3_VALID", "valid", "PASS"):
            issues.append("%s verification.verdict=%s" % (s, v.get("verdict")))

    # 3) evidence/semantics ??? + ????
    for s in samples:
        for fname, keys in (("evidence.json", ["sample_id", "module", "error_type", "fail_step", "file", "line"]),
                            ("semantics.json", ["sample_id", "module", "error_type", "text_summary"])):
            p = os.path.join(BUGS, s, fname)
            try:
                data = json.load(open(p, encoding="utf-8"))
            except Exception as e:
                issues.append("%s %s ????: %s" % (s, fname, e))
                continue
            for k in keys:
                if k not in data:
                    issues.append("%s %s ??? %s" % (s, fname, k))
            if data.get("sample_id") and data["sample_id"] != s:
                issues.append("%s %s sample_id=%s ???" % (s, fname, data["sample_id"]))

    # 4) ????buggy.v ?? hash ?? + inject ???
    hashes = collections.defaultdict(list)
    inject_keys = collections.defaultdict(list)
    for s in samples:
        d = os.path.join(BUGS, s)
        buggy = open(os.path.join(d, "buggy.v"), encoding="utf-8").read()
        hashes[hashlib.md5(buggy.encode("utf-8")).hexdigest()].append(s)
        meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
        k = (meta.get("module"), meta.get("error_type"), meta.get("inject_line"))
        inject_keys[k].append(s)
    for h, ss in hashes.items():
        if len(ss) > 1:
            issues.append("buggy.v ????: %s" % ",".join(ss))
    for k, ss in inject_keys.items():
        if len(ss) > 1:
            issues.append("(module,type,line) ??: %s <- %s" % (str(k), ",".join(ss)))

    # 5) verify_repair.sby ?? prove ??
    for s in samples:
        p = os.path.join(BUGS, s, "verify_repair.sby")
        if os.path.isfile(p):
            content = open(p, encoding="utf-8").read()
            if "prove" not in content.lower() and "k-induction" not in content.lower():
                issues.append("%s verify_repair.sby ? prove ??" % s)

    print("\n=== ???? ===")
    if issues:
        print("?? %d ???:" % len(issues))
        for it in issues:
            print("  [%s]" % it)
        return 1
    print("???? ??34 ???????meta ??????????????")
    return 0


if __name__ == "__main__":
    sys.exit(audit())