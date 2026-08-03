#!/usr/bin/env python3
# PreCex - scripts/bug_injector.py：L3 缺陷样本注入器（黄金 RTL → 规则化文本变换注入 7 类缺陷 → 三通过自动校验 → 7 件套落盘）
# 作者：Toylog | 版本：v0.1 | 功能概述：对 rtl/<模块>/<模块>.sv 做规则化正则变换注入缺陷，生成 samples/bugs/<sample-id>/
#   7 件套（buggy.v / golden.v / assertions.sv / tb_weak.sv / cex.vcd / cex.log / meta.json / evidence.json / notes.md），
#   复用 harness/evaluator.py 三通过判定（compile 0 error + 弱 tb 全绿 + sby formal 抓反例），三者同时满足才产出有效 L3 样本。
# 运行环境：WSL 内 python3（iverilog/vvp/sby/z3 均在 PATH；sby 环境由 evaluator.formal_check 注入 PATH+SMTBMC）
# 用法：
#   python3 bug_injector.py --list-types
#   python3 bug_injector.py --module fifo_sync --error-type fifo_full --sample-id s01 [--line N] [--seed 0] [--dry-run]

"""L3 反例驱动缺陷样本注入器（纯标准库）。"""

import argparse
import json
import os
import random
import re
import shutil
import sys
import tempfile

# ---- 路径与常量 ----
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
from evaluator import compile_check, sim_check, formal_check  # noqa: E402  复用三通过判定

RTL_DIR = os.path.join(REPO_ROOT, "rtl")
SAMPLES_DIR = os.path.join(REPO_ROOT, "samples", "bugs")
DATE = "2026-08-03"          # 构造日期（数据集污染检查用）
FORMAL_TIMEOUT = 240.0       # 注入校验时 formal 超时（sby smtbmc+z3，秒）
SIM_TIMEOUT = 120.0          # 弱 tb 仿真超时

# 各模块 sby BMC 深度：反例可达拍数 + 裕量（fifo A5 需写 4 拍；fsm A6 需走完序列约 12 拍）
MODULE_DEPTH = {
    "fifo_sync": 12, "fsm_ctrl": 24, "uart_tx": 24, "uart_rx": 24,
    "axi_lite_slave": 16, "counter_alu": 12,
}


# ---- 弱 tb 清洗规则：按 error_type 剥离会击穿该缺陷的仿真检查行 ----
# 弱 tb 要求“放过缺陷”：黄金 tb 若显式断言 full/empty/half_full/count 等被注入缺陷直接影响的信号，
# 会在 sim 阶段击穿 buggy，导致 L3 校验失败。清洗即删除含这些关键字的 $fatal 检查行（保留数据通路检查）。
WEAK_TB_STRIP = {"fifo_full": ["full", "empty", "half_full", "count", "dout"]}


def _weaken_tb(tb_src, error_type):
    # 按错误类型清洗弱 tb：删除会击穿该缺陷的仿真检查行，返回清洗后源码
    keys = WEAK_TB_STRIP.get(error_type)
    if not keys:
        return tb_src
    out = []
    removed = 0
    for line in tb_src.splitlines():
        # 命中 $fatal 且包含任一关键字的行：整行剥离（弱 tb 不再检查该信号）
        if "$fatal" in line and any(k in line for k in keys):
            removed += 1
            continue
        out.append(line)
    new = "\n".join(out)
    if removed:
        new += "\n// [bug_injector] weak tb sanitized for %s: stripped %d fatal check(s) on %s\n" % (
            error_type, removed, "/".join(keys))
    return new


