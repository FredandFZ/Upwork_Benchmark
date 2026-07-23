# Agent Benchmark Data Analysis Report

> Basic data check + first-pass metric analysis
>
> About the data: This Excel file is not just one table. It is an agent benchmark/evaluation database. The core idea is:
> **Upwork-style tasks → three agents try to finish them → an evaluator scores each try over several turns → failed tries move to the next round for edits and re-scoring.**

---

## 1. Overall Data Structure

The workbook has these main sheets:

| Sheet                               | Main content                                              | Valid records |
| ----------------------------------- | --------------------------------------------------------- | ------------: |
| `jobs`                              | Raw task info: title, description, category, budget, attachments, acceptance criteria | 145 jobs      |
| `agent_traces`                      | Agent turn 0 submissions and evaluation JSON              | 312 rows      |
| `evals_turn0`                       | Round 0 evaluation results                                | 312 rows      |
| `evals_turn1`                       | Round 1 evaluation results                                | 186 rows      |
| `evals_turn2`                       | Round 2 evaluation results                                | 111 rows      |
| `job_status`                        | Status changes for each job-agent-evaluator-thread        | 2142 rows     |
| `assignments` / `turn1_assignments` | Evaluator assignments                                     | 145 job IDs   |
| `M5_submission_fails`               | Failed submissions / Drive file issues                    | 66 rows       |
| `slack_evals`                       | Eval file status on the Slack/Drive side                  | 70 rows       |
| `Stats`                             | Summary stats page, but some formulas show `#NAME?`       |               |

One important point about the structure: `evals_turn0` has **312 rows = 104 jobs × 3 agents**. So even though `jobs` defines 145 tasks, only **104 jobs** actually went through the full agent evaluation chain. The other **41 jobs** do not appear in the main eval/traces data.

---

## 2. Basic Facts About the `jobs` Data

This set of tasks is very focused:

| Dimension            | Result                                          |
| -------------------- | ----------------------------------------------- |
| Total jobs           | 145                                             |
| Top category         | All are `Web, Mobile & Software Dev`            |
| Main subcategory     | 138 Web Development, 7 Web & Mobile Design      |
| Main sub-types       | Front-End 64, Full Stack 52, Back-End 22        |

The budget `job_amount` is skewed:

| Metric  | Value  |
| ------- | -----: |
| Minimum | 5      |
| Median  | 50     |
| Average | 203.92 |
| Maximum | 3000   |

The average is much higher than the median. This means a few high-budget tasks pull the average up. By budget range:

| Budget range | Jobs |
| ------------ | ---: |
| ≤ $25        | 40   |
| $26–50       | 34   |
| $51–100      | 26   |
| $101–200     | 18   |
| > $200       | 27   |

The acceptance criteria for each job are fairly complete. On average each task has about **5.98 criteria**, of which about **5.46 are critical**. There are few optional criteria.

---

## 3. Agent Coverage

`agent_traces` has 312 valid records in total:

| Agent     | Records |
| --------- | ------: |
| anthropic | 104     |
| google    | 104     |
| openai    | 104     |

This shows that all 104 jobs were handled once by each of the three agents.

The `job_status` values in `agent_traces` break down like this:

| Status         | Count |
| -------------- | ----: |
| `up:InReview`  | 132   |
| `up:Reviewed`  | 95    |
| `up:Success`   | 85    |

This table looks more like a record of agent submissions and early scoring. The real pass/fail results come mainly from `evals_turn0/1/2`.

---

## 4. Three Rounds of Scoring: turn0 → turn1 → turn2

### Looking at each round on its own

| Round  | Eval records | Pass | Fail | Round pass rate | Avg total_score |
| ------ | -----------: | ---: | ---: | --------------: | --------------: |
| Turn 0 | 312          | 126  | 186  | 40.38%          | 0.7065          |
| Turn 1 | 186          | 75   | 111  | 40.32%          | 0.7147          |
| Turn 2 | 111          | 48   | 63   | 43.24%          | 0.7353          |

Note this: **the 186 rows in Turn 1 basically match the 186 failed rows from Turn 0. The 111 rows in Turn 2 basically match the 111 failed rows from Turn 1.**
So the process does not re-score all 312 attempts each round. Instead:

> Turn 0 scores everything → failed ones go to Turn 1 → still-failing ones go to Turn 2.

Because of this, the round pass rate is not the overall system success rate. It should be read as "the share of the previous round's failures that were fixed and passed in this round."

---

## 5. The Cumulative Success Rate Is More Useful

If we add up all three rounds:

