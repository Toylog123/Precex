# -*- coding: utf-8 -*-
"""Paper cross-reference integrity audit (P0.3)."""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _find_tex():
    for rel in ("paper/manuscript/precex_paper.tex", "manuscript/precex_paper.tex"):
        p = os.path.join(ROOT, rel)
        if os.path.isfile(p):
            return p
    return os.path.join(ROOT, "paper", "manuscript", "precex_paper.tex")

def _find_abstract_en():
    for rel in ("paper/manuscript/abstract_en.tex", "manuscript/abstract_en.tex"):
        p = os.path.join(ROOT, rel)
        if os.path.isfile(p):
            return p
    return os.path.join(ROOT, "paper", "manuscript", "abstract_en.tex")

DEFAULT_TEX = _find_tex()
DEFAULT_EN = _find_abstract_en()

def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + ": " + name + (" | " + detail if detail else ""))
    return cond

def main():
    tex_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEX
    en_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_EN
    tex = open(os.path.abspath(tex_path), encoding="utf-8").read()
    en = open(os.path.abspath(en_path), encoding="utf-8").read()
    fails = 0

    labels = re.findall(r"\\label\{([^}]+)\}", tex)
    dups = sorted({x for x in labels if labels.count(x) > 1})
    fails += not check("labels unique", not dups, "dups=%s" % dups)

    refs = re.findall(r"\\(?:ref|eqref|autoref)\{([^}]+)\}", tex)
    missing = sorted({r for r in refs if r not in labels})
    fails += not check("refs resolve", not missing, "missing=%s" % missing)

    cites_raw = re.findall(r"\\cite[a-z]*\{([^}]+)\}", tex)
    cite_keys = [k.strip() for g in cites_raw for k in g.split(",") if k.strip()]
    bibs = re.findall(r"\\bibitem\{([^}]+)\}", tex)
    missing_c = sorted({k for k in cite_keys if k not in bibs})
    unused = sorted({b for b in bibs if b not in cite_keys})
    fails += not check("cites resolve", not missing_c, "missing=%s" % missing_c)
    fails += not check("bibitems cited", not unused, "uncited=%s" % unused)

    imgs = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", tex)
    def _img_ok(i):
        cands = [
            os.path.join(ROOT, "paper", "manuscript", i),
            os.path.join(ROOT, "paper", "figures", os.path.basename(i)),
            os.path.join(ROOT, "manuscript", i),
            os.path.join(ROOT, "figures", os.path.basename(i)),
        ]
        return any(os.path.isfile(c) for c in cands)
    bad_imgs = [i for i in imgs if not _img_ok(i)]
    fails += not check("figures exist", not bad_imgs, "missing=%s" % bad_imgs)

    floats = re.findall(r"\\begin\{(figure|table)\*?\}(.*?)\\end\{\1\*?\}", tex, re.S)
    bad = []
    for env, body in floats:
        nc = len(re.findall(r"\\caption\{", body)); nl = len(re.findall(r"\\label\{", body))
        if nc != 1 or nl != 1:
            bad.append(env + ":cap=" + str(nc) + ",lab=" + str(nl))
    fails += not check("floats caption/label", not bad, "bad=%s" % bad)

    # 5b) bare % that would truncate body text (skip full-line comments,
    #     BOM-prefixed comment lines, trailing "}%" and "\\author{...%")
    bare_pct = []
    for i, ln in enumerate(tex.split("\n"), 1):
        s = ln.lstrip("﻿").lstrip()
        if s.startswith("%"):
            continue
        stripped = s.rstrip()
        if stripped.endswith("}%"):
            continue
        if re.match(r"\\author\{[^}]*%\s*$", stripped):
            continue
        if re.search(r"(?<!\\)%", stripped):
            bare_pct.append(i)
    fails += not check("no bare % in body", not bare_pct, "lines=%s" % bare_pct)

    # 6) abstract cn/en key numbers consistent
    pairs = [
        ("408", "408"),
        ("61\\.8", "61\\.8"),
        ("47\\.1", "47\\.1"),
        ("49\\.0", "49\\.0"),
        ("88\\.5", "88\\.5"),
        ("81\\.8", "81\\.8"),
        ("91\\.7", "91\\.7"),
        ("306", "306"),
        ("78", "78"),
        ("43", "43"),
    ]
    mism = []
    for cn, e in pairs:
        has_c = re.search(cn, tex) is not None
        has_e = re.search(e, en) is not None
        if has_c != has_e:
            mism.append(cn + " cn=" + str(has_c) + " en=" + str(has_e))
    fails += not check("abstract cn/en key numbers consistent", not mism, "mism=%s" % mism)

    print()
    print("summary: labels=%d refs=%d cites=%d figures=%d floats=%d + abstract_en sync" % (
        len(labels), len(set(refs)), len(set(cite_keys)), len(imgs), len(floats)))
    print("TOTAL FAILS:", fails)
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
