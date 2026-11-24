# Task: tune Config thresholds on data

Precondition: the evaluation harness (04) exists with a dev and a test split. Never look at test metrics while tuning.

1. Grid-search on dev: `min_words`, `min_words_with_context`, `min_candidate_words`, `max_gap`, `min_altered_matched`, `min_altered_ratio`, `frequent_bigram`, plus the formulaic phrase list (propose additions with evidence, i.e. phrases that caused false `verified` on hard negatives).
2. Objective: maximize recall of true quotes **subject to** the 95% upper bound on `verified` error rate ≤ 1%. Report the Pareto frontier, not just one point.
3. Write the chosen values into `HIGH_PRECISION` and `BALANCED`, run test once, and report dev and test metrics side by side.
4. Add a regression test that loads the frozen presets and asserts the dev metrics stay above the floor recorded today (stored in `evaluation/baselines.json`).
