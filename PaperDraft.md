# ReqMemBench: Benchmarking Temporal Requirement-State Reconstruction for Coding Agents

> Status: consolidated first-draft workspace with a seven-section ICLR main-text outline. This file retains paragraph-level writing instructions, figure/table plans, and paper-facing research notes while separating main-text content from appendix detail. Bracketed `TODO` items are unresolved author actions rather than established findings.

## Draft control panel

### Current paper claim

ReqMemBench studies whether a coding agent that joins an ongoing project at an arbitrary intermediate time can use the preceding project history to identify the historical requirements directly affected by the current task, reconstruct their pre-task state, determine a unique post-task update or request clarification, and then deliver the update in the pre-task repository.

The intended end-to-end formulation is

$$
\underbrace{H^{(c)}_{<t^*}+q_{t^*}
\rightarrow
\bigl(\widehat{R}^{\mathrm{hist}}_{t^*},
\widehat{G}^{-}_{t^*},
\widehat{G}^{+}_{t^*}\ \text{or Clarification}\bigr)}_{\text{Phase A: RQ1--RQ3, no repository}}
\rightarrow
\underbrace{H^{(c)}_{<t^*}+q_{t^*}+C_{t^{*-}}+\text{Frozen Phase-A Response}
\rightarrow C_{t^{*+}}}_{\text{Phase B: eligible RQ4 only}}.
$$

The intended capability chain is

$$
\mathrm{Select}\rightarrow\mathrm{Reconstruct}
\rightarrow\mathrm{Decide}\rightarrow\mathrm{Execute}.
$$

### Current benchmark snapshot

The current abstract reports 51 projects, 859 requirement atoms, 2,793 requirement events, and 210 Task-Gold takeover targets from 39 projects, with histories ranging from 1 to 898 turns. A read-only recount of the current `outputs/stage2` artifacts reproduces all six values: 51 state graphs, 859 requirement graphs, 2,793 graph edges/events, 210 task gold states, 39 projects with at least one task, and a 1–898 `history_turn_count` range. These counts describe the construction snapshot, not the number of formally reviewed or RQ4-executable evaluation instances.

> **TODO — regenerate and freeze statistics.** These numbers must be generated from one canonical benchmark-statistics script, versioned with the dataset snapshot, and reconciled with the project-, requirement-, event-, task-, RQ-, condition-, and difficulty-level counts used in the tables.

### Master paper outline

The main paper uses seven top-level sections and no `subsubsection` headings. Bold labels below are drafting aids, not visible LaTeX headings.

1. **Introduction**
2. **Related Work**
   - 2.1 Coding and Repository-Level Benchmarks
   - 2.2 Memory and Long-Horizon Coding Agents
3. **Temporal Requirement-State Reconstruction**
   - 3.1 Problem Formulation
   - 3.2 Takeover Task and Evaluation Stages
4. **ReqMemBench Construction**
   - 4.1 Data and Temporal Requirement Graph Construction
   - 4.2 Takeover Instance Construction and History Conditions
   - 4.3 Annotation Quality and Benchmark Statistics
5. **Experiments**
   - 5.1 Experimental Setup
   - 5.2 Main Results: Requirement Identification and Reconstruction
   - 5.3 Main Results: Update Decisions and Code Delivery
6. **Analysis and Limitations**
   - 6.1 Failure Modes and Error Propagation
   - 6.2 Implications and Limitations
7. **Conclusion**
- AI Use Statement
- Ethics Statement
- Reproducibility Statement
- Appendix

**Nine-page planning budget:** Abstract 0.2 page; Introduction 1.0; Related Work 0.6; Sections 3–4 together 2.6–2.8; Experiments 2.4–2.7; Analysis and Limitations 0.8–1.0; Conclusion 0.2–0.3. Figures and tables must fit inside these allocations.

Introduction：约 1 页
Related Work：0.5–0.7 页
Method：1.1–1.3 页
Benchmark/Data：约 1.5 页
Experiments and Results：2.3–2.6 页
Analysis and Limitations：0.8–1.0 页
Conclusion：0.2–0.3 页

### Figure plan

| ID | Placement | Purpose | Required content | Status |
| --- | --- | --- | --- | --- |
| Figure 1 | Introduction / Section 3 | Motivate the takeover task and make the repository-isolation boundary explicit | Requirement-event timeline and takeover time $t^*$; Phase A uses history and task to produce frozen RQ1–RQ3 outputs without a repository; eligible ACT runs enter Phase B with the pre-task repository for RQ4 | Placeholder specified |
| Figure 2 | Section 4 | Explain benchmark construction | Project records → reviewed events → deterministic state graph → target selection → task-local Gold and C1/C2 instances; distinguish model assistance, deterministic processing, and human review | Compact main-text figure |
| Figure 3 | Section 6 | Diagnose cross-stage error propagation | $P(\mathrm{RQ4Pass}\mid\mathrm{RQ2/RQ3\ correct})$ versus $P(\mathrm{RQ4Pass}\mid\mathrm{RQ2/RQ3\ incorrect})$ on eligible runs; optionally include the strongest history-characteristic effect | Required but not yet designed |
| Appendix figures | Appendix | Preserve benchmark distributions and detailed failure analyses | Project/history distributions, requirement/event distributions, target coverage, remaining history-characteristic plots, and detailed failure taxonomy | Candidate; depends on data |

### Table plan

| ID | Placement | Purpose | Status |
| --- | --- | --- | --- |
| Table 1 | Section 3 | Summarize the four evaluation stages, applicable conditions, repository visibility, outputs, and scoring units | Replaces repeated per-RQ definitions across sections |
| Table 2 | Section 4 | Report compact project-, requirement-, event-, task-, and eligibility-level benchmark statistics | Structure exists; values incomplete |
| Table 3 | Section 5.1 | Summarize primary metrics, denominators, and comparisons | Structure exists |
| Table 4 | Section 5.2 | Main results for requirement selection and pre-task state reconstruction | Two compact panels for RQ1 and RQ2; full breakdowns move to the appendix |
| Table 5 | Section 5.3 | Main results for update/clarification decisions and repository delivery | Compact RQ3 and RQ4 panels; branch-specific and validator diagnostics move to the appendix |

The main text therefore targets four required tables plus one optional related-work table, rather than one full standalone table for every RQ.

### Source-to-section map

