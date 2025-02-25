import os
import math
import logging

import numpy as np
import pandas as pd
import streamlit as st
from pathlib import Path
from PIL import Image, ImageFile
from datetime import datetime, timedelta, timezone


# Project imports
from .backend_helper import BackendHelper
from .io_utils import md5_hash
from src.utils.argument_parser_utils import parse_arguments
from src.utils import save_plots_and_table, config, categories_and_mapping
from src.src_root import src_root
from src.environment.initialize_environment import environment_info


env_name = environment_info.ENVIRONMENT_NAME.value

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


ImageFile.LOAD_TRUNCATED_IMAGES = True

st.set_page_config(layout="wide")


categories_and_mapping_dict = (
    categories_and_mapping.get_categories_and_mapping()
)

rev_types = categories_and_mapping_dict["rev_types"]
rev_type_color = categories_and_mapping_dict["rev_type_color"]
campaign_ids = categories_and_mapping_dict["campaign_ids"]
campaign_ids_l = sorted(np.array(campaign_ids).astype(int))
partner_ids = categories_and_mapping_dict["partner_ids"]
downstream_source_types = categories_and_mapping_dict[
    "downstream_source_types"
]
insurance_types = categories_and_mapping_dict["insurance_types"]
partner_campaign_mapping = categories_and_mapping_dict[
    "partner_campaign_mapping"
]
downstreamsource_campaign_mapping = categories_and_mapping_dict[
    "downstreamsource_campaign_mapping"
]
insurance_type_mapping = categories_and_mapping_dict["insurance_type_mapping"]
list_of_states = sorted(categories_and_mapping_dict["list_of_states"])


colors_dict = {
    "green": "#73c983",
    "yellow": "#f2f283",
    "orange": "#f5aa42",
    "red": "#f2838c",
    "grey": "#9a9c9a",
}

flag_colors = {
    "A": colors_dict["green"],
    "B": colors_dict["yellow"],
    "C": colors_dict["orange"],
    "D": colors_dict["red"],
    "E": colors_dict["grey"],
}
flag_colors_legend_type1 = {
    "A": "All bins have abs(relative click revenue difference)<= 0.1 ",
    "B": (
        "At least one bin has abs(relative click revenue difference)>0.1"
        " and <=0.25 "
    ),
    "C": (
        "At least one bin has abs(relative click revenue difference)>0.25"
        " and <=0.5 "
    ),
    "D": "At least one bin has abs(relative click revenue difference)>0.5",
    "E": "Single bin without enough statistcics",
}

flag_colors_legend_type2 = {
    "A": "abs(zscore)<1",
    "B": "abs(zscore)>1 and abs(zscore)<2.5",
    "D": "abs(zscore)>2.5",
    "E": "zscore not available",
}


priority_dict = {
    "5": "last 5 bins are within priority hours.",
    "4": "last 4 bins are within priority hours.",
    "3": "last 3 bins are within priority hours.",
    "2": "last 2 bins are within priority hours.",
    "1": "last 1 bins are within priority hours.",
    "0": "last bin is wider than priority hours.",
}

tab_types = [
    "by campaign_id",
    "by partner_id",
    "by downstream_source",
    "by state",
    "by source_type_id",
    "all revenue plots",
    "all pff plots",
    "overall",
]


def apply_color(color):
    color = flag_colors[color]
    return f"background-color: {color}"


def display_image(filename, st_object):
    with Image.open(filename) as image:
        st_object.image(image)


