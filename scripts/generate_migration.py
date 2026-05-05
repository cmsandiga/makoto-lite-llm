"""Spin up a testcontainer PostgreSQL and run alembic autogenerate."""
import os
import subprocess
import sys

from testcontainers.postgres import PostgresContainer


def main():
    msg = sys.argv[1] if len(sys.argv) > 1 else "auto migration"

    with PostgresContainer("postgres:15") as pg:
        # testcontainers gives us a sync URL like postgresql+psycopg2://...
        # We need the asyncpg variant for our async engine
        sync_url = pg.get_connection_url()
        # Convert to asyncpg URL
        async_url = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        os.environ["DATABASE_URL"] = async_url
        print(f"Using database: {async_url}")

        result = subprocess.run(
            ["alembic", "revision", "--autogenerate", "-m", msg],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