| Existing source | Paper-facing material | Intended destination |
| --- | --- | --- |
| `ICLR 2027-Upwork Benchmark- 9.19/iclr2027_conference.tex` | Current abstract, full outline, section instructions, equations, placeholders, figures, and tables | Canonical content migrated below |
| `Constuction_guideline/ReqMemBench_RP_V2.md` | Core claim, benchmark landscape, research gap, RQ definitions, examples, and diagnostic decomposition | Introduction, Related Work, Sections 3–6 |
| `Constuction_guideline/Stage 1_guideline.md` | Requirement atom/event definitions and annotation procedure | Sections 3–4, Appendix |
| `Constuction_guideline/Requirement Graph.md` | Event replay, state graph, and gold-state definitions | Sections 3–4, Appendix |
| `Constuction_guideline/DESIGN_stage2_target_time_selection.md` | Target selection, pre/post state boundary, deterministic replay, and review gates | Construction, Reproducibility, Appendix |
| `Constuction_guideline/DESIGN_RQ_instance_construction.md` | RQ instance construction and code-environment classification | Section 4, Section 5, Appendix |
| `Constuction_guideline/DESIGN_RQ_evaluation.md` | RQ1–RQ4 metrics, aggregation, errors, and validator logic | Section 5, Appendix |
| `Constuction_guideline/DESIGN_RQ_agent_input_materialization.md` | Public/private input separation and run materialization | Sections 4–5, Reproducibility, Appendix |
| `Constuction_guideline/DESIGN_RQ1_deferred_publication_risks.md` | Judge calibration, baselines, human ceiling, sampling, and statistical risks | Sections 5–6, Appendix |
| `Constuction_guideline/PII 流程详解.md` | De-identification pipeline and fidelity/safety auditing | Ethics, Construction, Appendix |
| `Code/README.md` and implementation | Executable construction pipeline and artifact definitions | Reproducibility and Appendix |

For RQ inputs, Gold, availability, metrics, and denominators, the three detailed `DESIGN_RQ_*` documents govern this draft when a high-level research-plan description is older or less specific. `Requirement Graph.md` governs event and state ontology. The manuscript must not reintroduce retired conditions or event types from earlier outlines.

### Unresolved data-provenance decision

The current LaTeX draft and `ReqMemBench_RP_V2.md` describe the project histories and requirement evolution as real. Code-environment metadata, however, uses labels such as `simulated-executable-pre-state` and `simulated-state-model` for at least some repository artifacts. The manuscript must distinguish observed conversation/history provenance from reconstructed or simulated code-state provenance and record mixed cases at the instance level.

This is not a wording detail. The paper must document one evidence-backed provenance account for each artifact class, for example:

- fully observed real interaction;
- real source projects plus privacy-preserving rewritten messages;
- or a mixed benchmark with explicit per-instance provenance labels.

Until that decision is resolved, all uses of “authentic,” “naturally occurring,” “real histories,” and “real code states” remain provisional.

---

## Abstract

Coding agents increasingly operate as persistent participants in software projects, inheriting evolving codebases midway through long-running client collaborations. Successful continuation requires more than solving the current request: requirements may have been revised, narrowed, deferred, resumed, or withdrawn, leaving the specification that governs the task distributed across the interaction history. Existing coding benchmarks evaluate task completion, while memory and long-context benchmarks largely evaluate access to past information; neither directly measures whether an agent can determine which requirements still hold. We formulate this problem as temporal requirement-state reconstruction and introduce ReqMemBench, a benchmark derived from real freelance software projects with naturally evolving requirements. ReqMemBench reconstructs the gold requirement state at each takeover point and evaluates agents across evidence selection, state reconstruction, clarification decisions, and code execution under controlled access to project history. This evaluation is designed to determine how closely current coding agents can approach the annotated gold state even when relevant history is provided, testing whether persistent software development requires not only remembering the past, but reasoning about how past requirements evolve into the specification that governs the present.

> **TODO:** After the experiments are complete, replace the final future-facing sentence with the supported quantitative finding and conclusion. Reconcile “real freelance software projects with naturally evolving requirements” with the frozen provenance account before submission.

## 1. Introduction

**Drafting goal.**

Establish that correctly continuing a software project requires both temporal requirement reasoning and repository execution. An agent must determine which historically expressed requirements are directly implicated by the current task and what states they have before acting. The argument should move from the temporal nature of projects, through task-relevant state reconstruction, to the missing explicit temporal requirement-state target in existing evaluations. Write five or six natural paragraphs rather than formal subsections.

**Paragraph 1 — From isolated coding tasks to stateful software projects.**

Explain that coding agents are evolving from one-shot code generators into persistent participants in software projects, and that an agent may enter a project at any intermediate time. A requirement may evolve as

$$
\mathrm{INTRODUCE}\rightarrow\mathrm{MODIFY}\rightarrow\mathrm{DEFER}
\rightarrow\mathrm{RESUME}\rightarrow\mathrm{REMOVE},
$$

Ambiguity is represented as an independent state dimension introduced by an `AMBIGUOUS` event. A later state-changing event such as `MODIFY`, `REMOVE`, `DEFER`, or `RESUME` can explicitly resolve that ambiguity through its provenance link; `CLARIFY` and `RESOLVE` are not event types.

Consequently, different time points correspond to different valid specifications, and the desired action is generally not a function of the current task alone:

$$
\mathrm{DesiredAction}_{t^*}\neq f(q_{t^*}),
\qquad
\mathrm{RequirementDecision}_{t^*}
=f(H_{<t^*},q_{t^*}),
\qquad
C_{t^{*+}}=g(C_{t^{*-}},q_{t^*},\mathrm{FrozenReasoning}_{t^*}).
$$

**Paragraph 2 — The missing state between history and coding.**

Distinguish between what happened and what remains valid now. If a requirement was introduced, modified, deferred, and then removed, the correct interpretation is not merely to retain four messages, but to infer

$$
\mathrm{State}_{X}(t_4)=\mathrm{REMOVED}.
$$

Central sentence: **The challenge is not to remember everything that happened, but to determine what still matters now.**

**Paragraph 3 — The gap in existing coding evaluation.**

Summarize conventional repository-level evaluation as

$$
(C,q)\rightarrow\mathrm{Patch},
$$

where correctness is primarily defined by whether a model resolves a given issue in a given repository. In contrast, ReqMemBench separates requirement reasoning from repository execution:

$$
(H,q)\rightarrow
\bigl(\mathrm{PreState},\mathrm{PostState\ or\ Clarification}\bigr)
\rightarrow
C_{t^-}\rightarrow\mathrm{Delivery}.
$$

