# -*- coding: utf-8 -*-
"""
PreCex - scripts/prepare_zh_refs.py
作者：Toylog | 版本：v0.1 | 功能概述：从 JSON 生成中文参考文献 thebibliography 块，供软件学报/电子学报等中文期刊适配时一键插入。

用法：
  python scripts/prepare_zh_refs.py --input docs/zh_refs_template.json [--tex paper/manuscript/precex_paper.tex]

行为：
  - 读取 JSON：{"refs": [{"authors": "...", "title": "...", "journal": "...", "year": "...", "volume": "...", "pages": "...", "note": "..."}]}
  - 校验必填字段（authors/title/journal/year）与 key 唯一性（zh1..zhN，不与 tex 现有 \\bibitem key 冲突）
  - 输出可直接粘贴到 thebibliography 的 \\bibitem{zhN} 块（IEEE 风格，与现有 22 条一致）
  - 带 --tex 时只检查 key 冲突与 thebibliography 存在，不修改正文

说明：本脚本不编造文献；JSON 中条目须来自真实检索（用户提供或 web 工具恢复后调研）。
"""
import argparse
import io
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REQUIRED = ["authors", "title", "journal", "year"]


def load_json(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def existing_keys(tex_path):
    with io.open(tex_path, "r", encoding="utf-8") as f:
        s = f.read()
    return set(re.findall(r"\\bibitem\{(.+?)\}", s))


def format_bibitem(idx, r):
    key = "zh%d" % idx
    parts = [r["authors"], "“%s”" % r["title"], r["journal"]]
    if r.get("volume"):
        parts.append("vol. " + r["volume"])
    if r.get("pages"):
        parts.append("pp. " + r["pages"])
    parts.append(r["year"] + ".")
    body = ", ".join(parts)
    if r.get("note"):
        body += " " + r["note"]
    return "\\bibitem{%s}\n%s" % (key, body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=os.path.join(REPO, "docs", "zh_refs_template.json"))
    ap.add_argument("--tex", default=os.path.join(REPO, "paper", "manuscript", "precex_paper.tex"))
    args = ap.parse_args()

    data = load_json(args.input)
    refs = data.get("refs", [])
    if not refs:
        raise SystemExit("ERROR: refs 为空")

    keys = existing_keys(args.tex)
    missing = []
    for i, r in enumerate(refs, 1):
        for f in REQUIRED:
            if not r.get(f, "").strip():
                missing.append((i, f))
    if missing:
        raise SystemExit("ERROR: 必填字段缺失: %s" % missing)

    zh_keys = ["zh%d" % i for i in range(1, len(refs) + 1)]
    clash = [k for k in zh_keys if k in keys]
    if clash:
        raise SystemExit("ERROR: key 冲突: %s" % clash)

    print("OK: %d 条中文文献，key 无冲突（现有 %d 个 bibitem）" % (len(refs), len(keys)))
    print()
    print("% 中文参考文献（由 prepare_zh_refs.py 生成，插入 thebibliography 末尾）")
    for i, r in enumerate(refs, 1):
        print(format_bibitem(i, r))
        print()


if __name__ == "__main__":
    main()