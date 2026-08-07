# -*- coding: utf-8 -*-
"""BMC 深度扫描（1x -> 2x -> 4x -> 8x -> 10x 自适配），替代固定 2x 抽查。"""
import os, re, sys, json, subprocess, tempfile, shutil

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _to_wsl(path):
    p = os.path.abspath(path).replace("\\", "/")
    drive, rest = p.split(":", 1)
    return "/mnt/%s%s" % (drive.lower(), rest)


def run_sby_workdir(work_dir, sby_name, timeout=900):
    """在 WSL 中于 work_dir 内运行 sby，返回 (rc, stdout)。"""
    cmd = "cd %s && bash %s -f %s" % (
        _to_wsl(work_dir),
        _to_wsl(os.path.join(REPO, "smoke", "run_sby.sh")),
        sby_name,
    )
    try:
        r = subprocess.run(["wsl", "bash", "-lc", cmd],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "timeout"


def scan_sample(sample_dir, base_depth, out_dir=None):
    """对单个样本做深度扫描。使用 sample_dir/buggy.v（修复后）+ verify.sby 模板。"""
    work = out_dir or tempfile.mkdtemp(prefix="depth_scan_")
    buggy = os.path.join(sample_dir, "buggy.v")
    tb = os.path.join(sample_dir, "tb_weak.sv")
    sby = os.path.join(sample_dir, "verify.sby")

    if not (os.path.isfile(buggy) and os.path.isfile(tb) and os.path.isfile(sby)):
        return {"sample": os.path.basename(sample_dir), "error": "missing files"}

    shutil.copy2(buggy, os.path.join(work, "buggy.v"))
    shutil.copy2(tb, os.path.join(work, "tb_weak.sv"))
    with open(sby, encoding="utf-8") as f:
        sby_text = f.read()

    depths = []
    d = base_depth
    while d <= base_depth * 10:
        depths.append(d)
        d *= 2

    results = {}
    for depth in depths:
        patched = re.sub(r"(depth\s+)\d+", r"\g<1>%d" % depth, sby_text)
        sby_work = os.path.join(work, "verify_depth_%d.sby" % depth)
        with open(sby_work, "w", encoding="utf-8") as f:
            f.write(patched)

        rc, out = run_sby_workdir(work, os.path.basename(sby_work))
        if "DONE (PASS" in out:
            results[str(depth)] = "PASS"
        elif "Assert failed" in out or "DONE (FAIL" in out:
            results[str(depth)] = "FAIL"
        elif rc == -1:
            results[str(depth)] = "TIMEOUT"
        else:
            results[str(depth)] = "UNKNOWN"
        print("  [%s] depth=%d -> %s" % (os.path.basename(sample_dir), depth, results[str(depth)]), flush=True)

    return {
        "sample": os.path.basename(sample_dir),
        "base_depth": base_depth,
        "depths": depths,
        "results": results,
        "work_dir": work,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", help="sample id e.g. s04")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default=os.path.join(REPO, "experiments", "runs", "depth_scan.json"))
    args = ap.parse_args()

    base_depths = {
        "fifo_sync": 12, "uart_tx": 12, "fsm_ctrl": 12, "counter_alu": 12,
        "axi_lite_slave": 16, "uart_rx": 24,
    }

    samples = []
    if args.sample:
        samples = [os.path.join(REPO, "samples", "bugs", args.sample)]
    elif args.all:
        bugs = os.path.join(REPO, "samples", "bugs")
        for sid in sorted(os.listdir(bugs)):
            sp = os.path.join(bugs, sid)
            if os.path.isdir(sp) and os.path.isfile(os.path.join(sp, "buggy.v")):
                samples.append(sp)

    results = []
    for sp in samples:
        meta_path = os.path.join(sp, "meta.json")
        module = "?"
        if os.path.isfile(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                module = json.load(f).get("module", "?")
        base = base_depths.get(module, 12)
        print("[depth] %s base=%d" % (os.path.basename(sp), base), flush=True)
        r = scan_sample(sp, base)
        results.append(r)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("[depth] saved %d samples -> %s" % (len(results), args.out))


if __name__ == "__main__":
    main()
