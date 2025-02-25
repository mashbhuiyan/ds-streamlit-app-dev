from .ds_app_files_pydantic_models import DsAppFilesResponse, CustomRequestHeaders, DsAppFilesRequest
from src.aws_utils.aws_utils import S3Prefixes, FileStore
from src.environment.initialize_environment import environment_info


async def get_ds_app_files(file_name: str, _ds_app_files_request: DsAppFilesRequest) -> DsAppFilesResponse:
    fs = FileStore(environment_info.S3_BUCKET)
    key = f"{S3Prefixes.get_output_runs()}/" + file_name.split("/")[-1]
    file_exists, file_head_obj = fs.file_head_object(key)
    presigned_url = None
    if file_exists:
        presigned_url = fs.get_presigned_url(key)

    md5sum = None
    if file_exists:
        md5sum = file_head_obj['ETag'].replace('"', '')
    return DsAppFilesResponse(presigned_url=presigned_url,
                              file_exists=file_exists,
                              md5sum=md5sum)
