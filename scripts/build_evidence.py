#!/usr/bin/env python3
# PreCex - scripts/build_evidence.py 证据批量生成（A/B/C 证据链）
# 作者：Toylog | 版本：v0.1 | 功能概述：对 samples/bugs 或 samples/prestudy 下样本批量生成
#   evidence.json（EvidenceEngine 结构化证据，设置 B）与 semantics.json（CexSemantizer
#   反例语义化，设置 C，mock 摘要默认；--real 时真实调用 MiniMax M3）。
#   生成后可被 run_experiments.py A/B/C 评测直接消费。
# 用法：
#   python3 scripts/build_evidence.py [--samples s04-s34 或 s04,s05] [--mock|--real] [--window 8]
"""
PreCex 证据批量生成。
"""

import argparse
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "agents", "evidence_engine"))
sys.path.insert(0, os.path.join(REPO_ROOT, "agents", "cex_semantizer"))

from evidence_engine import build_evidence  # noqa: E402
from cex_semantizer import CexSemantizer  # noqa: E402

SAMPLES_BUGS = os.path.join(REPO_ROOT, "samples", "bugs")
SAMPLES_PRESTUDY = os.path.join(REPO_ROOT, "samples", "prestudy")


def expand_samples(spec):
    """展开样本列表：'s04-s34' 区间或 's04,s05' 列表；返回排序后的 sample_id 列表。"""
    ids = []
    for part in spec.split(","):
        part = part.strip()
        m = re.match(r"^s(\d+)-s(\d+)$", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            ids += ["s%02d" % i for i in range(lo, hi + 1)]
        else:
            ids.append(part)
    # 去重保序
    seen = set()
    out = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def sample_dirs(sample_ids):
    """返回 {sample_id: abs_dir}：优先 samples/bugs，其次 samples/prestudy。"""
    out = {}
    for sid in sample_ids:
        p = os.path.join(SAMPLES_BUGS, sid)
        if os.path.isdir(p):
            out[sid] = p
            continue
        p = os.path.join(SAMPLES_PRESTUDY, sid)
        if os.path.isdir(p):
            out[sid] = p
    return out


def write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    ap = argparse.ArgumentParser(prog="build_evidence.py")
    ap.add_argument("--samples", default="s04-s34", help="样本列表/区间（默认 s04-s34）")
    ap.add_argument("--mock", action="store_true", help="semantics 摘要用 mock（默认）")
    ap.add_argument("--real", action="store_true", help="semantics 摘要真实调用 MiniMax M3")
    ap.add_argument("--window", type=int, default=8, help="语义化触发窗口（默认 8）")
    ap.add_argument("--evidence-only", action="store_true", help="仅生成 evidence.json，不生成 semantics")
    args = ap.parse_args(argv)

    samples = expand_samples(args.samples)
    dirs = sample_dirs(samples)
    missing = [s for s in samples if s not in dirs]
    if missing:
        print("warning: 未找到样本目录: %s" % ", ".join(missing))

    mock = not args.real
    ok = 0
    fail = []
    for sid, sdir in sorted(dirs.items()):
        try:
            ev = build_evidence(sdir)
            write_json(os.path.join(sdir, "evidence.json"), ev)
            print("[evidence] %s: module=%s line=%s step=%s x_warn=%s" % (
                sid, ev.get("module"), ev.get("line"), ev.get("fail_step"), ev.get("x_state_warn")))
            if not args.evidence_only:
                cs = CexSemantizer(sdir)
                cs.build(window=args.window)
                cs.summarize(mock=mock)
                write_json(os.path.join(sdir, "semantics.json"), cs.semantics)
                print("[semantics] %s: cycles=%d cone=%d summary=%s" % (
                    sid, len(cs.semantics.get("cycle_events", [])),
                    len(cs.semantics.get("fault_cone", [])),
                    (cs.semantics.get("text_summary") or "")[:60].replace("\n", " ")))
            ok += 1
        except Exception as e:
            fail.append((sid, repr(e)))
            print("[FAIL] %s: %s" % (sid, e))
    print("\n== done: ok=%d fail=%d ==\n" % (ok, len(fail)))
    for sid, e in fail:
        print("  %s: %s" % (sid, e))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
