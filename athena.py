import os

import pandas as pd

from pyathena import connect


def execute_query(
    query,
    database_name
):

    aws_access_key = os.getenv(
        "AWS_ACCESS_KEY_ID"
    )

    aws_secret_key = os.getenv(
        "AWS_SECRET_ACCESS_KEY"
    )

    aws_region = os.getenv(
        "AWS_REGION",
        "ap-south-1"
    )

    s3_staging_dir = os.getenv(
        "ATHENA_S3_STAGING_DIR"
    )

    if not aws_access_key:
        raise Exception(
            "AWS_ACCESS_KEY_ID is not configured"
        )

    if not aws_secret_key:
        raise Exception(
            "AWS_SECRET_ACCESS_KEY is not configured"
        )

    if not s3_staging_dir:
        raise Exception(
            "ATHENA_S3_STAGING_DIR is not configured"
        )

    connection = connect(
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=aws_region,
        s3_staging_dir=s3_staging_dir,
        schema_name=database_name
    )

    try:

        dataframe = pd.read_sql(
            query,
            connection
        )

        return dataframe

    finally:

        connection.close()