def set_revenue_tab(st_object, name, plot_limits, config_attr, summary_path):
    now = (
        datetime.now(timezone.utc)
        .astimezone(timezone.utc)
        .replace(tzinfo=None, second=0, microsecond=0)
    ) + timedelta(hours=25)
    four_weeks_ago = (now - timedelta(days=28)).replace(
        minute=0, second=0, microsecond=0
    )
    three_weeks_ago = (now - timedelta(days=21)).replace(
        minute=0, second=0, microsecond=0
    )
    col1, col2 = st_object.columns([3, 1])

    with col1:
        binning_type_choice = st_object.radio(
            "Select binning type:",
            [
                "equal count",
                "equal width",
            ],
            key=f"bin_type_{name}",
        )
        binning_type = binning_type_choice.replace(" ", "")
        name += f"_{binning_type}"
        if not f"revenue_{name}" in plot_limits.keys():
            plot_limits[f"revenue_{name}"] = {}
        old_plot_limits = plot_limits[f"revenue_{name}"].copy()

        plot_limits[f"revenue_{name}"]["binning_type"] = binning_type
        if binning_type == "equalwidth":
            time_bin = st_object.number_input(
                "Select bin size (hours):",
                min_value=1,
                value=24,
                step=1,
                format="%d",
                key=f"time_bin_{name}",
            )
            time_bin = f"{time_bin}H"
            plot_limits[f"revenue_{name}"]["time_bin_width"] = time_bin

        elif binning_type == "equalcount":
            min_count_per_bin = st_object.number_input(
                "Select target count of events per bin:",
                min_value=30,
                value=200,
                step=5,
                format="%i",
                key=f"target_count_{name}",
            )

            plot_limits[f"revenue_{name}"][
                "min_count_per_bin"
            ] = min_count_per_bin

        date_time_min, date_time_max = st_object.slider(
            "Select datetime range:",
            min_value=four_weeks_ago,
            max_value=now,
            value=(three_weeks_ago, now),
            step=timedelta(hours=24),
            key=name,
        )

        plot_limits[f"revenue_{name}"]["date_time_min"] = int(
            date_time_min.timestamp() * 1000
        )
        plot_limits[f"revenue_{name}"]["date_time_max"] = int(
            date_time_max.timestamp() * 1000
        )

    col1, col2 = st_object.columns([3, 1])
    with col2:
        lines = ["revenue", "payout", "revenue expected"]
        show_lines = {
            line: st_object.checkbox(
                f"{line}", value=True, key=f"{line}_{name}"
            )
            for line in lines
        }
        for rev_type in rev_types:
            line = f"{rev_type} revenue"
            show_lines[line] = st_object.checkbox(
                f"{line}", value=True, key=f"{line}_{name}"
            )
            line = f"{rev_type} revenue expected"

            show_lines[line] = st_object.checkbox(
                f"{line}", value=False, key=f"{line}_{name}"
            )
        lines = str([k for k in show_lines.keys() if show_lines[k] is True])

        plot_limits[f"revenue_{name}"]["lines"] = lines
        pd.DataFrame(plot_limits).to_json(
            os.path.join(summary_path, "plot_limits_revenue.json")
        )
    if (old_plot_limits != plot_limits[f"revenue_{name}"]).any():
        save_plots_and_table.GeneratePlotsAndTable(
            config_attr
        ).generate_plots_for_revenue_tab(
            t_name=f"revenue_{name}",
            plot_list=["revenue_payout"],
        )
    if (
        old_plot_limits.drop(columns=["lines"])
        != plot_limits[f"revenue_{name}"].drop(columns=["lines"])
    ).any():
        save_plots_and_table.GeneratePlotsAndTable(
            config_attr
        ).generate_plots_for_revenue_tab(
            t_name=f"revenue_{name}",
            plot_list=[
                "revenue_exp_cm",
                "revenue_frac",
                "cm",
                "pff",
                "revenue_nz",
            ],
        )

    with col1:
        display_image(
            os.path.join(summary_path, f"revenue_{name}_revenue_payout.png"),
            st_object,
        )

    col1, col2 = st_object.columns([3, 1])
    with col1:
        display_image(
            os.path.join(summary_path, f"revenue_{name}_revexpcm_full.png"),
            st_object,
        )

    col1, col2 = st_object.columns([3, 1])
    old_plot_limits = plot_limits[f"revenue_{name}"].copy()
    with col2:
        ymax = st_object.number_input(
            "Enter the maximum y-axis limit:", value=0.5, key=f"rev_max_{name}"
        )
        ymin = st_object.number_input(
            "Enter the minimum y-axis limit:",
            value=-0.5,
            key=f"rev_min_{name}",
        )
        plot_limits[f"revenue_{name}"]["rev_ymin"] = ymin
        plot_limits[f"revenue_{name}"]["rev_ymax"] = ymax

    pd.DataFrame(plot_limits).to_json(
        os.path.join(summary_path, "plot_limits_revenue.json")
    )

    if (old_plot_limits != plot_limits[f"revenue_{name}"]).any():
        save_plots_and_table.GeneratePlotsAndTable(
            config_attr
        ).generate_plots_for_revenue_tab(
            t_name=f"revenue_{name}",
            plot_list=["revenue_exp_cm"],
        )

    with col1:
        display_image(
            os.path.join(
                summary_path, f"revenue_{name}_revexpcm_truncated.png"
            ),
            st_object,
        )

    col1, col2 = st_object.columns([3, 1])
    with col1:
        display_image(
            os.path.join(summary_path, f"revenue_{name}_revfrac.png"),
            st_object,
        )

    col1, col2 = st_object.columns([3, 1])
    with col1:
        display_image(
            os.path.join(summary_path, f"revenue_{name}_revnz.png"),
            st_object,
        )
        display_image(
            os.path.join(summary_path, f"revenue_{name}_revfracnz.png"),
            st_object,
        )

    col1, col2 = st_object.columns([3, 1])
    with col1:
        display_image(
            os.path.join(summary_path, f"revenue_{name}_pff.png"),
            st_object,
        )

    col1, col2 = st_object.columns([3, 1])
    with col1:
        display_image(
            os.path.join(summary_path, f"revenue_{name}_cm.png"),
            st_object,
        )
    st_object.markdown("### Data Summary")
    revenue_df = pd.read_json(
        os.path.join(summary_path, f"revenue_{name}.json"),
        orient="records",
    )
    if "datetime_min" in revenue_df.keys():
        revenue_df["datetime_min"] = pd.to_datetime(
            revenue_df["datetime_min"], unit="ms"
        )
        revenue_df["datetime_max"] = pd.to_datetime(
            revenue_df["datetime_max"], unit="ms"
        )
        revenue_df["bin_width"] = pd.to_timedelta(
            revenue_df["bin_width"], unit="ms"
        )
    st_object.dataframe(
        revenue_df.sort_values(by="datetime", ascending=False).reset_index(
            drop=True
        )
    )


