"""Run both preprocessing stages from a separately downloaded author repository."""
import argparse
import json
import runpy
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--author-code", type=Path, required=True, help="Root of collaboration_MAS")
    parser.add_argument("--input", type=Path, required=True, help="AmbiFC test.certain.jsonl")
    parser.add_argument("--output", type=Path, required=True, help="New processed JSON file")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new filename")
    source = args.author_code / "fact_code/filter_claim_data.py"
    # Loads function definitions; the author's __main__ block is not executed.
    author = runpy.run_path(str(source), run_name="author_preprocessing")
    raw = author["load_jsonl"](str(args.input))
    first_stage = author["filter_claim_data"](raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Keep the temporary stage beside the requested output, not on a fixed drive.
    with tempfile.NamedTemporaryFile(prefix="stage_one_", suffix=".json",
                                     dir=args.output.parent, delete=False) as file:
        intermediate = Path(file.name)
    try:
        author["save_json"](first_stage, str(intermediate))
        author["process_filtered_data"](str(intermediate), str(args.output))
    finally:
        intermediate.unlink()
    processed = json.loads(args.output.read_text(encoding="utf-8"))
    print(f"Raw: {len(raw)}; stage one: {len(first_stage)}; processed: {len(processed)}")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
