import requests
import logging
import os
from pathlib import Path

# Project imports
from .user import User
from .io_utils import md5_hash

logging.basicConfig(
    format="[%(asctime)s %(filename)s->%(funcName)s():%(lineno)s]::%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)
logger.setLevel(os.getenv('LOG_LEVEL') or 'INFO')


class BackendHelper:
    def __init__(self, ds_app_backend_url: str, user: User, target_directory: str):
        self.user = user
        self.auth_headers = {'Authorization': self.user.bearer_token}
        self.target_directory = target_directory
        self.ds_app_backend_url = ds_app_backend_url

    def download_file_from_ds_app(self, file_key) -> bool:
        """
        Get the file from DS app backend
        :param file_key: file key to fetch
        :return: True if file received and saved to storage, False otherwise
        """
        target_file_path = Path(self.target_directory, file_key)
        target_file_path_str = os.fspath(target_file_path)
        res_presigned_url: requests.Response = requests.get(
            f"{self.ds_app_backend_url}/api/v1/ds-app-files/{file_key}",
            headers=self.auth_headers)

        if res_presigned_url.status_code != 200:
            logger.error(f"Failed to fetch file: {file_key}")
            return False

        res_body = res_presigned_url.json()
        if res_body['file_exists'] is False:
            return False

        if res_body['md5sum'] == md5_hash(target_file_path_str):
            return True

        with requests.get(
            res_body['presigned_url'],
            stream=True
        ) as download_file_res:
            code = download_file_res.status_code
            if code != 200:
                return False
            with open(target_file_path_str, 'wb') as file:
                for chunk in download_file_res.iter_content(chunk_size=8192):  # Download in chunks
                    file.write(chunk)