# ---- 7 类错误注入器：每类 = 一组规则化文本变换 variant（正则匹配黄金源码，优先顺序即尝试顺序）----
# variant 结构：{"desc", "pat"(编译后正则), "repl"(替换串/None=删除整行), "hit"(击穿的断言提示), "expect"(预期适用模块)}
INJECTORS = {
    "state_trans": {
        "name": "状态跳转",
        "desc": "状态机跳转/内部时序错误：删转移分支、改跳转目标、删状态机计数清零",
        "variants": [
            {"desc": "删 S_IDLE 中 step_cnt 清零（状态机内部步进计数不清零，击穿 fsm_ctrl A6 单调性）",
             "pat": re.compile(r"(S_IDLE:\s*begin\n)(\s*)step_cnt\s*<=\s*6'd0;\n"),
             "repl": r"\1", "hit": "fsm_ctrl A6（空闲期 step_cnt 必须为 0）", "expect": "fsm_ctrl"},
            {"desc": "S1 正常完成分支跳转目标 S2 改 S3（跳过 S2，击穿状态跳转合法性）",
             "pat": re.compile(r"hold_cnt\s*==\s*S1_HOLD\)\s*begin\s*\n(\s*)state\s*<=\s*S2;"),
             "repl": r"hold_cnt == S1_HOLD) begin\n\1state    <= S3;", "hit": "状态跳转合法性断言", "expect": "fsm_ctrl"},
            {"desc": "IDLE 启动目标 S1 改 S2（击穿启动语义断言）",
             "pat": re.compile(r"if\s*\(\s*start\s*\)\s*begin\s*\n(\s*)state\s*<=\s*S1;"),
             "repl": r"if (start) begin\n\1state    <= S2;", "hit": "启动语义断言", "expect": "fsm_ctrl"},
        ],
    },
    "handshake": {
        "name": "握手",
        "desc": "握手信号条件错误：握手使能放宽/应答丢失/握手状态不释放",
        "variants": [
            {"desc": "起始位握手失效：删 S_IDLE 中『起始位立即输出低电平』（txd 保持高，击穿 uart A1 起始位为低）",
             "pat": re.compile(r"txd\s*<=\s*1'b0;\s*//\s*起始位立即输出低电平\n"),
             "repl": None, "hit": "uart_tx A1（START 时 txd==0）", "expect": "uart_tx"},
            {"desc": "写地址应答不释放：aw_done 完成分支删除（AWREADY 持续应答，重复握手）",
             "pat": re.compile(r"(\s*else\s+if\s+\(S_AXI_BVALID\s*&&\s*S_AXI_BREADY\)\s*begin\s*\n)(\s*)S_AXI_AWREADY\s*<=\s*1'b0;\s*\n(\s*)aw_done\s*<=\s*1'b0;\n"),
             "repl": r"\1\2// BUG: AWREADY 应答释放被删除（握手状态不释放）\n\3// aw_done <= 1'b0;\n",
             "hit": "axi 写通道握手断言", "expect": "axi_lite_slave"},
        ],
    },
    "fifo_full": {
        "name": "FIFO 满空",
        "desc": "FIFO 满/空/半满指示或门控错误：改 count 比较、去掉满/空写读保护",
        "variants": [
            {"desc": "半满标志比较 >= 改 >（count==DEPTH/2 时半满错误为 0，击穿 A5）",
             "pat": re.compile(r"(assign\s+half_full\s*=\s*\(count\s*)(>=)(\s*\(DEPTH\s*>>\s*1\)\);)$", re.M),
             "repl": r"\g<1>>\g<3>", "hit": "fifo_sync A5（half_full==(count>=DEPTH/2)）", "expect": "fifo_sync"},
            {"desc": "写满保护去除：can_wr 去掉 !full 门控（满时仍写，击穿 A1）",
             "pat": re.compile(r"(wire\s+can_wr\s*=\s*wr_en\s*)&&\s*!full\s*;"),
             "repl": r"\g<1>;", "hit": "fifo_sync A1（满时不写）", "expect": "fifo_sync"},
            {"desc": "空标志比较 ==0 改 <=1（count==1 时误报空，击穿 A2 类性质）",
             "pat": re.compile(r"(assign\s+empty\s*=\s*\(count\s*==\s*)0(\s*\);)$", re.M),
             "repl": r"\g<1>1'b1\g<2>", "hit": "fifo_sync A2（空时不读）", "expect": "fifo_sync"},
        ],
    },
    "boundary_wrap": {
        "name": "边界回绕",
        "desc": "边界比较/回绕逻辑错误：比较界提前/推迟、指针回绕失效、超时阈值偏移",
        "variants": [
            {"desc": "超时阈值提前一拍：step_cnt >= TIMEOUT 改 >= TIMEOUT-1（提前触发超时，击穿 A3 前置）",
             "pat": re.compile(r"(step_cnt\s*>=\s*TIMEOUT\s*-\s*)(1'b1)(\s*)\)"),
             "repl": r"\g<1>1'b0\g<3>", "hit": "fsm_ctrl A3（timeout_irq 前置 step_cnt_d>=TIMEOUT）", "expect": "fsm_ctrl"},
            {"desc": "写指针不回绕推进：tail <= tail+1 改 tail 保持（同址覆写，数据顺序错乱）",
             "pat": re.compile(r"(tail\s*<=\s*)(tail\s*\+\s*1'b1);"),
             "repl": r"\1tail;", "hit": "fifo_sync A4/A3 类指针性质", "expect": "fifo_sync"},
            {"desc": "数据位计数终值偏移：bit_cnt == DATA_W-1 改 == DATA_W（数据位永不结束，卡死 DATA）",
             "pat": re.compile(r"(bit_cnt\s*==\s*DATA_W\s*-\s*)1'b1(\s*\)\s*begin)"),
             "repl": r"\g<1>1'b1\g<2>", "hit": "uart_tx A4（DATA→STOP 收尾）", "expect": "uart_tx"},
        ],
    },
    "reset": {
        "name": "复位",
        "desc": "复位行为错误：复位值改动、复位分支删除/条件反转、复位寄存器遗漏",
        "variants": [
            {"desc": "读指针复位值 0 改全 1（head 越界，击穿 A3 指针不越界）",
             "pat": re.compile(r"(head\s*<=\s*\{ADDR_W\{)1'b0(\}\};)"),
             "repl": r"\g<1>1'b1\g<2>", "hit": "fifo_sync A3（head<DEPTH）", "expect": "fifo_sync"},
            {"desc": "计数器复位值 0 改全 1（复位释放后 cnt 非 0，击穿 A3 复位归 0）",
             "pat": re.compile(r"(cnt\s*<=\s*\{DATA_W\{)1'b0(\}\};)"),
             "repl": r"\g<1>1'b1\g<2>", "hit": "counter_alu A3（复位释放归 0）", "expect": "counter_alu"},
            {"desc": "复位条件取反：!rst_n 改 rst_n（复位/运行反转，状态机失序）",
             "pat": re.compile(r"always\s*@\(posedge\s+clk\s+or\s+negedge\s+rst_n\)\s*begin\s*\n(\s*)if\s*\(!rst_n\)\s*begin"),
             "repl": r"always @(posedge clk or negedge rst_n) begin\n\1if (rst_n) begin",
             "hit": "复位行为断言", "expect": "通用"},
        ],
    },
    "width_trunc": {
        "name": "位宽截断",
        "desc": "数据/计数位宽或截断错误：寄存器位宽变窄、增量位宽错误、输出截高位",
        "variants": [
            {"desc": "count 位宽收窄 1 位（count 存满值时截断回绕，击穿 A1/A4 满值与守恒）",
             "pat": re.compile(r"(reg\s+\[CNT_W-1:0\]\s+count;)"),
             "repl": r"reg [CNT_W-2:0] count;", "hit": "fifo_sync A1/A4", "expect": "fifo_sync"},
            {"desc": "计数器增量 1 改 2（cnt_en 时 +2，击穿 A1 仅使能 +1）",
             "pat": re.compile(r"(cnt\s*<=\s*cnt\s*\+\s*)1'b1(\s*;)$", re.M),
             "repl": r"\g<1>2'd2\g<2>", "hit": "counter_alu A1（仅使能自增 1）", "expect": "counter_alu"},
        ],
    },
    "edge": {
        "name": "边沿",
        "desc": "时钟/数据采样边沿错误：触发沿改反、打拍删除、脉冲条件取反",
        "variants": [
            {"desc": "状态机触发沿 posedge 改 negedge（与断言 posedge 打拍错拍，跨周期性质失配）",
             "pat": re.compile(r"(always\s*@\(posedge\s+clk\s+or\s+negedge\s+rst_n\))"),
             "repl": r"always @(negedge clk or negedge rst_n)", "hit": "跨周期打拍断言", "expect": "通用"},
            {"desc": "波特率脉冲取反：baud_tick 改 !baud_tick（位节奏错误）",
             "pat": re.compile(r"(if\s*\()(baud_tick)(\)\s*begin\s*\n\s*baud_cnt\s*<=\s*DIV\s*-\s*1'b1;)"),
             "repl": r"\g<1>!\g<2>\g<3>", "hit": "uart_tx 位周期性质", "expect": "uart_tx"},
        ],
    },
}


