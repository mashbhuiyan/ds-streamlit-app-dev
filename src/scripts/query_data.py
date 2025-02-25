import os
import gc
import logging
import psycopg2
import psycopg2.extras
import pandas as pd

from pathlib import Path
from datetime import timedelta

# Project imports
from src.environment.initialize_environment import environment_info
from src.aws_utils.aws_utils import FileStore, S3Prefixes

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


def get_data(sql_query):
    """
    Run SQL query on ad_portal_prod_db database

    Parameters
    ----------
    sql_query : str
        SQL query to execute

    Returns
    -------
    pandas.DataFrame
        A DataFrame containing the qiery results

    Examples
    --------
    >>> df = get_data("SELECT * FROM rtb_bids")
    """
    conn = psycopg2.connect(
        host=environment_info.DB_HOST.get_secret_value(),
        database=environment_info.DB_NAME.get_secret_value(),
        user=environment_info.DB_USER.get_secret_value(),
        password=environment_info.DB_PASSWORD.get_secret_value(),
        port=environment_info.DB_PORT.get_secret_value(),
        connect_timeout=240,
    )

    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cursor.execute(sql_query)
    ssh_res = cursor.fetchall()

    logger.info("Query completed.")
    if not ssh_res:
        logger.info("Query result is empty")
        return None
    else:
        logger.info(f"Length of query result: {len(ssh_res)}")
        return pd.DataFrame(ssh_res)


def save_pd_to_json(dataframe, filename, orient="records", lines=True):
    """
    Save a pandas DataFrame to a JSON file with customizable orientation and
    line formatting.

    Parameters
    ----------
    dataframe : pandas.DataFrame
        The DataFrame to be saved to a JSON file.
    filename : str
        The name of the file where the JSON data will be saved.
    orient : str, optional, default="records"
        The format of the JSON string. Allowed values are:
        'split', 'records', 'index', 'columns', 'values', 'table'.
    lines : bool, optional, default=True
        If True, write each record to a separate line.

    Returns
    -------
    None

    Example
    -------
    >>> import pandas as pd
    >>> df = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
    >>> save_pd_to_json(df, 'data.json')
    """
    dataframe.to_json(filename, orient=orient, lines=lines)


def save_query_res(
    sql_query,
    filename="query_res.json",
    merge=False,
):
    """
    Executes an SQL query and saves the result as a JSON file, optionally
    merging with existing data.

    Parameters
    ----------
    sql_query : str
        The SQL query to be executed to retrieve data from the database.
    filename : str, optional
        The name of the file to save the query result to (default is
        "query_res.json").
    merge : bool, optional
        If True, merges the query result with existing data in the file,
        keeping only the records from the past 60 days (default is False).

    Returns
    -------
    pandas.DataFrame
        The DataFrame containing the query result, optionally merged with
        existing data.

    Examples
    --------
    >>> sql_query = "SELECT * FROM rtb_bids"
    >>> save_query_res(sql_query, "data.json")
    """
    file_exists = os.path.exists(filename)
    fs = FileStore(environment_info.S3_BUCKET)
    query_s3_key = f"{S3Prefixes.get_output_runs()}/{Path(filename).name}"
    if not file_exists:
        file_exists = fs.download_file(query_s3_key, filename)

    res = get_data(sql_query)
    if res is not None:
        current_date = res["created_at"][0].date()
        date_60_days_ago = current_date - timedelta(days=60)
        if merge:
            if file_exists:
                current_df = pd.read_json(
                    filename, orient="records", lines=True
                )
                date_time = current_df["created_at"]
                current_df["date_to_lim"] = [x.date() for x in date_time]

                current_df = current_df[
                    (current_df["date_to_lim"] > date_60_days_ago)
                    & (current_df["date_to_lim"] <= current_date)
                ]
                current_df = current_df.drop("date_to_lim", axis=1)
                res = pd.concat([current_df, res], axis=0)
                del current_df
                logger.info(
                    "Length of query result combined with past "
                    f"60 days of data before drop: {len(res)}"
                )

                gc.collect()
                res = res.drop_duplicates(subset=["id"])
                logger.info(
                    "Length of query result combined with past "
                    f"60 days of data: {len(res)}"
                )

        save_pd_to_json(res, filename, orient="records", lines=True)
    else:
        logger.info("Query result  is None")
        if merge:
            if file_exists:
                res = pd.read_json(filename, orient="records", lines=True)
    if res is not None:
        fs.upload_file(filename, query_s3_key)
    return res
