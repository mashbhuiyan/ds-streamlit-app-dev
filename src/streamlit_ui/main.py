import logging
import os
import streamlit as st

import src.utils.config as config
from src.utils.argument_parser_utils import parse_arguments
from src.environment.initialize_environment import environment_info
from .create_status_page import start_streamlit_app
from .user import User

logging.basicConfig(
    format="[%(asctime)s %(filename)s->%(funcName)s():%(lineno)s]::%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)
logger.setLevel(os.getenv('LOG_LEVEL') or 'INFO')


def get_auth_token():
    return st.query_params.get('auth_token', None)


def main():
    user = User(get_auth_token())
    if user.authenticated:
        args = parse_arguments()
        config_attr = config.load(args.config_file)
        start_streamlit_app(config_attr)
    else:
        st.write("You are not authorized to access this page.")


if __name__ == '__main__':
    main()
