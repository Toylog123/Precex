# Threats to Validity and Conclusion (Draft)

> PreCex: Counterexample-Driven Pre-Synthesis RTL Defect Localization and Repair
> Working draft. Author: Toylog | 2026-08-04

## Threats to validity

### Internal validity

**Repair criterion.** All reported results use BMC (verify.sby) as the primary criterion, consistent with golden verification. We found that prove/k-induction does not converge on gated sequential assertions in the axi/uart modules: the golden design itself returns UNKNOWN, and the original protocol misjudged 78 correct repairs as failures. A golden-first rule now guards the criterion — any candidate criterion must first pass on the golden design. Residual risk remains that a defect manifests only beyond the probed BMC depth; we probe to bug depth + 2 and cross-check against golden verification, but this is not a completeness guarantee.

**LLM nondeterminism.** We run 3 seeds per sample per setting and report paired statistics. The pipeline itself is deterministic (parsing, extraction, verification); the only stochastic component is the LLM inference.

**Repair-success definition.** Success requires compilation, weak-testbench regression, BMC with no counterexample, and golden double-check. A patch that satisfies the probed assertions while changing behavior beyond the property set would pass; the T2 audit bounds this risk by checking for interface changes and assertion tampering, but it is not a full equivalence check.

### External validity

**Scale and scope.** The benchmark contains 34 L3 samples across 6 modules (fifo_sync, uart_tx, uart_rx, axi_lite_slave, fsm_ctrl, counter_alu) and 7 error classes. The modules are open-source teaching-grade RTL; we do not claim industrial protocol coverage. Handshake and state-transition defects remain the hardest classes to locate (loc_top1 27.8% and 36.1% respectively), and uart_rx's baud-timing constant mutations are weakly killed (const 40.9%) — a documented limitation of structural assertions for timing-constant shifts.

**Contamination.** Common modules may appear in LLM training corpora. We mitigate with construction-date records, per-sample provenance, and error-class diversity, but residual memorization cannot be fully excluded.

**Single LLM provider.** All 408 runs use MiniMax M3. Absolute rates may shift with model versions or providers; the relative evidence-representation effect is the claim we report.

### Construct validity

loc_top1 records whether the model's top-ranked candidate line is inside the injected defect's reference diff; repair rate is measured under the BMC criterion; cost is metered by API tokens. These constructs match the repair-benchmark literature. Statistical claims use paired McNemar tests on per-sample localization outcomes (102 pairs per comparison): B vs A p=0.0035 and B vs D p=0.0164 are significant; B vs C p=0.404 and C vs D p=0.186 are not. All comparisons are reported, including non-significant ones.

## Conclusion

We presented PreCex, an open-source, counterexample-driven pipeline for pre-synthesis RTL defect localization and repair, and studied the evidence-representation axis that prior counterexample-understanding systems leave uncontrolled. On a 34-sample cross-cycle (L3) benchmark with 408 LLM repair runs:

- All four evidence settings (raw logs, structured evidence, semanticized counterexamples, FVDebug-style causal graphs) reach 100% repair under a consistent BMC criterion; the representation determines how precisely and how cheaply, not whether.
- Structured evidence (B) achieves the highest localization precision (61.8%), statistically significant over raw logs (47.1%, p=0.0035) and causal graphs (49.0%, p=0.0164). Causal graphs (D) are the cheapest ($1.56 vs $2.72, 43% lower); semanticization (C) adds cost without significant precision gain.
- Repairs are trustworthy by construction: mutation analysis kills 88.5% of strong and 81.8% of constant mutants, vacuity control passes, and the independent T2 audit passes 408/408 runs with zero interface or assertion-tampering changes and zero median localization deviation.
- The criterion-reversal audit (BMC over prove/k-induction, with a golden-first rule) is a methodological lesson for automated repair pipelines: the evaluation criterion itself must be validated before repairs are judged.

Future work includes scaling to industrial protocols and larger assertion sets, stronger mutation families, multi-provider and multi-model evaluation, a GROVE-style knowledge layer for cross-sample reuse, and reinforcement learning with formal proofs as reward.
