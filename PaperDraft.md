# ReqMemBench: Benchmarking Coding Agents on Temporal Requirement-State Reconstruction

> Canonical manuscript mirror. The scientific content below is synchronized with `ICLR 2027-Upwork Benchmark- 9.19/iclr2027_conference.tex`. Markdown headings, equations, figures, and tables mirror the LaTeX manuscript; bibliography entries remain managed by the `.bib` file.

## Draft status and structure

- Main sections: Introduction; Related Work; Temporal Requirement-State Reconstruction; ReqMemBench Construction; Experiments; Analysis and Limitations; Conclusion.
- Figures: Figure 1, takeover setting; Figure 2, construction pipeline; Figure 3, cross-stage error propagation.
- Tables: four evaluation stages; benchmark statistics; primary metrics; RQ1/RQ2 results; RQ3/RQ4 results; cross-stage failure analysis.
- Missing evidence remains marked as **TODO/TBD**. No experimental result is asserted before the formal evaluation is frozen.

## Abstract

Coding agents increasingly operate as persistent participants in software projects, inheriting evolving codebases midway through long-running client collaborations. Successful continuation requires recovering the specification governing the current task: requirements may have been revised, narrowed in scope, deferred, resumed, or withdrawn across earlier interactions. Existing coding and memory benchmarks offer limited visibility into whether agents correctly reconstruct the requirement state that should guide implementation. We introduce ReqMemBench, a benchmark for temporal requirement-state reconstruction built from real freelance project histories that have been rewritten for privacy and include a subset of role-played messages. At intermediate takeover points, ReqMemBench provides evidence-linked gold requirement states and evaluates four capabilities: selecting relevant historical requirements and evidence, reconstructing their pre-task states, updating requirements or identifying material clarification needs, and delivering the requested code changes. A two-phase protocol freezes history-based responses before agents choosing to act on eligible tasks receive repository access. Full History and Oracle Relevant History conditions assess the effect of history filtering and agents’ reconstruction accuracy when relevant evidence is explicitly supplied. **[TO COMPLETE: report the principal quantitative findings, including performance under oracle history and the relationship between requirement-state accuracy and code delivery.]**

## 1. Introduction

Code-generation evaluation has progressively expanded from self-contained function synthesis to repository-scale software engineering. HumanEval and MBPP measure whether models can produce short programs from natural-language specifications \citep{chen2021codex,austin2021mbpp}. CrossCodeEval and RepoBench add cross-file retrieval and repository context \citep{ding2023crosscodeeval,liu2024repobench}, while SWE-bench evaluates patches for real GitHub issues and SWE-Lancer evaluates freelance engineering tasks with executable or expert-derived criteria \citep{jimenez2024swebench,miserendino2025swelancer}. These benchmarks broaden the scope and realism of coding evaluation, but do not explicitly measure a central challenge faced by agents that join ongoing projects: determining which requirements still govern the task before they take any steps.

The information needed to reconstruct these requirements is distributed across the project's interaction history. Requirements engineering has long emphasized tracing requirements from their origins through refinement and implementation \citep{nuseibeh2000requirements,gotel1994analysis}. In a long-running project, a requirement may be introduced, modified, deferred, resumed, or removed. Some aspects may remain ambiguous while others are settled, and execution feedback may update the known implementation status without changing the requirement itself. A previously authoritative statement may therefore be superseded in whole or in part at takeover, yet remain useful evidence for reconstructing how a requirement evolved. The central challenge is to reconstruct the current state of task-relevant requirements from these updates, preserving both settled constraints and unresolved ambiguities.

Several related lines of evaluation test important parts of this challenge. Conversational coding benchmarks measure how models revise programs in response to iterative compilation, execution, or verbal feedback \citep{han2025convcodeworld}. Long-term memory benchmarks test capabilities including information extraction, temporal reasoning, knowledge updates, long-range understanding, selective forgetting, and abstention over extended interactions \citep{wu2025longmemeval,maharana2024locomo,hu2025memoryagentbench}. These benchmarks assess the use of historical information, and some also evaluate retrieval quality. However, they do not directly score the task-relevant project requirement state that should guide code implementation, including requirement values, lifecycle status, scope, unresolved ambiguities, and implementation evidence. Explicit evaluation of this state would support separate assessment of history selection, requirement reconstruction, and code delivery.

We formulate this setting as *temporal requirement-state reconstruction*. An agent enters a project at a target time $t^*$ and first reasons from the condition-specific pre-target history $H^{(c)}_{<t^*}$ and current task $q_{t^*}$. During this history-only phase, it selects the directly affected historical requirements and their supporting evidence, reconstructs their pre-task states, and either predicts complete post-task states for all affected requirements (`ACT`) or identifies material ambiguities requiring clarification (`CLARIFY`). The response is frozen before repository access is granted. For an execution-eligible target, a run proceeds to an execution phase with the pre-task repository $C_{t^{*-}}$ only when the agent's frozen decision is `ACT`. This separation protects the history-only evaluation from repository-derived information and allows the frozen requirement interpretation to be compared with final code correctness.