# ---- 黄金源码解析（模块头：参数 + ANSI 端口）----
_MODULE_HEAD = re.compile(
    r"module\s+(\w+)(?:\s*#\((?P<params>.*?)\))?\s*\((?P<ports>.*?)\);", re.S)
_PORT_DECL = re.compile(
    r"^\s*(input|output)\s+(?:wire|reg)?\s*(\[[^\]]*\])?\s*(\w+)\s*,?\s*(?://.*)?$")
_PARAM_LINE = re.compile(r"(\w+)\s*=\s*([^,]+)")
_ASSERT_PORT = re.compile(
    r"^\s*(?:input|output)\s+(?:wire|reg)?\s*(?:\[[^\]]*\])?\s*(\w+)\s*;\s*(?://.*)?$", re.M)
_TB_MODULE = re.compile(r"module\s+(tb_\w+)")


def _module_info(src):
    """提取模块名/参数/端口。返回 (name, params[(n,default)], ports[(dir,width,name)])。"""
    m = _MODULE_HEAD.search(src)
    if not m:
        raise ValueError("无法解析模块头")
    params = _PARAM_LINE.findall(m.group("params") or "")
    ports = []
    for line in m.group("ports").splitlines():
        pm = _PORT_DECL.match(line)
        if pm:
            ports.append((pm.group(1), pm.group(2), pm.group(3)))
    if not ports:
        raise ValueError("未能解析模块端口声明")
    return m.group(1), params, ports


