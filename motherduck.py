import os
import duckdb
from dotenv import load_dotenv

load_dotenv()


def execute_query(query, database_name=None):

    token = os.getenv("MOTHERDUCK_TOKEN")
    motherduck_database = os.getenv("MOTHERDUCK_DATABASE")

    if not token:
        raise Exception(
            "MOTHERDUCK_TOKEN is not configured"
        )

    if not motherduck_database:
        raise Exception(
            "MOTHERDUCK_DATABASE is not configured"
        )

    connection = None

    try:

        # ----------------------------------------
        # Create DuckDB connection
        # ----------------------------------------

        connection = duckdb.connect(":memory:")

        # ----------------------------------------
        # Install / load MotherDuck
        # ----------------------------------------

        connection.execute(
            "INSTALL motherduck;"
        )

        connection.execute(
            "LOAD motherduck;"
        )

        connection.execute(
            f"SET motherduck_token='{token}';"
        )

        # ----------------------------------------
        # Attach database from .env
        # ----------------------------------------

        connection.execute(
            f"ATTACH 'md:{motherduck_database}' "
            f"AS report_db;"
        )

        # ----------------------------------------
        # Execute query
        # ----------------------------------------

        dataframe = connection.execute(
            query
        ).fetchdf()

        return dataframe

    finally:

        if connection:
            connection.close()