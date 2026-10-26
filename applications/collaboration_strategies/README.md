# Collaboration Strategies with MASFactory

[中文说明](README.zh-CN.md)

MASFactory implementations of nine collaboration strategies from **Beyond
Frameworks: Unpacking Collaboration Strategies in Multi-Agent Systems**
(Wang et al., ACL 2025).

- [Paper](https://aclanthology.org/2025.acl-long.1037/)
- [Authors' implementation](https://github.com/s65b40/collaboration_MAS)
- [AmbiFC dataset](https://github.com/CambridgeNLIP/verification-real-world-info-needs)

This application covers AmbiFC claim verification, not the MIMIC-III experiments.
The recorded comparisons use `gpt-4o-mini` on both sides; they are comparisons
against the author baseline under that model setting, not a reproduction of
the paper's published scores with its original model configuration.

## Layout

```text
collaboration_strategies/
├── README.md
├── README.zh-CN.md
├── .gitignore
├── prepare_data.py
├── compare_results.py
├── merge_results.py
└── workflows/
    ├── g1_p1_i1_c1.py
    ├── g1_p1_i1_c2.py
    ├── g1_p1_i2_c1.py
    ├── g1_p1_i2_c2.py
    ├── g1_p1_i3_c1.py
    ├── g1_p1_i3_c2.py
    ├── g1_p2_i4_c2.py
    ├── g2_p3_i1_c3.py
    └── g2_p3_i2_c3.py
```

Each strategy keeps its prompts, formatter, graph builder and execution loop in
one script. No dataset, result JSON, diagnostic script, or original-author
repository copy is bundled. `merge_results.py` preserves the necessary rerun
assembly operations without shipping duplicate shard scripts.

## Workflow design

Each claim gets a new `RootGraph`; a `Loop` manages at most ten rounds.
`CustomNode` stages invoke `Agent.step()` and pass the discussion state onward.
Individual agents are called inside these stages rather than represented as
separate graph vertices.

| Family | Per-round stages |
|---|---|
| G1-P1 | Speak → collect judgments → update history/summary as appropriate |
| G1-P2-I4-C2 | Communicate → judge → collect → update summaries |
| G2-P3 | Speak → instructor decision → summary and next-speaker selection |

I1 judgments are simultaneous; I2 judgments follow agent-number order; I3
reshuffles speakers each round. I4 agents choose persuasion recipients; only
recipients rejudge after the first round. C1 retains recent conversation records;
C2 maintains individual summaries; C3 uses instructor-generated summaries.

G1 stops on unanimity, or chooses the highest-count label after ten rounds.
Tie-breaking follows each workflow's ordering. G2 uses the instructor's answer,
without adding a majority-vote fallback. An undecided G2 run may return an empty
prediction and `rounds=0`; `actual_rounds` separately records executed rounds.

## Setup

From the MASFactory repository root, install the local framework:

```bash
python -m pip install -e .
```

The local offline checks used MASFactory 1.0.4. Compatibility with other framework
revisions should be checked when integrating this application.

Set credentials and the API base URL. PowerShell:

```powershell
$env:OPENAI_API_KEY = "<your-api-key>"
$env:OPENAI_BASE_URL = "<your-api-base-url>"
```

Bash:

```bash
export OPENAI_API_KEY="<your-api-key>"
export OPENAI_BASE_URL="<your-api-base-url>"
```

The base URL is the API root expected by the OpenAI-compatible client, not a
complete `/chat/completions` URL. Credentials are never written into the scripts.

## Prepare data

Download AmbiFC from its upstream repository and locate `test.certain.jsonl`.
Download the authors' code separately:

```bash
git clone https://github.com/s65b40/collaboration_MAS.git ../collaboration_MAS
python applications/collaboration_strategies/prepare_data.py --author-code ../collaboration_MAS --input /path/to/test.certain.jsonl --output /path/to/filtered_test_certain_new.json
```

`prepare_data.py` loads `fact_code/filter_claim_data.py` without executing its
main block and calls both processing stages. It refuses to overwrite an existing
output. The author checkout is an external prerequisite for this utility only;
the workflows do not import it.

1. Keep sentences whose annotations agree and retain claims with differing
   sentence labels.
2. Remove empty sentences, group sentences matching the passage label first,
   then keep up to six sentences, filling remaining slots from the other group.

This ordering is preserved even for claims with at most six sentences; it affects
ordered discussion. The recorded dataset contains 501 claims (409 supporting,
92 refuting) and one to six agents per claim. Predictions can still be supporting,
neutral or refuting. Gold labels affect the authors' preprocessing and evaluation,
but are not supplied in model prompts. Output is a JSON object keyed by claim ID,
not JSONL.

## Run

All commands below run from the MASFactory repository root. Replace `/path/to/...`
with your own paths; quote paths containing spaces.

One claim:

```bash
python -B -X utf8 applications/collaboration_strategies/workflows/g1_p1_i1_c1.py --data /path/to/filtered_test_certain_new.json --limit 1 --output-dir /path/to/results
```

Full dataset: use `--limit 0`. Other strategies use the corresponding filename.
Each completed claim is saved to a timestamped JSON via a temporary file and
replacement. A run does not execute different claims concurrently; parallelism
is within the workflow's parallel stages.

Resume:

```bash
python -B -X utf8 applications/collaboration_strategies/workflows/g1_p1_i1_c1.py --data /path/to/filtered_test_certain_new.json --limit 0 --resume /path/to/previous_result.json
```

Resume skips **all saved IDs**, including saved invalid/empty predictions. A failed
claim with the default `--on-error stop` is not saved and starts from round one
on resumption. `--on-error record` instead saves an empty prediction with an error
reason and continues. No automatic score-based selection or retry of wrong answers
is performed. Use the same strategy, dataset and model settings when resuming.
Do not run two processes writing the same result file.

| Option | Meaning / default |
|---|---|
| `--data` | Required processed dataset path |
| `--limit` | First N selected claims, 0 = all |
| `--start-index` | Zero-based offset before applying the limit, default 0 |
| `--output-dir` | Default: this application's `results/<strategy>/` |
| `--resume` | Existing result file; otherwise a new timestamped file |
| `--model` | `gpt-4o-mini` |
| `--timeout` | 60 seconds |
| `--sdk-retries` | 1,000,000, retaining the previous scripts' large finite limit |
| `--invoke-attempts` | 3 MASFactory adapter attempts, including the first |
| `--agent-workers` | Python thread-pool default; only affects parallel stages |
| `--on-error` | `stop` or `record`, default `stop` |

There are three retry layers: OpenAI SDK, MASFactory model adapter, and Agent
execution/formatting. `--sdk-retries 0` alone does not disable adapter retries.
`--sdk-retries 0 --invoke-attempts 1` disables the first two layers' additional
attempts. Agent attempts remain 1 except for judgment agents in G2-P3-I2-C3,
which retain 3; its instructor remains at 1. The large historical SDK default can
wait a long time during an outage; choose an explicit smaller value if desired.

## I2-C1 / I3-C1 rerun settings

The relevant rerun behavior is exposed in the packaged scripts, rather than
depending on local diagnostic files. Only I2-C1 and I3-C1 support these options:

- `--loose-parse`: keep malformed judgment text as a vote instead of rejecting it.
- `--author-errors`: convert an exhausted model invocation exception to the
  author's fixed error response. It does not itself disable retries or validation.

I2-C1 rerun request/parser settings:

```bash
python -B -X utf8 applications/collaboration_strategies/workflows/g1_p1_i2_c1.py --data /path/to/filtered_test_certain_new.json --limit 0 --timeout 180 --sdk-retries 0 --invoke-attempts 3 --loose-parse --author-errors --output-dir /path/to/i2_rerun
```

The archived I2 runner skipped graph failures without saving them; the packaged
default stops on such failures, allowing resumption after diagnosis. Successful
discussion logic is unchanged. The historical adapter retained its own retries;
this must not be described as identical request failure handling to the author.

I3-C1 tail rerun settings (dataset positions 321–501):

```bash
python -B -X utf8 applications/collaboration_strategies/workflows/g1_p1_i3_c1.py --data /path/to/filtered_test_certain_new.json --start-index 320 --limit 0 --sdk-retries 0 --invoke-attempts 1 --loose-parse --on-error record --output-dir /path/to/i3_tail
```

This preserves the tail runner's distinction: malformed responses may become
votes, while request exceptions abort the claim and produce an empty final label.
The retry change is a recorded experimental setting, not a proven explanation
of the earlier accuracy discrepancy. I3 order is random; identical future outputs
are not guaranteed.

Each new result record includes non-secret `run_settings`. The historical table
below predates this packaging and is not the output of a new uniform-config run.

## Merge and compare

Merge disjoint shards (duplicate IDs are rejected):

```bash
python applications/collaboration_strategies/merge_results.py --data /path/to/filtered_test_certain_new.json --inputs /path/to/shard0.json /path/to/shard1.json --output /path/to/merged.json
```

Combine an earlier head with a rerun tail by dataset position, once per role:

```bash
python applications/collaboration_strategies/merge_results.py --data /path/to/filtered_test_certain_new.json --head /path/to/earlier.json --tail /path/to/tail.json --split-index 320 --output /path/to/combined.json
```

Merging preserves records without selecting by prediction correctness. The head/tail
mode requires complete coverage; shard mode explicitly reports incomplete coverage.
Both modes refuse to overwrite an existing file.

```bash
python applications/collaboration_strategies/compare_results.py --data /path/to/filtered_test_certain_new.json --author /path/to/author.json --mas /path/to/mas.json --output-dir /path/to/comparison
```

The comparison validates IDs and gold labels, evaluates common IDs, reports missing
IDs and writes `summary.json`, `summary.csv`, `all_samples.json` and
`different_predictions.json`. Repeating a comparison in the same output directory
updates its reports. Labels are normalized for case, whitespace and surrounding
Markdown asterisks, then matched exactly. Invalid/empty labels count as wrong.
Partial coverage is not a full-dataset score. No model requests are made by these
utilities.

## Recorded results

Each row contains 501 paired records. Values are percentages; delta is MASFactory
accuracy minus author accuracy in percentage points. These are descriptive results,
not proof of statistical equivalence.

| Strategy | Author | MASFactory | Delta (pp) | Agreement |
|---|---:|---:|---:|---:|
| G1-P1-I1-C1 | 18.56 | 17.37 | -1.20 | 89.02 |
| G1-P1-I1-C2 | 65.67 | 67.27 | +1.60 | 88.02 |
| G1-P1-I2-C1 | 75.05 | 73.05 | -2.00 | 85.43 |
| G1-P1-I2-C2 | 65.07 | 65.47 | +0.40 | 85.03 |
| G1-P1-I3-C1 | 36.33 | 36.73 | +0.40 | 81.24 |
| G1-P1-I3-C2 | 74.65 | 68.46 | -6.19 | 82.44 |
| G1-P2-I4-C2 | 83.23 | 87.62 | +4.39 | 89.82 |
| G2-P3-I1-C3 | 89.02 | 88.62 | -0.40 | 92.02 |
| G2-P3-I2-C3 | 84.23 | 90.02 | +5.79 | 87.23 |

### Provenance and limitations

- I2-C1: eight shards per role, assembled into result files timestamped
  `20261025_150412`. The full-run launcher reused 100 completed records from an
  earlier partial run and filled the rest; this was not necessarily one continuous
  fresh execution of all 501 claims.
- I3-C1: first 320 records from the earlier author/MAS files, plus 181 records per
  role from reruns; also assembled as `20261025_150412`. API credentials or
  endpoint/channel settings changed during the experimental process. Do not treat
  this as a single unchanged-environment run.
- Other selected author/MAS timestamps respectively: I1-C1 `20261019_225822` /
  `20261020_162919`; I1-C2 `20261020_165540` / `20261021_111517`; I2-C2
  `20261021_174650` / `20261021_175053`; I3-C2 `20261022_105248` /
  `20261022_105856`; I4-C2 `20261022_155656` / `20261022_232629`; G2-I1-C3
  `20261022_232230` / `20261022_232728`; G2-I2-C3 `20261022_232348` /
  `20261022_232735`. These refer to local `author_<strategy>_<timestamp>.json`
  and `mas_<strategy>_<timestamp>.json` artifacts, which are not distributed here.
- Invalid final labels remain in the denominator: 13 author I1-C2 records,
  nine MAS I3-C1 records, and three author plus two MAS G2-I2-C3 records.
- G2 baselines fix two upstream call errors: pass the summary as `message` and
  the integer round as `current_round` to `update_history`; additionally pass the
  missing `current_round` to G2-I2's sequential speaking function. Both sides use
  these corrected semantics. The baseline is not the untouched upstream version.
- The author's API wrapper may return failures as ordinary response text; default
  MAS scripts validate judgment labels and raise. Historical retries differed.
  Valid final labels cannot establish that all intermediate calls succeeded.
- Token counts use `tiktoken` on user prompt and response text, including summaries
  and instructor calls. They are not provider billing usage. SDK-internal failures,
  unsaved work and overwritten attempts may be absent; even a saved failed claim's
  counters need not account for every attempted request.
- G2 can return empty answers with `rounds=0` despite executing discussion rounds.
  Agreement counts equal normalized text, not just valid predictions.

## Citation

```bibtex
@inproceedings{wang-etal-2025-beyond,
    title = "Beyond Frameworks: Unpacking Collaboration Strategies in Multi-Agent Systems",
    author = "Wang, Haochun and Zhao, Sendong and Wang, Jingbo and Qiang, Zewen and Qin, Bing and Liu, Ting",
    booktitle = "Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)",
    year = "2025",
    publisher = "Association for Computational Linguistics",
    pages = "21361--21375",
    url = "https://aclanthology.org/2025.acl-long.1037/",
    doi = "10.18653/v1/2025.acl-long.1037"
}
```
