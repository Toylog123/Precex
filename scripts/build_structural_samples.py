#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex - scripts/build_structural_samples.py 结构性缺陷样本构造 (WP3)

从 rtl 黄金基线生成"结构级"缺陷变体——改写跳转目标/删除保护分支等，
复用 bug_injector 的断言内联+环境约束+三通过校验+7件套落盘管线。

用法（WSL）:
  python3 scripts/build_structural_samples.py --module fsm_ctrl --smoke
  python3 scripts/build_structural_samples.py          # 全部模板
"""
from __future__ import annotations
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
import bug_injector  # noqa: E402
import evaluator  # noqa: E402

RTL_DIR = os.path.join(REPO_ROOT, "rtl")
SAMPLES_DIR = os.path.join(REPO_ROOT, "samples", "structural")
SAMPLES_BUGS = os.path.join(REPO_ROOT, "samples", "bugs")
SAMPLES_DEEP = os.path.join(REPO_ROOT, "samples", "deep")

# ---- 结构级模板：改写跳转/删除保护，diff >= 3 行 ----


def _block_remove(src, marker, keep_comment=True):
    """删除 marker 所在整块（begin/end 平衡）。"""
    lines = src.splitlines(keepends=True)
    start = None
    for i, ln in enumerate(lines):
        if marker in ln and "begin" in ln:
            start = i
            break
    if start is None:
        return None
    depth = 0
    end = start
    for i in range(start, len(lines)):
        depth += lines[i].count("begin") - lines[i].count("end")
        if depth <= 0:
            end = i
            break
    del_start = start - 1 if keep_comment and start > 0 and "//" in lines[start - 1] else start
    del lines[del_start:end + 1]
    return "".join(lines)


def _branch_remove(src, cond_marker):
    """删除 if (cond) begin ... end [else] 分支。"""
    lines = src.splitlines(keepends=True)
    start = None
    for i, ln in enumerate(lines):
        if cond_marker in ln and "begin" in ln:
            start = i
            break
    if start is None:
        return None
    depth = 0
    end = start
    for i in range(start, len(lines)):
        depth += lines[i].count("begin") - lines[i].count("end")
        if depth <= 0:
            end = i
            break
    j = end
    while j + 1 < len(lines) and lines[j + 1].strip().startswith("//"):
        j += 1
    if j + 1 < len(lines) and lines[j + 1].strip().startswith("else"):
        del lines[start:j + 1]
    else:
        del lines[start:end + 1]
    return "".join(lines)


def _jump_rewrite(src, old_line, new_line):
    idx = src.find(old_line)
    if idx < 0:
        return None
    return src[:idx] + new_line + src[idx + len(old_line):]


def _timeout_remove(src):
    """把每处 `if (step_cnt>=TIMEOUT) begin ... end else if(X)` 改写为 `if(X)`（只去掉超时保护前缀，保留原 else-if 链）。

    golden:  if (step_cnt >= TIMEOUT) begin S_IDLE; timeout_irq; end else if (data_in==AA) begin ...
    buggy:   if (data_in==AA) begin ...           # 超时保护缺失，原逻辑保留
    """
    pat = re.compile(
        r"if \(step_cnt >= TIMEOUT\) begin\n"
        r"(\s*state       <= S_IDLE;\n)"
        r"(\s*timeout_irq <= 1'b1;      // 超时保护\n)"
        r"(\s*)end else if "
    )
    out = src
    for _ in range(3):
        if not pat.search(out):
            break
        out = pat.sub(r"if ", out, count=1)
    return out


STRUCTURAL = {
    "fsm_ctrl": [
        {
            "desc": "S1 停留满后跳转目标 S2 改 S3（跳过 S2 停留，修复需重建 S2 中间态/停留逻辑 split_state）",
            "fn": "jump_rewrite",
            "args": ["state    <= S2;", "state    <= S3;"],
            "hit": "fsm_ctrl A1（状态跳转合法性：S1->S3 非法）",
            "error_type": "状态跳转", "error_type_code": "state_trans",
            "template": "split_state",
        },
        {
            "desc": "删除全部超时保护分支（step_cnt>=TIMEOUT 保护移除，修复需重插 guard_boundary）",
            "fn": "timeout_remove",
            "args": [],
            "hit": "fsm_ctrl 强断言 A8（step_cnt 超阈值后必须回 IDLE）",
            "error_type": "边界回绕", "error_type_code": "boundary_wrap",
            "template": "guard_boundary",
            "strong_assert": "timeout_guard",
        },
        {
            "desc": "删除 S2 停留计数分支（hold_cnt==S2_HOLD 判断改无条件跳 S3，停留不足，修复需重建等待逻辑 insert_wait）",
            "fn": "fsm_s2_hold_remove",
            "args": [],
            "hit": "fsm_ctrl 强断言 A8（S2 停留不足 S2_HOLD 拍不得离开）",
            "error_type": "状态跳转", "error_type_code": "state_trans",
            "template": "insert_wait",
            "strong_assert": "wait_guard",
        },
    ],
    "uart_tx": [
        {
            "desc": "数据位结束跳转目标 S_STOP 改 S_IDLE（帧缺停止位，修复需重建 STOP 状态 split_state）",
            "fn": "jump_rewrite_re",
            "args": [r"state\s*<=\s*S_STOP;", "state    <= S_IDLE;"],
            "hit": "uart_tx A4（DATA→STOP 收尾）",
            "error_type": "状态跳转", "error_type_code": "state_trans",
            "template": "split_state",
            "param_override": {"CLK_FREQ": "400", "BAUD": "100"},
        },
    ],
    "fifo_sync": [
        {
            "desc": "删除同拍读写 count 守恒分支（同时读写时 count 仍 +1，修复需重建守恒保护 guard_boundary）",
            "fn": "branch_remove",
            "args": ["if (can_wr && can_rd) begin"],
            "hit": "fifo_sync A4（count 增量守恒）",
            "error_type": "FIFO 满空", "error_type_code": "fifo_full",
            "template": "guard_boundary",
            "template": "guard_boundary",
        },
        {
            "desc": "half_full 半满边界改写（count > DEPTH/2 误判，修复需恢复 >= 边界 guard_boundary）",
            "fn": "half_full_rewrite",
            "args": [],
            "hit": "fifo_sync A5（half_full == (count >= DEPTH/2)）",
            "error_type": "边界判断", "error_type_code": "boundary_wrap",
            "template": "guard_boundary",
        },
    ],
    "uart_rx": [
        {
            "desc": "起始位中点确认分支删除（跳过毛刺确认，修复需重建确认态 split_state）",
            "fn": "rx_start_confirm_remove",
            "args": [],
            "param_override": {"CLK_FREQ": "400", "BAUD": "100"},
            "hit": "uart_rx A2（起始位中点确认后才进数据接收）",
            "error_type": "状态跳转", "error_type_code": "state_trans",
            "template": "split_state",
        },
    ],
    "axi_lite_slave": [
        {
            "desc": "BVALID 保持逻辑删除（不等 BREADY 就清零，握手保持态缺失 split_state）",
            "fn": "bvalid_hold_remove",
            "args": [],
            "hit": "axi_lite A3（BVALID 保持至 BREADY）",
            "error_type": "握手", "error_type_code": "handshake",
            "template": "split_state",
        },
    ],
}



def _fsm_s2_hold_remove(src):
    # insert_wait：删除 S2 停留计数分支（hold_cnt==S2_HOLD 判断改无条件进 S3），
    # S2 只停留 1 拍即跳 S3，修复需重建停留等待逻辑（wait_guard 强断言抓停留不足）
    idx = src.find("S2: begin")
    if idx < 0:
        return None
    sub = src[idx:]
    old = (
        "                    end else if (hold_cnt == S2_HOLD) begin" + chr(10)
        + "                        state    <= S3;" + chr(10)
        + "                        hold_cnt <= 4'd1;" + chr(10)
        + "                    end else begin" + chr(10)
        + "                        hold_cnt <= hold_cnt + 1'b1;" + chr(10)
        + "                    end"
    )
    new = (
        "                    end else begin" + chr(10)
        + "                        state    <= S3;" + chr(10)
        + "                        hold_cnt <= 4'd1;" + chr(10)
        + "                    end"
    )
    if old not in sub:
        return None
    return src[:idx] + sub.replace(old, new, 1)


def _rx_start_confirm_remove(src):
    # uart_rx START 中点确认删除：把 if(rxd)毛刺回IDLE/else进DATA 整块替换为无条件进 DATA
    i0 = src.find('                        if (rxd) begin')
    if i0 < 0:
        return None
    m = re.search(r"if \(rxd\) begin.*?end else begin.*?end", src[i0:], re.S)
    if not m:
        return None
    NL = chr(10)
    repl = ('                        // [structural] 毛刺检测分支被删除，中点无条件进 DATA' + NL
            + '                        baud_cnt <= {DIV_W{1' + chr(39) + 'b0}};' + NL
            + '                        bit_cnt  <= 4' + chr(39) + 'd0;' + NL
            + '                        state    <= S_DATA;' + NL)
    return src[:i0] + repl + src[i0 + m.end():]


def _bvalid_hold_remove(src):
    NL = chr(10)
    old = '        end else if (S_AXI_BVALID && S_AXI_BREADY) begin' + NL + '            S_AXI_BVALID <= 1' + chr(39) + 'b0;' + NL + '        end'
    new = '        end else begin' + NL + '            S_AXI_BVALID <= 1' + chr(39) + 'b0;' + NL + '        end'
    if old not in src:
        return None
    return src.replace(old, new, 1)


def _half_full_rewrite(src):
    old = 'count >= (DEPTH >> 1)'
    new = 'count >  (DEPTH >> 1)'
    if old not in src:
        return None
    return src.replace(old, new, 1)

def _apply_template(golden, tpl):
    fn = tpl["fn"]
    if fn == "jump_rewrite":
        buggy = _jump_rewrite(golden, tpl["args"][0], tpl["args"][1])
    elif fn == "jump_rewrite_re":
        m = re.search(tpl["args"][0], golden)
        if not m:
            return None, "jump_rewrite_re target not found"
        buggy = golden[:m.start()] + tpl["args"][1] + golden[m.end():]
    elif fn == "timeout_remove":
        buggy = _timeout_remove(golden)
    elif fn == "rx_start_confirm_remove":
        buggy = _rx_start_confirm_remove(golden)
    elif fn == "fsm_s2_hold_remove":
        buggy = _fsm_s2_hold_remove(golden)
    elif fn == "bvalid_hold_remove":
        buggy = _bvalid_hold_remove(golden)
    elif fn == "half_full_rewrite":
        buggy = _half_full_rewrite(golden)
    elif fn == "block_remove":
        buggy = _block_remove(golden, tpl["args"][0])
    elif fn == "branch_remove":
        buggy = _branch_remove(golden, tpl["args"][0])
    else:
        return None, "unknown fn"
    if buggy is None:
        return None, "template match failed"
    if buggy == golden:
        return None, "template produced identical source"
    return buggy, None


def _build_sample(module, tpl, sample_id, out_dir, timeout):
    """复用 bug_injector 管线：内联断言+环境约束 → 三通过校验 → 7件套落盘。"""
    res = {"sample": sample_id, "module": module, "ok": False, "error": "", "template": tpl["template"]}
    try:
        golden = open(os.path.join(RTL_DIR, module, module + ".sv"), encoding="utf-8").read()
        assertions = open(os.path.join(RTL_DIR, module, "assertions.sv"), encoding="utf-8").read()
        tb = open(os.path.join(RTL_DIR, module, "tb_" + module + ".sv"), encoding="utf-8").read()
        param_override = tpl.get("param_override")
        if param_override:
            golden = bug_injector._apply_params(golden, param_override)
            assertions = bug_injector._apply_params(assertions, param_override)
            tb = bug_injector._apply_params(tb, param_override)
        buggy, err = _apply_template(golden, tpl)
        if buggy is None:
            res["error"] = err
            return res
        tb = bug_injector._weaken_tb(tb, tpl["error_type_code"])
        tb = bug_injector._strip_tb_assert(tb)
        # 内联断言 + 环境约束（复用 bug_injector 的 _finalize 逻辑）
        def _finalize(design_src):
            src = bug_injector._inline_assert(design_src, assertions, module)
            clk_name, rst_name, quiet_inputs = bug_injector.RESET_SILENCE.get(
                module, ("clk", "rst_n", []))
            if quiet_inputs:
                lines = [
                    "\n    // 环境约束：初始拍处于复位（%s==0），复位释放沿（0->1）输入静默，"
                    "与弱 tb 复位行为一致；设计内部状态由复位分支初始化（避免 initial 覆盖注入缺陷）" % rst_name,
                    "    initial assume (!%s);" % rst_name,
                    "    always @(posedge %s) begin" % clk_name,
                    "        if (!%s) begin" % rst_name,
                ]
                for sig in quiet_inputs:
                    lines.append("            assume (!%s);" % sig)
                lines += ["        end", "    end", ""]
                src = src.replace("endmodule", "\n".join(lines) + "\nendmodule\n")
            for gclk, gexpr in bug_injector.GLOBAL_ASSUME.get(module, []):
                ga = (
                    "\n    // 环境约束：%s（断言依赖的环境假设，避免与缺陷无关的假反例）\n"
                    "    always @(posedge %s) assume (%s);\n" % (gexpr, gclk, gexpr))
                src = src.replace("endmodule", ga + "\nendmodule\n")
            return src
        golden_inline = _finalize(golden)
        buggy_inline = _finalize(buggy)
        # 结构性缺陷 rx_start_confirm_remove 与 GLOBAL_ASSUME 的 START 约束冲突：
        # 该约束强制 START 期间 rxd==0，直接排除"毛刺误触发"场景，使缺陷不可达（sby 空洞 PASS）。
        # 仅对本模板移除 START 期间 rxd 静默约束（保留 STOP 期间 rxd==1 约束），使毛刺场景可被反例触发。
        if tpl.get("fn") == "rx_start_confirm_remove":
            _start_assume = "    always @(posedge clk) assume (!(state == S_START) || !rxd);\n"
            golden_inline = golden_inline.replace(_start_assume, "")
            buggy_inline = buggy_inline.replace(_start_assume, "")

        # 强断言注入：超时保护必须存在（step_cnt 超阈值后下一拍必须回 IDLE）
        if tpl.get("strong_assert") == "timeout_guard":
            guard = (
                "\n    // [structural] A8 强断言：非空闲且 step_cnt 达阈值后下一拍必须回 IDLE\n"
                "    always @(posedge clk) begin\n"
                "        if (rst_n && (state_d != S_IDLE) && (step_cnt_d >= TIMEOUT)) begin\n"
                "            assert (state == S_IDLE);\n"
                "        end\n"
                "    end\n"
            )
            # 插在 A6 之前（endmodule 前的最后一个 always 之前）
            buggy_inline = buggy_inline.replace(
                "    // 环境约束：初始拍处于复位",
                guard + "    // 环境约束：初始拍处于复位")
            golden_inline = golden_inline.replace(
                "    // 环境约束：初始拍处于复位",
                guard + "    // 环境约束：初始拍处于复位")
        # [structural] A8 强断言：S2 停留不足 S2_HOLD 拍不得离开（insert_wait 模板）
        if tpl.get("strong_assert") == "wait_guard":
            guard_w = (
                chr(10) + "    // [structural] A8 强断言：S2 停留不足 S2_HOLD 拍不得离开" + chr(10)
                + "    always @(posedge clk) begin" + chr(10)
                + "        if (rst_n && (state_d == S2) && (hold_cnt_d < S2_HOLD) && (state != S_IDLE)) begin" + chr(10)
                + "            assert (state == S2);" + chr(10)
                + "        end" + chr(10)
                + "    end" + chr(10)
            )
            buggy_inline = buggy_inline.replace(
                "    // 环境约束：初始拍处于复位",
                guard_w + "    // 环境约束：初始拍处于复位")
            golden_inline = golden_inline.replace(
                "    // 环境约束：初始拍处于复位",
                guard_w + "    // 环境约束：初始拍处于复位")
        top_mod, _params, _ports = bug_injector._module_info(golden)
        tb_top = bug_injector._TB_MODULE.search(tb)
        tb_top = tb_top.group(1) if tb_top else None
        depth = bug_injector.MODULE_DEPTH.get(module, 24)
        if param_override and module == "uart_tx":
            try:
                clk = int(param_override.get("CLK_FREQ", 50000000))
                baud = int(param_override.get("BAUD", 115200))
                div = max(1, clk // baud)
                depth = 10 * div + 16
            except ValueError:
                pass
        sby_file = os.path.join(out_dir, sample_id, "verify.sby")
        os.makedirs(os.path.join(out_dir, sample_id), exist_ok=True)
        with open(sby_file, "w", encoding="utf-8") as f:
            f.write(bug_injector._gen_sby(module, top_mod, depth))
        tmp_dir = tempfile.mkdtemp(prefix="struct_")
        work_dir = tempfile.mkdtemp(prefix="sby_work_")
        try:
            for name, data in (("buggy.v", buggy_inline), ("golden.v", golden_inline),
                               ("tb_weak.sv", tb)):
                with open(os.path.join(tmp_dir, name), "w", encoding="utf-8") as f:
                    f.write(data)
            if module == "uart_rx":
                shutil.copy(os.path.join(RTL_DIR, "uart_tx", "uart_tx.sv"), os.path.join(tmp_dir, "uart_tx.sv"))
            t_sby = os.path.join(tmp_dir, "verify.sby")
            with open(t_sby, "w", encoding="utf-8") as f:
                f.write(bug_injector._gen_sby(module, top_mod, depth))
            ok, detail = bug_injector._validate_candidate(
                tmp_dir, tb_top, t_sby, depth, work_dir, module, top_mod)
            res["compile"] = True
            res["sim"] = detail.get("stage") != "sim"
            res["formal"] = "fail" if ok else detail.get("stage")
            if not ok:
                res["error"] = "validate fail: %s" % json.dumps(detail, ensure_ascii=False)[:200]
                return res
            # 生成 diff 文本（golden vs buggy 原始设计，供 meta/复现）
            diff = "".join(
                "+ " + l if i in {0} else l for i, l in enumerate([])
            ) or ""
            # 用 git-style 简化 diff：直接记录模板描述
            cmd_line = ("python3 scripts/build_structural_samples.py --module %s" % module)
            sample_dir = os.path.join(out_dir, sample_id)
            bug_injector._write_sample(
                sample_dir, module, sample_id, golden_inline, buggy_inline, assertions,
                tb, top_mod, tb_top, depth,
                {"desc": tpl["desc"], "hit": tpl["hit"], "template": tpl["template"]},
                1, diff,
                {"err_name": tpl["error_type"], "code": tpl["error_type_code"]},
                cmd_line, None, "L3",
                {"structural_template": tpl["template"]})
            copied = bug_injector._copy_cex(detail["sby_work"], sample_dir)
            # 修正 _write_sample 生成的 meta（_doc %s 未格式化 / diff 空 / date 旧）
            meta_p = os.path.join(sample_dir, "meta.json")
            if os.path.isfile(meta_p):
                meta = json.load(open(meta_p, encoding="utf-8"))
                meta["_doc"] = ("PreCex L3 结构性缺陷样本元数据 | 作者：Toylog | 版本：v0.1 | "
                                "功能概述：结构级缺陷（跳转目标改写/保护分支删除），修复需结构性重写")
                meta["diff"] = "structural: %s" % tpl["desc"]
                meta["date"] = "2026-08-05"
                meta["structural_template"] = tpl["template"]
                with open(meta_p, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            res["ok"] = True
            res["copied_cex"] = copied
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            shutil.rmtree(work_dir, ignore_errors=True)
    except Exception as e:
        res["error"] = repr(e)[:250]
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default=None)
    ap.add_argument("--out-dir", default=SAMPLES_DIR)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--template", default=None)
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    tasks = []
    for module, tpls in STRUCTURAL.items():
        if args.module and module != args.module:
            continue
        for i, tpl in enumerate(tpls):
            if args.smoke and i > 0:
                continue
            if args.template and tpl.get("fn") != args.template:
                continue
            tasks.append((module, tpl))
    existing = set()
    for base in (SAMPLES_BUGS, SAMPLES_DEEP, args.out_dir):
        if os.path.isdir(base):
            for d in os.listdir(base):
                m = re.match(r"^s(\d+)$", d)
                if m:
                    existing.add(int(m.group(1)))
    nxt = 43
    if existing:
        nxt = max(nxt, max(existing) + 1)
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = []
        for module, tpl in tasks:
            sid = "s%02d" % nxt
            nxt += 1
            futs.append(ex.submit(_build_sample, module, tpl, sid, args.out_dir, args.timeout))
        for fu in as_completed(futs):
            r = fu.result()
            results.append(r)
            print("[%s] %s/%s ok=%s compile=%s sim=%s formal=%s err=%s" % (
                r["sample"], r["module"], r["template"], r["ok"],
                r.get("compile"), r.get("sim"), r.get("formal"),
                (r.get("error") or "")[:100]), flush=True)
    ok = sum(1 for r in results if r["ok"])
    print("== done: ok=%d/%d ==" % (ok, len(results)), flush=True)
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())