def _line_of(src, match):
    """匹配对象起始位置所在行号（1-based）。"""
    return src.count("\n", 0, match.start()) + 1


def _apply_variant(src, variant):
    """对源码应用一个 variant 变换。返回 (new_src, line_no, diff) 或 None（未匹配）。"""
    m = variant["pat"].search(src)
    if not m:
        return None
    if variant["repl"] is None:                      # 删除整行（含换行）
        new_src = src[: m.start()] + src[m.end():]
        old, new = src[m.start(): m.end()].rstrip("\n"), "<deleted>"
    else:
        new_src = variant["pat"].sub(variant["repl"], src, count=1)
        old = src[m.start(): m.end()].rstrip("\n")
        # 子串替换：匹配区前/后内容不变，替换后匹配区长度可能变化，按新文本精确截取
        new = new_src[m.start(): len(new_src) - len(src[m.end():])].rstrip("\n")
    diff = "- %s\n+ %s" % (old, new)
    return new_src, _line_of(src, m), diff


# ---- formal 顶层 wrapper 与 verify.sby 生成 ----
def _gen_formal_top(module, params, ports, assert_ports):
    """生成 sby 顶层 wrapper：例化设计 uut + 断言 u_assert（内部信号经 uut.xxx 分层接入）。"""
    top = module + "_formal_top"
    port_names = [n for _d, _w, n in ports]
    param_inst = ",\n".join("        .%s(%s)" % (p, p) for p, _d in params)
    lines = [
        "// PreCex - %s L3 缺陷样本 formal 顶层 wrapper（sby 用）" % module,
        "// 作者：Toylog | 版本：v0.1 | 功能概述：例化设计 uut 与断言 u_assert，供 sby (smtbmc+z3) BMC 检查断言",
        "",
        "module %s #(" % top,
    ]
    # 参数声明（保持参数化，端口宽度引用参数名）
    for i, (p, d) in enumerate(params):
        lines.append("    parameter %s = %s%s" % (p, d, "," if i < len(params) - 1 else ""))
    lines.append(") (")
    # 顶层端口：与设计同方向同宽度（output 一律 wire）
    for i, (d, w, n) in enumerate(ports):
        lines.append("    %s wire %s %s%s" % (d, w or "", n, "," if i < len(ports) - 1 else ""))
    lines.append(");")
    # 设计输出连线声明
    # 设计实例（实例名 uut 与弱 tb 一致）
    lines += ["", "    // 设计实例（实例名 uut 与弱 tb 一致）", "    %s #(" % module, param_inst, "    ) uut ("]
    for i, (_d, _w, n) in enumerate(ports):
        lines.append("        .%s(%s)%s" % (n, n, "," if i < len(ports) - 1 else ""))
    lines += ["    );", "", "    // 断言实例：内部信号分层引用 uut.xxx", "    %s_assert #(" % module,
              param_inst, "    ) u_assert ("]
    for i, an in enumerate(assert_ports):
        conn = an if an in port_names else "uut.%s" % an
        lines.append("        .%s(%s)%s" % (an, conn, "," if i < len(assert_ports) - 1 else ""))
    lines += ["    );", "", "endmodule", ""]
    return "\n".join(lines)


