import os

from pathlib import Path

from src.environment.initialize_environment import environment_info
from src.aws_utils.aws_utils import FileStore, S3Prefixes


def s3_download(filename, create_tmp=False):
    file_exists = os.path.exists(filename)
    fs = FileStore(environment_info.S3_BUCKET)
    query_s3_key = f"{S3Prefixes.get_output_runs()}/{Path(filename).name}"
    if not file_exists:
        try:
            file_exists = fs.download_file(query_s3_key, filename)
        except:
            if create_tmp:
                file_exists = fs.download_tmp_file(query_s3_key)
    return


def s3_upload(filename):
    file_exists = os.path.exists(filename)
    fs = FileStore(environment_info.S3_BUCKET)
    query_s3_key = f"{S3Prefixes.get_output_runs()}/{Path(filename).name}"
    fs.upload_file(filename, query_s3_key)
    return
