import os
import sys
import subprocess
import json
import logging

import pandas as pd
import numpy as np

from pathlib import Path

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


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


env_name = environment_info.ENVIRONMENT_NAME.value
if env_name == "production":
    use_staging_env = False
else:
    use_staging_env = True


args = parse_arguments(Path(__file__).stem)
config_attr = config.load(args.config_file)
write_to_ds_app = config_attr["jobs"]["write_to_ds_app"]


apply_negative = False
apply_positive = False
apply_nz = False
apply_pnz = False
apply_pff = False
apply_home = False
apply_auto = False
if args.apply_all_corrections:
    apply_negative = True
    apply_positive = True
    apply_nz = True
    apply_pnz = True
    apply_pff = True
    apply_home = True
    apply_auto = True
else:
    if args.apply_negative_corrections:
        apply_negative = True
    else:
        apply_negative = False
    if args.apply_positive_corrections:
        apply_positive = True
    else:
        apply_positive = False

    if args.apply_nz:
        apply_nz = True
    if args.apply_pnz:
        apply_pnz = True
    if args.apply_pff:
        apply_pff = True

    if args.apply_home:
        apply_home = True
    if args.apply_auto:
        apply_auto = True

logging.info(
    f"""Arguments used
    apply_negative={apply_negative},
    apply_positive={apply_positive},
    apply_nz={apply_nz},
    apply_pnz={apply_pnz},
    apply_pff={apply_pff},
    apply_home={apply_home},
    apply_auto={apply_auto}
"""
)

recommended_correction_dir = str(Path(src_root, config_attr["output_path"]))

local_bases_db_dir = os.path.join(
    recommended_correction_dir, "local_bases_db/"
)

categories_and_mapping_dict = (
    categories_and_mapping.get_categories_and_mapping()
)
insurance_type_mapping = categories_and_mapping_dict["insurance_type_mapping"]

insurance_types = []
if apply_home:
    insurance_types.append("home")
if apply_auto:
    insurance_types.append("auto")
if insurance_types == []:
    sys.exit(
        "Exiting:  insurance_types is empty. "
        "Try using argument --apply-auto and/or --apply-home"
    )
if apply_positive is False and apply_negative is False:
    sys.exit(
        "Exiting:  specify sign of the correction to apply. "
        "Try using argument --apply-postive and/or --apply-negative"
    )

if apply_nz or apply_pnz:
    # for state bases
    state_bases_db_csv_file = os.path.join(
        local_bases_db_dir, "state_bases_local_db.csv"
    )

    state_bases_df = pd.read_csv(state_bases_db_csv_file, index_col=[0])
    state_bases_df_copy = state_bases_df.copy()


# Updating nz statebases for click rev
if apply_nz:
    downstream_source_types = categories_and_mapping_dict[
        "downstream_source_types"
    ]
    for source in downstream_source_types:
        insurance_type = None
        for insurtype in insurance_types:
            if source in insurance_type_mapping[insurtype]:
                insurance_type = insurtype
        if insurance_type is None:
            continue

        try:
            recommend_correction_file = os.path.join(
                recommended_correction_dir,
                f"recommended_correction_stateclickrev_{source}.json",
            )
            recommended_corrections = pd.read_json(
                recommend_correction_file, orient="index"
            )

        except FileNotFoundError:
            continue
        logger.info(f"Applying nz corrections to {source} {insurance_type}")
        original_bases = db_conversion_utils.filter_by_state_group_type(
            db_conversion_utils.filter_by_param_name(
                db_conversion_utils.filter_by_model_id(
                    state_bases_df, insurance_type
                ),
                "nz_rev_click",
            ),
            source,
        )
        all_states = original_bases.state
        for state in all_states:
            if state in recommended_corrections.index:
                recommended_correction = 1.0 + float(
                    recommended_corrections.loc[
                        state, "recommended_correction"
                    ]
                )
                apply_correction = False

                if recommended_correction >= 1:
                    if apply_positive:
                        apply_correction = True
                else:
                    if apply_negative:
                        apply_correction = True
                if recommended_correction != 1.0 and apply_correction:
                    index_of_base = original_bases.index[
                        original_bases["state"] == state
                    ].item()
                    state_bases_df_copy.loc[
                        index_of_base, "state_base"
                    ] *= recommended_correction

if apply_pnz:
    # Updating pnz state bases for call and lead
    partner_ids = categories_and_mapping_dict["partner_ids"]
    for partner_id in partner_ids:
        insurance_type = None
        for insurtype in insurance_types:
            if partner_id in insurance_type_mapping[insurtype]:
                insurance_type = insurtype
        if insurance_type is None:
            continue

        for rev_type in ["call", "lead"]:
            try:
                recommend_correction_file = os.path.join(
                    recommended_correction_dir,
                    "recommended_correction_state"
                    f"{rev_type}pnz_{partner_id}.json",
                )
                recommended_corrections = pd.read_json(
                    recommend_correction_file, orient="index"
                )

            except FileNotFoundError:
                continue
            logger.info(
                "Applying pnz corrections to "
                f"{rev_type} {partner_id} {insurance_type}"
            )
            original_bases = db_conversion_utils.filter_by_state_group_type(
                db_conversion_utils.filter_by_param_name(
                    db_conversion_utils.filter_by_model_id(
                        state_bases_df, insurance_type
                    ),
                    f"pnz_{rev_type}",
                ),
                partner_id.split("_")[0],
            )

            all_states = original_bases.state
            for state in all_states:
                if state in recommended_corrections.index:
                    recommended_correction = 1.0 + float(
                        recommended_corrections.loc[
                            state, "recommended_correction"
                        ]
                    )
                    apply_correction = False

                    if recommended_correction >= 1:
                        if apply_positive:
                            apply_correction = True
                    else:
                        if apply_negative:
                            apply_correction = True
                    if recommended_correction != 1.0 and apply_correction:
                        index_of_base = original_bases.index[
                            original_bases["state"] == state
                        ].item()
                        state_bases_df_copy.loc[
                            index_of_base, "state_base"
                        ] *= recommended_correction

