# Related Work (Draft)

> PreCex: Counterexample-Driven Pre-Synthesis RTL Defect Localization and Repair
> Working draft. Author: Toylog | 2026-08-04

## Scope

PreCex sits at the intersection of four lines of work: (i) formal-verification failure analysis and counterexample understanding; (ii) LLM-based RTL debugging and repair; (iii) assertion generation and verification sufficiency; and (iv) RTL debugging benchmarks. This section positions our pipeline against each, with emphasis on the evidence-representation axis that PreCex ablates.

## Counterexample-driven debugging and root-cause analysis

**FVDebug** [arXiv:2510.15906] is the closest competitor. It builds a causal DAG from a failing formal trace, scans suspicious nodes with batched LLM calls, produces a root-cause narrative through an agent, and generates fixes, demonstrated on two industrial counterexamples. PreCex shares the counterexample-understanding core: our Setting D is a deterministic, fully open-source realization of the FVDebug-style causal graph (failed assertion + fault cone + full-cycle state trace + trigger condition). FVDebug leaves three axes unaddressed that PreCex controls for: it depends on a commercial toolchain, it reports no controlled ablation of the evidence representation, and it does not quantify verifier sufficiency. PreCex is fully open-source (iverilog/yosys/SymbiYosys/Z3), compares four evidence representations on the same 34-sample dataset, and audits the verifier with mutation analysis, vacuity control, and an independent T2 review agent.

**GROVE** [arXiv:2511.17833] organizes assertion-failure debugging knowledge as a layered knowledge tree, validates knowledge items with model checking at training time, and performs budget-aware retrieval at test time, consistently improving pass@1/pass@5. GROVE and PreCex are complementary: GROVE accumulates reusable knowledge across samples, whereas PreCex consumes the single failing counterexample in a closed localize-repair-reverify loop without a history store. A GROVE-style knowledge layer is a natural extension of our pipeline.

**Open-source LLM-driven formal verification** [arXiv:2607.28877] uses the same open toolchain (Yosys/SymbiYosys/Z3) with LLM-guided counterexample-driven iterative repair, stopping on k-induction proof or budget exhaustion, and reliably fixed only 1 of 6 benchmarks. This work validates the open-source pipeline as feasible and catalogs its failure modes. PreCex differs in two ways: it adds an evidence-semanticization layer (that work feeds raw counterexamples directly to the LLM) and it evaluates on a larger, controlled L3 dataset with a golden-first verification criterion.

**FormalRTL** uses a software reference model as a formal specification and closes a plan/synthesis/equivalence-checking loop, including a counterexample simplifier that highlights only the failing function and mismatched signals. PreCex makes no reference-model assumption: it works from assertions plus a counterexample alone, which is the common pre-synthesis setting where no golden model exists.

**ChipAgents RCA** (commercial, 2026) combines a waveform-understanding engine with a prover-verifier agent pair and self-consistency ranking, and reports localization of a three-cycle race condition in industrial deployment. It corroborates that cross-cycle root-cause analysis is a real industrial pain point, but is a closed black box with no ablation detail.

## LLM-based RTL repair

**VeriPilot** [arXiv:2606.23759] uses a golden reference model with CDFG signal tracking and raises GPT-4o repair rates on CVDP from 54.3% to 85.71%. **VeriDebug** [arXiv:2504.19099] learns a contrastive embedding and guides correction, reaching 64.7% Acc@1 on a combined localization-plus-type task. **RTLFixer** applies retrieval-augmented repair to syntax errors. These works are not counterexample-driven: they rely on reference models, fine-tuned embeddings, or syntax-only fixes. PreCex deliberately targets the pre-synthesis setting with no reference model and treats the evidence representation rather than model capacity as the studied variable.

**Fixbench-RTL** and **HDL-FixBench** are repair benchmarks spanning syntax/functional/security domains (Fixbench) and repository-scale instances (57 instances from OpenTitan/CVA6/Ibex, best model 40.3%; rejected by ICLR 2026). HDL-FixBench's rejection highlights pitfalls we engineered against: small scale, insufficient diversity, disputed patch thresholds, missing non-LLM baselines, and contamination risk. BugBench-PS addresses these with 34 L3 samples across 6 modules and 7 error classes, per-sample golden double-checking, tool-execution adjudication, and a documented contamination statement.

## Assertion generation and verification sufficiency

**AssertLLM** [ASPDAC'25] and **AssertLLM2** generate SVA from natural-language specifications plus waveforms; AssertLLM2 introduces an 83-design assertion benchmark and evaluates assertions through mutation-based bug detection in a bug-hunting setting. **AssertGen** [ATS'25] extracts verification goals via chain-of-thought and bridges cross-layer signals, with mutation-testing coverage evaluation. **LASSO** [MLCAD'25] generates safety properties with explicit vacuity checking and coverage feedback, detecting 5 real bugs in OpenTitan. **LintLLM** [GLSVLSI'25] performs LLM linting with mutation-based defect injection.

These works generate or audit assertions; PreCex consumes assertions plus counterexamples to localize and repair. Their evaluation practices (mutation coverage, vacuity, bug-hunting) provide the methodological precedent for our sufficiency audits: 88.5% strong mutants and 81.8% constant mutants killed, with delete-mutation vacuity control.

## Benchmarks and evaluation methodology

Tool-execution adjudication is an accepted evaluation practice in the EDA-AI literature: Rule2DRC (ICML 2026) compares 13,921 layout-rule results and PostEDA-Bench evaluates 145 DRC/PPA tasks by executing design tools. PreCex follows the same principle: repair success is adjudicated by compilation, weak-testbench regression, and formal BMC, never by the LLM's self-report. Engineering-semantics datasets (OpenRTLSet, EDA-Schema-V2, ChipLingo) informed our evidence schema design.

## Positioning

| Work | Evidence representation | Open-source | Cross-cycle (L3) focus | Controlled evidence ablation | Sufficiency quantification |
| --- | --- | --- | --- | --- | --- |
| FVDebug | causal graph | no | partial | no | no |
| GROVE | knowledge tree | no | no | no | no |
| 2607.28877 | raw cex | yes | partial | no | no |
| FormalRTL | cex simplification + reference model | partial | no | no | no |
| VeriPilot | CDFG + reference model | no | no | no | no |
| VeriDebug | learned embedding | no | no | no | no |
| AssertLLM2 | — (assertion gen.) | — | — | — | mutation-based |
| **PreCex** | **raw / structured / semanticized / causal graph** | **yes** | **yes (34 samples)** | **yes (A/B/C/D)** | **yes (mutation/vacuity/T2)** |

Our three differentiators are each evidenced by controlled experiments in this paper: (1) a fully open-source, reproducible counterexample-driven pipeline; (2) a four-setting evidence-representation ablation with paired significance testing; (3) a cross-cycle (L3) benchmark with a verifier-sufficiency loop (mutation, vacuity, and an independent T2 audit). In addition, the criterion-reversal audit (Results, RQ3) contributes a methodological lesson: a repair criterion must be validated against the golden design before it is used to judge repairs.
