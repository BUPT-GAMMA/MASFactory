# DMAD_MAS — Reproducing DMAD with masfactory

This project reproduces the paper **[ICLR 2025] Breaking Mental Set to Improve Reasoning through Diverse Multi-Agent Debate**
using the [masfactory](https://github.com/BUPT-GAMMA/MASFactory) multi-agent framework.

## Paper & Repository

- **Paper**: [[ICLR 2025] Breaking Mental Set to Improve Reasoning through Diverse Multi-Agent Debate](https://openreview.net/forum?id=t6QHYUOQL7&referrer=%5BAuthor%20Console%5D%28%2Fgroup%3Fid%3DICLR.cc%2F2025%2FConference%2FAuthors%23your-submissions%29)
- **Original Repository**: https://github.com/MraDonkey/DMAD
- **Framework**: masfactory

## Project Structure

```
DMAD_MAS/
├── main.py                  # Entry point (dataset loading + graph invocation + saving)
├── graph.py                 # Graph definitions (PromptBuilder, Agents, LoopD, AnswerCollector)
├── prompts.py               # Agent instructions for ScienceQA and mm-vet
├── model.py                 # OpenAI model configuration (reads from .env)
├── record.py                # Answer extraction, majority voting, accuracy, mm-vet eval export
├── collect_dataset.py       # Image downloader for ScienceQA
├── mm-vet_evaluator.py      # GPT-based mm-vet scoring evaluator
└── requirements.txt         # Python dependencies
```

## Environment

- Python >= 3.10
- Install: `pip install -r requirements.txt`
- Configure `.env`:
  ```
  OPENAI_API_KEY
  OPENAI_BASE_URL
  OPENAI_MODEL_NAME
  ```

## How to Run

### ScienceQA

```powershell
# Generate answers (one question per run)
python main.py

# Evaluate
python -c "from record import calculate_consistency_acc; calculate_consistency_acc(dataset='ScienceQA', reasoning='DMAD')"
```

### mm-vet

```powershell
# Generate answers
python main.py --dataset mm-vet --num_items <N>

# Convert to evaluation format
python -c "from record import align_mmvet; align_mmvet(reasoning='io')"
python -c "from record import align_mmvet; align_mmvet(reasoning='ccot')"
python -c "from record import align_mmvet; align_mmvet(reasoning='ddcot')"
python -c "from record import align_mmvet; align_mmvet(reasoning='DMAD')"

# GPT scoring (3-run average)
python mm-vet_evaluator.py --result_file answer/mm-vet/mm-vet_eval/DMAD_round_0.json --num_run 3
python mm-vet_evaluator.py --result_file answer/mm-vet/mm-vet_eval/DMAD_round_1.json --num_run 3
python mm-vet_evaluator.py --result_file answer/mm-vet/mm-vet_eval/DMAD_round_2.json --num_run 3
```

## Output

### ScienceQA

| File | Description |
|------|-------------|
| `answer/ScienceQA/ScienceQA_test_DMAD_results.json` | Full 3-round debate results |
| `answer/ScienceQA/ScienceQA-io.json` | IO strategy answers per round |
| `answer/ScienceQA/ScienceQA-ccot.json` | CCoT strategy answers per round |
| `answer/ScienceQA/ScienceQA-ddcot.json` | DDCOT strategy answers per round |
| `answer/ScienceQA/ScienceQA-DMAD-Accuracy.json` | Per-round accuracy |

### mm-vet

| File | Description |
|------|-------------|
| `answer/mm-vet/mm-vet_DMAD_results.json` | Full 3-round debate results |
| `answer/mm-vet/mm-vet-{io,ccot,ddcot}.json` | Per-strategy answers |
| `answer/mm-vet/mm-vet_eval/{io,ccot,ddcot,DMAD_round_*}.json` | Eval-format outputs |
| `answer/mm-vet/mm-vet_eval/*cap-score-*.csv` | Per-capability scores |

## Results

### ScienceQA — DMAD Accuracy (gpt-4o-mini)

| Round | Our Accuracy | Original Accuracy |
|-------|-------------|----------------|
| Round 0  | 80% | 78% |
| Round 1 | 83% | 82% |
| Round 2 | 82% | 82% |

### mm-vet — DMAD Score (gpt-4o-mini, 3-run GPT judge)

| Round | Our Score | Original Score |
|-------|-------------|----------------|
| Round 0  | 69.4 | 58.3 |
| Round 1 | 67.1 | 56.0 |
| Round 2 | 76.2 | 62.1 |