def set_combined_plots_tab(
    st_object,
    t_name,
    plot_limits,
    config_attr,
    downstream_source_type=None,
    partner_id=None,
):
    output_path = str(Path(src_root, config_attr["output_path"]).resolve())
    summary_path = os.path.join(output_path, "summary")

    now = (
        datetime.now(timezone.utc)
        .astimezone(timezone.utc)
        .replace(tzinfo=None, second=0, microsecond=0)
    ) + timedelta(hours=25)
    four_weeks_ago = (now - timedelta(days=28)).replace(
        minute=0, second=0, microsecond=0
    )
    three_weeks_ago = (now - timedelta(days=21)).replace(
        minute=0, second=0, microsecond=0
    )
    if downstream_source_type:
        key = f"{t_name}_{downstream_source_type}"
    elif partner_id:
        key = f"{t_name}_{partner_id}"
    else:
        key = t_name

    col1, col2 = st_object.columns([3, 1])
    with col1:

        date_time_min, date_time_max = st_object.slider(
            "Select datetime range:",
            min_value=four_weeks_ago,
            max_value=now,
            value=(three_weeks_ago, now),
            step=timedelta(hours=24),
            key=key,
        )

    if t_name in ["all revenue plots", "all state revenue plots"]:
        plot_type = "revexpcm_truncated"
        plot_list = ["revenue_exp_cm"]
        key_type = "rev"
    elif t_name == "all pff plots":
        plot_type = "pff"
        plot_list = ["pff"]
        key_type = "pff"
    if t_name in ["all revenue plots", "all pff plots"]:
        all_categories = campaign_ids + partner_ids + downstream_source_types
    else:
        all_categories = list_of_states
    if t_name == "all state revenue plots":
        binning_type = "equalcount"
    else:
        binning_type = st_object.radio(
            "Select binning type",
            [
                "equal count",
                "equal width",
            ],
            key=f"{key_type}_{key}",
        )
        binning_type = binning_type.replace(" ", "")

    for cat in all_categories:
        try:
            if cat in campaign_ids:
                name_type = "campaign_id = "
                filename_str = "campaign"
                campaign_str = ""
            elif cat in downstream_source_types:
                name_type = "downstream_source_type = "
                filename_str = "source"
                campaign_str = (
                    "; campaigns = "
                    f"{downstreamsource_campaign_mapping[cat]}"
                )
            elif cat in partner_ids:
                name_type = "partner_id = "
                filename_str = "partner"
                campaign_str = f"; campaigns = {partner_campaign_mapping[cat]}"
            elif cat in list_of_states:
                name_type = "state = "
                if downstream_source_type:
                    filename_str = f"source_{downstream_source_type}_state"
                    campaign_str = (
                        "; campaigns = "
                        f"""{downstreamsource_campaign_mapping[
                            downstream_source_type]
                        }"""
                    )
                elif partner_id:
                    filename_str = f"partner_{partner_id}_state"
                    campaign_str = (
                        "; campaigns = "
                        f"""{partner_campaign_mapping[
                            partner_id]
                        }"""
                    )
            st_object.markdown(f"### {name_type}{cat}{campaign_str}")
            name = f"revenue_plots_{filename_str}_{cat}_{binning_type}"
            col1, col2 = st_object.columns([3, 1])
            old_plot_limits = plot_limits[name]
            with col1:
                if binning_type == "equalcount":
                    if t_name == "all state revenue plots":
                        default_count = 50
                    else:
                        default_count = 200

                    min_count_per_bin = st_object.number_input(
                        "Select target count of events per bin:",
                        min_value=30,
                        value=default_count,
                        step=5,
                        format="%i",
                        key=(
                            f"target_count_{filename_str}_{cat}"
                            f"_{key}_{plot_type}"
                        ),
                    )
                    plot_limits[name]["min_count_per_bin"] = min_count_per_bin
                else:
                    time_bin = st_object.number_input(
                        "Select bin size (hours):",
                        min_value=1,
                        value=24,
                        step=1,
                        format="%d",
                        key=(
                            f"time_bin_{filename_str}_{cat}"
                            f"_{key}_{plot_type}"
                        ),
                    )
                    time_bin = f"{time_bin}H"
                    plot_limits[name]["time_bin_width"] = time_bin

            with col2:
                if plot_type != "pff":
                    ymax = st_object.number_input(
                        "Enter the maximum y-axis limit:",
                        value=0.5,
                        key=(
                            f"key_type_max_{filename_str}"
                            f"_{cat}_{key}_{plot_type}"
                        ),
                    )
                    ymin = st_object.number_input(
                        "Enter the minimum y-axis limit:",
                        value=-0.5,
                        key=(
                            f"{key_type}_min_{filename_str}"
                            f"_{cat}_{key}_{plot_type}"
                        ),
                    )
                    plot_limits[name][f"{key_type}_ymin"] = ymin
                    plot_limits[name][f"{key_type}_ymax"] = ymax
                    plot_limits[name]["binning_type"] = binning_type

            plot_limits[name]["date_time_min"] = date_time_min
            plot_limits[name]["date_time_max"] = date_time_max

            pd.DataFrame(plot_limits).to_json(
                os.path.join(summary_path, "plot_limits_revenue.json")
            )
            if t_name != "all state revenue plots":
                if (old_plot_limits != plot_limits[name]).any():
                    save_plots_and_table.GeneratePlotsAndTable(
                        config_attr
                    ).generate_plots_for_revenue_tab(
                        t_name=name, plot_list=plot_list
                    )
            else:
                if (old_plot_limits != plot_limits[name]).any():
                    save_plots_and_table.GeneratePlotsAndTable(
                        config_attr
                    ).generate_plots_for_state_tab(t_name=name)

            with col1:
                display_image(
                    os.path.join(
                        summary_path,
                        (
                            f"revenue_plots_{filename_str}_{cat}"
                            f"_{binning_type}_{plot_type}.png"
                        ),
                    ),
                    st_object,
                )

        except Exception as e:
            logging.exception(e)
            continue


