from fastapi import Depends, Path

# Project imports
from src.api.fastapi_app.fastapi_app import app
from .ds_app_files_pydantic_models import DsAppFilesResponse, CustomRequestHeaders, DsAppFilesRequest
from .ds_app_files_controller import get_ds_app_files
from src.api.middlewares.authentication import verify_io_token

DS_APP_FILES_ROUTES_PREFIX = '/api/v1/ds-app-files'


@app.get(f"{DS_APP_FILES_ROUTES_PREFIX}" + '/{file_name}', dependencies=[Depends(verify_io_token)])
async def get_ds_app_files_route(
        file_name: str = Path(..., description="Name of the file to retrieve")) -> DsAppFilesResponse:
    return await get_ds_app_files(file_name, DsAppFilesRequest())
