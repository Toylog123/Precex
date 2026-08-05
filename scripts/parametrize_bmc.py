# -*- coding: utf-8 -*-
"""PreCex - scripts/parametrize_bmc.py 源头参数化 BMC 验证（WP2c）

对『源头参数化构建』的样本（bug_injector --param CLK_FREQ=400,BAUD=100 生成，
如 s38/s39/s40）做 buggy-vs-golden 对照 BMC：验证 buggy 在完整周期覆盖下
可被抓到缺陷（FAIL + fail_step），golden 在同样深度下 PASS。

重要约束（2c 实证结论）：不要对固定参数的旧样本（如 s16，DIV=434）做参数
默认值改写——内联断言依赖原始参数语义，改写后 golden 也会被误判 FAIL。
正确做法是从源头用 bug_injector --param 生成参数化样本，断言随模板适配。

用法（WSL，源头参数化样本）:
  python3 scripts/parametrize_bmc.py --sample s38 --depth 64
  python3 scripts/parametrize_bmc.py --sample s38 --out experiments/runs/parametrize_bmc_s38.json
  """
from __future__ import annotations
import argparse, json, os, re, shutil, subprocess, sys, tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODULE_PARAMS = {
    "uart_tx": [("CLK_FREQ", "400"), ("BAUD", "100"), ("DATA_W", "8")],
    "uart_rx": [("CLK_FREQ", "400"), ("BAUD", "100"), ("DATA_W", "8")],
    "fifo_sync": [("DEPTH", "8")],
    "fsm_ctrl": [("TIMEOUT", "8")],
    "axi_lite_slave": [],
    "counter_alu": [],
}
DEFAULT_DEPTH = 48
SAMPLE_BASES = ("samples/bugs", "samples/deep", "samples/structural")


def find_sample(sid):
    for base in SAMPLE_BASES:
        p = os.path.join(REPO_ROOT, base, sid)
        if os.path.isdir(p):
            return p
    return None


def gen_sby(sample_dir, design, top, params, depth, timeout):
    # 直接改写参数默认值（DIV=4 类），绕开 chparam 模块名/实例名匹配问题。
    # sample_dir 下设计文件副本：read 后 prep -top 即可，无需 chparam。
    src_path = os.path.join(sample_dir, design)
    src = open(src_path, encoding="utf-8").read()
    for k, v in params:
        src = re.sub(r"(parameter\s+%s\s*=\s*)[^,;)]*" % re.escape(k),
                     lambda m: m.group(1) + v, src)
    open(src_path, "w", encoding="utf-8").write(src)
    lines = ["# PreCex parametrize_bmc: 周期参数化 BMC（完整周期覆盖）",
             "[tasks]", "bmc", "[options]",
             "bmc: mode bmc", "bmc: depth %d" % depth, "bmc: timeout %d" % timeout,
             "[engines]", "bmc: smtbmc z3", "[script]",
             "read -sv -formal %s" % design,
             "prep -top %s" % top,
             "[files]", design]
    return "\n".join(lines)


def run_sby(workdir, sby_file, timeout):
    """Run sby (invoked inside WSL); return (rc, tail)."""
    script = "cd %s && timeout %d sby -f %s > /tmp/pbmc.log 2>&1; echo RC=$?; tail -40 /tmp/pbmc.log" % (workdir, timeout + 30, sby_file)
    try:
        p = subprocess.run(["bash", "-lc", script],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout + 60)
        return p.returncode, (p.stdout or "")[-3000:]
    except Exception as e:
        return -1, "sby run fail: %s" % repr(e)[:200]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--clk-freq", default=None)
    ap.add_argument("--baud", default=None)
    ap.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    sample_dir = find_sample(args.sample)
    if sample_dir is None:
        print("sample not found: %s" % args.sample, file=sys.stderr)
        return 1
    meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
    module = meta.get("module")
    params = list(MODULE_PARAMS.get(module, []))
    if args.clk_freq and args.baud:
        params = [(k, (args.clk_freq if k == "CLK_FREQ" else (args.baud if k == "BAUD" else v))) for k, v in params]
    work = tempfile.mkdtemp(prefix="pbmc_")
    report = {"sample": args.sample, "module": module, "params": dict(params),
              "depth": args.depth, "buggy": None, "golden": None,
              "buggy_fail_step": None, "error": ""}
    for tag, design in (("buggy", "buggy.v"), ("golden", "golden.v")):
        d = os.path.join(work, tag)
        os.makedirs(d, exist_ok=True)
        shutil.copy(os.path.join(sample_dir, design), os.path.join(d, design))
        sby = gen_sby(d, design, module, params, args.depth, args.timeout)
        open(os.path.join(d, "verify.sby"), "w", encoding="utf-8").write(sby)
        rc, tail = run_sby(d, "verify.sby", args.timeout)
        m = re.search(r"failed assertion .*? step\s+(\d+)\b", tail)
        fail_step = int(m.group(1)) if m else None
        passed = "Status: passed" in tail or "returned pass" in tail
        report[tag] = {"rc": rc, "passed": passed, "fail_step": fail_step, "tail_tail": tail[-600:]}
        print("[%s] %s rc=%d passed=%s fail_step=%s" % (args.sample, tag, rc, passed, fail_step), flush=True)
    # 判定：buggy 应 FAIL（抓到缺陷），golden 应 PASS（完整周期覆盖下修复正确）
    ok = (report["buggy"] and report["buggy"]["passed"] is False
          and report["golden"] and report["golden"]["passed"] is True)
    report["verdict"] = "CONFIRMED" if ok else "NOT_CONFIRMED"
    out_path = args.out or os.path.join(REPO_ROOT, "experiments", "runs",
                                        "parametrize_bmc_%s.json" % args.sample)
    json.dump(report, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("verdict=%s -> %s" % (report["verdict"], out_path), flush=True)
    shutil.rmtree(work, ignore_errors=True)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