ReqMemBench operationalizes this formulation by annotating longitudinal project histories as evidence-linked Requirement Events and replaying validated events into temporal Requirement State Graphs. Each takeover instance includes task-local gold pre-task states and either complete post-task states or clarification targets; execution-eligible instances additionally have a fixed hidden validator. The benchmark evaluates four capabilities along the path from history to delivery: selecting directly affected historical requirements and supporting evidence, reconstructing their pre-task states, producing complete post-task states or identifying material clarification needs, and delivering the requested code changes. Full History provides the complete transformed pre-target conversation, whereas Oracle Relevant History provides an audited, order-preserving subsequence retaining the relevant requirement trajectories and context, including superseded statements where needed. Requirement and evidence selection are scored only under Full History because oracle construction uses gold relevance annotations. The oracle condition evaluates reconstruction and update-or-clarify reasoning with relevant evidence explicitly supplied.

Our contributions are:

1. We formulate temporal requirement-state reconstruction as an evaluation problem for coding-agent takeover, with explicit task-local targets for reconstructing pre-task requirement states and determining their updates or material clarification needs under the current request.
2. We construct ReqMemBench from transformed longitudinal freelance project histories, providing evidence-linked Requirement Events, temporal Requirement State Graphs, and annotated takeover instances at intermediate project stages.
3. We design a two-phase protocol that freezes history-based responses before repository access and compares requirement reconstruction, update-or-clarify reasoning, and eligible code delivery under Full History and Oracle Relevant History.

**Figure 1 placeholder: Motivation and task definition**

```text
Introduce A → Modify A → Defer A → Resume A → Ambiguous A
                              ↓ t*
Phase A: history + current task → select → reconstruct → act or clarify → freeze
Phase B: eligible act + pre-task repository → execute → hidden validator
```

*Figure 1 caption.* The ReqMemBench takeover setting. An agent first reasons from the preceding history and current task without repository access. After its response is frozen, eligible `ACT` runs receive the pre-task repository for delivery evaluation.

## 2. Related Work

**Coding benchmarks.** Coding benchmarks cover function-level synthesis and library use \citep{chen2021codex,austin2021mbpp,zhuo2025bigcodebench}, cross-file completion \citep{ding2023crosscodeeval,liu2024repobench}, repository issue resolution and freelance engineering \citep{jimenez2024swebench,miserendino2025swelancer}, and release-level evolution and project development \citep{le2026sweevo,lu2026projdevbench}. Sequential benchmarks address knowledge transfer, trajectory reuse, and code-quality degradation under evolving specifications \citep{joshi2025swebenchcl,zhu2026swecontextbench,orlanski2026slopcode}. RigorBench additionally evaluates engineering process discipline, including abstention and clarification \citep{madiraju2026rigorbench}.

**Memory and long context.** LongBench and RULER evaluate retrieval and reasoning over extended inputs \citep{bai2024longbench,hsieh2024ruler}. LongMemEval, MemoryAgentBench, and LoCoMo assess complementary capabilities across interactions, including temporal and multi-session reasoning, knowledge updates, selective forgetting, and abstention \citep{wu2025longmemeval,hu2025memoryagentbench,maharana2024locomo}. These evaluations cover both access to historical information and its integration and revision.

**Conversational coding.** ConvCodeWorld and RECODE-H evaluate iterative code revision under execution or simulated expert feedback \citep{han2025convcodeworld,miao2026recodeh}, while SR-Eval studies stepwise requirement refinement \citep{zhan2025sreval}. LoCoEval introduces conflicting requirement information in repository-oriented conversations and separately evaluates information-item extraction and function generation at conversation end \citep{liu2026locoeval}. ReqMemBench focuses on task-local requirement states at intermediate takeover points, explicitly tracking attributes, lifecycle, scope, ambiguity, and implementation evidence. Its protocol freezes reconstruction and update-or-clarify responses before repository access and evaluates them alongside eligible code delivery.

## 3. Temporal Requirement-State Reconstruction

Requirements evolve through revisions, deferrals, resumptions, and removals, so a takeover agent must recover the state that governs the project now rather than merely retrieve earlier statements. Building on requirements traceability \citep{nuseibeh2000requirements,gotel1994analysis}, ReqMemBench represents this state explicitly and evaluates its reconstruction before code execution.

### 3.1 Temporal State and Task-Local Gold

