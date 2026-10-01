"""Command-line entry point for the native MaAS reproduction."""
from __future__ import annotations
import argparse
from pathlib import Path


def _load_env_file() -> None:
    """Load the project-local .env once, without overriding the real environment.

    Doing this here rather than in launch.json keeps the debugger and a plain
    ``python -m applications.maas_reproduction.main`` run on the same config.
    """
    path = Path(__file__).parent / ".env"
    if not path.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(path, override=False)
from .maas_reproduction.runtime.settings import load_settings
from .maas_reproduction.runtime.bootstrap import build_runtime

def main(argv: list[str] | None = None) -> int:
    _load_env_file()
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("train", "test", "smoke"), default="test")
    parser.add_argument("--dataset", choices=("GSM8K", "MATH", "HumanEval"), default=None)
    parser.add_argument("--split", choices=("train", "test"), default=None)
    parser.add_argument("--sample", type=int, default=None,
                        help="number of dataset samples to run per invocation; an epoch only completes once the whole dataset is consumed")
    parser.add_argument("--epochs", type=int, default=None, help="override the configured number of epochs")
    parser.add_argument("--subset", type=int, default=None,
                        help="use only the first N dataset samples, so a small debug run can still complete an epoch")
    parser.add_argument("--fresh", action="store_true",
                        help="start a new run instead of auto-resuming the newest checkpoint")
    parser.add_argument("--config-root", type=Path, default=Path(__file__).parent / "assets" / "config")
    parser.add_argument("--fake-model", action="store_true")
    parser.add_argument("--resume", type=Path, default=None)
    parser.add_argument(
        "--source-bundle",
        type=Path,
        default=None,
        help="test a source MaAS Controller bundle without restoring or training",
    )
    args = parser.parse_args(argv)
    settings = load_settings(args.config_root, mode_override=args.mode, dataset_override=args.dataset,
                             split_override=args.split, sample_override=args.sample,
                             epochs_override=args.epochs)
    if args.fresh and args.resume is not None:
        raise ValueError("--fresh and --resume are mutually exclusive")
    if args.source_bundle is not None and args.mode != "test":
        raise ValueError("--source-bundle is valid only with --mode test")
    if args.source_bundle is not None and args.resume is not None:
        raise ValueError("--source-bundle and --resume are mutually exclusive")
    if args.subset is not None and (isinstance(args.subset, bool) or args.subset <= 0):
        raise ValueError("--subset must be a positive int")
    # A source bundle is a complete test artifact.  It must bypass both
    # explicit restore and discovery of training checkpoints.
    resume_path = None if args.fresh or args.source_bundle is not None else args.resume
    output_override = None
    if settings.mode == "train" and resume_path is None and not args.fresh:
        configured_output = settings.output_root
        if not configured_output.is_absolute() and configured_output.as_posix() == "assets/output":
            output_base = args.config_root.parent / "output"
        else:
            output_base = configured_output if configured_output.is_absolute() else Path.cwd() / configured_output
        candidates = sorted(output_base.glob("run_*/checkpoints/latest.pt"),
                            key=lambda path: path.stat().st_mtime, reverse=True)
        if candidates:
            resume_path = candidates[0]
            output_override = resume_path.parent.parent
    elif resume_path is not None and settings.mode == "train":
        output_override = resume_path.parent.parent
    runtime = build_runtime(settings, fake=args.fake_model or args.mode == "smoke",
                            output_root_override=output_override, subset=args.subset,
                            source_bundle_path=args.source_bundle)
    if args.source_bundle is not None:
        runtime.dataset_runner._log_event(
            "source_bundle_loaded",
            source_bundle_path=str(args.source_bundle.resolve()),
            dataset=settings.dataset,
            operator_catalog=list(runtime.operator_catalog),
        )
    if resume_path is not None:
        try:
            payload = runtime.checkpoint_manager.load(
                resume_path,
                controller=runtime.policy_controller,
                optimizer=runtime.optimizer if settings.mode == "train" else None,
                expected_operator_catalog=runtime.operator_catalog,
            )
            if settings.mode == "train":
                runtime.dataset_runner.restore_checkpoint(payload)
                runtime.dataset_runner._log_event(
                    "resume_loaded", checkpoint_path=str(resume_path),
                    epoch=runtime.dataset_runner.epoch, cursor=runtime.dataset_runner.cursor,
                )
            else:
                # Test runs reuse only the controller weights.  Do not restore
                # training progress or write test artifacts into the training run.
                runtime.dataset_runner._log_event(
                    "weights_loaded", checkpoint_path=str(resume_path),
                    checkpoint_epoch=payload.get("epoch"), test_epoch=0, cursor=0,
                )
        except Exception as exc:
            runtime.dataset_runner._log_error(stage="load_resume", error=exc, checkpoint_path=str(resume_path))
            raise
    # ``--subset`` already bounds the run by the size of the subset, so the
    # separate per-invocation budget only applies when it was asked for.
    limit = settings.sample
    if args.subset is not None and args.sample is None:
        limit = None
    for result in runtime.dataset_runner.iter_run(limit=limit):
        print(result)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ["main"]