def format_table_for_display(df):
    def format_single_element_list(dataframe, column_name):
        for i, d in enumerate(dataframe[column_name]):
            if d is not None:
                if isinstance(d, list):
                    dataframe[column_name][i] = [
                        round(d[0], 2) if d[0] is not None else d[0]
                    ]
        return dataframe

    def format_multiple_element_list(dataframe, column_name):
        for i, d_i in enumerate(dataframe[column_name]):
            if d_i is not None:
                if isinstance(d_i, list):
                    if len(d_i) >= 1:
                        for j, d_i_j in enumerate(d_i):
                            if d_i_j is not None:
                                dataframe[column_name][i][j] = round(d_i_j, 2)
        return dataframe

    def format_single_number_list(dataframe, column_name, ndigits=2):
        if column_name in dataframe.keys():
            dataframe[column_name] = [
                str(round(d, ndigits)) if not math.isnan(d) else None
                for d in dataframe[column_name]
            ]
        return dataframe

    df.index = [str(d) for d in df.index]
    df["recommended_correction"] = [
        str(round(d, 2)) for d in df["recommended_correction"]
    ]
    df["most_recent_event_before"] = pd.to_datetime(
        df["most_recent_event_before"], unit="ms"
    )
    if "after_last_update:number_of_bins" in df.keys():
        df["after_last_update:number_of_bins"] = [
            str(d) for d in df["after_last_update:number_of_bins"]
        ]
        df = format_single_element_list(df, "CUSUM:average_correction")
        df = format_single_element_list(
            df, "after_last_update:average_correction"
        )
        df = format_single_element_list(df, "all_data:average_correction")
        df = format_single_element_list(
            df, "last_5_bins_in_priority:average_correction"
        )
        df = format_single_element_list(df, "last_2_weeks:average_correction")
        df = format_single_element_list(
            df, "last_4_hours_after_correction:average_correction"
        )

        df["max_bin_width"] = pd.to_timedelta(df["max_bin_width"], unit="ms")
        df["min_bin_width"] = pd.to_timedelta(df["min_bin_width"], unit="ms")
        df = format_multiple_element_list(
            df, "last_5_bins:cumulative_average_correction"
        )
        df["min_n_events_per_bin"] = [
            str(int(d)) if not math.isnan(d) else d
            for d in df["min_n_events_per_bin"]
        ]
        df["max_n_events_per_bin"] = [
            str(int(d)) if not math.isnan(d) else d
            for d in df["max_n_events_per_bin"]
        ]
    for k in [
        "zscore",
        "zscore_threshold",
        "nff_expected",
        "nff_measured",
        "pff_expected",
        "pff_measured",
        "conf_int:correction",
        "current_weight",
        "overall_correction",
        "new_weight",
    ]:
        format_single_number_list(df, k)

    if "conf_int" in df.keys():
        df["conf_int"] = [
            (
                [round(conf_int[0], 2), round(conf_int[1], 2)]
                if conf_int is not None
                else None
            )
            for conf_int in df["conf_int"]
        ]

    if "last_5_bins:relative_click_revenue_diff" in df.keys():
        df = format_multiple_element_list(
            df, "last_5_bins:relative_click_revenue_diff"
        )
    elif "last_5_bins:relative_pff_diff" in df.keys():
        df = format_multiple_element_list(df, "last_5_bins:relative_pff_diff")
    return df