We represent a project as $P=(H,C)$, where $H=\langle h_1,\ldots,h_n\rangle$ is the ordered interaction history and $C(t)$ is the corresponding code state. A target request $q_{t^*}$ defines a strict temporal boundary: $H_{<t^*}$ and $C_{t^{*-}}$ contain only pre-target evidence. We use $t^{*+}$ for the point after incorporating requirement changes expressed by the target but before any subsequent implementation or execution feedback.

The atomic unit is a *Requirement Atom*. For atom $r$, its state is

$$
G_r(t)=\bigl(A_r(t),L_r(t),S_r(t),U_r(t),X_r(t)\bigr),
$$

where $A_r$ records attribute values, $L_r$ the lifecycle, $S_r$ persistence and scope, $U_r$ unresolved ambiguities, and $X_r$ the latest implementation evidence. Unknown fields remain explicit. These dimensions are independent: an active requirement can be ambiguous or have failed implementation evidence, while a removed requirement retains its prior attributes and evidence under lifecycle `REMOVED`.

States are reconstructed by deterministically replaying the validated event sequence $E_r$ up to time $t$:

$$
G_r(t)=\operatorname{Replay}\bigl(E_r^{\leq t}\bigr),
$$

using the transition rules in the appendix. Let $R_P(t)$ be the atoms introduced by time $t$, and let $A_{t^*}$ be all atoms affected by the target, including newly introduced ones. The task-local pre- and post-target gold states are

$$
\begin{aligned}
R^{\mathrm{hist}}_{t^*}
    &= A_{t^*}\cap R_P(t^{*-}), \\
G^-_{t^*}
    &= \bigl(G_r(t^{*-})\bigr)_{r\in R^{\mathrm{hist}}_{t^*}}, \\
G^+_{t^*}
    &= \bigl(G_r(t^{*+})\bigr)_{r\in A_{t^*}}.
\end{aligned}
$$

Thus, atoms introduced by the target are absent from $G^-_{t^*}$ but included in $G^+_{t^*}$. The task-local projection evaluates selection, reconstruction, and updating without requiring recovery of unrelated project state.

### 3.2 Takeover Protocol and Evaluation Stages

Full History (C1) exposes $H_{<t^*}$, whereas Oracle Relevant History (C2) exposes an audited, order-preserving subsequence containing the evidence required to determine the same task-local state and action. C2 isolates reasoning over relevant evidence from the additional problem of finding that evidence in a long history.

Evaluation separates history reasoning from code execution. In Phase A, the agent receives the condition-specific history and current request, but no repository:

$$
\bigl(H^{(c)}_{<t^*},q_{t^*}\bigr)
\longrightarrow
\left(
\widehat{R}^{\mathrm{hist}}_{t^*},
\widehat{G}^{-}_{t^*},
\widehat{d}_{t^*},
\widehat{Z}_{t^*}
\right),
$$

where $c\in\{\mathrm{C1},\mathrm{C2}\}$ and $\widehat{d}_{t^*}\in\{\mathrm{ACT},\mathrm{CLARIFY}\}$. The output contains selected historical atoms and evidence, their reconstructed pre-task states, and either the complete predicted post-task state $\widehat{G}^{+}_{t^*}$ for `ACT` or material blocking issues and questions $\widehat{Q}_{t^*}$ for `CLARIFY`. Clarification is correct only when visible evidence leaves a target-relevant ambiguity that blocks a determinate update.

The Phase-A response is frozen before repository access. For an execution-eligible target, Phase B begins only after a parseable `ACT` response, at which point the agent receives a fresh copy of $C_{t^{*-}}$. Hidden validators remain inaccessible to the agent, separating requirement-state prediction from repository correctness.

**Table 1. The four evaluation stages. C1 is Full History and C2 is Oracle Relevant History. RQ4 applies only to eligible targets.**

| Stage | Evaluated capability | Gold target | History | Repository |
| --- | --- | --- | --- | --- |
| RQ1 | Select affected historical atoms and supporting evidence | $R^{\mathrm{hist}}_{t^*}$ and supporting evidence groups | C1 | No |
| RQ2 | Reconstruct pre-task states | $G^-_{t^*}$ restricted to matched atoms | C1/C2 | No |
| RQ3 | Update requirements or identify material blockers | $G^+_{t^*}$ for `ACT`; blocking issues and questions for `CLARIFY` | C1/C2 | No |
| RQ4 | Implement the requested changes | Final repository passing the frozen validator | C1/C2 | After freeze |

RQ1 is evaluated only under C1 because C2 is selected from the gold requirement trajectories and would therefore reveal the evidence-selection target. The remaining stages use both conditions, allowing errors to be localized across reconstruction, decision, and execution.

