# -*- coding: utf-8 -*-
"""PreCex T2 验证 agent（确定性版）：对每条修复 diff 做三类审查：
1) 接口/端口/参数变更（模块头 hunk）
2) 断言变更（assert/assume 行被改）
3) 证据闭环（diff 改动信号 in LLM signals/reason/fault_cone；loc_line 与 hunk 偏差）
用法: python3 scripts/t2_audit.py --results experiments/runs/experiments_results_corrected.json
作者: Toylog | 版本: v0.1
"""
import argparse, json, os, re, sys, collections

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUGS = os.path.join(REPO_ROOT, "samples", "bugs")

HUNK_RE = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
SIG_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
PORT_KEYWORDS = ("input ", "output ", "parameter ", "localparam ")

def parse_diff(diff_text):
    """返回 [(old_start, new_start, add_lines, del_lines), ...]"""
    hunks = []
    cur = None
    for line in (diff_text or "").splitlines():
        m = HUNK_RE.search(line)
        if m:
            if cur: hunks.append(cur)
            cur = {"old": int(m.group(1)), "new": int(m.group(3)), "add": [], "del": []}
            continue
        if cur is None: continue
        if line.startswith("+"):
            cur["add"].append(line[1:])
        elif line.startswith("-"):
            cur["del"].append(line[1:])
    if cur: hunks.append(cur)
    return hunks

def get_design_lines(sample_dir, fname="buggy.v"):
    p = os.path.join(sample_dir, fname)
    if not os.path.exists(p):
        return []
    return open(p, encoding="utf-8", errors="replace").read().splitlines()

def audit_one(sample_id, r):
    sample_dir = os.path.join(BUGS, sample_id)
    diff = r.get("diff_text") or ""
    hunks = parse_diff(diff)
    buggy = get_design_lines(sample_dir)
    sem = {}
    sp = os.path.join(sample_dir, "semantics.json")
    if os.path.exists(sp):
        try: sem = json.load(open(sp, encoding="utf-8"))
        except Exception: pass
    fault_cone = set()
    for x in (sem.get("fault_cone") or []):
        if isinstance(x, str): fault_cone.add(x)
    # LLM 报告信号
    llm_sigs = set()
    for key in ("signals",):
        v = r.get(key)
        if isinstance(v, str):
            llm_sigs.update(s.lower() for s in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", v))
    reason = (r.get("reason") or "").lower()
    # 失败断言所在行（evidence.json）
    ev = {}
    ep = os.path.join(sample_dir, "evidence.json")
    if os.path.exists(ep):
        try: ev = json.load(open(ep, encoding="utf-8"))
        except Exception: pass
    failed_line = ev.get("failed_line") or ev.get("inject_line") or r.get("inject_line")

    interface_ok, assertion_ok, loop_ok = True, True, True
    issues = []
    changed_sigs = set()
    hunk_locs = []
    for h in hunks:
        old_start, new_start = h["old"], h["new"]
        hunk_locs.append(new_start)
        # 检查旧行是否在模块头/端口区（前 60 行 heuristic + 关键字）
        for ln in h["del"] + h["add"]:
            if any(k in ln for k in PORT_KEYWORDS):
                interface_ok = False
                issues.append("接口/端口/参数行被改: " + ln.strip()[:80])
            if re.search(r"\b(assert|assume)\b", ln):
                assertion_ok = False
                issues.append("断言行被改: " + ln.strip()[:80])
            for m in SIG_RE.finditer(ln):
                s = m.group(1)
                if s not in ("a", "b", "buggy", "sv", "if", "else", "begin", "end", "module", "wire", "reg", "assign", "always", "posedge", "negedge", "or"):
                    changed_sigs.add(s)
    # 证据闭环：改动信号与 LLM 报告信号 / fault_cone 交集
    if changed_sigs:
        inter = changed_sigs & fault_cone
        inter_llm = changed_sigs & llm_sigs
        if not inter and not inter_llm:
            # 允许 loc_line 与 hunk 一致的情况（diff 命中注入行）
            loop_ok = False
            issues.append("改动信号不在 fault_cone/LLM 信号内: " + ",".join(sorted(changed_sigs))[:100])
    # loc 偏差
    loc_line = r.get("loc_line")
    loc_dev = None
    if loc_line is not None and hunk_locs:
        loc_dev = min(abs(int(loc_line) - x) for x in hunk_locs)
    return {
        "sample": sample_id, "setting": r.get("setting"), "seed": r.get("seed"),
        "hunks": len(hunks), "hunk_locs": hunk_locs, "loc_line": loc_line,
        "loc_dev": loc_dev, "changed_sigs": sorted(changed_sigs),
        "interface_ok": interface_ok, "assertion_ok": assertion_ok, "loop_ok": loop_ok,
        "t2_pass": interface_ok and assertion_ok and loop_ok,
        "issues": issues,
    }

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(REPO_ROOT, "experiments/runs/experiments_results_corrected.json"))
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "experiments/runs/t2_audit.json"))
    args = ap.parse_args(argv)
    d = json.load(open(args.results, encoding="utf-8"))
    rs = d["results"]
    audits = []
    for r in rs:
        sid = r.get("sample")
        if not r.get("diff_text"):
            audits.append({"sample": sid, "setting": r.get("setting"), "seed": r.get("seed"), "no_diff": True, "t2_pass": None, "issues": []})
            continue
        try:
            audits.append(audit_one(sid, r))
        except Exception as e:
            audits.append({"sample": sid, "setting": r.get("setting"), "seed": r.get("seed"), "error": str(e), "t2_pass": False, "issues": ["exception: " + str(e)]})
    n = len(audits)
    withdiff = [a for a in audits if not a.get("no_diff")]
    t2_pass = [a for a in withdiff if a.get("t2_pass")]
    t2_fail = [a for a in withdiff if not a.get("t2_pass")]
    print("total=%d with_diff=%d t2_pass=%d (%.1f%%) t2_fail=%d" % (
        n, len(withdiff), len(t2_pass), 100.0*len(t2_pass)/max(1,len(withdiff)), len(t2_fail)))
    print("interface_fail=%d assertion_fail=%d loop_fail=%d" % (
        sum(1 for a in withdiff if not a["interface_ok"]),
        sum(1 for a in withdiff if not a["assertion_ok"]),
        sum(1 for a in withdiff if not a["loop_ok"])))
    # 汇总失败原因
    if t2_fail:
        print("\n-- 失败示例（前 10）--")
        for a in t2_fail[:10]:
            print(a["sample"], a["setting"], a["seed"], a["issues"][:2])
    # loc 偏差统计
    devs = [a["loc_dev"] for a in withdiff if a.get("loc_dev") is not None]
    if devs:
        print("\nloc_dev: median=%d mean=%.1f zero=%d/%d (%.1f%%)" % (
            sorted(devs)[len(devs)//2], sum(devs)/len(devs),
            sum(1 for x in devs if x == 0), len(devs), 100.0*sum(1 for x in devs if x == 0)/len(devs)))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"n": n, "with_diff": len(withdiff), "t2_pass": len(t2_pass),
                   "t2_fail": len(t2_fail), "results": audits}, f, ensure_ascii=False, indent=1)
    print("[done] ->", args.out)

if __name__ == "__main__":
    sys.exit(main())
