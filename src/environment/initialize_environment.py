from pydantic import SecretStr
from pydantic_settings import BaseSettings
from enum import Enum

from dotenv import load_dotenv

# Load all environment variables
load_dotenv()


class EnvironmentNameEnum(str, Enum):
    production = "production"
    development = "development"
    stage = "stage"


class EnvironmentInfo(BaseSettings):
    ENVIRONMENT_NAME: EnvironmentNameEnum
    API_APP_PORT: int = 8080
    IO_API_URL: str  # example: https://api.portal.insurance.io
    DB_HOST: SecretStr
    DB_PORT: SecretStr
    DB_NAME: SecretStr
    DB_USER: SecretStr
    DB_PASSWORD: SecretStr
    TUNNEL_USER: str = "ec2-user"
    TUNNEL_PRIVATE_KEY_PATH: str = '~/.ssh/id_rsa'
    TUNNEL_REMOTE_HOST: str = "127.0.0.1"
    TUNNEL_REMOTE_PORT: int = 22
    TUNNEL_REMOTE_BIND_HOST: str = "127.0.0.1"
    TUNNEL_REMOTE_BIND_PORT: int = 5432
    TUNNEL_LOCAL_BIND_HOST: str = 'localhost'
    TUNNEL_LOCAL_BIND_PORT: int = 7999
    S3_BUCKET: str
    AWS_ACCESS_KEY_ID: SecretStr
    AWS_DEFAULT_REGION: SecretStr
    AWS_SECRET_ACCESS_KEY: SecretStr
    SLACK_CHANNEL_TOKEN: str
    DS_APP_API_URL: str | None = None # example: https://api.portal.insurance.io
    DS_DB_PASSWORD: SecretStr
    DS_DB_USER: SecretStr
    DS_DB_NAME: SecretStr
    DS_DB_HOST: SecretStr
    


environment_info = EnvironmentInfo()
if environment_info.DS_APP_API_URL is None:
    environment_info.DS_APP_API_URL = f"http://127.0.0.1:{environment_info.API_APP_PORT}"