## 4. ReqMemBench Construction

ReqMemBench turns longitudinal project records into takeover tasks whose governing requirements can be reconstructed and tested. Construction proceeds from the project timeline to reviewed Requirement Events, from those Events to temporal Requirement States, and finally from selected takeover points to paired agent inputs and gold targets. Figure 2 summarizes this process. The definitions in Section 3 determine what each instance must contain; the construction pipeline makes those objects recoverable from project evidence.

**Figure 2. Construction pipeline.**

```text
Project records → reviewed Requirement Events → deterministic replay → temporal State Graph
→ target selection → task-local gold → C1/C2 instances

Model-assisted proposals | deterministic validation and replay | human review
```

*Figure 2 caption.* ReqMemBench converts longitudinal project records into evidence-linked Requirement States and leakage-controlled takeover instances.

### 4.1 Temporal Requirement Graph Construction

Construction begins with longitudinal records of real freelance software projects. We transform the project histories to protect participant privacy while preserving the order and meaning of requirement changes. When an exact historical message or executable environment is unavailable, we reconstruct it from the surviving project evidence and the requirement state at the corresponding time. Instance-level provenance distinguishes transformed records, reconstructed messages, recovered environments, and reconstructed environments. The Ethics Statement and Data Card specify the authorization, transformation, and release procedures for these records.

The transformed timeline is then converted into the representation defined in Section 3. A model first proposes Requirement Atoms, state-changing Events, and links from each Event to its supporting messages. Schema checks reject malformed objects and broken references, after which human review resolves semantic errors and freezes the accepted annotations. Deterministic replay applies the reviewed Events in project order to obtain the state of every Requirement Atom after each change. An invalid transition stops replay instead of being repaired by another model call, and each resulting state retains the evidence from which it was derived. The complete annotation schema and transition rules appear in the appendix.

> **TODO:** Report frozen project and message counts and the proportions of transformed histories, reconstructed messages, recovered code environments, and reconstructed code environments.

### 4.2 Takeover Instance Construction

The temporal graph becomes a benchmark instance only at a task that both depends on earlier project context and produces a verifiable Requirement transition. All changes requested in the same client message remain within one takeover task. We exclude context-free introductions and messages that provide implementation evidence without changing a requirement. The remaining candidates pass through a fixed historical-dependence and requirement-evolution rubric, followed by human review for borderline cases. The appendix gives the rubric, threshold, and candidate flow.

For an accepted target, deterministic replay is stopped immediately before the target and resumed through the target message. These two boundaries yield the pre-task and post-task states defined in Section 3. Although the graph retains the complete project state, the instance contains the task-local projection over affected Requirements. A Requirement introduced by the target therefore appears only in the post-task state, whereas a removed Requirement remains in the projection with lifecycle `REMOVED`. This alignment produces the gold objects used to evaluate historical selection, state reconstruction, and update-or-clarify decisions.

We materialize each target with Full History and Oracle Relevant History. Full History preserves every admissible message before the target. Oracle Relevant History preserves message order but retains only the trajectories and contextual evidence needed to recover the same pre-task state and interpret the current request. During Phase A, the agent receives the current task and one of these two histories. Gold annotations, internal identifiers, future messages, repository artifacts, and validators remain outside its workspace. The Phase-A response is frozen before any repository is mounted. For an RQ4-eligible target, an agent that chooses `ACT` then receives a fresh copy of the same pre-task repository under both history conditions; the hidden validator remains external to the execution workspace. Consequently, the visible history is the only intended difference between the paired conditions. The appendix specifies the serialized instance schema and the checks that enforce this separation.

> **TODO:** Report accepted and rejected targets, C1/C2 instance counts, and RQ4 candidate, environment, eligibility, and exclusion counts.

### 4.3 Curation Validity and Benchmark Statistics

Validity checks follow the same boundaries as construction. Code validates schemas, references, event order, and deterministic replay, while human reviewers decide the semantic content of Requirement Events and ambiguity-sensitive gold. The annotation audit draws a stratified sample of at least 200 state transitions. A human reviewer and two independent LLM assessors label each sampled transition under the same annotation scheme; raw agreement and a coefficient matched to the final rater design quantify consistency. Disagreements are adjudicated before the benchmark snapshot is frozen. This annotation audit is distinct from calibrating the RQ1 semantic judge, adjudicating RQ3 decisions, and validating RQ4 repositories.

A separate audit tests whether Oracle Relevant History preserves the information needed for evaluation. Its messages must form an ordered subsequence of Full History and support the same pre-task state and RQ3 gold decision. If the two views yield different gold interpretations, the oracle subset is corrected; targets that cannot be repaired without adding unavailable evidence are excluded. This prevents curation errors from appearing as an experimental effect of history selection.

