# Pypi packages
import argparse
import os
import logging
from pathlib import Path

# Internal packages
from src.environment.initialize_environment import environment_info
from src.src_root import src_root

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


def default_environment_file():
    src_root_dir = Path(src_root).resolve()
    config_dir = src_root_dir.joinpath("cfg")
    environment_file = config_dir.joinpath(
        f"{environment_info.ENVIRONMENT_NAME.value}.ini"
    )
    environment_file_str = os.fspath(environment_file)
    logger.debug(f"Environment file: {environment_file_str}")
    return environment_file_str


def parse_arguments(script_name=None):
    parser = argparse.ArgumentParser(description="Process a config file.")
    parser.add_argument(
        "--config-file",
        type=str,
        default=default_environment_file(),
        help="The path to the config file",
    )

    if script_name in ["run_query", "save_plots_and_table"]:
        parser.add_argument(
            "--only-for-update",
            action="store_true",
            help="If True, summarize only state and sourcetype id",
        )
        parser.add_argument(
            "--only-for-plots",
            action="store_true",
            help="If True, exclude state and sourcetype id summarization",
        )

    if script_name == "run_query":
        parser.add_argument(
            "--query-data",
            action="store_true",
            help="If True, query data from DB",
        )

    if script_name == "update_model_bases":

        parser.add_argument(
            "--apply-negative-corrections",
            action="store_true",
            help="If True apply negative corrections",
        )
        parser.add_argument(
            "--apply-positive-corrections",
            action="store_true",
            help="If True apply positive corrections",
        )
        parser.add_argument(
            "--apply-all-corrections",
            action="store_true",
            help="If True apply all corrections",
        )
        parser.add_argument(
            "--apply-nz",
            action="store_true",
            help="If True apply correction to nz state bases",
        )
        parser.add_argument(
            "--apply-pnz",
            action="store_true",
            help="If True apply correction to pnz state bases",
        )
        parser.add_argument(
            "--apply-pff",
            action="store_true",
            help="If True apply correction to pff source_type_id bases",
        )
        parser.add_argument(
            "--apply-auto",
            action="store_true",
            help="If True apply correction to auto  bases",
        )
        parser.add_argument(
            "--apply-home",
            action="store_true",
            help="If True apply correction to home bases",
        )

    args = parser.parse_args()

    return args
