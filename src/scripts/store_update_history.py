import os
import json

import numpy as np
import pandas as pd

from pathlib import Path
from datetime import datetime, timezone, timedelta

from src.utils.argument_parser_utils import parse_arguments
from src.utils import (
    categories_and_mapping,
    config,
    s3_bucket_utils,
    sync_local_and_main_db,
    db_conversion_utils,
)
from src.environment.initialize_environment import environment_info
from src.src_root import src_root

args = parse_arguments(Path(__file__).stem)
config_attr = config.load(args.config_file)

read_with_block_updates = config_attr["jobs"]["read_with_block_updates"]
env_name = environment_info.ENVIRONMENT_NAME.value
if env_name == "production":
    use_staging_env = False
else:
    use_staging_env = True


recommended_correction_dir = str(Path(src_root, config_attr["output_path"]))
local_bases_db_dir = os.path.join(
    recommended_correction_dir,
    "local_bases_db/",
)
sync_local_and_main_db.read_live_model_from_main_db(
    local_db_path=local_bases_db_dir,
    use_staging_env=use_staging_env,
    block_updates=read_with_block_updates,
    env_from_environment_info=True,
)

now = (
    datetime.now(timezone.utc)
    .astimezone(timezone.utc)
    .replace(tzinfo=None, second=0, microsecond=0)
)

five_weeks_ago = (now - timedelta(days=35)).replace(
    minute=0, second=0, microsecond=0
)
five_weeks_ago_str = five_weeks_ago.strftime("%Y-%m-%d %H:%M:%S")


# For state bases
state_bases_db_csv_file = os.path.join(
    local_bases_db_dir, "state_bases_local_db.csv"
)
state_bases_df = pd.read_csv(state_bases_db_csv_file, index_col=[0])
state_bases_df_copy = state_bases_df.copy()


all_timestamps = np.unique(state_bases_df["created_at"])
categories_and_mapping_dict = (
    categories_and_mapping.get_categories_and_mapping()
)

# For statebases nz for click
downstream_source_types = categories_and_mapping_dict[
    "downstream_source_types"
]
insurance_type_mapping = categories_and_mapping_dict["insurance_type_mapping"]

# For nz_rev_click state base time stamps
for downstream_source_type in downstream_source_types:
    if downstream_source_types in insurance_type_mapping["home"]:
        insurance_type = "home"
    else:
        insurance_type = "auto"
    update_history_file = os.path.join(
        recommended_correction_dir,
        f"update_history_{downstream_source_type}.json",
    )
    s3_bucket_utils.s3_download(update_history_file)
    df_for_type = db_conversion_utils.filter_by_state_group_type(
        db_conversion_utils.filter_by_param_name(
            db_conversion_utils.filter_by_model_id(
                state_bases_df, insurance_type
            ),
            "nz_rev_click",
        ),
        downstream_source_type,
    )
    if os.path.exists(update_history_file):
        with open(update_history_file, "r") as u_f:
            timestamp_dict = json.load(u_f)
    else:
        timestamp_dict = {}

    for index, row in df_for_type.iterrows():
        state, created_at = row[["state", "created_at"]]
        created_at = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S%z")
        created_at = created_at.strftime("%Y-%m-%d %H:%M:%S")
        if state in timestamp_dict.keys():
            timestamp_dict[state].append(created_at)
        else:
            timestamp_dict[state] = [created_at]
        current_timestamp_list = np.array(timestamp_dict[state])[
            np.array(timestamp_dict[state]) > five_weeks_ago_str
        ]
        timestamp_dict[state] = sorted(
            np.unique(current_timestamp_list).tolist()
        )
    with open(update_history_file, "w") as u_f:
        json.dump(timestamp_dict, u_f, indent=4)

    s3_bucket_utils.s3_upload(update_history_file)


# For pnz state base time stamps call and lead
partner_ids = categories_and_mapping_dict["partner_ids"]

