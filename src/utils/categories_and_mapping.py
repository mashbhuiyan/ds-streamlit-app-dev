import os
import json
from pathlib import Path

from src.src_root import src_root

script_path = Path(src_root).resolve().joinpath("static")


def get_categories_and_mapping():
    with open(
        os.path.join(script_path, "categories_and_mapping.json"), "r"
    ) as f:
        categories_and_mapping = json.load(f)
    return categories_and_mapping
