#!/usr/bin/env python3
# PreCex - harness/evaluator.py 三通过判定骨架
# 作者：Toylog | 版本：v0.1 | 功能概述：RTL 修复评估管线入口：iverilog 编译（0 error）-> vvp 弱 tb 仿真（全绿）
#   -> sby bmc 形式验证（无反例），三阶段统一输出 verdict（PASS/FAIL/BROKEN/INCONCLUSIVE）JSON。
#   纯标准库实现，设计在 WSL 内运行（工具命令 iverilog/vvp/sby 直接经 subprocess 调用）。

"""PreCex 三通过判定 evaluator。

用法：
    python3 evaluator.py <sample_dir> [--cfg <json>]   # 对样本目录执行三通过判定
    python3 evaluator.py --unit-test                    # 内置自检（对 smoke 样本，期望 verdict=FAIL）

verdict 规则：
    compile 失败 -> BROKEN
    compile 过 + formal fail -> FAIL（抓到反例，bug 存在）
    compile 过 + sim 过 + formal pass/prove -> PASS（修复成功判据）
    formal timeout/error（或 sim 挂但 formal 通过）-> INCONCLUSIVE
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# 仓库根与 smoke 目录（用于默认 SMTBMC wrapper 定位）
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SMTBMC = os.path.join(REPO_ROOT, "smoke", "yosys-smtbmc-z3.sh")

# 通用失败重试上限（≤2 次；超时不重试）。formal 因耗时（默认 600s）默认不重试。
MAX_RETRIES = 2
LOG_TAIL = 2000  # formal 日志尾部保留字符数


def _to_wsl_path(path):
    """若在 WSL 内收到 Windows 路径（如 d:\\... 或 D:/...），转换为 /mnt/<盘>/..."""
    if os.name != "posix":
        return path
    m = re.match(r"^([a-zA-Z]):[\\/](.*)$", path)
    if m:
        wsl_p = "/mnt/%s/%s" % (m.group(1).lower(), m.group(2).replace("\\", "/"))
        if os.path.exists(wsl_p):
            return wsl_p
    return path


def _decode(x):
    """统一解码 subprocess 输出（bytes/str/None）。"""
    if x is None:
        return ""
    if isinstance(x, bytes):
        return x.decode("utf-8", errors="replace")
    return x


def _run_cmd(cmd, timeout, cwd=None, env=None, retries=MAX_RETRIES):
    """运行命令（列表参数、shell=False、带超时），非零退出失败重试；返回统一结果字典。

    返回: {"cmd", "exit_code", "stdout", "stderr", "timed_out", "error"}
    """
    for attempt in range(retries + 1):
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout, cwd=cwd, env=env,
            )
            if proc.returncode == 0 or attempt >= retries:
                # 成功或重试耗尽：返回最终结果
                return {"cmd": " ".join(cmd), "exit_code": proc.returncode,
                        "stdout": proc.stdout or "", "stderr": proc.stderr or "",
                        "timed_out": False, "error": None}
            # 非零退出且还有重试次数：继续循环
        except subprocess.TimeoutExpired as e:
            # 超时不重试（重试无意义且昂贵）
            return {"cmd": " ".join(cmd), "exit_code": -1,
                    "stdout": _decode(e.stdout), "stderr": _decode(e.stderr),
                    "timed_out": True, "error": "timeout"}
        except FileNotFoundError as e:
            return {"cmd": " ".join(cmd), "exit_code": -1, "stdout": "",
                    "stderr": "tool not found: %s" % e, "timed_out": False, "error": str(e)}
        except Exception as e:  # 其他异常（权限等）直接返回，不重试
            return {"cmd": " ".join(cmd), "exit_code": -1, "stdout": "",
                    "stderr": str(e), "timed_out": False, "error": str(e)}
    # 理论不可达（循环内已返回）
    return {"cmd": " ".join(cmd), "exit_code": -1, "stdout": "", "stderr": "retries exhausted",
            "timed_out": False, "error": "retries exhausted"}


def compile_check(sv_files, top=None, out="a.out", iverilog="iverilog",
                  timeout=60.0, cwd=None, retries=MAX_RETRIES):
    """① 编译检查：iverilog -g2012 <files> [-s <top>] -o <out>，0 error 判据。

    返回 {"ok", "cmd", "stdout", "stderr"}
    """
    cmd = [iverilog, "-g2012"] + list(sv_files)
    if top:
        cmd += ["-s", top]
    cmd += ["-o", out]
    res = _run_cmd(cmd, timeout=timeout, cwd=cwd, retries=retries)
    return {"ok": res["exit_code"] == 0 and not res["timed_out"],
            "cmd": res["cmd"], "stdout": res["stdout"], "stderr": res["stderr"]}


def sim_check(tb_and_design_files, top=None, out_bin="a.out", iverilog="iverilog",
              vvp="vvp", compile_timeout=60.0, sim_timeout=120.0,
              cwd=None, retries=MAX_RETRIES):
    """② 弱 testbench 仿真检查：复用 compile_check 编译，随后 vvp <out_bin>。

    判定：退出 0 且无 "FAIL" 且含 "$finish" -> ok=True；
          非零退出 / 超时 / 含 "$fatal"/"FAIL" -> ok=False。
    返回 {"ok", "exit_code", "stdout", "stderr", "compile"}
    """
    # 先编译（内部复用 compile_check），失败则提前返回
    comp = compile_check(tb_and_design_files, top=top, out=out_bin,
                         iverilog=iverilog, timeout=compile_timeout,
                         cwd=cwd, retries=retries)
    if not comp["ok"]:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": comp["stderr"],
                "compile": comp}
    # 再仿真
    res = _run_cmd([vvp, out_bin], timeout=sim_timeout, cwd=cwd, retries=retries)
    out = (res["stdout"] or "") + (res["stderr"] or "")
    ok = (res["exit_code"] == 0 and not res["timed_out"]
          and "$fatal" not in out and "FAIL" not in out and "$finish" in out)
    return {"ok": ok, "exit_code": res["exit_code"], "stdout": res["stdout"],
            "stderr": res["stderr"], "compile": comp}


def _classify_formal(res, out):
    """按 sby 退出码与输出特征分类形式验证结果。"""
    if res["timed_out"]:
        return "timeout"
    if res["error"]:
        return "error"
    # 反例特征优先（FAIL 时输出中也可能出现 Successfully 等无关字样）
    if res["exit_code"] == 2 or "Assert failed" in out or "Reached cover" in out or "DONE (FAIL" in out:
        return "fail"
    # 归纳证明成功特征（prove 模式）
    if "Temporal induction successful" in out or "successful proof" in out:
        return "prove"
    # bmc 通过特征
    if res["exit_code"] == 0 and ("Successfully" in out or "BMC successful" in out or "DONE (PASS" in out):
        return "pass"
    return "error"


def formal_check(sby_file, timeout=600.0, run_script=None, sby="sby",
                 smtbmc=DEFAULT_SMTBMC, cwd=None, retries=0, design_dir=None):
    """③ sby 形式验证（bmc）：env 注入 z3 PATH 与 SMTBMC wrapper。

    - 默认直接 `sby -f <sby_file>`；若提供 run_script 则改为 `bash <run_script> -f <sby_file>`。
    - design_dir：sby 工作目录（-d），指向临时目录以免污染样本目录。
    - 返回 {"result", "exit_code", "stdout", "stderr", "log_tail"}，
      result 取值 pass/prove/fail/timeout/error。
    """
    # 构建注入环境：z3 位于 ~/.local/bin；SMTBMC 指向 yosys-smtbmc-z3.sh 包装
    env = dict(os.environ)
    local_bin = os.path.join(os.path.expanduser("~"), ".local", "bin")
    if local_bin not in env.get("PATH", ""):
        env["PATH"] = local_bin + os.pathsep + env.get("PATH", "")
    if smtbmc and os.path.exists(smtbmc):
        env["SMTBMC"] = smtbmc
    # 组装命令
    if run_script:
        cmd = ["bash", run_script, "-f", sby_file]
    else:
        cmd = [sby, "-f", sby_file]
    if design_dir:
        # 指定 sby 工作目录到临时目录，避免在样本目录残留 counter_bmc 等产物
        cmd += ["-d", design_dir]
    res = _run_cmd(cmd, timeout=timeout, cwd=cwd, env=env, retries=retries)
    out = (res["stdout"] or "") + "\n" + (res["stderr"] or "")
    return {"result": _classify_formal(res, out), "exit_code": res["exit_code"],
            "stdout": res["stdout"], "stderr": res["stderr"], "log_tail": out[-LOG_TAIL:]}


def _discover(sample_dir, cfg):
    """发现样本文件：cfg 可显式指定 files/tb/sby_file，否则按目录约定自动发现。

    约定：设计 = *.sv 排除 tb_*.sv；tb = tb_*.sv；sby = *.sby。
    返回 (design_files, tb_file, sby_file) 均为绝对路径（不存在时为 None）。
    """
    files = cfg.get("files")
    if not files:
        files = sorted(
            os.path.join(sample_dir, f)
            for f in os.listdir(sample_dir)
            if (f.endswith(".sv") or f.endswith(".v")) and not f.startswith("tb_") and f not in ("formal_top.sv", "golden.v", "golden.sv")
        )
    else:
        files = [f if os.path.isabs(f) else os.path.join(sample_dir, f) for f in files]
    tb_file = cfg.get("tb")
    if tb_file is None:
        tbs = [f for f in sorted(os.listdir(sample_dir)) if f.startswith("tb_") and (f.endswith(".sv") or f.endswith(".v"))]
        tb_file = tbs[0] if tbs else None
    if tb_file and not os.path.isabs(tb_file):
        tb_file = os.path.join(sample_dir, tb_file)
    sby_file = cfg.get("sby_file")
    if sby_file is None:
        sbys = [f for f in sorted(os.listdir(sample_dir)) if f.endswith(".sby")]
        sby_file = sbys[0] if sbys else None
    if sby_file and not os.path.isabs(sby_file):
        sby_file = os.path.join(sample_dir, sby_file)
    return files, tb_file, sby_file


def evaluate(sample_dir, cfg=None):
    """三通过判定总入口。cfg 可配置 files/tb/sby_file/top/各工具路径/超时/verbose/run_formal 等。

    返回统一 JSON：{"sample", "compile", "sim", "formal", "verdict"}
    """
    cfg = cfg or {}
    sample_dir = os.path.abspath(_to_wsl_path(sample_dir))  # 绝对路径：避免相对路径叠加到 cwd 导致文件找不到
    design_files, tb_file, sby_file = _discover(sample_dir, cfg)
    sample = os.path.basename(os.path.normpath(sample_dir))

    # 运行产物写临时目录（结束后清理；keep_tmp 可保留供诊断）
    tmpdir = tempfile.mkdtemp(prefix="harness_")
    try:
        # ① 编译检查（设计文件，0 error 判据）
        comp_out = os.path.join(tmpdir, "a.out")
        compile_res = compile_check(design_files, top=cfg.get("top"),
                                    out=comp_out, iverilog=cfg.get("iverilog", "iverilog"),
                                    timeout=cfg.get("compile_timeout", 60.0),
                                    cwd=sample_dir, retries=cfg.get("retries", MAX_RETRIES))
        if cfg.get("verbose"):
            print("[evaluate:%s] compile ok=%s" % (sample, compile_res["ok"]))

        # ② 弱 tb 仿真（设计 + tb 一起编译运行）
        sim_files = design_files + ([tb_file] if tb_file else [])
        # tb top 从文件内容提取模块名（文件名可能被重命名，如 tb_weak.sv 内模块 tb_fifo_sync）；cfg 可覆盖
        sim_top = cfg.get("tb_top")
        if not sim_top and tb_file:
            m = re.search(r"module\s+(tb_\w+)", open(tb_file, encoding="utf-8").read())
            sim_top = m.group(1) if m else os.path.splitext(os.path.basename(tb_file))[0]
        sim_out = os.path.join(tmpdir, "sim.out")
        sim_res = sim_check(sim_files, top=sim_top, out_bin=sim_out,
                            iverilog=cfg.get("iverilog", "iverilog"),
                            vvp=cfg.get("vvp", "vvp"),
                            compile_timeout=cfg.get("compile_timeout", 60.0),
                            sim_timeout=cfg.get("sim_timeout", 120.0),
                            cwd=sample_dir, retries=cfg.get("retries", MAX_RETRIES))
        if cfg.get("verbose"):
            print("[evaluate:%s] sim ok=%s exit=%s" % (sample, sim_res["ok"], sim_res["exit_code"]))

        # ③ sby 形式验证（默认跑；run_formal=False 时跳过）
        formal_res = {"result": "skipped", "exit_code": None, "stdout": "", "stderr": "", "log_tail": ""}
        if cfg.get("run_formal", True) and sby_file:
            formal_res = formal_check(
                sby_file, timeout=cfg.get("formal_timeout", 600.0),
                run_script=cfg.get("run_script"),
                sby=cfg.get("sby", "sby"),
                smtbmc=cfg.get("smtbmc", DEFAULT_SMTBMC),
                cwd=sample_dir, retries=cfg.get("formal_retries", 0),
                design_dir=os.path.join(tmpdir, "sby_out"),
            )
            if cfg.get("verbose"):
                print("[evaluate:%s] formal result=%s exit=%s" % (sample, formal_res["result"], formal_res["exit_code"]))

        # verdict：提前返回、避免多层嵌套
        if not compile_res["ok"]:
            verdict = "BROKEN"
        elif formal_res["result"] == "fail":
            verdict = "FAIL"
        elif formal_res["result"] in ("pass", "prove"):
            verdict = "PASS" if sim_res["ok"] else "INCONCLUSIVE"
        else:
            verdict = "INCONCLUSIVE"

        return {"sample": sample, "compile": compile_res, "sim": sim_res,
                "formal": formal_res, "verdict": verdict}
    finally:
        # 结束后清理运行产物（keep_tmp=True 时保留）
        if not cfg.get("keep_tmp"):
            shutil.rmtree(tmpdir, ignore_errors=True)
        elif cfg.get("verbose"):
            print("[evaluate:%s] keep_tmp=%s" % (sample, tmpdir))


def run_unit_test():
    """内置自检：对 smoke 样本（buggy counter）跑三通过，期望 verdict=FAIL（formal 抓到反例）。"""
    sample_dir = os.path.join(REPO_ROOT, "smoke")
    result = evaluate(sample_dir, {"verbose": True})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    verdict = result.get("verdict")
    # 摘要：compile/sim/formal 三阶段结果
    summary = "compile=%s sim=%s formal=%s" % (
        result["compile"].get("ok"),
        result["sim"].get("ok"),
        result["formal"].get("result"),
    )
    ok = verdict == "FAIL"
    print("\n[unit-test] 期望 verdict=FAIL（counter buggy）| 实际 verdict=%s | %s | 自检%s" % (
        verdict, summary, "通过" if ok else "未通过"))
    return 0 if ok else 1


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    # 内置自检模式
    if argv and argv[0] == "--unit-test":
        return run_unit_test()
    # 用法：python evaluator.py <sample_dir> [--cfg <json>]
    if not argv:
        print(__doc__)
        return 1
    sample_dir = argv[0]
    cfg = {}
    if "--cfg" in argv:
        idx = argv.index("--cfg")
        if idx + 1 >= len(argv):
            print("error: --cfg 需要 JSON 参数", file=sys.stderr)
            return 1
        try:
            cfg = json.loads(argv[idx + 1])
        except json.JSONDecodeError as e:
            print("error: --cfg JSON 解析失败: %s" % e, file=sys.stderr)
            return 1
    result = evaluate(sample_dir, cfg)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