Do not claim that existing benchmarks contain no history or no evolving requirements. The more precise claim is that they generally center correctness on a current task outcome, retrieval, iterative refinement, or prior experience rather than treating an explicit temporally evolving project requirement state as the evaluated object. The problem is also distinct from simple long-context retrieval: even when all relevant messages are accessible, an agent must reconcile revisions, invalidations, deferrals, resumptions, clarifications, and execution feedback.

**Paragraph 4 — The evaluation target.**

Introduce the core two-phase formulation:

$$
\boxed{
H^{(c)}_{<t^*}+q_{t^*}
\rightarrow
\bigl(\widehat{R}^{\mathrm{hist}}_{t^*},
\widehat{G}^{-}_{t^*},
\widehat{G}^{+}_{t^*}\ \text{or Clarification}\bigr)
}.
$$

The structured response is frozen before the repository becomes visible. For an eligible run whose frozen decision is `ACT`, the execution phase evaluates

$$
H^{(c)}_{<t^*}+q_{t^*}+C_{t^{*-}}+\mathrm{FrozenReasoning}_{t^*}
\rightarrow C_{t^{*+}}.
$$

ReqMemBench does not assume that the same agent has participated since the first day. It evaluates a takeover setting: when a coding agent enters a project at an arbitrary intermediate time, can it reconstruct what the project currently requires and continue development correctly?

**Paragraph 5 — The ReqMemBench approach.**

Present the construction pipeline at a high level without serialization details:

$$
\mathrm{RealProjectHistory}\rightarrow\mathrm{RequirementEvents}
\rightarrow\mathrm{RequirementStateGraph}\rightarrow\mathrm{GoldState}(t^*)
\rightarrow\mathrm{EvaluationInstance}.
$$

State that source material is converted into requirement events; event replay constructs temporal state; one project can yield instances at multiple takeover points; each point has an explicit pre-task gold state; and the target task determines the correct next action. The exact wording about real versus role-played history and code must follow the frozen provenance account.

**Paragraph 6 — Contributions.**

Fix the contribution list to four items:

1. **A new evaluation problem.** Formalize temporal requirement-state reconstruction for coding agents: identifying the historical requirements directly affected by a takeover task and recovering their valid pre-task states.
2. **A project-level benchmark.** Construct ReqMemBench from longitudinal software projects, client–developer histories, evolving requirements, intermediate code states, and target tasks. The provenance adjective must be finalized.
3. **Temporal gold-state construction.** Introduce
   $$
   \mathrm{Messages}\rightarrow\mathrm{Events}\rightarrow\mathrm{StateGraph}
   \rightarrow G_P(t),
   $$
   providing explicit temporal requirement ground truth rather than only a collection of historical messages.
4. **Empirical findings.** Use controlled Full-History and Oracle-Relevant-History evaluations to separate context-selection and stale-history errors from temporal state reasoning, clarification, and downstream delivery failures.

> **TODO:** Replace the fourth contribution with concrete findings after completing the experiments.

**Figure 1 — Motivation and task definition.**

**Visual specification:**

```text
Introduce A → Modify A → Introduce B → Remove B → Ambiguous A
                         ↓ takeover time t*
Phase A: history + current task → RQ1/RQ2/RQ3 response → freeze
Phase B: eligible ACT + pre-task repository → final repository → hidden validator
```

**Caption:** The ReqMemBench takeover setting. An agent first reasons from the preceding history and current task without repository access. After its RQ1–RQ3 response is frozen, eligible ACT runs receive the pre-task repository for RQ4 delivery evaluation.

## 2. Related Work

**Drafting goal.**

Establish that coding benchmarks, long-term memory benchmarks, and long-horizon conversational coding benchmarks each cover part of the problem, but do not use the temporal requirement state defined by ReqMemBench as the same explicit evaluation object. Compare inputs, gold targets, outputs, and provenance without understating prior work.

> **TODO:** Add and verify all citations before submission. The current `.bib` contains only unrelated template references and cannot support this section.

### 2.1 Coding and Repository-Level Benchmarks

Organize this subsection around

$$
\mathrm{FunctionGeneration}\rightarrow\mathrm{RepositoryIssueResolution}
\rightarrow\mathrm{AgenticSoftwareEngineering}.
$$

Begin with function-generation benchmarks such as HumanEval and MBPP. Then discuss SWE-bench and related work that extends evaluation to issue resolution in real repositories. Continue with project-level and agentic software-engineering benchmarks, including process-oriented evaluations such as RigorBench. Conclude that these benchmarks have progressively expanded how an agent completes a task, while correctness is generally centered on the outcome of a given task rather than an explicit project requirement state at an arbitrary time.

### 2.2 Memory and Long-Horizon Coding Agents

Review benchmarks such as LongMemEval, which evaluate information extraction, multi-session reasoning, temporal reasoning, knowledge updates, and abstention. Explain how these abilities relate to ReqMemBench while emphasizing the different evaluation object. A typical memory benchmark takes the form

$$
\mathrm{History}+\mathrm{Query}\rightarrow\mathrm{Answer},
$$

whereas ReqMemBench evaluates a permission-separated chain:

$$
\mathrm{ProjectHistory}+\mathrm{Task}
\rightarrow\mathrm{TaskRelevantState/Clarification}
\rightarrow\mathrm{FrozenReasoning}+\mathrm{Code}
\rightarrow\mathrm{ValidatedDelivery}.
$$

Here, history is not merely a knowledge base to query; it is temporal evidence from which the current project specification must be constructed.

**Long-horizon conversational coding.**

Use LoCoEval as the main comparison. Describe its focus on repository-oriented long-horizon conversational context management, iterative requirements, and information retention. The intended distinction is not that one problem subsumes the other: LoCoEval asks how long conversational context should be managed in repository-oriented interaction, whereas ReqMemBench asks which requirements remain valid in an evolving project and what the agent should do next. Verify the data-generation setting, task types, annotation targets, and whether requirement lifecycle, scope, ambiguity, execution state, and arbitrary takeover points are explicitly represented.

Also position ConvCodeWorld, SWE-Bench-CL, SWE-ContextBench, SR-Eval, and RECODE-H according to whether history represents feedback, past coding experience, iterative refinement, or a persistent requirement state.

**Positioning ReqMemBench.**

The comparison should make the distinct evaluation object visible without marking every competing benchmark as missing every feature.

**Candidate comparison inventory from the existing research plan.**

The following rows are working comparison notes, not an additional main-text subsection. They are not publication-ready until each paper, year, venue, and feature judgment is checked against primary sources; the final table may move to the appendix if it does not fit the page budget.

