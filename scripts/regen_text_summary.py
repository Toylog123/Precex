#!/usr/bin/env python3
# PreCex - scripts/regen_text_summary.py 摘要统一重生成（MM 只当裁判口径）
# 作者：Toylog | 版本：v0.1 | 功能概述：把 C 证据（semantics.json）的 text_summary 统一重生成
#   为指定 provider（默认 deepseek），使"证据生成 = 主实验修复 = DeepSeek，MiniMax 仅作可解释性
#   评分裁判"，消除"评分者=生成者/修复者"的角色重叠。
#   - bugs 主样本：已有 MM 版摘要 → 先备份为 semantics_mm.json，再用 DS 覆盖 text_summary
#   - deep 深时序样本：结构已有、摘要为空 → 用 DS 生成 text_summary
#   - l2 门禁样本：结构缺失 → 先 build（window=8）再 DS 生成 text_summary
# 用法：
#   python3 scripts/regen_text_summary.py [--samples-dir bugs|deep|l2] [--provider deepseek]
#       [--samples s04-s37] [--window 8] [--max-budget 5]
"""PreCex 摘要统一重生成。"""
import argparse
import json
import os
import re
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "agents", "cex_semantizer"))

from llm_client import LLMClient, configured_providers, TokenLedger  # noqa: E402
from cex_semantizer import CexSemantizer  # noqa: E402

SAMPLES = {
    "bugs": os.path.join(REPO_ROOT, "samples", "bugs"),
    "deep": os.path.join(REPO_ROOT, "samples", "deep"),
    "l2": os.path.join(REPO_ROOT, "samples", "l2"),
}


def expand_samples(spec):
    ids = []
    for part in spec.split(","):
        part = part.strip()
        m = re.match(r"^s(\d+)-s(\d+)$", part)
        if m:
            ids += ["s%02d" % i for i in range(int(m.group(1)), int(m.group(2)) + 1)]
        else:
            ids.append(part)
    return ids


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples-dir", default="bugs", choices=list(SAMPLES))
    ap.add_argument("--provider", default="deepseek")
    ap.add_argument("--samples", default=None, help="逗号分隔；默认全部（bugs=s04-s37, deep=s38-s42, l2=全部）")
    ap.add_argument("--window", type=int, default=8)
    ap.add_argument("--max-budget", type=float, default=5.0)
    args = ap.parse_args(argv)

    base = SAMPLES[args.samples_dir]
    if args.samples:
        ids = expand_samples(args.samples)
    elif args.samples_dir == "bugs":
        ids = ["s%02d" % i for i in range(4, 38)]
    elif args.samples_dir == "deep":
        ids = ["s%02d" % i for i in range(38, 43)]
    else:
        ids = sorted(os.listdir(base))
    ids = [x for x in ids if os.path.isdir(os.path.join(base, x))]
    if not ids:
        raise SystemExit("no sample dirs found under %s" % base)
    print("targets=%d dir=%s" % (len(ids), base))

    if args.provider not in configured_providers():
        raise SystemExit("provider %r 未配置（env 缺 key）：%s" % (args.provider, configured_providers()))
    llm = LLMClient(mock=False, temperature=0.2, provider=args.provider)
    ok, skip, fail = 0, 0, []

    for sid in sorted(ids):
        sdir = os.path.join(base, sid)
        sem_path = os.path.join(sdir, "semantics.json")
        has_sem = os.path.isfile(sem_path)
        # 断点续跑：已 DS 化（mode=real 且短摘要 <2000）则跳过，避免重复花费
        if has_sem:
            try:
                with open(sem_path, "r", encoding="utf-8") as f:
                    _old = json.load(f)
                _meta = _old.get("summary_meta") or {}
                _len = len((_old.get("text_summary") or "").strip())
                if _meta.get("mode") == "real" and _len < 2000 and args.samples_dir == "bugs":
                    print("[skip] %s 已 DS 化 (len=%d)" % (sid, _len))
                    skip += 1
                    continue
            except Exception:
                pass
        cs = CexSemantizer(sdir, llm=llm)
        if has_sem:
            with open(sem_path, "r", encoding="utf-8") as f:
                cs.semantics = json.load(f)
        else:
            try:
                cs.build(window=args.window, adaptive=False)
            except Exception as e:
                fail.append((sid, "build: %r" % e))
                print("[FAIL] %s: %s" % (sid, e))
                continue
        ts = (cs.semantics.get("text_summary") or "").strip()
        if ts and args.samples_dir == "bugs":
            mm_backup = os.path.join(sdir, "semantics_mm.json")
            if not os.path.isfile(mm_backup):
                shutil.copyfile(sem_path, mm_backup)
                print("[backup] %s -> semantics_mm.json (len=%d)" % (sid, len(ts)))
        try:
            cs.summarize(mock=False, tag="regen:%s:%s" % (args.samples_dir, sid))
        except Exception as e:
            fail.append((sid, "summarize: %r" % e))
            print("[FAIL] %s: %s" % (sid, e))
            continue
        with open(sem_path, "w", encoding="utf-8") as f:
            json.dump(cs.semantics, f, ensure_ascii=False, indent=2)
        new = cs.semantics.get("text_summary") or ""
        mode = cs.semantics.get("summary_meta", {}).get("mode")
        cost = cs.semantics.get("summary_meta", {}).get("cost", 0)
        print("[ok] %s mode=%s len=%d cost=%.5f" % (sid, mode, len(new), float(cost or 0)))
        sys.stdout.flush()
        ok += 1

    print("")
    print("== done: ok=%d skip=%d fail=%d ==" % (ok, skip, len(fail)))
    sys.stdout.flush()
    for sid, e in fail:
        print("  %s: %s" % (sid, e))
    # 强制关闭所有连接（部分环境 urllib 连接句柄残留导致进程不退出）
    import gc
    gc.collect()
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
