"""Apply the search schema using an explicitly supplied migration connection."""

import asyncio
import os

from .store import Store


def main():
    dsn = os.environ.get("AI_SEARCH_MIGRATION_DSN", "")
    if not dsn:
        raise SystemExit("Set AI_SEARCH_MIGRATION_DSN to the separately provisioned search database.")
    asyncio.run(Store(dsn, "migration", "migration", 1).migrate())
    print("Search schema migration complete.")


if __name__ == "__main__":
    main()