**Table 2. ReqMemBench corpus statistics at the current construction snapshot. Evaluation counts are finalized after annotation review and eligibility checks.**

| Level | Main-text statistic | Current snapshot |
| --- | --- | --- |
| Project | Projects | 51 |
| Requirement | Requirement Atoms | 859 |
| Event | Requirement Events | 2,793 |
| Task | Takeover tasks and source projects | 210 tasks; 39 projects |
| Evaluation | Reviewed/eligible instances by RQ and condition | **TBD** |

The appendix characterizes the corpus by Requirement lifecycle, Event type, provenance category, repository recoverability, and exclusion reason.

> **TODO:** Insert agreement and oracle-history audit results, correction counts, and regenerated benchmark statistics after the review freeze.

## 5. Experiments

We evaluate whether a coding agent can carry an evolving specification from historical evidence to a validated repository. The evaluation unit is a model–harness pair, and the logical run unit is a target–condition pair. One frozen Phase-A response supplies all applicable RQ1–RQ3 outputs. Phase B begins only when the RQ3 decision is `ACT` and the target passes the RQ4 eligibility gate. This design preserves the dependency between the four capabilities without rerunning the same agent separately for each research question.

### 5.1 Experimental Setup

**Conditions and protocol.** C1 provides the complete transformed pre-target conversation, whereas C2 provides an order-preserving oracle subset containing the affected requirements' trajectories and the context needed to interpret them. RQ1 is evaluated only under C1 because C2 is constructed from the gold-relevant trajectory and would reveal the selection answer. RQ2 and RQ3 use both conditions. RQ4 inherits the corresponding condition-specific history but exposes the same pre-task repository only after Phase A has been frozen. No-History is not a formal condition.

For a given target, C1 and C2 use the same current task, response schema, model, prompt, non-repository tools, and resource budget. Each condition and replicate runs in a fresh workspace without cross-run session memory. Condition labels, research-question labels, gold states, internal requirement identifiers, and evaluator artifacts are hidden from the agent. In Phase B, both conditions additionally share the same repository snapshot, execution tools, budget, and target-specific validator. History length is analyzed, rather than sampled, using Short (0–25 prior turns), Medium (26–50), and Long ($>50$) strata.

**Agents and run controls.** We treat the model and its coding-agent harness as a single deployed system because scaffolding, tool use, and stopping behavior can affect the result. The experiment manifest will record the provider model identifier and revision, harness version, evaluation date, context window, temperature and sampling settings, prompt and output-schema hashes, permitted tools and network access, token and wall-clock budgets, retry and stopping policies, and the number of independent runs. The runner will retain the frozen Phase-A response, tool and token logs, final Phase-B repository, and evaluator outputs.

> **TODO:** Freeze the evaluated Codex and Claude Code configurations, exact model versions, prompts, budgets, evaluation dates, and replicate policy before formal runs.

**Scoring.** RQ1 aligns predicted and gold requirement atoms through a frozen semantic-relation classifier followed by deterministic one-to-one matching. It reports Requirement Precision, Recall, and F1; Evidence Precision, Recall, and F1; and Exact Requirement Set Accuracy. Requirement and evidence scores remain separate, and RQ1 receives no C2 result.

RQ2 evaluates the pre-task state only for one-to-one matched historical requirements. Typed comparators score attributes, scope, lifecycle, ambiguity, and execution. *Matched Full-State Exact* requires every applicable field of every matched requirement to be correct. Because unmatched gold requirements are not scored a second time, Reconstruction Coverage, $|M_t|/|R_t^{\mathrm{gold}}|$, is reported separately. Targets with no matched requirement are `N/A`, not perfect reconstructions. An oracle-aligned constant-state baseline exposes class imbalance, and the paired C2–C1 contrast estimates the effect of removing irrelevant and stale history.

RQ3 first scores the `ACT`/`CLARIFY` decision using Decision Accuracy, Balanced Accuracy, and class recall. Gold-ACT targets additionally report typed Post-State Score, Post-State Exact, and end-to-end success. A missing affected requirement scores zero, and an extra requirement is a closed-world false positive. Gold-CLARIFY targets report blocking-issue Precision/Recall/F1, question validity, and clarification success, with requirement-, dimension-, and field-level diagnostics. Unsupported Autonomy uses Gold-CLARIFY targets as its denominator, whereas Unnecessary Clarification uses Gold-ACT targets. All-ACT and all-CLARIFY decision baselines are reported for both conditions.

RQ4 scores only the final repository. A target–condition pair is eligible only if its frozen RQ3 gold decision is `ACT`, the pre-task environment is reproducibly runnable, the requested behavior is deterministically observable, the hidden target tests have passed two independent reviews, the validator has passed calibration, and the agent-visible repository passes the leakage audit. For an eligible target,

