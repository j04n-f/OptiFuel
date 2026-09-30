from importlib.resources import files
from typing import LiteralString, cast

import psycopg
from procrastinate.schema import SchemaManager

from optifuel.config import Settings


def main() -> None:
    # ponytail: no migration tool. Upgrading Procrastinate needs its versioned migration
    # scripts, which is the point to adopt one.
    url = Settings().database_url.get_secret_value()
    # Our own file, shipped in the package: as trusted as a literal.
    ours = cast(LiteralString, (files("optifuel") / "sql" / "schema.sql").read_text())
    with psycopg.connect(url) as conn, conn.transaction():
        # Procrastinate's schema is not re-runnable, so apply it only when absent.
        if conn.execute("SELECT to_regclass('procrastinate_jobs') IS NULL").fetchone() == (True,):
            conn.execute(SchemaManager.get_schema())
        conn.execute(ours)


if __name__ == "__main__":
    main()