def start_streamlit_app(config_attr):

    output_path = str(Path(src_root, config_attr["output_path"]).resolve())
    summary_path = os.path.join(output_path, "summary")
    if not os.path.exists(summary_path):
        os.makedirs(summary_path)

    now = (
        datetime.now(timezone.utc)
        .astimezone(timezone.utc)
        .replace(tzinfo=None, second=0, microsecond=0)
    ) + timedelta(hours=25)
    four_weeks_ago = (now - timedelta(days=28)).replace(
        minute=0, second=0, microsecond=0
    )
    three_weeks_ago = (now - timedelta(days=21)).replace(
        minute=0, second=0, microsecond=0
    )
    if env_name != "prod":
        st.markdown(
            f"""
        <div style="background-color:#FFCCCC;padding:5px;border-radius:5px">
            <h4 style="color:black;text-align:center;">
            {env_name.upper()} ENVIRONMENT
            </h4>
        </div>
        """,
            unsafe_allow_html=True,
        )
    with open(os.path.join(output_path, "last_day.txt")) as f:
        last_query_at = f.readlines()[0].rstrip()

    now_diff = (
        datetime.now(timezone.utc)
        .astimezone(timezone.utc)
        .replace(tzinfo=None, second=0, microsecond=0)
    ) - datetime.strptime(last_query_at, "%Y-%m-%d %H:%M:%S")

    st.sidebar.write(f"Last query at {last_query_at} UTC ({now_diff} ago)")

    st.title("Daily Monitor")
    main_selection = st.sidebar.radio(
        "", ["Latency and Output Code", "Revenue"]
    )

    # ----------------------------------------------------------------------------------
    if main_selection == "Latency and Output Code":
        plot_limits_path = os.path.join(
            summary_path, "plot_limits_latency.json"
        )
        if os.path.exists(plot_limits_path):
            plot_limits = pd.read_json(plot_limits_path)
        else:
            plot_limits = {}

        col1, col2 = st.columns([3, 1])
        latency_df = pd.read_json(
            os.path.join(summary_path, "latency.json"), orient="records"
        )
        with col1:
            if "latency" not in plot_limits:
                plot_limits["latency"] = {}
            old_plot_limits = plot_limits["latency"].copy()

            date_time_min, date_time_max = st.slider(
                "Select datetime range:",
                min_value=four_weeks_ago,
                max_value=now,
                value=(three_weeks_ago, now),
                step=timedelta(days=1),
                key="latency",
            )

            plot_limits["latency"]["date_time_min"] = int(
                date_time_min.timestamp() * 1000
            )
            plot_limits["latency"]["date_time_max"] = int(
                date_time_max.timestamp() * 1000
            )

            pd.DataFrame(plot_limits).to_json(plot_limits_path)
            if (old_plot_limits != plot_limits["latency"]).any():

                save_plots_and_table.GeneratePlotsAndTable(
                    config_attr
                ).generate_plots_for_latency_tab()

            display_image(os.path.join(summary_path, "latency.png"), st)
            display_image(
                os.path.join(summary_path, "frac_high_latency.png"), st
            )
            display_image(
                os.path.join(summary_path, "n_output_code_above_100.png"), st
            )

        st.markdown("### Data Summary")
        st.dataframe(latency_df)
    # -----------------------------------------------------------------------------
    if main_selection == "Revenue":
        plot_limits_path = os.path.join(
            summary_path, "plot_limits_revenue.json"
        )
        if os.path.exists(plot_limits_path):
            plot_limits = pd.read_json(plot_limits_path)
        else:
            plot_limits = {}

        revenue_selection = st.sidebar.radio(
            "Select category",
            tab_types,
        )
        # --------------------------------------------------------------
        if revenue_selection == "overall":
            try:
                set_revenue_tab(
                    st,
                    name=f"individual_{revenue_selection}",
                    plot_limits=plot_limits,
                    config_attr=config_attr,
                    summary_path=summary_path,
                )
            except Exception as e:
                logger.exception(e)
                pass
        # -------------------------------------------------------------
        if revenue_selection == "by campaign_id":
            campaign_tabs = st.tabs(campaign_ids)

            for campaign_tab, campaign_id in zip(campaign_tabs, campaign_ids):
                try:
                    with campaign_tab:
                        set_revenue_tab(
                            st,
                            name=f"individual_campaign_{campaign_id}",
                            plot_limits=plot_limits,
                            config_attr=config_attr,
                            summary_path=summary_path,
                        )
                except Exception as e:
                    logger.exception(e)
                    continue
        # --------------------------------------------------------
        if revenue_selection == "by partner_id":
            partner_tabs = st.tabs(partner_ids)

            for partner_tab, partner_id in zip(partner_tabs, partner_ids):
                try:
                    with partner_tab:
                        set_revenue_tab(
                            st,
                            name=f"individual_partner_{partner_id}",
                            plot_limits=plot_limits,
                            config_attr=config_attr,
                            summary_path=summary_path,
                        )
                except Exception as e:
                    logger.exception(e)
                    continue
        # ----------------------------------------------------------------
        if revenue_selection == "by downstream_source":
            downstream_source_tabs = st.tabs(downstream_source_types)

            for downstream_source_tab, downstream_source_type in zip(
                downstream_source_tabs, downstream_source_types
            ):
                try:
                    with downstream_source_tab:
                        set_revenue_tab(
                            st,
                            name=f"individual_source_{downstream_source_type}",
                            plot_limits=plot_limits,
                            config_attr=config_attr,
                            summary_path=summary_path,
                        )
                except Exception as e:
                    logger.exception(e)
                    continue
        # ------------------------------------------------------------

        if revenue_selection in ["all revenue plots", "all pff plots"]:
            set_combined_plots_tab(
                st,
                t_name=revenue_selection,
                config_attr=config_attr,
                plot_limits=plot_limits,
            )
        # ------------------------------------------------------------
        if revenue_selection == "by state":
            state_tab_selection = st.sidebar.radio(
                "Select summary type",
                ["table", "plots"],
            )

            if state_tab_selection == "table":
                rev_type_tab_selection = st.sidebar.radio(
                    "Select revenue type",
                    ["click (nz)", "lead (pnz)", "call (pnz)"],
                )
                if rev_type_tab_selection == "click (nz)":
                    st.latex(
                        r"""
                        \text{relative nz difference}:
                        Rev_{\text{diff}} =
                        \frac{Rev_{\text{measured}}
                        -Rev_{\text{expected}}}
                        {Rev_{\text{expected}}}
                    """
                    )

                    col1, col2 = st.columns([1, 1])
                    with col1:
                        st.markdown("#### Color Legend")
                        for color in flag_colors.keys():
                            st.markdown(
                                f"""
                            <div style="display: flex; align-items: center;">
                                <div style="width: 20px; height: 20px;
                                background-color:
                                {flag_colors[color]}; margin-right: 10px;">
                                </div>
                                <div>{flag_colors_legend_type1[color]}</div>
                            </div>
                            """,
                                unsafe_allow_html=True,
                            )

                    with col2:
                        st.markdown("#### Priority Legend")
                        for priority in priority_dict.keys():
                            st.write(f"{priority}: {priority_dict[priority]}")

                    downstreamsource_tabs = st.tabs(downstream_source_types)
                    min_count_per_bin = st.sidebar.number_input(
                        "Select target count of events per bin:",
                        min_value=30,
                        value=50,
                        step=5,
                        format="%i",
                        key="target_count_state",
                    )

                    priority_limit = st.sidebar.number_input(
                        "last 5 bins: Select priority hours:",
                        min_value=1,
                        value=48,
                        step=1,
                        format="%i",
                        key="priority_limit",
                    )

                    plot_limits = pd.read_json(plot_limits_path)

                    for downstream_source_tab, downstream_source_type in zip(
                        downstreamsource_tabs, downstream_source_types
                    ):
                        name = save_plots_and_table.get_tab_name(
                            tab_type="table",
                            table_type="state",
                            downstream_source_type=downstream_source_type,
                            binning_type="equalcount",
                            revenue_type="click",
                        )

                        old_plot_limits = plot_limits[name].copy()
                        plot_limits[name][
                            "min_count_per_bin"
                        ] = min_count_per_bin
                        plot_limits[name]["priority_limit"] = priority_limit
                        pd.DataFrame(plot_limits).to_json(
                            os.path.join(
                                summary_path, "plot_limits_revenue.json"
                            )
                        )
                        if (old_plot_limits != plot_limits[name]).any():
                            save_plots_and_table.GeneratePlotsAndTable(
                                config_attr
                            ).generate_table_for_state_tab(name)

                        downstream_source_table = pd.read_json(
                            os.path.join(
                                summary_path,
                                (f"{name}.json"),
                            ),
                            orient="records",
                        )

                        with downstream_source_tab:
                            if not downstream_source_table.empty:
                                downstream_source_table = (
                                    format_table_for_display(
                                        downstream_source_table
                                    )
                                )
                                table_height = int(
                                    35.05 * (len(downstream_source_table) + 1)
                                )

                                downstream_source_table = (
                                    downstream_source_table.style.applymap(
                                        apply_color, subset=["flag"]
                                    )
                                )
                                print_campaign = categories_and_mapping_dict[
                                    "downstreamsource_campaign_mapping"
                                ]
                                st.markdown(
                                    "campaign_ids = "
                                    f"{print_campaign[downstream_source_type]}"
                                )
                                st.dataframe(
                                    downstream_source_table,
                                    use_container_width=True,
                                    height=table_height,
                                )
                if rev_type_tab_selection in ["lead (pnz)", "call (pnz)"]:

                    st.latex(
                        r"""
                            \text{relative pnz difference}:
                            pnz_{\text{diff}} =
                            \frac{pnz_{\text{measured}}
                            -pnz_{\text{expected}}}
                            {pnz_{\text{expected}}}
                        """
                    )

                    col1, col2 = st.columns([1, 1])
                    with col1:
                        st.markdown("#### Color Legend")
                        for color in flag_colors.keys():
                            st.markdown(
                                f"""
                                <div style="display: flex; align-items:
                                 center;">
                                    <div style="width: 20px; height: 20px;
                                    background-color:
                                    {flag_colors[color]}; margin-right: 10px;">
                                    </div>
                                    <div>{flag_colors_legend_type1[color]}</div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                    with col2:
                        st.markdown("#### Priority Legend")
                        for priority in priority_dict.keys():
                            st.write(f"{priority}: {priority_dict[priority]}")

                    partnerid_tabs = st.tabs(partner_ids)
                    # -----------------------------------------------------------------
                    min_count_per_bin = st.sidebar.number_input(
                        "Select target count of events per bin:",
                        min_value=30,
                        value=50,
                        step=5,
                        format="%i",
                        key="target_count_state",
                    )

                    priority_limit = st.sidebar.number_input(
                        "last 5 bins: Select priority hours:",
                        min_value=1,
                        value=48,
                        step=1,
                        format="%i",
                        key="priority_limit",
                    )

                    plot_limits = pd.read_json(plot_limits_path)

                    for partnerid_tab, partner_id in zip(
                        partnerid_tabs, partner_ids
                    ):

                        name = save_plots_and_table.get_tab_name(
                            tab_type="table",
                            table_type="state",
                            partner_id=partner_id,
                            binning_type="equalcount",
                            revenue_type=rev_type_tab_selection.split(" ")[0],
                        )

                        old_plot_limits = plot_limits[name].copy()
                        plot_limits[name][
                            "min_count_per_bin"
                        ] = min_count_per_bin
                        plot_limits[name]["priority_limit"] = priority_limit
                        pd.DataFrame(plot_limits).to_json(
                            os.path.join(
                                summary_path, "plot_limits_revenue.json"
                            )
                        )
                        if (old_plot_limits != plot_limits[name]).any():
                            save_plots_and_table.GeneratePlotsAndTable(
                                config_attr
                            ).generate_table_for_state_tab(name)

                        partnerid_table = pd.read_json(
                            os.path.join(
                                summary_path,
                                (f"{name}.json"),
                            ),
                            orient="records",
                        )

                        with partnerid_tab:
                            if not partnerid_table.empty:
                                partnerid_table = format_table_for_display(
                                    partnerid_table
                                )
                                table_height = int(
                                    35.05 * (len(partnerid_table) + 1)
                                )

                                partnerid_table = (
                                    partnerid_table.style.applymap(
                                        apply_color, subset=["flag"]
                                    )
                                )
                                print_campaign = categories_and_mapping_dict[
                                    "partner_campaign_mapping"
                                ]
                                st.markdown(
                                    "campaign_ids = "
                                    f"{print_campaign[partner_id]}"
                                )
                                st.dataframe(
                                    partnerid_table,
                                    use_container_width=True,
                                    height=table_height,
                                )

            # --------------------------------------------------------------------
            if state_tab_selection == "plots":
                plot_type_tab_selection = st.sidebar.radio(
                    "Select plot data",
                    ["by downstream source", "by partner"],
                )

                if plot_type_tab_selection == "by downstream source":
                    downstreamsource_tabs = st.tabs(downstream_source_types)
                    for downstream_source_tab, downstream_source_type in zip(
                        downstreamsource_tabs, downstream_source_types
                    ):
                        try:
                            with downstream_source_tab:
                                set_combined_plots_tab(
                                    st,
                                    t_name="all state revenue plots",
                                    config_attr=config_attr,
                                    plot_limits=plot_limits,
                                    downstream_source_type=(
                                        downstream_source_type
                                    ),
                                )
                        except Exception as e:
                            logging.exception(e)
                            continue

                if plot_type_tab_selection == "by partner":

                    partnerid_tabs = st.tabs(partner_ids)
                    for partnerid_tab, partner_id in zip(
                        partnerid_tabs, partner_ids
                    ):
                        try:
                            with partnerid_tab:
                                set_combined_plots_tab(
                                    st,
                                    t_name="all state revenue plots",
                                    config_attr=config_attr,
                                    plot_limits=plot_limits,
                                    partner_id=partner_id,
                                )
                        except Exception as e:
                            logging.exception(e)
                            continue

        # -------------------------------------------------------------------
        if revenue_selection == "by source_type_id":
            tab_selection = st.sidebar.radio(
                "Select summary",
                ["table (pff)"],
            )

            if tab_selection == "table (pff)":
                st.latex(
                    r"""
                    \text{relative pff difference}:
                    \rm{pff}_{\text{click, diff}} =
                    \frac{\rm{pff}_{\text{click, measured}}
                    -\rm{pff}_{\text{click, expected}}}
                    {\rm{pff}_{\text{click, expected}}}
                """
                )

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.markdown("#### Color Legend")
                    for color in flag_colors_legend_type2.keys():
                        st.markdown(
                            f"""
                        <div style="display: flex; align-items: center;">
                            <div style="width: 20px; height: 20px;
                            background-color:
                            {flag_colors[color]}; margin-right: 10px;"></div>
                            <div>{flag_colors_legend_type2[color]}</div>
                        </div>
                        """,
                            unsafe_allow_html=True,
                        )

                insurance_types = ["auto", "home"]
                insurance_type_tabs = st.tabs(insurance_types)

                for insurance_type_tab, insurance_type in zip(
                    insurance_type_tabs, insurance_types
                ):
                    save_plots_and_table.GeneratePlotsAndTable(
                        config_attr
                    ).generate_table_for_sourcetypeid_tab(
                        (
                            "revenue_table_pff_insurancetype_"
                            f"{insurance_type}_equalcount.json"
                        )
                    )
                    source_type_table = pd.read_json(
                        os.path.join(
                            summary_path,
                            (
                                "revenue_table_pff_insurancetype_"
                                f"{insurance_type}_equalcount.json"
                            ),
                        ),
                        orient="records",
                    )

                    with insurance_type_tab:

                        if not source_type_table.empty:
                            source_type_table = format_table_for_display(
                                source_type_table
                            )

                            source_type_table = (
                                source_type_table.style.applymap(
                                    apply_color, subset=["flag"]
                                )
                            )
                            st.dataframe(
                                source_type_table,
                                use_container_width=True,
                            )


if __name__ == "__main__":
    args = parse_arguments()
    config_attr = config.load(args.config_file)

    start_streamlit_app(config_attr)
