from fastapi import Header, HTTPException
import requests

# Project imports
from src.environment.initialize_environment import environment_info


async def verify_io_token(authorization: str = Header(..., description="Bearer token for Insurance.io API")):
    token = authorization.split(" ")[-1]
    bearer_token = f"Bearer {token}"
    response = requests.get(
        f"{environment_info.IO_API_URL}/api/v1/ds-app-auth",
        headers={
            "Authorization": bearer_token
        }
    )
    if response.status_code != 200:
        json_data = {"errors": {
                "title": "Invalid token",
                "code": "ERR_INVALID_TOKEN"
            }
        }
        try:
            json_data = response.json()
        except Exception as e:
            pass

        raise HTTPException(status_code=response.status_code, detail=json_data)

    return response