| Benchmark | Current characterization | Intended distinction from ReqMemBench |
| --- | --- | --- |
| CrossCodeEval | Real-repository cross-file code completion and dependency/context discovery | Static repository context rather than evolving client requirement state |
| RepoBench | Repository-level retrieval, completion, and retrieval-plus-completion | Repository as current/static context rather than longitudinal requirement evolution |
| SWE-bench | Real issue resolution in a repository | Task/issue outcome rather than reconstructing project requirement state before the task |
| BigCodeBench | Complex instruction-following with functions, libraries, and APIs | Complex but mainly static single-task specification |
| SWE-Lancer | Real freelance software-engineering tasks, including coding and managerial tasks | Real task origin but not necessarily same-project requirement trajectories |
| LongMemEval | Multi-session memory, temporal reasoning, knowledge updates, and abstention | Conversational answer target rather than project state plus executable action |
| ConvCodeWorld | Multi-turn code generation with execution/verbal feedback | Feedback-driven repair rather than long-term requirement-state maintenance |
| SWE-Bench-CL | Temporally ordered repository issues for continual learning/transfer/forgetting | Past coding experience rather than persistent client requirement state |
| SWE-ContextBench | Retrieval/reuse of past execution trajectories or summaries | Reuse of prior experience rather than deciding which prior requirements remain valid |
| SR-Eval | Multi-round requirement refinement with code modification and tests | Close on evolving requirements; verify whether persistent/local/removed/ambiguous state is explicit |
| RECODE-H | Multi-turn simulated human feedback for research-code revision | Feedback-driven improvement rather than arbitrary-time state reconstruction |
| LoCoEval | Repository-oriented long-horizon conversation, iterative requirements, noise, and retrospective questions | Closest comparison; verify whether it explicitly evaluates lifecycle/scope/ambiguity/execution state and state-to-action chain |
| ReqMemBench | Arbitrary-time takeover with history-only requirement reasoning followed by gated pre-task-repository execution | Explicit task-relevant pre/post requirement states and validated delivery under a leakage-controlled phase boundary |

## 3. Temporal Requirement-State Reconstruction

**Drafting goal.**

Establish that temporal requirement state is a well-defined construction object and that the benchmark evaluates task-relevant subgraphs rather than exact recovery of the entire project graph. Define the temporal project boundary, requirement atoms and their state, the directly affected historical subset, pre- and post-task state targets, and the two-stage boundary between reasoning and repository delivery.

### 3.1 Problem Formulation

**Temporal project setting.**

Define a project as

$$
P=(H,C),
$$

where $H$ is the timestamped project history and $C$ is the code state as it evolves over time. For a target task $q_{t^*}$ arriving at time $t^*$, construction uses only the preceding history

$$
H_{<t^*}
$$

and aligns it with the code snapshot immediately before the task arrives,

$$
C_{t^{*-}}.
$$

Specify which client messages, developer messages, milestones, feedback, and execution signals belong to $H$; how code snapshots are aligned with time; how $t^*$ is determined; and why all evidence after $t^*$ is excluded to prevent future-information leakage. Agent visibility is stricter than construction visibility: Phase A exposes only condition-specific history and the current task, while $C_{t^{*-}}$ is isolated until eligible Phase B execution.

**Requirement and requirement state.**

Use a requirement atom as the independent lifecycle unit. A requirement family is a semantic grouping and does not have an independent lifecycle. For a requirement atom $r$, define

$$
G_r(t)=
\bigl(\mathrm{Attributes},\mathrm{Lifecycle},\mathrm{Scope},
\mathrm{Ambiguity},\mathrm{Execution}\bigr).
$$

The five dimensions represent:

- the current requirement value/attributes;
- lifecycle such as `ACTIVE`, `DEFERRED`, or `REMOVED`;
- persistence, component, and contextual scope;
- open or closed ambiguity and affected dimensions;
- execution states such as `FAILED`, `CLAIMED_WORKING`, and `VERIFIED_WORKING`.

> **TODO:** Provide complete state vocabularies, formal transition semantics, and requirement-atom segmentation rules. Keep `persistence` inside `scope` so the paper and scorer consistently use five state dimensions.

**Project state and evaluated task-local subgraphs.**

Define the project-level requirement state at time $t$ as

$$
G_P(t)=\{G_r(t)\mid r\text{ appeared before }t\}.
$$

A removed requirement does not disappear from the project graph. It remains represented with lifecycle `REMOVED` because recognizing invalidity, avoiding continued implementation, and avoiding accidental resurrection are part of temporal replay.

The benchmark does not ask the Agent to reproduce all of $G_P(t)$. For target $q_{t^*}$, let $A_{t^*}$ be the requirements directly affected by target events and let $R_P(t^{*-})$ be the requirements that already exist before the target. RQ1 and RQ2 use

$$
R^{\mathrm{hist}}_{t^*}=A_{t^*}\cap R_P(t^{*-}),
\qquad
G^-_{t^*}=\{G_r(t^{*-})\mid r\in R^{\mathrm{hist}}_{t^*}\}.
$$

New requirements introduced by the target are excluded from $G^-_{t^*}$. RQ3 instead evaluates the complete post-task states of all affected requirements,

$$
G^+_{t^*}=\{G_r(t^{*+})\mid r\in A_{t^*}\},
$$

including requirements first introduced by the target. Preserved or inherited requirements that are not directly affected remain in the project graph but are outside the frozen RQ1 Gold set.

**Requirement state as event replay.**

Convert the history relevant to requirement $r$ into an ordered event sequence

$$
E_r=(e_1,e_2,\ldots,e_n),
$$

and recover the complete state at any time through

$$
G_r(t)=\mathrm{Replay}(E_r^{\leq t}).
$$

Events record what changed and why, while state nodes represent the complete requirement state after each change. This design reflects four properties: requirements are evolving objects; messages are evidence rather than states; events retain temporal provenance; and the same project graph can be replayed at multiple takeover points.

### 3.2 Takeover Task and Evaluation Stages

Table 1 should define the complete evaluation chain once. Later sections refer back to these stages rather than redefining the RQs.