for partner_id in partner_ids:
    if partner_id in insurance_type_mapping["home"]:
        insurance_type = "home"
    else:
        insurance_type = "auto"
    for rev_type in ["call", "lead"]:
        update_history_file = os.path.join(
            recommended_correction_dir,
            f"update_history_{partner_id}_{rev_type}.json",
        )
        s3_bucket_utils.s3_download(update_history_file)
        df_for_type = db_conversion_utils.filter_by_state_group_type(
            db_conversion_utils.filter_by_param_name(
                db_conversion_utils.filter_by_model_id(
                    state_bases_df, insurance_type
                ),
                f"pnz_{rev_type}",
            ),
            partner_id,
        )
        if os.path.exists(update_history_file):
            with open(update_history_file, "r") as u_f:
                timestamp_dict = json.load(u_f)
        else:
            timestamp_dict = {}

        for index, row in df_for_type.iterrows():
            state, created_at = row[["state", "created_at"]]

            created_at = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S%z")
            created_at = created_at.strftime("%Y-%m-%d %H:%M:%S")

            if state in timestamp_dict.keys():
                timestamp_dict[state].append(created_at)
            else:
                timestamp_dict[state] = [created_at]
            current_timestamp_list = np.array(timestamp_dict[state])[
                np.array(timestamp_dict[state]) > five_weeks_ago_str
            ]
            timestamp_dict[state] = sorted(
                np.unique(current_timestamp_list).tolist()
            )
        with open(update_history_file, "w") as u_f:
            json.dump(timestamp_dict, u_f, indent=4)

        s3_bucket_utils.s3_upload(update_history_file)

# For pff
pff_bases_db_csv_file = os.path.join(
    local_bases_db_dir, "feature_weights_local_db.csv"
)
pff_bases_df = pd.read_csv(pff_bases_db_csv_file, index_col=[0])

insurance_types = ["home", "auto"]


# For pff update time stamps per insurance type
update_history_file = os.path.join(
    recommended_correction_dir,
    "update_history_pff.json",
)
s3_bucket_utils.s3_download(update_history_file)
if os.path.exists(update_history_file):
    with open(update_history_file, "r") as u_f:
        timestamp_dict = json.load(u_f)
else:
    timestamp_dict = {k: [] for k in insurance_type}


df_for_type = db_conversion_utils.filter_by_param_name(
    (
        db_conversion_utils.filter_by_feature_group(
            pff_bases_df, "source_type_id"
        )
    ),
    "pff",
)

for index, row in df_for_type.iterrows():
    model_id, created_at = row[["model_id", "created_at"]]
    created_at = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S%z")
    created_at = created_at.strftime("%Y-%m-%d %H:%M:%S")

    if model_id in timestamp_dict.keys():
        timestamp_dict[model_id].append(created_at)
    else:
        timestamp_dict[model_id] = [created_at]
    current_timestamp_list = np.array(timestamp_dict[model_id])[
        np.array(timestamp_dict[model_id]) > five_weeks_ago_str
    ]
    timestamp_dict[model_id] = sorted(
        np.unique(current_timestamp_list).tolist()
    )
with open(update_history_file, "w") as u_f:
    json.dump(timestamp_dict, u_f, indent=4)

s3_bucket_utils.s3_upload(update_history_file)
# For pff update time stamps per insurance type per sourcetype id
for insurance_type in insurance_types:
    update_history_file = os.path.join(
        recommended_correction_dir,
        f"update_history_sourcetypeid_{insurance_type}.json",
    )
    s3_bucket_utils.s3_download(update_history_file)
    df_for_type = db_conversion_utils.filter_by_param_name(
        (
            db_conversion_utils.filter_by_feature_group(
                db_conversion_utils.filter_by_model_id(
                    pff_bases_df, insurance_type
                ),
                "source_type_id",
            )
        ),
        "pff",
    )
    if os.path.exists(update_history_file):
        with open(update_history_file, "r") as u_f:
            timestamp_dict = json.load(u_f)
    else:
        timestamp_dict = {}

    for index, row in df_for_type.iterrows():
        sourcetype_id, created_at = row[["feature_group_type", "created_at"]]
        created_at = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S%z")
        created_at = created_at.strftime("%Y-%m-%d %H:%M:%S")

        if sourcetype_id in timestamp_dict.keys():
            timestamp_dict[sourcetype_id].append(created_at)
        else:
            timestamp_dict[sourcetype_id] = [created_at]
        current_timestamp_list = np.array(timestamp_dict[sourcetype_id])[
            np.array(timestamp_dict[sourcetype_id]) > five_weeks_ago_str
        ]
        timestamp_dict[sourcetype_id] = sorted(
            np.unique(current_timestamp_list).tolist()
        )

    with open(update_history_file, "w") as u_f:
        json.dump(timestamp_dict, u_f, indent=4)
    s3_bucket_utils.s3_upload(update_history_file)
