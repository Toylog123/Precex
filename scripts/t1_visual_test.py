#!/usr/bin/env python3
# PreCex - scripts/t1_visual_test.py T1 视觉通道快测
# 作者：Toylog | 版本：v0.1 | 功能概述：VCD → PNG 波形图 → MiniMax M3 多模态摘要，
#   与文本通道（CexSemantizer text_summary）对比，验证 T1 探索价值（Gate-0 输入之一）。
# 用法：
#   python3 scripts/t1_visual_test.py <sample_dir> [--out <t1_result.json>] [--mock|--real]

import base64
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "agents", "cex_semantizer"))

from llm_client import LLMClient
from waveform_svg import render_png

T1_SYSTEM = """你是 PreCex 的 CexSemantizer 视觉通道：RTL 波形图理解专家。
基于给定的反例波形图（VCD → 时序图），用 3–5 句描述：
缺陷发生在哪个周期、哪些信号先异常、与断言违例的因果链。
要求：不猜测证据之外的原因；指出最可疑的代码位置（模块+信号+周期）。
"""


def png_to_data_url(path):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return "data:image/png;base64," + b64


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print(__doc__)
        return 1
    sample_dir = os.path.abspath(argv[0])
    out_path = None
    mock = True
    if "--out" in argv:
        out_path = argv[argv.index("--out") + 1]
    if "--real" in argv:
        mock = False

    vcd = os.path.join(sample_dir, "cex.vcd")
    png = os.path.join(sample_dir, "waveform.png")
    render_png(vcd, out_path=png)
    data_url = png_to_data_url(png)

    client = LLMClient(mock=mock)
    res = client.chat(
        messages=[
            {"role": "system", "content": T1_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": "请分析下面这张反例波形图（关键信号时序）。"},
                {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
            ]},
        ],
        tag="t1_visual",
    )
    result = {
        "sample": os.path.basename(sample_dir),
        "visual_summary": res["content"],
        "mode": res["mode"],
        "input_tokens": res["input_tokens"],
        "output_tokens": res["output_tokens"],
        "cost": res["cost"],
        "waveform_png": png,
    }
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    print("== T1 visual summary ==")
    print(result["visual_summary"][:800])
    print("== meta ==")
    print("mode=%s in=%d out=%d cost=%.6f" % (
        res["mode"], res["input_tokens"], res["output_tokens"], res["cost"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
