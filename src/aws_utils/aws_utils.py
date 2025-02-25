import os
import logging
import boto3
import tempfile
from botocore.exceptions import ClientError
import typing


logging.basicConfig(
    format="[%(asctime)s %(filename)s->%(funcName)s():%(lineno)s]::%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)
logger.setLevel(os.getenv('LOG_LEVEL') or 'INFO')


class S3Prefixes:
    @staticmethod
    def __get_root():
        return "data"

    @staticmethod
    def get_output_runs():
        return f"{S3Prefixes.__get_root()}/active_runs"


class FileStore:
    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name
        self.client = self.__get_s3_client()

    @staticmethod
    def __get_s3_client():
        return boto3.client('s3')

    def upload_file(self, file_path: str, key: str) -> bool:
        """
            Upload a file to an S3 bucket
            :param file_path: File to upload
            :param key: S3 object name
            :return: True if file was uploaded, else False
        """
        try:
            logger.debug(f"Uploading {file_path} to {key}")
            _ = self.client.upload_file(file_path, self.bucket_name, key)
        except ClientError as e:
            logger.error(e)
            return False
        return True

    def download_file(self, key: str, file_path: str) -> bool:
        """
            Download a file from an S3 bucket
            :param key: S3 object name
            :param file_path: File to upload
            :return: True if file was downloaded, else False
        """
        try:
            logger.debug(f"Downloading {key} from S3 to {file_path}")
            _ = self.client.download_file(self.bucket_name, key, file_path)
            logger.debug(f"Downloaded {key} from S3")
        except ClientError as e:
            logger.error(e)
            return False
        return True

    def download_tmp_file(self, key: str):
        """
            Download a file from an S3 bucket
            :param key: S3 object name
            :return: temp file object; None in case of failure
        """
        tmp_file = tempfile.NamedTemporaryFile()
        file_path = tmp_file.name
        success = self.download_file(key, file_path)
        if success is True:
            return tmp_file
        else:
            return None

    def download_fileobj(self, key: str, file_path: str) -> bool:
        """
            Download a file from an S3 bucket
            :param key: S3 object name
            :param file_path: File to upload
            :return: True if file was downloaded, else False
        """
        try:
            _ = self.client.download_fileobj(self.bucket_name, key, file_path)
        except ClientError as e:
            logger.error(e)
            return False
        return True

    def file_head_object(self, key: str):
        """
        Check if a file exists in S3 bucket
        :param key: S3 object name
        :return: [True, object_metadata] if file exists, [False, None] otherwise
        """
        try:
            response = self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True, response
        except ClientError:
            return False, None

    def get_presigned_url(self, key: str, expiration=3600) -> str | None:
        """
        Generate a presigned URL for an S3 object
        :param key: S3 object name
        :param expiration: time in seconds
        :return: presigned_url (string) if file exists, None otherwise
        """
        try:
            response = self.client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': key},
                ExpiresIn=expiration
            )
        except ClientError as e:
            logger.error(e)
            return None
        return response