$$
\mathrm{RQ4Pass}
=
\mathrm{BuildPass}\land
\mathrm{TargetTestPass}\land
\mathrm{RegressionPass}.
$$

A frozen non-`ACT` or unparsable Phase-A response on an eligible target yields `NO_CODE_SUBMISSION`/`FAIL`; evaluator, environment, or harness failures instead invalidate the attempt and trigger a clean rerun. RQ4 reports Success Rate and Executable Coverage. The primary C1/C2 comparison uses only targets eligible under both conditions with the same validator, while all-eligible results and coverage are shown separately.

**Table 3. Primary metrics and comparison sets for the four evaluation stages.**

| Stage | Main-text metrics | Scoring set or comparison |
| --- | --- | --- |
| RQ1 | Requirement/Evidence F1; Exact Set | C1 targets; target-level macro |
| RQ2 | Attribute Reconstruction; Matched Full-State Exact; Coverage | Matched historical requirements; paired C2–C1 |
| RQ3 | Decision/Balanced Accuracy; ACT and CLARIFY success | Separate Gold-ACT and Gold-CLARIFY denominators |
| RQ4 | Repository Success Rate; Executable Coverage | Eligible targets; C1/C2 common support |

**Aggregation and uncertainty.** Metrics are first computed at their stated unit and then macro-averaged over targets; benchmark-level cross-project claims use project macro-averages so that projects with many targets do not dominate. Every table reports the number of targets for each condition and RQ3 branch. C2–C1 effects use paired targets with identical gold, and RQ4 uses the common-support set described above. Class-conditional recall and risk rates with small denominators will include their numerator, denominator, and two-sided exact-binomial 95% confidence interval. Semantic-judge or schema failures are recorded as `JUDGE_ERROR` and rerun rather than converted into agent errors. Detailed field scores, judge calibration, validator calibration, and per-project results will be reported in the appendix.

> **TODO:** Freeze the replicate aggregation rule, confidence-interval and paired-comparison procedures, multiple-comparison policy, and final handling of agent timeouts and other missing outputs.

### 5.2 Main Results: Requirement Identification and Reconstruction

**RQ1: Can agents select the relevant historical requirements?**

> **Writing template:** Begin with one sentence that answers RQ1 using Requirement F1 and its uncertainty under C1. Identify the strongest model–harness pair and quantify the gap between Requirement F1, Evidence F1, and Exact Requirement Set Accuracy. Then explain the dominant precision or recall failure with one representative case. Report all target counts and avoid generalizing from a single project or history-length stratum.

**RQ2: Can agents reconstruct the current requirement state?**

> **Writing template:** Begin with one sentence that answers RQ2 using Attribute Reconstruction and Matched Full-State Exact. Report the paired C2–C1 difference with uncertainty, followed by Reconstruction Coverage so that matched-only state quality is not mistaken for end-to-end selection performance. Compare against the oracle-aligned constant-state baseline, identify the weakest state dimension, and discuss a counterexample. Do not apply current-task updates to the pre-task state.

**Table 4. Main-result template for RQ1 selection and RQ2 pre-task reconstruction. All entries remain TBD until the formal evaluation is frozen and executed.**

**Panel A: RQ1 selection under C1**

| Model/agent | Targets | Req. P | Req. R | Req. F1 | Exact Set | Evidence P | Evidence R | Evidence F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Model/agent** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** |

**Panel B: RQ2 reconstruction under C1/C2**

| Model/agent | Condition/contrast | $N$ | Attributes | Scope | Lifecycle | Ambiguity | Execution | Matched Exact | Recon. Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Model/agent** | C1 | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** |
| **Model/agent** | C2 | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** |
| **Model/agent** | C2–C1 | **paired TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** |
| Oracle-aligned constant | Baseline | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** |

### 5.3 Main Results: Update Decisions and Code Delivery

**RQ3: Can agents produce the correct requirement update or clarification?**

> **Writing template:** Answer RQ3 first with Decision Accuracy and Balanced Accuracy under C1/C2, together with Gold ACT/CLARIFY counts and the all-ACT/all-CLARIFY baselines. Report paired C2–C1 effects before separating the branches. For Gold-ACT targets, report Post-State Exact and end-to-end success; for Gold-CLARIFY targets, report Blocking-Issue F1, Question Validity, and Clarification Success. State the numerator, denominator, and exact 95% interval for Unsupported Autonomy and Unnecessary Clarification, and do not combine their denominators.

**RQ4: Can agents translate requirements into correct code?**