| Stage | Question | Phase-A input | Output / Gold target | Conditions | Repository |
| --- | --- | --- | --- | --- | --- |
| RQ1 — Selection | Which historical Requirement Atoms and evidence are directly affected by the current task? | $H_{<t^*}+q_{t^*}$ | $R^{\mathrm{hist}}_{t^*}$ and supporting evidence | C1 only | Hidden |
| RQ2 — Reconstruction | What were the matched affected historical Requirements immediately before takeover? | condition-specific history plus the current task as a relevance anchor | $G^-_{t^*}$ over matched historical Requirements | C1/C2 | Hidden |
| RQ3 — Update or Clarify | Does visible evidence determine a unique complete post-task state, or is clarification required? | the same frozen Phase-A context and reconstructed state | $G^+_{t^*}$ for ACT, or structured blockers/questions for CLARIFY | C1/C2 | Hidden |
| RQ4 — Delivery | Can an eligible ACT run implement the frozen interpretation correctly? | frozen Phase-A response plus $C_{t^{*-}}$ | final repository validated by Build, Target Test, and Regression | eligible C1/C2 | Visible only after freeze |

RQ1 is unavailable under C2 because oracle history is constructed from the RQ1 Gold trajectory and would expose the selection answer. RQ2 and RQ3 never receive a repository. RQ4 opens only after the Phase-A response is frozen, preventing code from revealing the earlier Gold state.

The Phase A reasoning task is

$$
H^{(c)}_{<t^*}+q_{t^*}
\rightarrow
\bigl(\widehat{R}^{\mathrm{hist}}_{t^*},
\widehat{G}^{-}_{t^*},
\widehat{d}_{t^*},
\widehat{G}^{+}_{t^*}\ \text{or}\ \widehat{Q}_{t^*}\bigr),
$$

where $d_{t^*}\in\{\mathrm{ACT},\mathrm{CLARIFY}\}$ and $\widehat{Q}_{t^*}$ contains structured blocking issues and clarification questions. RQ2 evaluates pre-task state only over successfully aligned historical requirements; requirement selection errors remain the responsibility of RQ1 and are summarized separately by reconstruction coverage.

The Phase A response is frozen before repository access. If the condition has Gold `ACT`, passes the RQ4 eligibility gate, and the Agent also selects `ACT`, Phase B evaluates

$$
H^{(c)}_{<t^*}+q_{t^*}+C_{t^{*-}}+\mathrm{FrozenReasoning}_{t^*}
\rightarrow\widehat{C}_{t^{*+}}.
$$

This separation distinguishes selection, pre-task reconstruction, update-or-clarify reasoning, and final repository delivery without allowing code to reveal the RQ1–RQ3 Gold.

## 4. ReqMemBench Construction

ReqMemBench converts longitudinal project records into temporal Requirement State Graphs and derives evaluation instances at intermediate takeover points. Figure 2 summarizes the pipeline and separates model-assisted extraction, deterministic processing, and human review. Section 3 defines the state representation and evaluation stages; this section describes how their Gold targets and agent-visible inputs are constructed.

**Figure 2 — Construction pipeline.**

Project records → reviewed Requirement Events → deterministic replay → temporal State Graph → target selection → task-local Gold → C1/C2 instances.

The figure should mark the cutoff at \(t^*\) and distinguish agent-visible inputs from hidden Gold.

**Caption:** ReqMemBench converts longitudinal project records into evidence-linked Requirement States and leakage-controlled takeover instances.

### 4.1 Temporal Requirement Graph Construction

ReqMemBench is derived from longitudinal records of real freelance software projects. All agent-visible histories are privacy-preserving transformations of project records, and some messages or code environments are reconstructed when exact historical artifacts are unavailable. These distinctions are recorded at the instance level; detailed access, authorization, transformation, and release procedures belong in the Ethics Statement and Data Card.

Using the vocabulary defined in Section 3, model-assisted extraction proposes Requirement Atoms, state-changing Events, and links to supporting messages. Schema checks, cross-reference validation, and human review determine which candidates enter the canonical annotation. Deterministic replay then applies the accepted Events in project order to produce temporally indexed Requirement States. Invalid transitions fail validation rather than receiving model-based repair, and every state retains its supporting evidence. Complete schemas, transition rules, and provenance categories move to the appendix.

> **TODO:** Report frozen project and message counts and the proportions of transformed histories, reconstructed messages, recovered code environments, and reconstructed code environments. Document authorization and public-release scope separately in the Ethics Statement and Data Card.

### 4.2 Takeover Instance Construction

Each target is a client task whose interpretation depends on earlier project context and induces a verifiable Requirement transition. A multi-requirement message remains one takeover task; context-free introductions and messages containing only implementation evidence are excluded. Candidates are admitted through a frozen historical-dependence and requirement-evolution rule, with the full rubric, threshold, review policy, and candidate-flow counts reported in the appendix.

Deterministic replay produces the pre-task and post-task boundaries defined in Section 3. The benchmark stores the complete project states but evaluates their affected task-local projection. Requirements introduced by the target have no pre-task state, while removed Requirements remain represented as **REMOVED**. This construction supplies the Gold for selection, reconstruction, and update-or-clarify evaluation without redefining the four RQs.

Each target is materialized under Full History and Oracle Relevant History. The latter is an audited, order-preserving subsequence that retains the affected Requirement trajectories and the context needed to determine the same Gold. Gold annotations, internal identifiers, future messages, repositories, and validators are excluded from Phase A; repository access begins only after the Phase-A response is frozen. Full serialization, RQ applicability, RQ4 eligibility, and runner-isolation details move to the appendix or Section 5.

> **TODO:** Report accepted and rejected targets, C1/C2 instance counts, and RQ4 candidate, environment, eligibility, and exclusion counts.

### 4.3 Curation Validity and Benchmark Statistics

Quality control is matched to each construction layer: language models propose candidates, deterministic code validates and replays Events, and human review freezes semantic annotations and ambiguity-sensitive Gold. At least 200 stratified state transitions will be reassessed through human review and two independent LLM assessments. The final report will define the unit, label space, reviewer independence, prevalence, and adjudication, then report raw agreement and coefficients appropriate to the final rater design. This audit remains separate from RQ1 judge calibration, RQ3 adjudication, and RQ4 validator calibration.

Oracle-history sufficiency is audited independently. C2 must be an ordered subsequence of C1 and retain the evidence needed to determine the same pre-task state and frozen RQ3 branch. Any disagreement triggers correction or exclusion rather than being counted as a condition effect.

| Level | Main-text statistic | Current snapshot |
| --- | --- | --- |
| Project | Projects | 51 |
| Requirement | Requirement Atoms | 859 |
| Event | Requirement Events | 2,793 |
| Task | Takeover tasks and source projects | 210 tasks from 39 projects |
| Evaluation | Reviewed/eligible instances by RQ and condition | TBD |