| Metric                  | Value      |
| ----------------------- | ---------: |
| Total initial attempts  | 312        |
| Passed in Turn 0        | 126        |
| Newly passed in Turn 1  | 75         |
| Newly passed in Turn 2  | 48         |
| Cumulative passes       | 249        |
| Cumulative success rate | **79.81%** |
| Still failing / not done | 63        |

This result tells us:
**The agents pass only about 40% on the first try, but after several rounds of feedback and edits, the cumulative success rate rises to about 80%.**

This is a key finding in this data.

---

## 6. How the Different Agents Performed

### Initial Turn 0 performance

| Agent     | Turn 0 records | Passes | Pass rate | Avg total_score |
| --------- | -------------: | -----: | --------: | --------------: |
| anthropic | 104            | 51     | 49.0%     | 0.755           |
| openai    | 104            | 44     | 42.3%     | 0.740           |
| google    | 104            | 30     | 28.8%     | 0.624           |

In Turn 0, `anthropic` had the highest first-try pass rate, and `google` was clearly the lowest.

### Cumulative performance over three rounds

| Agent     | Initial tasks | Cumulative passes | Cumulative rate | Avg score |
| --------- | ------------: | ----------------: | --------------: | --------: |
| anthropic | 104           | 88                | **84.6%**       | 0.7487    |
| openai    | 104           | 86                | **82.7%**       | 0.7435    |
| google    | 104           | 75                | **72.1%**       | 0.6596    |

The cumulative view shows the same order:

> anthropic ≈ openai > google

`google` is low on both its first-try and cumulative results. As a next step, we can focus on which criteria it fails, which task types, and whether the failures cluster in front-end, full-stack, or back-end tasks.

---

## 7. Final Pass Results, Seen From the Job Side

Of the 104 jobs that entered evaluation, each has 3 agent attempts. If we count "how many agents finally passed each job":

| Agents that finally passed a job | Jobs |
| -------------------------------- | ---: |
| All 3 agents passed              | 66   |
| 2 agents passed                  | 22   |
| 1 agent passed                   | 7    |
| 0 agents passed                  | 9    |

So most tasks are finished by at least 2 agents in the end. But **9 jobs were not passed by any of the three agents**. These may be hard tasks, tasks with unclear requirements, or tasks with very strict acceptance criteria. They are worth pulling out for a separate case study.

---

## 8. Success Rate by Task Type

A rough look at the final cumulative results:

| Sub-type               | Attempts | Final success rate | Initial avg score |
| ---------------------- | -------: | -----------------: | ----------------: |
| Full Stack Development | 105      | 84.8%              | 0.707             |
| Back-End Development   | 54       | 81.5%              | 0.745             |
| Front-End Development  | 141      | 74.5%              | 0.683             |
| Prototyping            | 6        | 83.3%              | 0.738             |

The interesting part here is: **Front-End Development has the most attempts, but a relatively lower final success rate**. This may mean that front-end tasks look simple, but their acceptance often depends on UI details, matching interactions, responsive layout, and visual consistency. They fail easily when a small detail is not met.

---

## 9. Data Quality Issues / Things to Watch

Here are a few things I noticed early on that need attention:

1. The `Stats` summary page has many formulas showing `#NAME?`. So it is best not to rely fully on the Stats page. Recompute from the raw eval tables instead.

2. `jobs` has 145 tasks, but `evals_turn0`/`agent_traces` only have 104 jobs. So the current full-evaluation coverage is not 100%.

3. One record in `evals_turn0` has a `turn` field that looks like it was written as 2, even though it sits in the `evals_turn0` sheet. This is a small data consistency issue that needs cleaning before precise analysis.

4. `completed_at` is almost always empty in `evals_turn0/1/2`. So for now we cannot do strict time-series analysis, such as "time spent per round" or "delay from submission to scoring."

5. `assignments` has 145 job IDs, but some have no evaluator name. Looking only at records that have an evaluator, about 107 jobs were assigned to an evaluator.

---

## 10. First Conclusions

The core value of this data is analyzing **how well agents can fix their work over several rounds on real development tasks**. In a single round, the agents' first-try pass rate is not high, only about **40.4%** overall. But after feedback and fixes in turn 1 and turn 2, the cumulative success rate rises to **79.8%**. This shows that the multi-round feedback loop is very important for helping agents finish tasks.

Comparing agents, `anthropic` and `openai` are close, with `anthropic` slightly ahead. `google` is lower on first-try pass rate, cumulative pass rate, and average score.
By task type, front-end tasks are the most common, but their final success rate is lower than full-stack and back-end tasks. As a next step, we can focus on whether front-end failures cluster in UI matching, interaction behavior, responsive layout, or acceptance criteria details.

The next step can go deeper in three directions: **agent comparison analysis, failure reason / criteria analysis, and repair-path analysis across turn0 → turn1 → turn2.**