> **Writing template:** Answer RQ4 with repository Success Rate on the C1/C2 common-support set, including paired uncertainty. Then report each condition's all-eligible Success Rate and Executable Coverage with Gold-ACT, eligible, and common-support counts. Attribute a history-condition effect only on common support. Reserve Build, Target Test, and Regression pass rates for failure analysis, and do not report formal PASS/FAIL values until the RQ3 gold, eligibility gates, validators, calibration, and leakage audits are frozen.

**Table 5. Main-result template for RQ3 update-or-clarify reasoning and RQ4 repository delivery. All entries remain TBD until the formal evaluation is frozen and executed.**

**Panel A: RQ3 decision quality**

| Model/agent | Cond. | Gold A/C | Dec. Acc. | Bal. Acc. | ACT Rec. | CLARIFY Rec. | Unsup. Autonomy | Unnec. Clarify |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Model/agent** | C1 | **TBD/TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** |
| **Model/agent** | C2 | **TBD/TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** |
| All-ACT | C1/C2 | **TBD/TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** |
| All-CLARIFY | C1/C2 | **TBD/TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** |

**Panel B: RQ3 Gold-ACT branch**

| Model/agent | Cond. | Gold-ACT $N$ | Post-State Score | Post-State Exact | End-to-End Success |
| --- | --- | ---: | ---: | ---: | ---: |
| **Model/agent** | C1 | **TBD** | **TBD** | **TBD** | **TBD** |
| **Model/agent** | C2 | **TBD** | **TBD** | **TBD** | **TBD** |

**Panel C: RQ3 Gold-CLARIFY branch**

| Model/agent | Cond. | Gold-CLARIFY $N$ | Req. Correct | Dim. Correct | Field Correct | Blocker P | Blocker R | Blocker F1 | Question Validity | Clarification Success |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Model/agent** | C1 | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** |
| **Model/agent** | C2 | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** |

**Panel D: RQ4 repository delivery**

| Model/agent | Cond. | Gold-ACT $N$ | Eligible $N$ | Common $N$ | PASS (common) | PASS (eligible) | Exec. Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **Model/agent** | C1 | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** |
| **Model/agent** | C2 | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** | **TBD** |

## 6. Analysis and Limitations

This section will analyze concrete failure mechanisms rather than only model rankings. Each implication will be tied to an observed result or case.

### 6.1 Failure Modes and Error Propagation

**Requirement-evolution failure modes.** The analysis will cover `INTRODUCE`, `MODIFY`, `DEFER`, `RESUME`, `REMOVE`, `AMBIGUOUS`, `IMPLEMENTATION_CLAIM`, `RUNTIME_FAILURE`, and `RUNTIME_VERIFICATION`. `CLARIFY` will be analyzed as an RQ3 decision rather than a Requirement Event. Initial categories include stale-state errors that retain superseded values, resurrection errors that reuse removed requirements, missing-scope errors, ambiguity hallucinations, and execution-state confusion.

> **TODO:** Revise this taxonomy using observed errors and add anonymized, provenance-safe examples.

**Effects of history characteristics.** Analyze history length, evidence distance, relevant-evidence density, number of updates, parallel requirements, target position, and number of affected requirements. The final analysis will specify bins, controls, model, and multiple-comparison treatment before interpreting correlations.

**Does unfiltered history hurt?** Compare C1 Full History with C2 Oracle Relevant History on paired targets with the same gold. A C2–C1 difference will be attributed to removal of irrelevant and stale context only after confirming identical prompts, models, budgets, non-repository tools, and sufficient oracle evidence. Candidate mechanisms include noise, stale-state interference, truncation, context competition, and dimension-specific state errors. No-History remains outside the formal comparison.

**Coding ability versus requirement-state ability.** Compare model rankings on a standard coding benchmark, ReqMemBench pre/post-state reasoning, and ReqMemBench RQ4 delivery. Any ranking inversion will be interpreted only after aligning model versions, evaluation dates, harnesses, and uncertainty. If no inversion occurs, the final text will report the observed relationship directly.

**Error propagation across the four stages.**

**Table 6. Planned cross-stage failure analysis.**

| Stage | Diagnostic question | Typical failure |
| --- | --- | --- |
| RQ1 | Were the affected historical requirements and evidence selected? | Missed gold atom/evidence group or imported unrelated requirement |
| RQ2 | Were the matched pre-task states reconstructed? | Stale attributes, widened scope, ignored lifecycle, or confused execution evidence |
| RQ3 | Was the complete update or every material blocker identified? | Incorrect update, unsupported action, or unnecessary/mislocalized question |
| RQ4 | Did the eligible ACT run pass the frozen validator? | Correct reasoning followed by Build, Target Test, or Regression failure |

The analysis distinguishes

