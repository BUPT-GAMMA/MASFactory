"""Merge disjoint shards, or explicitly combine an earlier head with a rerun tail."""
import argparse
import json
from pathlib import Path


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, nargs="+", help="Disjoint shard result files")
    parser.add_argument("--head", type=Path, help="Earlier run containing the head")
    parser.add_argument("--tail", type=Path, help="Rerun containing the tail")
    parser.add_argument("--split-index", type=int, help="Number of dataset IDs taken from head")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = load(args.data)
    ids = list(data)
    if args.output.exists():
        parser.error("Output already exists; choose a new filename")
    if args.inputs:
        if args.head or args.tail or args.split_index is not None:
            parser.error("Use --inputs OR --head/--tail/--split-index")
        merged = {}
        for path in args.inputs:
            part = load(path)
            duplicates = set(merged) & set(part)
            if duplicates:
                parser.error(f"Overlapping shard IDs: {sorted(duplicates)[:5]}")
            merged.update(part)
    else:
        if not args.head or not args.tail or args.split_index is None:
            parser.error("Provide --inputs or all of --head, --tail, --split-index")
        if not 0 <= args.split_index <= len(ids):
            parser.error("split-index must be within the dataset")
        head, tail = load(args.head), load(args.tail)
        missing = [k for i, k in enumerate(ids)
                   if k not in (head if i < args.split_index else tail)]
        if missing:
            parser.error(f"Missing head/tail records: {missing[:5]}")
        merged = {k: (head if i < args.split_index else tail)[k]
                  for i, k in enumerate(ids)}
    for claim_id, row in merged.items():
        if claim_id not in data or row.get("correct_answer") != data[claim_id]["labels"]:
            parser.error(f"ID or gold label mismatch: {claim_id}")
    # Selection is solely by shard membership or dataset position, never by accuracy.
    merged = {k: merged[k] for k in ids if k in merged}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(merged)}/{len(ids)} records to {args.output}")
    if len(merged) != len(ids):
        print("Incomplete coverage; this is not a full-dataset result.")


if __name__ == "__main__":
    main()