Detailed distributions, provenance categories, repository recoverability, and exclusion reasons move to the appendix.

> **TODO:** Insert the frozen review workflow, agreement and oracle-history audit results, correction counts, and regenerated benchmark statistics.
## 5. Experiments

**Drafting goal.**

Separate history selection, requirement-state reasoning, clarification behavior, and downstream delivery. Across C1/C2, Phase A uses the same target task, prompt, response schema, model, non-repository tools, and resource budget; only the visible history changes, and the condition name is hidden from the Agent. Repository access is prohibited in Phase A and opened only in eligible Phase B runs under the same execution prompt, tools, budget, repository, and validator.

### 5.1 Experimental Setup

Section 3 and Table 1 define the four evaluation stages. This subsection reports only the evaluated model–harness units, condition applicability, run budgets, prompts/tools, primary metrics, aggregation, and uncertainty. Full response schemas, comparator rules, metric equations, judge calibration, and validator calibration belong in the appendix.

**Evaluation matrix.**

The current plan crosses five dimensions:

| Dimension | Planned levels |
| --- | --- |
| History difficulty | Short (0–25 turns), Medium (26–50), Long (>50) |
| Research question | RQ1 Selection, RQ2 Pre-task Reconstruction, RQ3 Update-or-Clarify, RQ4 Delivery |
| Agent framework | Codex, Claude Code |
| Backbone model | Codex: GPT-5.6 SOL, GPT-5.6 Terra, GPT-5.5; Claude Code: Claude Opus 5, Claude Sonnet 5, Claude Haiku 4.5 |
| Input condition | C1 Full History, C2 Oracle Relevant History; RQ1 uses C1 only |

The protocol matrix below records applicability rather than reserving a rectangular result cell for every combination:

| RQ | Phase | C1 | C2 | Repository visible | Primary scoring unit |
| --- | --- | ---: | ---: | --- | --- |
| RQ1 | A | Yes | No | No | target under Full History |
| RQ2 | A | Yes | Yes | No | matched historical Requirement, then target aggregation |
| RQ3 | A | Yes | Yes | No | target × condition |
| RQ4 | B | Eligible only | Eligible only | Yes, after freeze | eligible target × condition; C1/C2 effect uses common support |

The default Agent run unit is `target × condition`, not `target × RQ × condition`: one frozen Phase A response supplies the applicable RQ1–RQ3 views, and Phase B opens only through the RQ4 gate.

> **TODO:** Freeze model availability, exact version identifiers, harness/model compatibility, evaluation dates, and a feasible cost-aware matrix. Do not name unreleased or unverified model versions in the final paper.

**Models and coding agents.**

Report every evaluated model and version, agent harness, context window, tools, execution budget, token/time budget, temperature, retry policy, stopping criteria, sandbox/network permissions, and evaluation date. Treat the model–harness combination as the deployed evaluation unit. Use a common scaffold where possible, and report unavoidable framework-specific differences.

> **TODO:** Insert final models, versions, prompts, tools, budgets, and repeated-run policy.

**Primary metrics and statistical reporting.**

| Stage | Primary main-text metrics | Critical denominator / comparison |
| --- | --- | --- |
| RQ1 | Requirement F1, Evidence F1, Exact Requirement Set | C1 targets only; requirement and evidence selection remain separate |
| RQ2 | Attribute Reconstruction, Full-State Exact, Reconstruction Coverage | State correctness uses one-to-one matched historical Requirements; coverage is reported separately; paired C2−C1 |
| RQ3 | Decision Accuracy/Balanced Accuracy; ACT post-state success; CLARIFY success | Report Gold ACT and Gold CLARIFY branches with their own denominators and constant-decision baselines |
| RQ4 | Repository PASS rate and Executable Coverage | PASS requires Build, Target Test, and Regression; C1/C2 comparison uses common support |

Freeze replicate count, aggregation order, missing/failure handling, and uncertainty before formal evaluation. Report sample counts beside every condition and branch. Aggregate correlated targets at the project level for cross-project claims. Full equations, field-level scores, class-conditional metrics, exact intervals, semantic-judge calibration, and validator diagnostics move to the appendix.

### 5.2 Main Results: Requirement Identification and Reconstruction

This subsection reports the two history-only capabilities evaluated before repository access. RQ1 measures whether an agent can locate the historical Requirements and evidence directly implicated by the target task. RQ2 then measures whether the agent can reconstruct the pre-task states of the Requirements that were successfully aligned to Gold. The two scores must be interpreted together: high matched-state accuracy with low Reconstruction Coverage indicates accurate recovery of a small selected subset rather than successful reconstruction of the full affected history.

**RQ1: Can agents select the relevant historical requirements?**

> **Result-writing template.** Under C1 Full History, **[best model–harness pair]** achieved a Requirement F1 of **[TBD]** (95% CI: **[TBD, TBD]**) and an Evidence F1 of **[TBD]**. Exact Requirement Set Accuracy was **[TBD]**, showing that **[state whether errors arose mainly from missed Requirements, imported distractors, or incomplete evidence]**. Across systems, **[precision/recall]** was consistently lower by **[TBD]** points, indicating that **[supported interpretation of the dominant selection failure]**.

| Model / agent | Targets | Req. P | Req. R | Req. F1 | Exact Req. Set | Evidence P | Evidence R | Evidence F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

> **Analysis template.** Relate the primary selection result to history length, evidence distance, relevant-evidence density, Gold Atom count, and competing Requirements only when the corresponding analysis is available. Use one provenance-safe example to distinguish a retrieval miss from a temporal-selection error, such as selecting a superseded Requirement that was easy to retrieve but no longer governed the target. Report project-level variation and avoid treating target counts from one project as independent cross-project evidence.

**RQ2: Can agents reconstruct the current requirement state?**

> **Result-writing template.** On one-to-one matched historical Requirements, **[best model–harness pair]** obtained an Attribute Reconstruction score of **[TBD]** under C1 and **[TBD]** under C2. The paired C2−C1 difference was **[TBD]** (95% CI: **[TBD, TBD]**), while Matched Full-State Exact changed from **[TBD]** to **[TBD]**. Reconstruction Coverage was **[TBD]** under C1 and **[TBD]** under C2. These results indicate that **[state whether oracle history mainly improved state recovery, selection coverage, both, or neither]** without counting unmatched Requirements a second time in the state score.