def _gen_sby(module, top_mod, depth):
    """生成 verify.sby（bmc + smtbmc/z3，read -formal 与断言矩阵收敛路径一致）。"""
    return (
        "# PreCex - L3 样本 (module=%s) SymbiYosys 配置：对 buggy 版运行 BMC，期望 Assert failed\n"
        "# 作者：Toylog | 版本：v0.1 | 功能概述：read -sv -formal 三文件 + prep -top wrapper + smtbmc(z3) BMC，depth %d\n"
        "# 运行方式（WSL）：export PATH=$HOME/.local/bin:$PATH; export SMTBMC=%s;\n"
        "#   sby -f verify.sby -d <workdir>    # 期望 DONE FAIL（counterexample）\n"
        "\n[tasks]\nbmc\n\n[options]\nbmc: mode bmc\nbmc: depth %d\n\n[engines]\nbmc: smtbmc\n\n"
        "[script]\nread -sv -formal buggy.v\nread -sv -formal assertions.sv\nread -sv -formal formal_top.sv\n"
        "prep -top %s\n\n[files]\nbuggy.v\nassertions.sv\nformal_top.sv\n"
    ) % (module, depth, os.path.join(REPO_ROOT, "smoke", "yosys-smtbmc-z3.sh"), depth, top_mod + "_formal_top")


def _with_init(src):
    """在 endmodule 前插入 initial 初值约束块（formal 友好：避免任意初始状态空洞反例；
    收敛文档 2.1-5 推荐；iverilog 仿真中与复位时序兼容）。只初始化体内标量 reg（数组/端口 reg 自然排除）。"""
    regs = re.findall(r"\breg\s+(?:\[[^\]]*\]\s*)?(\w+)\s*;", src)
    if not regs:
        return src
    lines = ["    // formal 初值约束（避免任意初始状态空洞反例；仿真中与复位时序兼容）",
             "    initial begin"]
    for r in regs:
        lines.append("        %s = 1'b0;" % r)
    lines.append("    end")
    block = "\n".join(lines) + "\n"
    return re.sub(r"\n(endmodule)\s*$", "\n" + block + "\\1\n", src)


# ---- 三通过校验（复用 evaluator 三函数）----
def _validate_candidate(tmp_dir, tb_top, sby_file, depth, work_dir):
    """对临时样本目录跑三通过判定。返回 (ok, 明细 dict)。"""
    buggy = os.path.join(tmp_dir, "buggy.v")
    asser = os.path.join(tmp_dir, "assertions.sv")
    tb = os.path.join(tmp_dir, "tb_weak.sv")
    # ① 编译：buggy 设计 + 断言，0 error
    comp = compile_check([buggy, asser], cwd=tmp_dir, out="a.out")
    if not comp["ok"]:
        return False, {"stage": "compile", "detail": (comp["stdout"] + comp["stderr"])[-800:]}
    # ② 弱 tb 仿真：必须放过 buggy（exit 0 且无 FAIL/$fatal 且含 $finish）
    sim = sim_check([buggy, asser, tb], top=tb_top, cwd=tmp_dir,
                    out_bin="sim.out", sim_timeout=SIM_TIMEOUT)
    if not sim["ok"]:
        out = sim["stdout"] + sim["stderr"]
        fail_lines = [l.strip() for l in out.splitlines() if "FAIL" in l or "$fatal" in l]
        return False, {"stage": "sim", "detail": "\n".join(fail_lines[-5:]) or out[-400:]}
    # ③ sby formal：期望抓到反例（result == fail）
    formal = formal_check(sby_file, timeout=FORMAL_TIMEOUT, cwd=tmp_dir,
                          design_dir=os.path.join(work_dir, "sby_work"))
    if formal["result"] != "fail":
        return False, {"stage": "formal", "result": formal["result"], "detail": formal["log_tail"][-400:]}
    return True, {"stage": "all", "formal": formal, "sby_work": os.path.join(work_dir, "sby_work")}


