# Results (Draft Skeleton)

> PreCex: Counterexample-Driven Pre-Synthesis RTL Defect Localization and Repair
> Working draft — results chapter skeleton. Author: Toylog | 2026-08-04
> All numbers below are from the corrected (BMC-judged) authoritative data unless noted.

## RQ1: Can counterexample-grounded evidence enable reliable repair of cross-cycle (L3) RTL defects?

**Setup.** 34 L3 samples (s04–s37) x 4 evidence settings x 3 seeds = 408 LLM repair runs
(A raw log / B structured evidence / C counterexample semanticization / D FVDebug-style causal graph,
added 2026-08-04). Repair success judged by BMC (verify.sby) with golden double-check.

| Setting | n | Loc Top-1 | Repair (BMC) | Tokens | Cost (USD) |
| --- | --- | --- | --- | --- | --- |
| A (raw) | 102 | 47.1% | 100% | 1.99M | $2.78 |
| B (structured) | 102 | 61.8% | 100% | 1.76M | $2.72 |
| C (semanticized) | 102 | 56.9% | 100% | 3.50M | $4.17 |
| D (causal graph) | 102 | 49.0% | 100% | 1.07M | $1.56 |

**Finding 1.** All four settings reach 100% repair under a consistent BMC criterion —
evidence representation does not gate *whether* the model can fix, but *how precisely and cheaply*.

**Finding 2.** B (structured evidence) dominates on precision (61.8%); D (FVDebug-style causal graph) is cheapest ($1.56, 43% below B; 1.07M tokens) at 49.0% precision - a clear precision/cost trade-off.
C's semanticization adds 1.7–2× cost with no repair gain (consistent with Gate-0 prestudy).

**Significance (paired McNemar on 102 loc outcomes).** B vs A: p=0.0035 (significant); B vs D: p=0.0164 (significant); B vs C: p=0.404; C vs D: p=0.186. B's precision lead over raw-log (A) and causal-graph (D) is statistically significant; C's semanticization adds cost without significant precision gain.

**Finding 3 (loc difficulty by error type).** Single-point semantic errors are easy to locate
(edge 100%, width_trunc 85.2%); cross-state/handshake errors are hard (state_trans 36.1%, handshake 27.8%).
The relative difficulty ordering is stable across settings. Setting-level localization by error class
(per-setting n: 24/24/24/24 for state_trans, 12/12/12/12 for handshake, 3/3/3/3 for edge):

| Error class | A | B | C | D |
| --- | --- | --- | --- | --- |
| state_trans | 33.3% | **37.5%** | 37.5% | 25.0% |
| handshake | 16.7% | 33.3% | 33.3% | **41.7%** |
| reset | 55.6% | 72.2% | **83.3%** | 44.4% |
| fifo_full_empty | 53.3% | 53.3% | **60.0%** | 46.7% |
| boundary_wrap | 42.9% | **81.0%** | 57.1% | 57.1% |
| width_trunc | 88.9% | **100%** | 66.7% | 100% |
| edge | 100% | 100% | 100% | 100% |

B is best or tied-best on boundary_wrap (81.0%), width_trunc (100%), and state_trans (37.5%);
D is highest on handshake (41.7%, n=12 per setting — small-n caveat). The hard-class ordering
(state_trans/handshake below width_trunc/edge) holds in every setting.

**Non-LLM baselines.** To establish that the LLM's localization is non-trivial, we evaluate simple heuristic baselines on the same exact-match criterion (candidate line == buggy_inject_line, 34 samples):

| Baseline | loc_top1 |
| --- | --- |
| First assertion line | 0.0% |
| Any assertion line | 0.0% |
| First line mentioning a failing signal | 0.0% |
| Random line (expected value) | 0.50% |

All four LLM settings (47.1%–61.8%) far exceed these baselines; structured evidence (B) achieves 61.8% — over 120x the random-line expectation. The assertion- and signal-based heuristics never hit because injected defects live in functional/sequential logic, not in the assertion block itself.

## RQ2: Is the repair trustworthy? (Verifier sufficiency + patch quality)

**Sufficiency family** (mutation analysis on golden):

| Mutation family | Mutants | Killed | Rate |
| --- | --- | --- | --- |
| Strong (comparator inversion) | 400 | 354 | 88.5% |
| Const (parameter constant replacement) | 484 | 396 | 81.8% |
| Delete (assertion removal) | sampled | all PASS | vacuity control |

Module-level: axi/fifo strong=100%; uart_rx weakest (strong 55.0%, const 40.9%) ?
structural assertions are insensitive to baud-timing constant shifts (documented limitation, future work).

**T2 audit** (deterministic, 408/408 pass: A/B/C 306 + D 102): interface changes 0, assertion tampering 0,
evidence-loop failures 0; loc_dev median = 0 (62.7% exact on A/B/C, 69.6% on D). Patches are minimal (mean 2.1 lines, max 6).

## RQ3: Does the method survive a criterion-reversal audit? (Methodology lesson)

The original repair criterion (prove/k-induction) misjudged 78 correct repairs on axi/uart
(golden itself UNKNOWN under prove). BMC reverification: 303/303 pass ? repair rate 74.3% ? 100%.
**Lesson:** repair criterion must be validated against golden first (criterion-vs-golden consistency check).

## RQ4: Cost & performance

- Total LLM cost: $9.67 main experiment (306 runs, $0.0316 avg); full ledger $14.36 (839 calls).
- C-window compression: main dataset traces are short (median 6 cycles); window=8 yields only 4.1%
  aggregate reduction ? semanticization cost is dominated by summary text, not trace length.
- Verification: BMC 8-concurrency Gate-2 reverify = 68 jobs / 3.4 min; axi golden ~87s, uart_rx ~151s.

## Open items before paper submission

- [x] Fill D setting numbers (102 runs, $1.56, loc 49.0%, repair 100%)
- [x] FVDebug quantitative comparison via D (D cheap but lower precision than B; B remains main setting)
- [ ] Human interpretability rating (small study) for C/D
- [x] Paper sections: Intro / Method (2026-08-04); Related Work + Threats to Validity / Conclusion (2026-08-04)
- [ ] Full-draft integration (paper/main.md) + cross-section consistency pass

