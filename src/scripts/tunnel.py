import logging
import os
import signal
from sshtunnel import SSHTunnelForwarder

# Project imports
from src.environment.initialize_environment import environment_info

logging.basicConfig(
    format="[%(asctime)s %(filename)s->%(funcName)s():%(lineno)s]::%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)
logger.setLevel(os.getenv('LOG_LEVEL') or 'INFO')

tunnel = SSHTunnelForwarder(
    (environment_info.TUNNEL_REMOTE_HOST, environment_info.TUNNEL_REMOTE_PORT),
    ssh_username=environment_info.TUNNEL_USER,
    ssh_private_key=environment_info.TUNNEL_PRIVATE_KEY_PATH,
    remote_bind_address=(
        environment_info.TUNNEL_REMOTE_BIND_HOST,
        environment_info.TUNNEL_REMOTE_BIND_PORT,
    ),
    local_bind_address=(
        environment_info.TUNNEL_LOCAL_BIND_HOST,
        environment_info.TUNNEL_LOCAL_BIND_PORT,
    ),
)

tunnel.start()
logger.info(f"Tunnel started on Port {environment_info.TUNNEL_LOCAL_BIND_PORT}")


def handler(signum, frame):
    tunnel.stop()


signal.signal(signal.SIGINT, handler)
logger.info("Waiting for SIGINT...")
signal.pause()