def _copy_cex(sby_work, sample_dir):
    """从 sby 工作目录拷贝反例证据：engine_0/trace.vcd → cex.vcd，engine_0/logfile.txt → cex.log。"""
    vcd = log = None
    for root, _dirs, files in os.walk(sby_work):
        for f in files:
            p = os.path.join(root, f)
            if f.endswith(".vcd") and vcd is None:
                vcd = p
            if f.endswith(".log") and ("engine" in root.replace("\\", "/") or log is None):
                log = p   # 优先引擎日志（engine_0/logfile.txt）
    copied = []
    for src, dst in ((vcd, "cex.vcd"), (log, "cex.log")):
        if src:
            shutil.copy(src, os.path.join(sample_dir, dst))
            copied.append(dst)
    return copied


# ---- 样本落盘 ----
def _write_sample(sample_dir, module, sample_id, golden_src, buggy_src, assertions_src,
                  tb_src, top_mod, tb_top, depth, variant, line_no, diff, verify, cmd_line):
    """生成 7 件套（buggy/golden/断言/弱tb/cex.vcd/cex.log/meta.json/evidence.json/notes.md）+ verify.sby + formal_top.sv。"""
    os.makedirs(sample_dir, exist_ok=True)
    _, params, ports = _module_info(golden_src)
    assert_ports = _ASSERT_PORT.findall(assertions_src)
    # 设计/断言/弱 tb（设计/断言加 initial 初值约束，避免 formal 空洞反例）
    with open(os.path.join(sample_dir, "golden.v"), "w", encoding="utf-8") as f:
        f.write(_with_init(golden_src))
    head = (
        "// PreCex - %s L3 缺陷样本 %s（buggy 版）\n"
        "// 作者：Toylog | 版本：v0.1 | 功能概述：注入『%s』类缺陷——%s\n"
        "// 来源：rtl/%s/%s.sv 单点注入（行 %d）| 击穿断言：%s\n\n" % (
            module, sample_id, verify["err_name"], variant["desc"], module, module, line_no, variant["hit"]))
    with open(os.path.join(sample_dir, "buggy.v"), "w", encoding="utf-8") as f:
        f.write(head + _with_init(buggy_src))
    with open(os.path.join(sample_dir, "assertions.sv"), "w", encoding="utf-8") as f:
        f.write(_with_init(assertions_src))
    with open(os.path.join(sample_dir, "tb_weak.sv"), "w", encoding="utf-8") as f:
        f.write(tb_src)
    # formal 附件
    with open(os.path.join(sample_dir, "formal_top.sv"), "w", encoding="utf-8") as f:
        f.write(_gen_formal_top(module, params, ports, assert_ports))
    with open(os.path.join(sample_dir, "verify.sby"), "w", encoding="utf-8") as f:
        f.write(_gen_sby(module, top_mod, depth))
    # meta.json（可复现：记录注入命令与参数）
    meta = {
        "_doc": "PreCex L3 缺陷样本元数据 | 作者：Toylog | 版本：v0.1 | 功能概述：描述样本标识/错误类型/注入点与复现命令",
        "sample_id": sample_id, "module": module,
        "error_type": verify["err_name"], "error_type_code": verify["code"],
        "level": "L3", "inject_line": line_no,
        "inject_desc": variant["desc"], "diff": diff,
        "hit_assertion": variant["hit"],
        "golden_source": "rtl/%s/%s.sv" % (module, module),
        "date": DATE, "reproduce_cmd": cmd_line,
        "verification": {"compile_ok": True, "sim_ok": True, "formal_result": "fail", "verdict": "L3_VALID"},
    }
    with open(os.path.join(sample_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    # evidence.json 空骨架（留待证据管线填充）
    with open(os.path.join(sample_dir, "evidence.json"), "w", encoding="utf-8") as f:
        json.dump({
            "_doc": "PreCex 结构化证据（由 EvidenceEngine 管线生成）| 作者：Toylog | 版本：v0.1",
            "sample_id": sample_id, "date": DATE,
            "entries": [], "note": "占位骨架：由证据管线填充反例周期事件/故障锥等结构化证据",
        }, f, ensure_ascii=False, indent=2)
    # notes.md 构造说明
    with open(os.path.join(sample_dir, "notes.md"), "w", encoding="utf-8") as f:
        f.write(
            "# %s - %s L3 缺陷样本构造说明\n\n"
            "> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录\n\n"
            "- 来源模块：`rtl/%s/%s.sv`（黄金基线）\n"
            "- 错误类型：%s（%s）\n"
            "- 注入点：第 %d 行，规则化文本变换：\n\n"
            "```\n%s\n```\n\n"
            "- 击穿断言：%s\n"
            "- 三通过校验（L3 判定）：① iverilog 编译 0 error ✓；② 弱 tb 仿真全绿（放过 buggy）✓；"
            "③ sby (smtbmc+z3) BMC 抓到反例 ✓\n"
            "- 复现命令：`%s`\n"
            "- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 %s）\n" % (
                sample_id, module, module, module, verify["err_name"], verify["code"],
                line_no, diff, variant["hit"], cmd_line, DATE))
    return meta


def _report_failure(cmd_line, module, err_code, fails):
    """校验全部失败：打印各 variant 失败原因（含调弱 tb 提示），不产出样本。"""
    print("== 注入失败：module=%s error_type=%s（不产出无效样本）==" % (module, err_code))
    for v, fail in fails:
        print("  variant[%s]：%s" % (v["desc"], fail["stage"]))
        print("    " + fail.get("detail", fail.get("result", "")).replace("\n", "\n    "))
        if fail["stage"] == "sim":
            print("    提示：黄金 tb 抓到 buggy，建议换注入点或对 tb_weak.sv 调弱（删除对应检查段）")
        if fail["stage"] == "formal":
            print("    提示：formal=%s 未抓到反例（断言未击穿），建议换 variant 或检查 depth" % fail.get("result"))
    print("复现命令：%s" % cmd_line)


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    ap = argparse.ArgumentParser(
        prog="bug_injector.py", description="PreCex L3 缺陷样本注入器（黄金 RTL → 7 类缺陷注入 → 三通过校验 → 7 件套）")
    ap.add_argument("--list-types", action="store_true", help="列出 7 类错误及其注入方式")
    ap.add_argument("--module", help="黄金模块名（rtl/<module>/）")
    ap.add_argument("--error-type", help="错误类型 code（见 --list-types）")
    ap.add_argument("--sample-id", default="s01", help="样本标识（默认 s01）")
    ap.add_argument("--line", type=int, default=None, help="指定注入点行号（限制 variant 匹配该行）")
    ap.add_argument("--seed", type=int, default=0, help="variant 尝试顺序随机种子（默认 0=声明顺序）")
    ap.add_argument("--dry-run", action="store_true", help="仅打印将应用的 diff，不落盘不校验")
    args = ap.parse_args(argv)

    if args.list_types:
        print("== PreCex 7 类错误模板（BugBench-PS L3）==")
        for code, t in INJECTORS.items():
            print("\n[%s] %s：%s" % (code, t["name"], t["desc"]))
            for i, v in enumerate(t["variants"], 1):
                print("  变体%d：%s（预期适用 %s；击穿 %s）" % (i, v["desc"], v["expect"], v["hit"]))
        return 0

    if not (args.module and args.error_type):
        ap.print_help()
        return 1
    err = INJECTORS.get(args.error_type)
    if not err:
        print("error: 未知错误类型 '%s'（--list-types 查看）" % args.error_type, file=sys.stderr)
        return 1
    mod_dir = os.path.join(RTL_DIR, args.module)
    if not os.path.isdir(mod_dir):
        print("error: 模块目录不存在 %s" % mod_dir, file=sys.stderr)
        return 1
    golden_path = os.path.join(mod_dir, "%s.sv" % args.module)
    assert_path = os.path.join(mod_dir, "assertions.sv")
    tb_path = os.path.join(mod_dir, "tb_%s.sv" % args.module)
    if not all(os.path.isfile(p) for p in (golden_path, assert_path, tb_path)):
        print("error: 模块 3 文件不齐（%s/assertions.sv/tb_%s.sv）" % (args.module, args.module), file=sys.stderr)
        return 1

    golden = open(golden_path, encoding="utf-8").read()
    assertions = open(assert_path, encoding="utf-8").read()
    tb = open(tb_path, encoding="utf-8").read()
    tb = _weaken_tb(tb, args.error_type)   # 弱 tb 清洗：剥离会击穿本类缺陷的仿真检查行
    top_mod, _params, _ports = _module_info(golden)
    tb_top = _TB_MODULE.search(tb)
    tb_top = tb_top.group(1) if tb_top else None
    depth = MODULE_DEPTH.get(args.module, 24)

    variants = list(err["variants"])
    if args.seed:
        random.Random(args.seed).shuffle(variants)
    cmd_line = "python3 scripts/bug_injector.py --module %s --error-type %s --sample-id %s%s%s" % (
        args.module, args.error_type, args.sample_id,
        " --line %d" % args.line if args.line else "", " --seed %d" % args.seed if args.seed else "")

    # 逐 variant 注入 + 校验（dry-run 时仅打印所有可应用 diff，不落盘不校验）
    fails = []
    sample_dir = os.path.join(SAMPLES_DIR, args.sample_id)
    for v in variants:
        applied = _apply_variant(golden, v)
        if not applied:
            continue
        buggy_src, line_no, diff = applied
        if args.line is not None and line_no != args.line:
            continue
        print("== 尝试注入：%s 变体 [%s]（第 %d 行）==" % (args.error_type, v["desc"], line_no))
        print(diff)
        if args.dry_run:
            continue  # 仅审计 diff，不落盘不校验
        # 临时样本目录做校验，成功才落盘正式目录
        tmp_dir = tempfile.mkdtemp(prefix="inject_")
        work_dir = tempfile.mkdtemp(prefix="sby_work_")
        try:
            _, params, ports = _module_info(golden)
            assert_ports = _ASSERT_PORT.findall(assertions)
            for name, data in (
                    ("buggy.v", _with_init(buggy_src)), ("golden.v", golden),
                    ("assertions.sv", _with_init(assertions)), ("tb_weak.sv", tb),
                    ("formal_top.sv", _gen_formal_top(args.module, params, ports, assert_ports))):
                with open(os.path.join(tmp_dir, name), "w", encoding="utf-8") as f:
                    f.write(data)
            sby_file = os.path.join(tmp_dir, "verify.sby")
            with open(sby_file, "w", encoding="utf-8") as f:
                f.write(_gen_sby(args.module, top_mod, depth))
            ok, detail = _validate_candidate(tmp_dir, tb_top, sby_file, depth, work_dir)
            if not ok:
                fails.append((v, detail))
                print("  校验失败（%s），尝试下一变体…" % detail["stage"])
                continue
            # 三通过成立 → 落盘样本 + 拷贝 cex 证据
            _write_sample(sample_dir, args.module, args.sample_id, golden, buggy_src, assertions,
                          tb, top_mod, tb_top, depth, v, line_no, diff,
                          {"err_name": err["name"], "code": args.error_type}, cmd_line)
            copied = _copy_cex(detail["sby_work"], sample_dir)
            print("  校验通过：compile ✓ sim ✓ formal=fail ✓  → 样本 %s 已产出（cex: %s）"
                  % (sample_dir, ",".join(copied) or "(未找到 trace 波形)"))
            return 0
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            shutil.rmtree(work_dir, ignore_errors=True)
    if args.dry_run:
        print("\n== dry-run：以上为将应用的 diff（未落盘、未校验）==")
        return 0
    _report_failure(cmd_line, args.module, args.error_type, fails)
    return 1


if __name__ == "__main__":
    sys.exit(main())
