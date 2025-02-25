from fastapi import HTTPException

from .fastapi_app.fastapi_app import app
from .controllers import routes


@app.get("/", include_in_schema=False)
def blank_route():
    return {}


# Catch all path in fastapi
@app.get("/{path:path}", include_in_schema=False)
def catch_all(path: str):
    raise HTTPException(
        status_code=404,
        detail="Path not found",
    )