$$
\mathrm{MemoryFailure}
\neq\mathrm{StateReasoningFailure}
\neq\mathrm{DecisionFailure}
\neq\mathrm{ImplementationFailure}.
$$

**Figure 3 placeholder: cross-stage error propagation.** Conditional RQ4 PASS rates given correct versus incorrect RQ2/RQ3 outputs, optionally paired with the strongest verified history-characteristic effect.

*Figure 3 caption.* Planned diagnostic of how requirement-state and decision errors propagate to repository delivery.

### 6.2 Implications and Limitations

**Implications for coding-agent design.** The final discussion will retain only implications supported by measured evidence. Candidate implications are that memory should represent current state rather than only retrieve messages; invalidation can matter as much as remembering; requirement memory should preserve temporal provenance; material unresolved ambiguity should trigger clarification; and requirement reasoning should be frozen before repository execution so code cannot reveal the state-reconstruction answer.

**Limitations.** The final paper will cover:

1. **Data domain.** Freelance projects do not represent every enterprise process, organization, safety requirement, or codebase.
2. **Data-generation provenance.** If histories or code states are rewritten, reconstructed, simulated, or mixed, conclusions apply to that construction rather than to unqualified naturally occurring development.
3. **Historical takeover setting.** ReqMemBench supplies an observed history and does not directly evaluate an online memory-writing policy from $t_0$.
4. **Annotation subjectivity.** Requirement atomicity, typed state fields, material ambiguity, post-task branches, and clarification targets permit interpretation differences and require stage-specific reliability evidence.
5. **Code availability and executability.** Dependencies, environments, external services, or original snapshots may not be recoverable for every project.
6. **Requirement gold versus implementation gold.** Multiple implementations may satisfy one requirement:

   $$
   \mathrm{RequirementGold}\neq\mathrm{UniqueCodePatch}.
   $$

7. **Evaluation-judge dependence.** Semantic scorers, target selectors, and validators may introduce model or schema bias; calibration and deterministic checks bound but do not eliminate this risk.
8. **Sampling and dependence.** Multiple targets from one project are correlated, and empty or imbalanced history strata limit generalization.
9. **Coverage.** The benchmark may not cover multi-team enterprise development, combined issue-tracker/chat/code-review histories, multi-year memory, or continuously operating autonomous agents.

## 7. Conclusion

The conclusion will briefly state what existing evaluation misses, what ReqMemBench introduces, and the one or two most important measured findings. ReqMemBench evaluates whether an agent can identify directly affected historical requirements, reconstruct their pre-task states, update or clarify affected post-task states, and complete eligible repository deliveries at intermediate takeover points.

> **TODO:** Insert the final findings and end with the supported form of the central message: persistent coding agents must know both how to code and what the project requires now.

## AI Use Statement

> **TODO:** Complete this statement according to the current ICLR 2027 author policy; disclose generative-AI use in research ideation, data processing, annotation, code, experiments, writing, or editing; and explain human verification and responsibility.

## Ethics Statement

> **TODO:** Describe data authorization, Terms-of-Service or contractual constraints, privacy and de-identification, credentials and sensitive content, reconstructed or simulated artifacts, release scope, re-identification risk, potential harms, and safeguards. Distinguish source-data access from the public release.

## Reproducibility Statement

> **TODO:** Point to the sections, appendices, code, configurations, prompts, schemas, dataset cards, and supplementary artifacts covering selection, provenance, PII processing, annotation, replay, target construction, instance materialization, models, metrics, judge calibration, validator calibration, and statistics.

## References

The canonical bibliography is generated from `iclr2027_conference.bib` with the ICLR bibliography style. Citation keys are preserved above.

## Appendix A. Appendix Structure

The appendix will contain:

1. the complete requirement-state schema and field definitions;
2. the event taxonomy and state-transition rules;
3. project selection, provenance categories, authorization, privacy, and de-identification procedures;
4. annotation guidelines, review interfaces, and agreement analysis;
5. target-time selection and leakage controls;
6. expanded RQ1–RQ4 definitions and examples, complete prompts, public response schemas, and hidden scoring contracts;
7. model, agent, tool, budget, and retry configurations;
8. full metric equations, field-level comparators, branch-specific denominators, aggregation, uncertainty, and statistical tests;
9. judge and validator calibration, baselines, and human-ceiling estimates;
10. full benchmark distributions and eligibility counts;
11. full per-RQ result tables and breakdowns by project, event, condition, model, and history characteristic;
12. failure cases and qualitative examples;
13. one end-to-end example from source evidence through events, the state graph, target-local pre/post states, the frozen Phase-A output and score, and validated repository delivery; and
14. a data card and release statement explaining which artifacts can and cannot be shared.
