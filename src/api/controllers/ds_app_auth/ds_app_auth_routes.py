from fastapi import Depends

# Project imports
from src.api.fastapi_app.fastapi_app import app
from src.api.middlewares.authentication import verify_io_token

DS_APP_FILES_ROUTES_PREFIX = '/api/v1/ds-app-auth'


@app.get(f"{DS_APP_FILES_ROUTES_PREFIX}", dependencies=[Depends(verify_io_token)])
async def get_ds_app_auth_route():
    return {
        'data': {
            'message': 'success'
        }
    }
