#!/usr/bin/env python3
"""Healthcare Data Migration & Validation Pipeline - command line entrypoint.

  python run_pipeline.py generate   [--patients 2000]   synthetic dirty CSVs -> data/raw
  python run_pipeline.py load-source                    CSVs -> MySQL (legacy source)
  python run_pipeline.py migrate    [--batch-size 1000] MySQL -> clean -> PostgreSQL
  python run_pipeline.py validate                       SQL reconciliation + integrity suites
  python run_pipeline.py selftest                       inject faults, prove validators catch them
  python run_pipeline.py all        [--patients 2000]   everything, in order
"""
import argparse
import logging
import sys

from healthcare_pipeline import config
from healthcare_pipeline.config import setup_logging


def _print_summary(summary: dict) -> None:
    from tabulate import tabulate
    rows = [[t, s["source_rows"], s["loaded"], s["duplicates_merged"], s["rejected"], s["load_failures"]]
            for t, s in summary.items() if not t.startswith("_")]
    print("\n" + tabulate(rows, headers=["table", "source", "loaded", "dupes merged", "rejected", "load failures"],
                          tablefmt="github"))
    print(f"\nrun_id={summary['_meta']['run_id']}  elapsed={summary['_meta']['seconds']}s")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["generate", "load-source", "migrate", "validate", "selftest", "all"])
    ap.add_argument("--patients", type=int, default=2000, help="number of base patients to generate")
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--batch-size", type=int, default=config.BATCH_SIZE)
    args = ap.parse_args(argv)
    setup_logging()
    log = logging.getLogger("pipeline")
    ok = True

    if args.command in ("generate", "all"):
        from healthcare_pipeline.generate_data import generate_all, write_csvs
        write_csvs(*generate_all(args.patients, args.seed))
    if args.command in ("load-source", "all"):
        from healthcare_pipeline.load_source import load_source
        load_source()
    if args.command in ("migrate", "all"):
        from healthcare_pipeline.migrate import run_migration
        _print_summary(run_migration(args.batch_size))
    if args.command in ("validate", "all"):
        from healthcare_pipeline.validate import run_validation
        _, ok = run_validation()
        log.info("full report: %s", config.REPORT_DIR / "validation_report.md")
    if args.command == "selftest":
        from healthcare_pipeline.selftest import run_selftest
        ok = run_selftest(args.batch_size)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