if apply_nz or apply_pnz:
    state_bases_df_copy.to_csv(state_bases_db_csv_file, index_label="id")

if apply_pff:
    # Updating pff bases
    pff_bases_db_csv_file = os.path.join(
        local_bases_db_dir, "feature_weights_local_db.csv"
    )
    pff_bases_df = pd.read_csv(pff_bases_db_csv_file, index_col=[0])

    pff_bases_df_copy = pff_bases_df.copy()

    old_source_type_ids_dict = {k: [] for k in insurance_types}
    new_source_type_ids_dict = {k: [] for k in insurance_types}

    for insurance_type in insurance_types:
        try:
            recommend_correction_file = os.path.join(
                recommended_correction_dir,
                f"recommended_correction_pff_{insurance_type}.json",
            )
            recommended_corrections = pd.read_json(
                recommend_correction_file, orient="index"
            )

        except FileNotFoundError:
            continue
        logger.info(f"Applying pff corrections to {insurance_type}")
        original_bases = db_conversion_utils.filter_by_param_name(
            db_conversion_utils.filter_by_feature_group(
                db_conversion_utils.filter_by_model_id(
                    pff_bases_df, insurance_type
                ),
                "source_type_id",
            ),
            "pff",
        )

        current_source_type_ids = original_bases.feature_group_type.tolist()

        all_source_type_ids = recommended_corrections.index
        for source_type_id in all_source_type_ids:
            if str(source_type_id) in current_source_type_ids:
                old_source_type_ids_dict[insurance_type].append(source_type_id)
            else:
                new_source_type_ids_dict[insurance_type].append(source_type_id)
        for source_type_id in old_source_type_ids_dict[insurance_type]:
            recommended_correction = 1.0 + float(
                recommended_corrections.loc[
                    source_type_id, "recommended_correction"
                ]
            )
            apply_correction = False
            if recommended_correction >= 1:
                if apply_positive:
                    apply_correction = True
            else:
                if apply_negative:
                    apply_correction = True
            if apply_correction:

                index_of_base = original_bases.index[
                    original_bases["feature_group_type"] == str(source_type_id)
                ]
                if recommended_correction != 0:
                    pff_bases_df_copy.loc[
                        index_of_base, "feature_weight"
                    ] *= recommended_correction
                else:
                    if (
                        pff_bases_df_copy.loc[index_of_base, "feature_weight"]
                        < 0.001
                    ):
                        pff_bases_df_copy.loc[
                            index_of_base, "feature_weight"
                        ] = 0.001
    for insurance_type in insurance_types:
        try:
            recommend_correction_file = os.path.join(
                recommended_correction_dir,
                f"recommended_correction_pff_{insurance_type}.json",
            )
            recommended_corrections = pd.read_json(
                recommend_correction_file, orient="index"
            )

        except FileNotFoundError:
            continue
        original_bases = db_conversion_utils.filter_by_param_name(
            db_conversion_utils.filter_by_feature_group(
                db_conversion_utils.filter_by_model_id(
                    pff_bases_df, insurance_type
                ),
                "source_type_id",
            ),
            "pff",
        )

        row_to_copy = original_bases.iloc[0].to_frame().T

        max_index = max(pff_bases_df_copy.index)

        for source_type_id in new_source_type_ids_dict[insurance_type]:
            recommended_correction = 1.0 + float(
                recommended_corrections.loc[
                    source_type_id, "recommended_correction"
                ]
            )
            apply_correction = False
            if recommended_correction >= 1:
                if apply_positive:
                    apply_correction = True
            else:
                if apply_negative:
                    apply_correction = True
            if apply_correction:

                row_to_copy_updated = row_to_copy.copy()
                row_to_copy_updated["feature_group_type"] = str(source_type_id)
                row_to_copy_updated["feature_weight"] = (
                    1.0 * recommended_correction
                )
                row_to_copy_updated["flat_scaleup_factor"] = 1.0

                row_to_copy_updated.index = [max_index + 1]
                pff_bases_df_copy = pd.concat(
                    [pff_bases_df_copy, row_to_copy_updated],
                    axis=0,
                )
            max_index += 1

    pff_bases_df_copy = pff_bases_df_copy.replace("", np.nan, inplace=False)
    pff_bases_df_copy.to_csv(
        pff_bases_db_csv_file, na_rep="NaN", index_label="id"
    )

if write_to_ds_app:
    sync_local_and_main_db.write_new_model_to_main_db(
        local_db_path=local_bases_db_dir,
        updated_by="monitor",
        disable_user_input=False,
        use_staging_env=use_staging_env,
        unblock_updates=True,
        env_from_environment_info=True,
    )
