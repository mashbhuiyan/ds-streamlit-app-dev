import uvicorn
import logging
import os

# Project imports
from src.api.server import *
from src.environment.initialize_environment import environment_info

logging.basicConfig(
    format="[%(asctime)s %(filename)s->%(funcName)s():%(lineno)s]::%(levelname)s: %(message)s"
)

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv('LOG_LEVEL') or 'INFO')


if __name__ == "__main__":
    logger.info("Starting Uvicorn Server")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=environment_info.API_APP_PORT
    )
