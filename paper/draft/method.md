# Method (Draft)

## System architecture

Core 4 components + 2 support elements (per docs/方案.md §4):

1. **EvidenceEngine** — parses cex.log into unified JSON (error_type/module/file/line/code_slice/signals/trigger_condition/fail_stage/fail_step).
2. **CexSemantizer** — converts VCD into cycle-event table + state trace + fault cone + NL summary (window=8 compression).
3. **LocalRepairer** — LLM (MiniMax M3, temperature 0.2) given design + assertions + evidence, outputs locate + minimal unified diff; retries <= 2.
4. **Verifier** — three-pass gate: (1) iverilog compile 0 error, (2) weak testbench sim all-green, (3) sby smtbmc+z3 BMC no counterexample (primary criterion); golden double-check.

Support: Controller (experiment variable), BugBench-PS (dataset assets).

## Evidence settings (controlled ablation)

| Setting | Evidence | Extraction | Cost/run |
| --- | --- | --- | --- |
| A | raw cex.log + VCD head/tail | none | baseline |
| B | evidence.json | deterministic | low |
| C | semantics.json (cycle events + state trace + fault cone + NL summary, window=8) | LLM semanticization | high |
| D | FVDebug-style causal graph (failed assertion + fault cone + full state trace + trigger) | deterministic (zero LLM) | lowest |

Same prompt family, only evidence segment replaced (anti-bias protocol).

## Repair criterion (revised)

- Primary: BMC (verify.sby), consistent with golden verification (verify_golden.sby).
- prove/k-induction (verify_repair.sby) kept as supplementary reference only — it is
  **not** a failure criterion, because it does not converge on gated sequential assertions
  (golden itself UNKNOWN, rc=4; 78 correct repairs were false-FAILed under the old criterion).
- **Golden-first rule**: any repair criterion must first pass on golden (criterion-vs-golden consistency check).

## Sufficiency audits

- Strong mutation (comparator inversion, d16): 400 mutants, 88.5% killed.
- Const mutation (parameter constants DATA_W/ADDR_W/DEPTH/DIV/HALF): 484 mutants, 81.8% killed.
- Delete mutation (assertion removal): vacuity control.
- T2 deterministic audit: interface change 0, assertion tampering 0, evidence-loop 0 (306 + 102).
