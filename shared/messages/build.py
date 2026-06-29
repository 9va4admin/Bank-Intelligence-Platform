"""
CLI: python -m shared.messages.build [--output-dir <path>]

Validates all locales and writes messages.{locale}.json to the output directory.
Default output: apps/web/src/shared/locales/

Exit codes:
  0 — success
  1 — validation errors (no output written)
"""
import argparse
import sys
from pathlib import Path

import structlog

log = structlog.get_logger()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build message JSON bundles from YAML locales.")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).parents[2] / "apps" / "web" / "src" / "shared" / "locales"),
        help="Directory to write messages.{locale}.json files",
    )
    parser.add_argument(
        "--locales-dir",
        default=str(Path(__file__).parent / "locales"),
        help="Root directory containing locale subdirectories",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Run validation only — do not write output",
    )
    args = parser.parse_args()

    from shared.messages.registry import MessageRegistry

    registry = MessageRegistry(locales_dir=Path(args.locales_dir))

    errors = registry.validate()
    if errors:
        log.error("messages.validation_failed", error_count=len(errors))
        for e in errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        return 1

    log.info("messages.validation_passed", key_count=len(registry.keys()))

    if args.validate_only:
        print(f"OK — {len(registry.keys())} messages validated, no output written.")
        return 0

    output_dir = Path(args.output_dir)
    registry.build(output_dir=output_dir)
    print(f"Built {len(registry.keys())} messages → {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