| Model / agent | Condition / contrast | N | Attributes | Scope | Lifecycle | Ambiguity | Execution | Matched Full-State Exact | Recon. Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| TBD | C1 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| TBD | C2 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| TBD | C2−C1 | paired TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Oracle-aligned constant | Baseline | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

> **Analysis template.** Compare the measured state dimensions with the oracle-aligned constant-state baseline before interpreting a high score, because common defaults such as `ACTIVE` or `null` may be frequent. Identify the weakest dimension and trace it to a concrete temporal operation: stale attributes, scope expansion, lifecycle confusion, unresolved ambiguity, or mistaken execution status. Keep `Matched State Score` and field-level breakdowns in the appendix unless they are necessary to explain the main result. The current task is a relevance anchor in RQ2; values introduced by that task belong to the RQ3 post-task state and must not be credited as correct pre-task reconstruction.

### 5.3 Main Results: Update Decisions and Code Delivery

**RQ3: Can agents produce the correct requirement update or clarification?**

The RQ3 portion of Table 5 uses separate panels because decision quality, ACT post-state quality, and CLARIFY quality have different denominators.

**Panel A — Decision quality**

| Model / agent | Condition | Gold ACT / CLARIFY | Decision Acc. | Balanced Acc. | ACT Recall | CLARIFY Recall | Unsupported Autonomy | Unnecessary Clarification |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| TBD | C1 | TBD / TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| TBD | C2 | TBD / TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| all-ACT baseline | C1/C2 | TBD / TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| all-CLARIFY baseline | C1/C2 | TBD / TBD | TBD | TBD | TBD | TBD | TBD | TBD |

**Panel B — Gold ACT branch**

| Model / agent | Condition | Gold-ACT N | Post-State Score | Post-State Exact | ACT End-to-End Success |
| --- | --- | ---: | ---: | ---: | ---: |
| TBD | C1 | TBD | TBD | TBD | TBD |
| TBD | C2 | TBD | TBD | TBD | TBD |

**Panel C — Gold CLARIFY branch**

| Model / agent | Condition | Gold-CLARIFY N | Req. Correct | Dimension Correct | Field Correct | Blocking Issue F1 | Question Validity | Clarification Success |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| TBD | C1 | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| TBD | C2 | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

Interpret C1/C2 differences as Agent sensitivity to full-history noise because both conditions use the same frozen Gold branch. Break down material ambiguity types in secondary analysis without treating every open ambiguity as a Gold CLARIFY case.

**RQ4: Can agents translate requirements into correct code?**

The RQ4 portion of Table 5 reports both the fair C1/C2 comparison on common support and the coverage of executable Gold-ACT cases.

| Model / agent | Condition | Gold-ACT N | Eligible N | Common-Support N | RQ4 Success, common support | RQ4 Success, all eligible | Executable Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| TBD | C1 | TBD | TBD | TBD | TBD | TBD | TBD |
| TBD | C2 | TBD | TBD | TBD | TBD | TBD | TBD |

Do not report formal PASS/FAIL results until RQ3 Gold, acceptance criteria, hidden validators, calibration, and repository-leakage audits are frozen. Build, Target Test, and Regression rates appear in failure analysis rather than as additional score levels.

Figure 3 may analyze

$$
P(\mathrm{RQ4Pass}\mid\mathrm{RQ2/RQ3\ correct})
\quad\text{versus}\quad
P(\mathrm{RQ4Pass}\mid\mathrm{RQ2/RQ3\ incorrect})
$$

over eligible runs. This cross-RQ analysis diagnoses error propagation but does not replace the RQ4 Success Rate or alter the RQ4 denominator.

## 6. Analysis and Limitations

**Drafting goal.**

Show concrete failure mechanisms rather than only a model ranking. Every implication must be tied to an observed result or case.

### 6.1 Failure Modes and Error Propagation

**Requirement-evolution failure modes.**

Break down errors involving `INTRODUCE`, `MODIFY`, `DEFER`, `RESUME`, `REMOVE`, `AMBIGUOUS`, `IMPLEMENTATION_CLAIM`, `RUNTIME_FAILURE`, and `RUNTIME_VERIFICATION`. Analyze `CLARIFY` separately as an RQ3 decision rather than a Requirement Event. Initial categories are:

- stale-state errors that retain superseded values;
- resurrection errors that reuse removed requirements;
- missing-scope errors that apply a valid requirement to the wrong component or context;
- ambiguity hallucinations that resolve underspecified choices without evidence;
- execution-state confusion that treats an implementation claim as verified success.

> **TODO:** Revise the taxonomy using observed errors and add anonymized, provenance-safe examples.

**Effects of history characteristics.**

Analyze history length, evidence distance, relevant-evidence density, number of updates, parallel requirements, target position, and number of affected requirements. Specify bins, controls, model, and multiple-comparison treatment before interpreting correlations.

**Does unfiltered history hurt?**

Compare C1 Full History with C2 Oracle Relevant History using paired targets and the same Gold. Attribute `C2 − C1` differences to removal of irrelevant and stale context only after confirming identical prompts, models, budgets, non-repository tools, and sufficient Oracle evidence. Analyze noise, stale-state interference, truncation, context competition, and the state dimensions responsible for the difference. No-History is outside the formal comparison.

**Coding ability versus requirement-state ability.**

Compare model rankings on a standard coding benchmark, ReqMemBench pre/post-state reasoning, and ReqMemBench RQ4 delivery. If a ranking inversion occurs, use it carefully to show that isolated-task coding scores may not fully predict persistent-project performance. If no inversion occurs, report the observed relationship. Align model versions, evaluation dates, harnesses, and uncertainty before computing correlation.

**Error propagation across the four stages.**

| Failure stage | Diagnostic question | Typical failure |
| --- | --- | --- |
| RQ1 — Selection | Did the agent identify the directly affected historical Requirements and evidence? | Misses a Gold Atom/evidence group or imports an unrelated Requirement |
| RQ2 — Reconstruction | Did it recover the matched Requirements' pre-task states? | Uses stale attributes, widens scope, ignores lifecycle changes, or confuses execution evidence |
| RQ3 — Update or Clarify | Did it construct the complete post-task state or locate every material blocker? | Produces an incorrect update, acts without sufficient evidence, or asks an unnecessary/mislocalized question |
| RQ4 — Delivery | Did the eligible ACT run produce a repository that passes the frozen validator? | Reasoning is correct but Build, Target Test, or Regression fails |

Thus the benchmark aims to distinguish

