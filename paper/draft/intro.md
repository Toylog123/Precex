# Introduction (Draft)

> PreCex: Counterexample-Driven Pre-Synthesis RTL Defect Localization and Repair
> Working draft. Author: Toylog | 2026-08-04

## Problem

RTL designs are increasingly complex, and cross-cycle behavioral defects (L3: weak
testbenches pass but formal verification fails) are among the hardest to localize and
repair before synthesis. Existing LLM-based repair pipelines struggle because they
either feed raw logs/waveforms (information overload) or rely on reference models
(not always available pre-synthesis). Recent work (FVDebug, GROVE) shows the value of
structured counterexample understanding, but lacks: (1) an open-source end-to-end
pipeline, (2) cross-cycle bug-specific study, (3) a rigorous verification-sufficiency
loop, and (4) a controlled ablation of evidence representations.

## Motivation

We observe that the *evidence representation* given to the LLM is a key but understudied
axis. We systematically compare four evidence settings on the same 34-sample L3 dataset
(408 LLM repair runs):

- A: raw cex log/VCD
- B: structured evidence (EvidenceEngine JSON)
- C: counterexample semanticization (CexSemantizer: cycle events + state trace + fault cone + NL summary)
- D: FVDebug-style causal graph (deterministic extraction)

## Contributions

1. **Open-source counterexample-driven repair pipeline** (iverilog/yosys/sby/z3 + MiniMax M3 API),
   fully reproducible; 34-sample L3 dataset with golden double-check and sufficiency audits.
2. **Evidence-representation ablation**: all settings reach 100% repair under a consistent BMC
   criterion; B (structured) significantly improves localization (61.8% vs A 47.1%, p=0.0035;
   vs D 49.0%, p=0.0164); D is cheapest ($1.56); C adds cost without significant gain (p=0.404).
3. **Verifier-sufficiency loop**: mutation family (strong 88.5% / const 81.8% killed),
   vacuity control (delete), deterministic T2 audit (interface/assertion/evidence-loop 306+102 all pass).
4. **Criterion-reversal lesson**: prove/k-induction misjudges 78 correct repairs on gated
   sequential assertions (golden itself UNKNOWN); BMC criterion + golden-first validation is
   required — a methodological contribution for reliable automated repair.
