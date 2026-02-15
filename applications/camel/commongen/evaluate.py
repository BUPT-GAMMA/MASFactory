"""Evaluate CommonGen generation results."""

import os
import sys
import json
import argparse
import re
from pathlib import Path
from typing import List, Dict

# Python 2 to Python 3 compatibility fixes
def fix_python2_syntax(file_path):
    """Fix Python 2 syntax to be Python 3 compatible."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Fix xrange -> range
        content = re.sub(r'\bxrange\b', 'range', content)
        
        # Fix .iteritems() -> .items()
        content = re.sub(r'\.iteritems\(\)', '.items()', content)
        
        # Fix tuple unpacking in function parameters: def func(x, (a, b)) -> def func(x, tuple_arg)
        # This is a more complex fix, need to find function definition and fix calls
        # For cook_test function in bleu_scorer.py
        if 'bleu_scorer.py' in str(file_path):
            # Fix function definition
            content = re.sub(
                r'def cook_test\(test, \(reflen, refmaxcounts\), eff=None, n=4\):',
                'def cook_test(test, ref_tuple, eff=None, n=4):\n    reflen, refmaxcounts = ref_tuple',
                content
            )
        
        # Write fixed content to temporary file or execute directly
        return content
    except Exception as e:
        print(f"Warning: Cannot fix file {file_path}: {e}")
        return None

# Add CommonGen evaluation script path
# Try multiple possible paths
possible_paths = [
    Path(__file__).parent.parent.parent.parent.parent / "datasets" / "CommonGen-master" / "CommonGen-master" / "evaluation" / "Traditional" / "eval_metrics",
    Path(__file__).parent.parent.parent.parent.parent.parent / "datasets" / "CommonGen-master" / "CommonGen-master" / "evaluation" / "Traditional" / "eval_metrics",
]

commongen_eval_path = None
for path in possible_paths:
    if path.exists():
        commongen_eval_path = path
        break

if commongen_eval_path:
    # Add eval_metrics directory to path
    sys.path.insert(0, str(commongen_eval_path))
    # Also add each subdirectory to path (for relative imports)
    for subdir in ['bleu', 'meteor', 'rouge', 'cider', 'spice']:
        subdir_path = commongen_eval_path / subdir
        if subdir_path.exists():
            sys.path.insert(0, str(subdir_path))
    
    # Fix Python 2 syntax files that need fixing
    import types
    
    # Fix bleu_scorer.py
    bleu_scorer_path = commongen_eval_path / "bleu" / "bleu_scorer.py"
    if bleu_scorer_path.exists():
        try:
            fixed_content = fix_python2_syntax(bleu_scorer_path)
            if fixed_content:
                code = compile(fixed_content, str(bleu_scorer_path), 'exec')
                module = types.ModuleType("bleu_scorer")
                exec(code, module.__dict__)
                sys.modules['bleu_scorer'] = module
        except Exception as e:
            print(f"Warning: Cannot fix bleu_scorer.py: {e}")
    
    # Fix cider_scorer.py
    cider_scorer_path = commongen_eval_path / "cider" / "cider_scorer.py"
    if cider_scorer_path.exists():
        try:
            fixed_content = fix_python2_syntax(cider_scorer_path)
            if fixed_content:
                code = compile(fixed_content, str(cider_scorer_path), 'exec')
                module = types.ModuleType("cider_scorer")
                exec(code, module.__dict__)
                sys.modules['cider_scorer'] = module
        except Exception as e:
            print(f"Warning: Cannot fix cider_scorer.py: {e}")
else:
    print("Warning: CommonGen evaluation script path not found")
    for path in possible_paths:
        print(f"Tried path: {path}")
    print("Please ensure CommonGen-master dataset is downloaded")


def convert_jsonl_to_txt(jsonl_file: str, txt_file: str, field: str = "generated_sentence"):
    """
    Convert JSONL result file to text file (one sentence per line).
    
    Args:
        jsonl_file: JSONL result file path.
        txt_file: Output text file path.
        field: Field name to extract (default: generated_sentence).
    """
    sentences = []
    
    with open(jsonl_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                sentence = data.get(field, "").strip()
                if sentence:
                    sentences.append(sentence)
                else:
                    # If sentence is empty, add empty line
                    sentences.append("")
    
    with open(txt_file, 'w', encoding='utf-8') as f:
        for sentence in sentences:
            f.write(sentence + '\n')
    
    print(f"Conversion complete: {len(sentences)} sentences")
    print(f"Output file: {txt_file}")
    return txt_file


def evaluate_with_commongen_metrics(
    key_file: str,
    gts_file: str,
    res_file: str,
    cs_str_file: str = None
):
    """
    Evaluate results using CommonGen official evaluation script, including all metrics.
    
    Args:
        key_file: Source file (concept list).
        gts_file: Reference sentence file.
        res_file: Generated sentence file.
        cs_str_file: Concept string file (for Coverage evaluation, optional).
    """
    global commongen_eval_path
    
    if not commongen_eval_path:
        print("Error: CommonGen evaluation script path not found")
        return None
    
    all_results = {}
    
    # 1. Traditional evaluation metrics (BLEU, METEOR, CIDEr, SPICE, ROUGE_L)
    try:
        # Try to import CommonGen evaluation modules
        # Note: Need to import from eval_metrics directory, not from subdirectories
        import importlib.util
        
        # Dynamically import each evaluation module
        bleu_module_path = commongen_eval_path / "bleu" / "bleu.py"
        spec = importlib.util.spec_from_file_location("bleu_module", bleu_module_path)
        bleu_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bleu_module)
        Bleu = bleu_module.Bleu
        
        meteor_module_path = commongen_eval_path / "meteor" / "meteor.py"
        spec = importlib.util.spec_from_file_location("meteor_module", meteor_module_path)
        meteor_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(meteor_module)
        Meteor = meteor_module.Meteor
        
        rouge_module_path = commongen_eval_path / "rouge" / "rouge.py"
        spec = importlib.util.spec_from_file_location("rouge_module", rouge_module_path)
        rouge_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rouge_module)
        Rouge = rouge_module.Rouge
        
        cider_module_path = commongen_eval_path / "cider" / "cider.py"
        spec = importlib.util.spec_from_file_location("cider_module", cider_module_path)
        cider_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cider_module)
        Cider = cider_module.Cider
        
        spice_module_path = commongen_eval_path / "spice" / "spice.py"
        spec = importlib.util.spec_from_file_location("spice_module", spice_module_path)
        spice_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(spice_module)
        Spice = spice_module.Spice
        
        import spacy  # type: ignore
        
        print("=" * 80)
        print("Using CommonGen official evaluation metrics (Traditional)")
        print("=" * 80)
        print(f"Source file: {key_file}")
        print(f"Reference file: {gts_file}")
        print(f"Result file: {res_file}")
        print()
        
        # Load spacy model
        try:
            nlp = spacy.load("en_core_web_sm", disable=['parser', 'ner'])
            # spacy 3.x no longer needs manual pipeline setup
        except OSError:
            print("Error: Need to install spacy English model")
            print("Please run: python -m spacy download en_core_web_sm")
            return None
        
        # Read files
        with open(key_file, 'r', encoding='utf-8') as f:
            key_lines = [line.strip() for line in f if line.strip()]
        
        with open(gts_file, 'r', encoding='utf-8') as f:
            gts_lines = [line.strip() for line in f if line.strip()]
        
        with open(res_file, 'r', encoding='utf-8') as f:
            res_lines = [line.strip() for line in f if line.strip()]
        
        # Build evaluation dictionary
        # Format: {key: [sentence1, sentence2, ...]}
        # For gts, can have multiple reference sentences
        # For res, each key has only one generated sentence (but needs to be wrapped in list)
        gts = {}
        res = {}
        
        for key_line, gts_line, res_line in zip(key_lines, gts_lines, res_lines):
            key = '#'.join(key_line.split())
            if key not in gts:
                gts[key] = []
            gts[key].append(gts_line)
            # res[key] should be a list containing a single sentence
            res[key] = [res_line]
        
        # Python 3 compatible tokenize function
        def tokenize_py3(dict_data):
            """Python 3 compatible tokenize function."""
            tokenized_dict = {}
            for key in dict_data:
                new_sentence_list = []
                for sentence in dict_data[key]:
                    a = ''
                    # Python 3 doesn't need unicode, use str directly
                    sentence_str = str(sentence) if not isinstance(sentence, str) else sentence
                    for token in nlp(sentence_str):
                        a += token.text
                        a += ' '
                    new_sentence_list.append(a.rstrip())
                tokenized_dict[key] = new_sentence_list
            return tokenized_dict
        
        # Tokenize
        print("Tokenization...")
        gts_tokenized = tokenize_py3(gts)
        res_tokenized = tokenize_py3(res)
        
        # Setup evaluators (consistent with official eval.py)
        print("Setting up scorers...")
        scorers = []
        
        # BLEU (always available)
        try:
            scorers.append((Bleu(4), ["Bleu_1", "Bleu_2", "Bleu_3", "Bleu_4"]))
        except Exception as e:
            print(f"Warning: Cannot initialize BLEU: {e}")
        
        # METEOR (requires Java and meteor-1.5.jar)
        try:
            scorers.append((Meteor(), "METEOR"))
        except Exception as e:
            print(f"Warning: Cannot initialize METEOR (requires Java and meteor-1.5.jar): {e}")
        
        # CIDEr (always available)
        try:
            scorers.append((Cider(), "CIDEr"))
        except Exception as e:
            print(f"Warning: Cannot initialize CIDEr: {e}")
        
        # SPICE (requires Java and spice-1.0.jar)
        try:
            scorers.append((Spice(), "SPICE"))
        except Exception as e:
            print(f"Warning: Cannot initialize SPICE (requires Java and spice-1.0.jar): {e}")
        
        # ROUGE_L (always available)
        try:
            scorers.append((Rouge(), "ROUGE_L"))
        except Exception as e:
            print(f"Warning: Cannot initialize ROUGE_L: {e}")
        
        # Calculate all available metrics
        eval_results = {}
        for scorer, method in scorers:
            print(f"Computing {scorer.method()} score...")
            try:
                score, scores = scorer.compute_score(gts_tokenized, res_tokenized)
                if isinstance(method, list):
                    for sc, m in zip(score, method):
                        eval_results[m] = sc
                        print(f"{m}: {sc:.4f}")
                else:
                    eval_results[method] = score
                    print(f"{method}: {score:.4f}")
            except Exception as e:
                print(f"Warning: {method} calculation failed: {e}")
                import traceback
                traceback.print_exc()
        
        all_results.update(eval_results)
        
    except ImportError as e:
        print(f"Error: Cannot import Traditional evaluation modules: {e}")
        print("\nPlease ensure:")
        print("1. CommonGen evaluation scripts are downloaded")
        print("2. Required dependencies are installed: pip install spacy nltk")
        print("3. spacy model is downloaded: python -m spacy download en_core_web_sm")
        print("4. get_stanford_models.sh has been run (if METEOR and SPICE are needed)")
    except Exception as e:
        print(f"Error during Traditional evaluation: {e}")
        import traceback
        traceback.print_exc()
    
    # 2. Coverage evaluation (PivotScore)
    if cs_str_file is None:
        # Try to automatically find cs_str file
        key_path = Path(key_file)
        if "dev" in key_path.name:
            cs_str_file = str(key_path.parent / "commongen.dev.cs_str.txt")
        elif "test" in key_path.name:
            cs_str_file = str(key_path.parent / "commongen.test.cs_str.txt")
        elif "train" in key_path.name:
            cs_str_file = str(key_path.parent / "commongen.train.cs_str.txt")
    
    if cs_str_file and os.path.exists(cs_str_file):
        try:
            print("\n" + "=" * 80)
            print("Calculating Coverage metric (PivotScore)")
            print("=" * 80)
            
            # Add PivotScore path
            pivotscore_path = Path(__file__).parent.parent.parent.parent.parent / "datasets" / "CommonGen-master" / "CommonGen-master" / "evaluation" / "PivotScore"
            if pivotscore_path.exists():
                sys.path.insert(0, str(pivotscore_path))
            
            import spacy  # type: ignore
            
            # Load spacy model (needs parser)
            try:
                nlp = spacy.load('en_core_web_sm')
                # spacy 3.x no longer needs manual pipeline setup
                # nlp already includes tagger and parser
            except OSError:
                print("Warning: Need to install spacy English model (with parser)")
                print("Please run: python -m spacy download en_core_web_sm")
            else:
                # Read files
                preds = []
                with open(res_file, 'r', encoding='utf-8') as f:
                    preds = [line.strip() for line in f if line.strip()]
                
                concept_sets = []
                with open(key_file, 'r', encoding='utf-8') as f:
                    concept_sets = [item.split() for item in f.read().strip().split("\n")]
                
                # Calculate Coverage
                covs = []
                for p, cs in zip(preds, concept_sets):
                    cs = set(cs)
                    lemmas = set()
                    for token in nlp(p):
                        lemmas.add(token.lemma_)
                    if len(cs) > 0:
                        cov = len(lemmas & cs) / len(cs)
                        covs.append(cov)
                    else:
                        covs.append(0.0)
                
                coverage = sum(covs) / len(covs) if covs else 0.0
                all_results["Coverage"] = coverage
                print(f"Coverage: {coverage:.4f} ({coverage*100:.2f}%)")
                
        except Exception as e:
            print(f"Warning: Coverage calculation failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("\nNote: cs_str file not found, skipping Coverage evaluation")
        print("Coverage evaluation requires concept string file (commongen.{split}.cs_str.txt)")
    
    # Display all results
    if all_results:
        print("\n" + "=" * 80)
        print("Complete Evaluation Results:")
        print("=" * 80)
        for metric, score in sorted(all_results.items()):
            if isinstance(score, float):
                print(f"{metric}: {score:.4f}")
            else:
                print(f"{metric}: {score}")
    
    return all_results


def simple_evaluation(jsonl_file: str, tgt_file: str):
    """
    Simple evaluation: calculate basic metrics like accuracy.
    
    Args:
        jsonl_file: JSONL result file.
        tgt_file: Reference sentence file.
    """
    print("=" * 80)
    print("Simple Evaluation (Basic Statistics)")
    print("=" * 80)
    
    # Read reference sentences
    references = []
    with open(tgt_file, 'r', encoding='utf-8') as f:
        references = [line.strip() for line in f if line.strip()]
    
    # Read generation results
    generated = []
    with open(jsonl_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                sentence = data.get("generated_sentence", "").strip()
                generated.append(sentence)
    
    # Basic statistics
    total = len(references)
    generated_count = sum(1 for g in generated if g)
    empty_count = total - generated_count
    
    print(f"Total questions: {total}")
    print(f"Successfully generated: {generated_count} ({generated_count/total*100:.2f}%)")
    print(f"Generation failed: {empty_count} ({empty_count/total*100:.2f}%)")
    
    # Calculate average length
    if generated_count > 0:
        avg_length = sum(len(g) for g in generated if g) / generated_count
        print(f"Average sentence length: {avg_length:.2f} characters")
    
    return {
        "total": total,
        "generated": generated_count,
        "empty": empty_count,
        "generation_rate": generated_count / total if total > 0 else 0
    }


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Evaluate CommonGen generation results")
    
    # Set default JSONL file path (automatically detect latest result file)
    result_dir = Path(__file__).parent / "result"
    default_jsonl_file = None
    
    # Try to find latest result file
    if result_dir.exists():
        jsonl_files = list(result_dir.glob("camel_commongen_*.jsonl"))
        if jsonl_files:
            # Sort by modification time, select latest
            jsonl_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            default_jsonl_file = str(jsonl_files[0])
    
    parser.add_argument(
        "--jsonl_file",
        type=str,
        default=default_jsonl_file,
        help=f"JSONL result file path (default: automatically detect latest result file)"
    )
    parser.add_argument(
        "--src_file",
        type=str,
        default=None,
        help="Source file path (concept list, for official evaluation)"
    )
    parser.add_argument(
        "--tgt_file",
        type=str,
        default=None,
        help="Reference sentence file path (required)"
    )
    parser.add_argument(
        "--output_txt",
        type=str,
        default=None,
        help="Converted text file path (default: same directory as JSONL file, with .txt extension)"
    )
    parser.add_argument(
        "--skip_official",
        action="store_true",
        help="Skip official evaluation, only run basic statistics (default: run full official evaluation)"
    )
    parser.add_argument(
        "--cs_str_file",
        type=str,
        default=None,
        help="Concept string file path (for Coverage evaluation, optional, will auto-detect)"
    )
    
    args = parser.parse_args()
    
    # If jsonl_file not specified, try auto-detection
    if not args.jsonl_file:
        result_dir = Path(__file__).parent / "result"
        if result_dir.exists():
            jsonl_files = list(result_dir.glob("camel_commongen_*.jsonl"))
            if jsonl_files:
                # Sort by modification time, select latest
                jsonl_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                args.jsonl_file = str(jsonl_files[0])
                print(f"Auto-detected latest result file: {args.jsonl_file}")
            else:
                print("Error: JSONL result file not found")
                print(f"Please ensure result directory contains camel_commongen_*.jsonl files")
                print(f"Or use --jsonl_file parameter to specify file path")
                return
        else:
            print("Error: result directory does not exist")
            print("Please run eval_commongen.py first to generate result file")
            return
    
    # Check if file exists
    if not os.path.exists(args.jsonl_file):
        print(f"Error: JSONL file does not exist: {args.jsonl_file}")
        return
    
    # If tgt_file not specified, try to infer from JSONL
    if args.tgt_file is None:
        # Try to find corresponding tgt file from dataset directory
        jsonl_path = Path(args.jsonl_file)
        if "dev" in jsonl_path.name:
            dataset_dir = jsonl_path.parent.parent / "dataset"
            args.tgt_file = str(dataset_dir / "commongen.dev.tgt.txt")
        elif "test" in jsonl_path.name:
            dataset_dir = jsonl_path.parent.parent / "dataset"
            args.tgt_file = str(dataset_dir / "commongen.test.tgt.txt")
        elif "train" in jsonl_path.name:
            dataset_dir = jsonl_path.parent.parent / "dataset"
            args.tgt_file = str(dataset_dir / "commongen.train.tgt.txt")
    
    if args.tgt_file and not os.path.exists(args.tgt_file):
        print(f"Warning: Reference file does not exist: {args.tgt_file}")
        args.tgt_file = None
    
    # Default run official evaluation unless --skip_official is specified
    use_official = not args.skip_official
    
    # Simple evaluation (always execute)
    if args.tgt_file:
        simple_evaluation(args.jsonl_file, args.tgt_file)
    
    # Official evaluation (enabled by default)
    if use_official:
        if not args.src_file:
            # Try to find corresponding src file from dataset directory
            jsonl_path = Path(args.jsonl_file)
            dataset_dir = jsonl_path.parent.parent / "dataset"
            if "dev" in jsonl_path.name:
                args.src_file = str(dataset_dir / "commongen.dev.src_alpha.txt")
            elif "test" in jsonl_path.name:
                args.src_file = str(dataset_dir / "commongen.test.src_alpha.txt")
            elif "train" in jsonl_path.name:
                args.src_file = str(dataset_dir / "commongen.train.src_alpha.txt")
        
        if not args.src_file or not os.path.exists(args.src_file):
            print(f"\nError: Source file needed for official evaluation, but not found: {args.src_file}")
            print("Please use --src_file parameter to specify source file path")
            return
        
        if not args.tgt_file or not os.path.exists(args.tgt_file):
            print(f"\nError: Reference file needed for official evaluation, but not found: {args.tgt_file}")
            print("Please use --tgt_file parameter to specify reference file path")
            return
        
        # Convert JSONL to text format
        if args.output_txt is None:
            jsonl_path = Path(args.jsonl_file)
            output_txt = jsonl_path.with_suffix('.txt')
        else:
            output_txt = Path(args.output_txt)
        
        print(f"\nConverting JSONL to text format...")
        convert_jsonl_to_txt(args.jsonl_file, str(output_txt))
        
        # Run official evaluation
        print(f"\nRunning official evaluation...")
        evaluate_with_commongen_metrics(
            key_file=args.src_file,
            gts_file=args.tgt_file,
            res_file=str(output_txt),
            cs_str_file=args.cs_str_file
        )
    # If skipped official evaluation, give hint
    if args.skip_official:
        print("\nNote: Official evaluation skipped. Default will run full official evaluation (BLEU, METEOR, ROUGE, CIDEr, SPICE)")
        print("To run full evaluation, do not use --skip_official parameter")


if __name__ == "__main__":
    main()