$$
\mathrm{MemoryFailure}
\neq\mathrm{StateReasoningFailure}
\neq\mathrm{DecisionFailure}
\neq\mathrm{ImplementationFailure}.
$$

### 6.2 Implications and Limitations

**Implications for coding-agent design.**

Connect results to five possible implications, retaining only those supported by evidence:

1. memory should represent current state rather than only retrieve messages;
2. forgetting and invalidation can matter as much as remembering;
3. requirement memory should preserve temporal provenance;
4. material ambiguity that affects the current update and cannot be resolved from visible evidence should trigger clarification;
5. requirement reasoning should be frozen before repository execution so code cannot leak the state-reconstruction answer.

**Limitations.**

ReqMemBench studies requirement-state reconstruction in freelance software projects, which differ from enterprise development in team structure, documentation practices, governance, safety constraints, and code-review processes. The source projects and client–freelancer interactions are real, but the released conversations are rewritten for privacy and include a subset of role-played messages. Some code environments are reconstructed from project artifacts and the annotated Requirement State rather than recovered as exact historical snapshots. Privacy transformation and reconstruction make controlled release possible, but they can remove linguistic or environmental cues that were present in the original collaboration. The benchmark therefore supports conclusions about the released takeover setting, not an unqualified reproduction of every original project interaction.

The benchmark evaluates an agent that enters after a project history has already been recorded. It tests reading, selecting, and reconciling that history, but does not test how a continuously operating agent decides what to store from the beginning of a project. The conversation is also the principal source of requirement evidence. Requirements expressed only in unavailable issue trackers, meetings, code review, or external documents may be missing, so the benchmark does not yet represent a complete multi-source organizational memory.

Temporal Requirement State annotation necessarily involves judgment. Annotators must decide when two statements belong to the same Requirement, which fields are superseded, whether an ambiguity materially blocks the current task, and which post-task state follows from the available evidence. ReqMemBench reduces this variability through evidence links, typed fields, deterministic replay, stage-specific review, and independent adjudication for RQ3, but the resulting Gold remains an operational interpretation of the project record. Semantic alignment and free-text comparators add dependence on frozen API judges; calibration can measure this dependence but cannot remove it.

End-to-end delivery is available for a narrower subset than history reasoning. RQ4 requires a runnable pre-task environment, a deterministically observable target, reviewed hidden tests, validator calibration, and a repository-leakage audit. Projects that depend on unavailable services, subjective visual judgments, or unrecoverable historical environments can contribute to RQ1–RQ3 but not to RQ4. Executable Coverage must therefore accompany repository Success Rate. A passing validator also establishes satisfaction of the frozen acceptance criteria, not equivalence to a unique implementation, because multiple code changes may satisfy the same Requirement State.

Finally, multiple targets drawn from one project share history, Requirements, and implementation context. Treating them as independent observations would overstate the effective sample size, so cross-project conclusions use project-level aggregation and report per-project variation. Sparse Gold-CLARIFY cases or empty Short and Medium history strata may further limit class-conditional and difficulty-specific claims. These limitations define where the benchmark provides evidence and where broader conclusions require additional projects, evidence sources, and execution environments.

## 7. Conclusion

Coding agents that enter an ongoing project must recover more than the intent of the latest request. They must determine which historical Requirements still govern the project, how those Requirements have changed, and whether the available evidence supports implementation or requires clarification. Existing coding benchmarks primarily score completion of a supplied task, while long-term-memory evaluations primarily score access to past information. Neither target directly captures the temporal Requirement State that connects project history to the action an agent should take now.

ReqMemBench makes this state explicit. It reconstructs evidence-linked Requirement Events and temporal State Graphs from longitudinal freelance projects, then evaluates takeover at intermediate target times. Its two-phase protocol separates selection of affected historical Requirements, reconstruction of their pre-task states, construction of a post-task update or clarification, and delivery of eligible code changes. Full History and Oracle Relevant History isolate the effect of irrelevant and stale context, while freezing the reasoning response before repository access prevents code and test feedback from revealing the history-reasoning answer.

> **TODO after formal evaluation:** Add one compact paragraph stating the one or two principal RQ1–RQ4 findings, with the decisive values and uncertainty. End with the supported form of the central conclusion: persistent coding agents need both software-engineering capability and an accurate account of what the project requires now.

## AI Use Statement

> **TODO:** Complete according to the current ICLR 2027 author policy. Disclose generative-AI use in research ideation, data processing, annotation, code, experiments, writing, or editing; explain human verification and responsibility. Verify the official policy at submission time.

## Ethics Statement

> **TODO:** Describe data authorization, Terms-of-Service or contractual constraints, privacy and de-identification, handling of credentials and sensitive content, role-play/simulation, release scope, re-identification risk, potential harms, and safeguards. Distinguish source-data access from what will be publicly released.

## Reproducibility Statement

> **TODO:** Point to sections, appendices, code, configuration, prompts, schemas, dataset cards, and supplementary artifacts covering project selection, provenance, PII processing, annotation, event replay, target selection, instance materialization, model configurations, metrics, judge calibration, validator calibration, and statistics.

## Appendix plan

The appendix should contain:

1. complete requirement-state schema and field definitions;
2. event taxonomy and state-transition rules;
3. project selection, provenance categories, authorization, privacy, and de-identification;
4. annotation guidelines, review interfaces, and agreement analysis;
5. target-time selection and leakage controls;
6. expanded RQ1–RQ4 task definitions and examples; complete prompts, public response schemas, and hidden scoring contracts;
7. model, agent, tool, budget, and retry configurations;
8. full metric equations, field-level comparators, branch-specific denominators, aggregation, uncertainty, and statistical tests;
9. judge and validator calibration, baselines, and human ceiling;
10. full benchmark distributions and eligibility counts;
11. full per-RQ result tables and results by project, event, condition, model, and history characteristic;
12. failure cases and qualitative examples;
13. one end-to-end example from source evidence to events, state graph, target-local pre/post states, frozen Phase A output, score, and validated repository delivery;
14. a data card and release statement explaining which artifacts can and cannot be shared.

## Reference backlog

The current bibliography is a template placeholder and contains unrelated references. The paper currently names or plans to discuss HumanEval, MBPP, CrossCodeEval, RepoBench, SWE-bench, BigCodeBench, SWE-Lancer, LongMemEval, ConvCodeWorld, SWE-Bench-CL, SWE-ContextBench, SR-Eval, RECODE-H, LoCoEval, and RigorBench. Every title, version, venue/year, task description, and comparison-table cell must be verified against the primary paper or official benchmark documentation before citation.
