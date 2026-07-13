"""
CLI: python -m shared.messages.build [options]

Validates messages.yaml, pushes to Redis, and writes messages.{locale}.json
for the browser bundle.

Redis is optional — if REDIS_MESSAGES_URL is not set (or --no-redis is passed),
the build skips the Redis push and only writes JSON files.

Exit codes:
  0 — success
  1 — validation errors (no output written, no Redis push)
"""
import argparse
import os
import sys
from pathlib import Path

import structlog

log = structlog.get_logger()

_DEFAULT_MESSAGES_FILE = str(Path(__file__).parent / "locales" / "messages.yaml")
_DEFAULT_OUTPUT_DIR = str(Path(__file__).parents[2] / "apps" / "web" / "src" / "shared" / "locales")


def _get_redis_client(url: str | None):
    """Return a Redis client or None if unavailable."""
    if not url:
        return None
    try:
        import redis
        client = redis.from_url(url, decode_responses=False)
        client.ping()
        log.info("messages.redis_connected", url=url.split("@")[-1])
        return client
    except Exception as exc:
        log.warning("messages.redis_unavailable", error=str(exc))
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Build ASTRA message bundles from messages.yaml.")
    parser.add_argument(
        "--messages-file",
        default=_DEFAULT_MESSAGES_FILE,
        help="Path to messages.yaml (default: shared/messages/locales/messages.yaml)",
    )
    parser.add_argument(
        "--output-dir",
        default=_DEFAULT_OUTPUT_DIR,
        help="Directory to write messages.{locale}.json browser bundles",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate only — do not write output or push to Redis",
    )
    parser.add_argument(
        "--no-redis",
        action="store_true",
        help="Skip Redis push even if REDIS_MESSAGES_URL is set",
    )
    parser.add_argument(
        "--redis-url",
        default=None,
        help="Redis URL (overrides REDIS_MESSAGES_URL env var)",
    )
    args = parser.parse_args()

    from shared.messages.registry import MessageRegistry

    registry = MessageRegistry(messages_file=Path(args.messages_file))

    errors = registry.validate()
    if errors:
        log.error("messages.validation_failed", error_count=len(errors))
        for e in errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        return 1

    key_count = len(registry.keys())
    locale_count = len(registry.locales())
    log.info("messages.validation_passed", key_count=key_count, locales=registry.locales())

    if args.validate_only:
        print(f"OK — {key_count} messages × {locale_count} locales validated, no output written.")
        return 0

    # Redis push
    redis_client = None
    if not args.no_redis:
        redis_url = args.redis_url or os.environ.get("REDIS_MESSAGES_URL")
        redis_client = _get_redis_client(redis_url)
        if redis_url and not redis_client:
            print("WARNING: Redis URL set but connection failed — skipping Redis push.", file=sys.stderr)

    output_dir = Path(args.output_dir)
    registry.build(output_dir=output_dir, redis_client=redis_client)

    redis_status = "pushed to Redis + " if redis_client else ""
    # ASCII-only: Windows consoles default to cp1252, which cannot encode
    # U+00D7/U+2192 and crashes print() before the HTML doc regen below runs.
    print(f"Built {key_count} messages x {locale_count} locales -> {redis_status}{output_dir}")

    # Regenerate the taxonomy HTML doc every time the build runs
    from shared.messages.build_docs import build_html
    build_html(yaml_path=Path(args.messages_file))

    return 0


if __name__ == "__main__":
    sys.exit(main())
