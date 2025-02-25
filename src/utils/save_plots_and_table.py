import os
import logging
import glob
import json
import math
import ast

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from pathlib import Path
from datetime import datetime, timedelta, timezone
from statsmodels.stats.proportion import proportion_confint


# Project imports
from src.utils import (
    categories_and_mapping,
    email_utils,
    slack_utils,
    config,
    db_conversion_utils,
)
from src.utils.argument_parser_utils import parse_arguments
from src.src_root import src_root
from src.environment.initialize_environment import environment_info

env_name = environment_info.ENVIRONMENT_NAME.value

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


plot_params = {
    "figure.figsize": (12, 4),
    "axes.labelsize": 10,
    "axes.titlesize": 10,
    "legend.fontsize": 10,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "figure.dpi": 300,
    "font.size": 10,
    "lines.linewidth": 1,
    "axes.grid": True,
}
matplotlib.rcParams.update(plot_params)

categories_and_mapping_dict = (
    categories_and_mapping.get_categories_and_mapping()
)

rev_types = categories_and_mapping_dict["rev_types"]
rev_type_color = categories_and_mapping_dict["rev_type_color"]
campaign_ids = categories_and_mapping_dict["campaign_ids"]
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


def replace_nan_inf_with_zero(lst):
    return [0 if math.isnan(x) or math.isinf(x) else x for x in lst]


def sort_df_by_date(df):
    try:
        df = df.sort_values(by="datetime", ascending=False)
    except KeyError:
        df = df.sort_values(by="date", ascending=False)
    df = df.reset_index(drop=True)
    df.index = df.index + 1
    return df


def get_plot_lim(
    date_time,
    date_time_min,
    date_time_max,
    date_format="%Y-%m-%d\n%H:%M:%S\n%A",
    return_indices=False,
):
    if isinstance(date_time_max, float):
        date_time_max = int(date_time_max)
        date_time_min = int(date_time_min)
    if isinstance(date_time_max, int):
        max_lim = datetime.strptime(
            pd.to_datetime(date_time_max / 1000, unit="s").strftime(
                date_format
            ),
            date_format,
        )

        min_lim = datetime.strptime(
            pd.to_datetime(date_time_min / 1000, unit="s").strftime(
                date_format
            ),
            date_format,
        )
    else:
        max_lim = datetime.strptime(
            date_time_max.strftime(date_format),
            date_format,
        )

        min_lim = datetime.strptime(
            date_time_min.strftime(date_format),
            date_format,
        )
    date_time_selected_indices = np.where(
        (date_time <= max_lim) & (date_time >= min_lim)
    )
    date_time_limited = date_time[date_time_selected_indices]
    if date_time_limited.size >= 2:
        min_lim, max_lim = min(date_time_limited), max(date_time_limited)
    if return_indices:
        return min_lim, max_lim, date_time_selected_indices
    else:
        return min_lim, max_lim


def format_date(x, date_format="%Y-%m-%d\n%H:%M:%S\n%A"):
    date = np.array([pd.to_datetime(x_i).strftime(date_format) for x_i in x])
    date = np.array([datetime.strptime(x_i, date_format) for x_i in date])
    return date


def set_fig_and_ax_params(
    fig, ax, date_format="%Y-%m-%d\n%H:%M:%S\n%A", legend=True, x_label=None
):
    ax.xaxis.set_major_formatter(mdates.DateFormatter(date_format))
    if x_label:
        ax.set_xlabel(x_label)
    else:
        ax.set_xlabel("Listing Created date")
    ax.tick_params(axis="x", labelrotation=45)
    if legend:
        ax.legend()
    return fig, ax


def plot_latency_mean(
    df,
    date_time_min,
    date_time_max,
    x="date",
    date_format="%Y-%m-%d\n%A",
    filename="latency.png",
):
    fig, ax = plt.subplots()
    date_time = format_date(df[x], date_format)
    ax.plot(
        date_time,
        df["mean"],
        color="k",
        linestyle="solid",
        marker=".",
        label="mean",
    )
    ax.plot(date_time, df["ci_l"], color="k", linestyle="--", label="90% CI")
    ax.plot(date_time, df["ci_u"], color="k", linestyle="--")

    ax.set_ylabel("Mean Latency")
    min_lim, max_lim = get_plot_lim(
        date_time, date_time_min, date_time_max, date_format
    )
    ax.set_xlim(min_lim, max_lim)
    fig, ax = set_fig_and_ax_params(
        fig, ax, date_format=date_format, x_label=x
    )
    fig.tight_layout()
    plt.savefig(filename)
    plt.close()
    return


def plot_data(
    df,
    column_name,
    date_time_min,
    date_time_max,
    x="date",
    date_format="%Y-%m-%d\n%A",
    filename="data.png",
):
    fig, ax = plt.subplots()
    date_time = format_date(df[x], date_format)

    ax.plot(date_time, df[column_name], color="k", marker=".")
    ax.set_ylabel(column_name)

    min_lim, max_lim = get_plot_lim(
        date_time, date_time_min, date_time_max, date_format
    )
    ax.set_xlim(min_lim, max_lim)

    fig, ax = set_fig_and_ax_params(
        fig, ax, date_format=date_format, x_label=x.capitalize(), legend=False
    )

    fig.tight_layout()
    plt.savefig(filename)
    plt.close()
    return


def resample_df_by_timedelta(df, time_bin):
    df.index = pd.to_datetime(df.index)
    df.index.name = "datetime"
    df_resampled = df.resample(time_bin).sum()
    midpoints = df_resampled.index + pd.to_timedelta(time_bin) / 2
    start_times = df_resampled.index
    end_times = df_resampled.index + pd.to_timedelta(time_bin)
    df_resampled.index = midpoints
    df_resampled.reset_index(inplace=True)
    df_resampled.rename(columns={"index": "datetime"}, inplace=True)
    df_resampled["datetime_min"] = start_times.values
    df_resampled["datetime_max"] = end_times.values
    return df_resampled


def combine_df_to_a_single_bin(df):
    df.index = pd.to_datetime(df.index)
    df.index.name = "datetime"
    df_resampled = pd.DataFrame(df.sum()).T
    start_time = df.index.min()
    end_time = df.index.max() + timedelta(hours=1)
    midpoints = start_time + (end_time - start_time) / 2
    df_resampled.reset_index(inplace=True)
    df_resampled.rename(columns={"index": "datetime"}, inplace=True)
    df_resampled["datetime_min"] = start_time
    df_resampled["datetime_max"] = end_time
    df_resampled["bin_width"] = end_time - start_time
    df_resampled["datetime"] = midpoints

    df_in_24 = df[
        df.index
        >= datetime.now(timezone.utc)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
        - timedelta(hours=24)
    ]
    if not df_in_24.empty:
        df_resampled["nclicked_in_24h"] = sum(df_in_24["n_clicked"])
    else:
        df_resampled["nclicked_in_24h"] = 0
    return df_resampled


def resample_df_by_equal_count_bin(
    df, count_column="listing_count", target_count=50
):
    df.index = pd.to_datetime(df.index)
    df.index.name = "datetime"
    df = df.sort_values(by="datetime", ascending=False)

    bin_range = df.index.max().value - df.index.min().value
    if bin_range == 0.0:
        bin_edges = [
            df.index[0] + timedelta(seconds=1),
            df.index[0] - timedelta(seconds=1),
        ]
    else:
        bin_edges = [df.index[0] + timedelta(hours=1)]

        current_count = 0
        count_per_bin = []
        for i, ind in enumerate(df.index):
            current_count += df[count_column].iloc[i]
            if current_count >= target_count:
                bin_edges.append(ind)
                count_per_bin.append(current_count)
                current_count = 0
        if bin_edges[-1] != df.index[-1]:
            bin_edges.append(df.index[-1])
    bin_edges = bin_edges[::-1]
    df["bin"] = pd.cut(df.index, bins=bin_edges, include_lowest=True)
    df_resampled = df.groupby("bin").sum()
    bin_edges = [b.to_pydatetime() for b in bin_edges]
    df_resampled["bin_width"] = np.diff(bin_edges)
    df_resampled["datetime_min"] = bin_edges[:-1]
    df_resampled["datetime_max"] = bin_edges[1:]
    timedelta_width = np.array(
        [pd.to_timedelta(x) / 2 for x in df_resampled["bin_width"]]
    )
    midpoints = [
        df_resampled.index[i].left + timedelta_width[i]
        for i in range(len(timedelta_width))
    ]
    df_resampled.index = midpoints
    df_resampled.reset_index(inplace=True)

    df_resampled.rename(columns={"index": "datetime"}, inplace=True)
    if df_resampled[count_column].iloc[-1] == 0:
        df_resampled = df_resampled[:-1]

    return df_resampled


def choose_resampling(df, binning_type, **kwargs):
    if binning_type == "equalwidth":
        return resample_df_by_timedelta(df, kwargs["time_bin"])
    elif binning_type == "equalcount":
        if "count_column" not in kwargs.keys():
            kwargs["count_column"] = "listing_count"
        return resample_df_by_equal_count_bin(
            df, kwargs["count_column"], target_count=kwargs["target_count"]
        )


def plot_revenue_payout(
    df,
    date_time_min,
    date_time_max,
    filename,
    name=None,
    **kwargs,
):
    if "lines" in kwargs:
        lines = ast.literal_eval(kwargs["lines"])
    else:
        lines = ["revenue", "payout", "revenue expected"]
        for rev_type in rev_types:
            line = f"{rev_type} revenue"
            lines.append(line)
            line = f"{rev_type} revenue expected"

            lines.append(line)

    fig, ax = plt.subplots(figsize=(12, 6))
    df_resampled = choose_resampling(df, **kwargs)
    date_time = format_date(df_resampled["datetime"])
    date_time_initial = date_time

    if "revenue" in lines:
        ax.plot(
            date_time,
            df_resampled["revenue_total"],
            color="k",
            label="revenue",
            marker=".",
        )

    if "revenue expected" in lines:

        ax.plot(
            date_time,
            df_resampled["revenue_exp_total"],
            linestyle="--",
            color="k",
            label="revenue expected",
            marker=".",
        )
    if "payout" in lines:
        ax.plot(
            date_time,
            df_resampled["payout"],
            linestyle=":",
            color="k",
            label="payout",
            marker=".",
        )

    for rev_type in rev_types:
        kwargs["count_column"] = f"conversions_count_{rev_type}"

        df_resampled = choose_resampling(df, **kwargs)
        date_time = format_date(df_resampled["datetime"])

        rev_expected = df_resampled[f"revenue_exp_{rev_type}"]
        revenue_by_type = df_resampled[f"revenue_{rev_type}"]
        if f"{rev_type} revenue" in lines:

            ax.plot(
                date_time,
                revenue_by_type,
                color=rev_type_color[rev_type],
                label=f"{rev_type} revenue",
                marker=".",
            )

        if f"{rev_type} revenue expected" in lines:
            ax.plot(
                date_time,
                rev_expected,
                color=rev_type_color[rev_type],
                label=f"{rev_type} revenue expected",
                marker=".",
                linestyle="--",
            )

    ax.set_ylabel("Amount")
    min_lim, max_lim = get_plot_lim(
        date_time_initial, date_time_min, date_time_max
    )
    ax.set_xlim(min_lim, max_lim)

    fig, ax = set_fig_and_ax_params(fig, ax)
    fig.tight_layout()
    plt.savefig(filename)
    plt.close()
    return


def plot_revenue_exp_cm(
    df,
    date_time_min,
    date_time_max,
    filename,
    name=None,
    plot_full=True,
    **kwargs,
):
    fig, ax = plt.subplots()
    df_resampled = choose_resampling(df, **kwargs)
    date_time = format_date(df_resampled["datetime"])
    date_time_initial = date_time
    rev_measured = df_resampled["revenue_total"]
    rev_expected = df_resampled["revenue_exp_total"]
    cm = (rev_measured - rev_expected) / rev_expected
    ax.plot(
        date_time,
        cm,
        color="k",
        linestyle="solid",
        marker=".",
        label="total",
    )
    var_exp = df_resampled["revenue_exp_total_variance"]
    var_measured = df_resampled["revenue_total_variance"]
    std = (rev_measured / rev_expected) * (
        (var_exp**0.5 / rev_expected) ** 2
        + (var_measured**0.5 / rev_measured) ** 2
    ) ** (0.5)

    ax.fill_between(date_time, cm - std, cm + std, color="k", alpha=0.2)

    for rev_type in rev_types:
        kwargs["count_column"] = f"conversions_count_{rev_type}"
        df_resampled = choose_resampling(df, **kwargs)
        date_time = format_date(df_resampled["datetime"])

        rev_expected = df_resampled[f"revenue_exp_{rev_type}"]

        rev_measured = df_resampled[f"revenue_{rev_type}"]
        cm = (rev_measured - rev_expected) / rev_expected

        ax.plot(
            date_time,
            cm,
            color=rev_type_color[rev_type],
            linestyle="solid",
            marker=".",
            label=rev_type,
        )
        var_exp = df_resampled[f"revenue_exp_{rev_type}_variance"]
        var_measured = df_resampled[f"revenue_{rev_type}_variance"]
        std = (rev_measured / rev_expected) * (
            (var_exp**0.5 / rev_expected) ** 2
            + (var_measured**0.5 / rev_measured) ** 2
        ) ** (0.5)
        ax.fill_between(
            date_time,
            cm - std,
            cm + std,
            color=rev_type_color[rev_type],
            alpha=0.2,
        )
    if (
        "update_history_statebases" in kwargs
        and kwargs["update_history_statebases"] is not None
    ):
        for d in kwargs["update_history_statebases"]:
            d = format_date([d])
            ax.axvline(d[0], linestyle="--", color="k")

    ax.set_ylabel(r"$(Rev_m-Rev_e)/Rev_e$")
    min_lim, max_lim = get_plot_lim(
        date_time_initial, date_time_min, date_time_max
    )
    ax.set_xlim(min_lim, max_lim)

    fig, ax = set_fig_and_ax_params(fig, ax)
    filename = os.path.abspath(filename)
    fig.tight_layout()
    plt.savefig(f"{filename.split('.')[0]}_full.png")

    ax.set_ylim(kwargs["rev_ymin"], kwargs["rev_ymax"])

    plt.savefig(f"{filename.split('.')[0]}_truncated.png")
    plt.close()
    return


def plot_revenue_frac(
    df,
    date_time_min,
    date_time_max,
    filename,
    name=None,
    **kwargs,
):
    fig, ax = plt.subplots()
    df_resampled = choose_resampling(df, **kwargs)
    date_time = format_date(df_resampled["datetime"])
    date_time_initial = date_time

    for rev_type in rev_types:
        kwargs["count_column"] = f"conversions_count_{rev_type}"
        df_resampled = choose_resampling(df, **kwargs)
        date_time = format_date(df_resampled["datetime"])

        rev_measured_total = df_resampled["revenue_total"]
        rev_measured = df_resampled[f"revenue_{rev_type}"]
        frac = rev_measured / rev_measured_total

        ax.plot(
            date_time,
            frac,
            color=rev_type_color[rev_type],
            linestyle="solid",
            marker=".",
            label=rev_type,
        )

    ax.set_ylabel(r"$Rev_m/Rev_{m, \mathrm{total}}$")
    min_lim, max_lim = get_plot_lim(
        date_time_initial, date_time_min, date_time_max
    )
    ax.set_xlim(min_lim, max_lim)

    fig, ax = set_fig_and_ax_params(fig, ax)
    fig.tight_layout()
    plt.savefig(filename)
    plt.close()

    return


def plot_revenue_nz(
    df,
    date_time_min,
    date_time_max,
    filename,
    name=None,
    **kwargs,
):
    fig, ax = plt.subplots()
    fig2, ax2 = plt.subplots()
    df_resampled = choose_resampling(df, **kwargs)
    date_time = format_date(df_resampled["datetime"])
    date_time_initial = date_time

    for rev_type in rev_types:
        kwargs["count_column"] = f"conversions_count_{rev_type}"
        df_resampled = choose_resampling(df, **kwargs)
        date_time = format_date(df_resampled["datetime"])

        max_nz = df_resampled[f"max_nz_{rev_type}"]
        exp_nz = df_resampled[f"nz_exp_{rev_type}"]

        ax.plot(
            date_time,
            max_nz,
            color=rev_type_color[rev_type],
            linestyle="solid",
            marker=".",
            label=f"max_nz_{rev_type}",
        )

        ax2.plot(
            date_time,
            (max_nz - exp_nz) / exp_nz,
            color=rev_type_color[rev_type],
            linestyle="--",
            marker=".",
            label=rev_type,
        )

    ax.set_ylabel("nz")
    ax2.set_ylabel(r"$(nz_m-nz_e)/nz_e$")
    min_lim, max_lim = get_plot_lim(
        date_time_initial, date_time_min, date_time_max
    )
    ax.set_xlim(min_lim, max_lim)
    ax2.set_xlim(min_lim, max_lim)

    fig, ax = set_fig_and_ax_params(fig, ax)
    fig2, ax2 = set_fig_and_ax_params(fig2, ax2)
    fig.tight_layout()
    fig2.tight_layout()
    fig.savefig(filename)
    fig2.savefig(filename.replace("nz", "fracnz"))
    plt.close()

    return


def plot_pff(
    df, date_time_min, date_time_max, filename, update_history=None, **kwargs
):
    fig, ax = plt.subplots()
    date_time = format_date(df["datetime"])
    bin_datetime_min = format_date(df["datetime_min"])
    pff_exp = df["pff_total"]
    pff_measured = df["conversions_count"]
    pff_rel_diff = (pff_measured - pff_exp) / pff_exp
    pff_rel_diff = replace_nan_inf_with_zero(pff_rel_diff)

    ax.set_ylabel(r"$(pff_m-pff_e)/pff_e$")
    if len(pff_rel_diff) != 0:
        min_lim, max_lim, selected_indices = get_plot_lim(
            date_time, date_time_min, date_time_max, return_indices=True
        )
        ax.set_xlim(min_lim, max_lim)
        min_y_lim = min(min(pff_rel_diff), -0.1)
        if min_y_lim < -1:
            min_y_lim = -1
        max_y_lim = max(max(pff_rel_diff), 0.1)
        if max_y_lim > 1:
            max_y_lim = 1
        selected_pffs_for_limits = np.array(pff_rel_diff)[selected_indices]
        if len(selected_pffs_for_limits) > 0:
            min_y_lim, max_y_lim = min(selected_pffs_for_limits), max(
                selected_pffs_for_limits
            )
            min_y_lim = min(min_y_lim, -0.1)
            max_y_lim = max(max_y_lim, -0.1)
        ax.set_ylim(min_y_lim, max_y_lim)

    ax.plot(date_time, pff_rel_diff, linestyle="solid", marker=".", label=" ")
    ax.axhline(-0.1, linestyle="--", color="k")
    ax.axhline(0.1, linestyle="--", color="k")

    fig, ax = set_fig_and_ax_params(fig, ax, legend=False)
    if update_history:
        for d in update_history:
            d = format_date([d])
            ax.axvline(d[0], linestyle="--", color="k")
    fig.tight_layout()
    plt.savefig(filename)
    plt.close()
    send_alert = False

    if update_history:
        last_updated_date = sorted(format_date(update_history))[-1]
        pff_after_update = np.array(pff_rel_diff)[
            bin_datetime_min > last_updated_date
        ]

    if update_history is not None:
        if any(np.array(pff_after_update) < -0.1):

            send_alert = True
    else:
        if any(np.array(pff_rel_diff[-10:]) < -0.1):
            send_alert = True
    return send_alert


def plot_cm(df, date_time_min, date_time_max, filename):
    fig, ax = plt.subplots()
    date_time = format_date(df["datetime"])
    ax.plot(date_time, df["cm"], color="k", label="actual", marker=".")
    ax.plot(
        date_time,
        df["cm_exp"],
        linestyle=":",
        color="k",
        label="expected",
        marker=".",
    )
    ax.set_ylabel("CM ((Revenue-Payout)/Revenue)")

    min_lim, max_lim, selected_indices = get_plot_lim(
        date_time, date_time_min, date_time_max, return_indices=True
    )
    ax.set_xlim(min_lim, max_lim)
    selected_cm_for_limits = np.array(df["cm"])[selected_indices]
    selected_cmexp_for_limits = np.array(df["cm_exp"])[selected_indices]
    if len(selected_cm_for_limits) > 0:
        min_y_lim, max_y_lim = min(selected_cm_for_limits), max(
            selected_cm_for_limits
        )
        if len(selected_cmexp_for_limits) > 0:
            min_y_lim, max_y_lim = min(
                min(selected_cmexp_for_limits), min_y_lim
            ), max(max(selected_cmexp_for_limits), max_y_lim)

        ax.set_ylim(min_y_lim, max_y_lim)

    fig, ax = set_fig_and_ax_params(fig, ax)
    fig.tight_layout()
    plt.savefig(filename)
    plt.close()
    return


def add_cm_data(revenue_df):
    revenue_df_copy = revenue_df.copy()
    revenue_df_copy["cm"] = (
        revenue_df["revenue_total"] - revenue_df["payout"]
    ) / revenue_df["revenue_total"]
    revenue_df_copy["cm_exp"] = (
        revenue_df["revenue_exp_total"] - revenue_df["payout"]
    ) / revenue_df["revenue_exp_total"]
    return revenue_df_copy


def plot_all_revenue_plots(
    df,
    save_path,
    plot_list,
    name=None,
    min_count_per_bin_default=200,
    update_history_statebases=None,
    update_history_pff=None,
    **all_kwargs,
):
    kwargs_main = {
        "df": df,
        "date_time_min": all_kwargs["date_time_min"],
        "date_time_max": all_kwargs["date_time_max"],
        "name": name,
        "binning_type": all_kwargs["binning_type"],
        "rev_ymin": all_kwargs["rev_ymin"],
        "rev_ymax": all_kwargs["rev_ymax"],
        "lines": all_kwargs["lines"],
    }
    # Plotting revenue_payout
    kwargs = kwargs_main.copy()
    if all_kwargs["binning_type"] == "equalwidth":
        kwargs["time_bin"] = all_kwargs["time_bin_width"]
    elif all_kwargs["binning_type"] == "equalcount":
        kwargs["target_count"] = all_kwargs["min_count_per_bin"]
    if "revenue_payout" in plot_list:
        plot_revenue_payout(
            **kwargs,
            filename=os.path.join(save_path, f"{name}_revenue_payout.png"),
        )
        kwargs["update_history_statebases"] = update_history_statebases
    if "revenue_exp_cm" in plot_list:
        plot_revenue_exp_cm(
            **kwargs,
            filename=os.path.join(save_path, f"{name}_revexpcm.png"),
        )
    if "revenue_frac" in plot_list:
        plot_revenue_frac(
            **kwargs,
            filename=os.path.join(save_path, f"{name}_revfrac.png"),
        )

    if "revenue_nz" in plot_list:
        plot_revenue_nz(
            **kwargs,
            filename=os.path.join(save_path, f"{name}_revnz.png"),
        )

    if all_kwargs["binning_type"] == "equalwidth":
        df_resampled = resample_df_by_timedelta(df, kwargs["time_bin"])
    elif all_kwargs["binning_type"] == "equalcount":
        df_resampled = resample_df_by_equal_count_bin(
            df, target_count=kwargs["target_count"]
        )

    send_alert = False
    kwargs["df"] = df_resampled
    if "pff" in plot_list:
        send_alert = plot_pff(
            update_history=update_history_pff,
            filename=os.path.join(save_path, f"{name}_pff.png"),
            **kwargs,
        )

    df_with_cm = add_cm_data(df_resampled)

    if "cm" in plot_list:
        plot_cm(
            df_with_cm,
            all_kwargs["date_time_min"],
            all_kwargs["date_time_max"],
            filename=os.path.join(save_path, f"{name}_cm.png"),
        )
    return df_with_cm, send_alert


def df_to_json_dict(df, filename):
    df.to_json(filename)


def set_plot_params(
    name, plot_params, date_time_min_default, date_time_max_default
):

    # set plot params
    all_kwargs = {}
    all_kwargs["binning_type"] = name.split("_")[-1]
    all_kwargs["date_time_min"] = date_time_min_default
    all_kwargs["date_time_max"] = date_time_max_default
    if all_kwargs["binning_type"] == "equalwidth":
        all_kwargs["time_bin_width"] = "24H"
    else:
        all_kwargs["min_count_per_bin"] = 50
    all_kwargs["rev_ymin"] = -1
    all_kwargs["rev_ymax"] = 1
    all_kwargs["lines"] = str(["revenue", "payout", "revenue expected"])
    if f"{name}" in plot_params:
        for k in plot_params[f"{name}"].keys():
            if plot_params[f"{name}"][k] is not None:
                all_kwargs[k] = plot_params[f"{name}"][k]
    return all_kwargs


def set_table_params(
    name,
    plot_params,
    date_time_min_default,
    date_time_max_default,
    target_count=50,
):

    # set plot params
    all_kwargs = {}
    all_kwargs["binning_type"] = name.split("_")[-1]
    all_kwargs["date_time_min"] = date_time_min_default
    all_kwargs["date_time_max"] = date_time_max_default
    if all_kwargs["binning_type"] == "equalwidth":
        all_kwargs["time_bin_width"] = "4H"
    else:
        all_kwargs["min_count_per_bin"] = target_count
    all_kwargs["priority_limit"] = 48
    if f"{name}" in plot_params:
        for k in plot_params[f"{name}"].keys():
            if plot_params[f"{name}"][k] is not None:
                all_kwargs[k] = plot_params[f"{name}"][k]
    return all_kwargs


def get_table_summary_pff_like(
    df,
    data_field="pff",
    last_correction_at=None,
    current_weight=None,
):

    bin_summary = {}

    def agreement_level(x):
        x = abs(x)
        if x > 0.5:
            return "D"
        elif x <= 0.5 and x > 0.25:
            return "C"
        elif x <= 0.25 and x > 0.1:
            return "B"
        else:
            return "A"

    datetime_max = df["datetime_max"].max()

    relative_pff_diff = (df["conversions_count"] - df["pff_total"]) / df[
        "pff_total"
    ]
    relative_pff_diff = round(relative_pff_diff.iloc[0], 2)
    column_name = "relative_pff_diff"
    df[column_name] = relative_pff_diff
    bin_summary["overall_correction"] = relative_pff_diff

    new_sourcetype_id = False
    if not current_weight or current_weight == 1.0:
        new_sourcetype_id = True

    bin_summary["recommended_correction"] = [0.0]

    nff = sum(df["conversions_count"])
    nclicked = sum(df["n_clicked"])
    pff_exp = sum(df["pff_total"]) / nclicked if nclicked != 0 else 0
    pff_meas = nff / nclicked if nclicked != 0 else 0

    # Recommended correction from confint
    conf_int = proportion_confint(
        nff, nclicked, alpha=(1 - 0.68), method="beta"
    )
    zscore = None
    z_threshold = 2.5
    bin_summary["conf_int:correction"] = None
    bin_summary["zscore"] = zscore
    bin_summary["zscore_threshold"] = z_threshold
    apply_correction = False
    bin_summary["correction_from_conf_int"] = "False"
    if nclicked != 0:
        if pff_exp < conf_int[0]:
            stddev = pff_meas - conf_int[0]
            zscore = (pff_exp - pff_meas) / stddev
        elif pff_exp > conf_int[1]:
            stddev = conf_int[1] - pff_meas
            zscore = (pff_exp - pff_meas) / stddev
        else:
            zscore = 0
        if pff_meas == 0.0 or ((conf_int[1] - conf_int[0]) / pff_meas) > 0.2:
            new_pff = conf_int[0] + (conf_int[1] - conf_int[0]) / 2.0
            bin_summary["conf_int:correction"] = (
                new_pff / pff_exp - 1.0 if pff_exp != 0.0 else 0
            )
        bin_summary["zscore"] = round(zscore, 2)
        bin_summary["conf_int"] = [
            round(conf_int[0], 2),
            round(conf_int[1], 2),
        ]

        if new_sourcetype_id and sum(df["n_clicked"]) > 10:
            z_threshold = 1.0

        bin_summary["zscore_threshold"] = z_threshold
        if abs(zscore) > z_threshold:
            apply_correction = True
    if apply_correction:
        if bin_summary["conf_int:correction"] is not None:
            bin_summary["recommended_correction"] = [
                bin_summary["conf_int:correction"]
            ]
            bin_summary["correction_from_conf_int"] = "True"

        else:
            bin_summary["recommended_correction"] = [relative_pff_diff]

    if not zscore:
        bin_summary["flag"] = "E"
    elif abs(zscore) < 1:
        bin_summary["flag"] = "A"
    elif abs(zscore) > 1 and abs(zscore) < 2.5:
        bin_summary["flag"] = "B"
    else:
        bin_summary["flag"] = "D"

    bin_summary["current_weight"] = current_weight
    if new_sourcetype_id:
        bin_summary["type"] = "new"
    else:
        bin_summary["type"] = "old"
    bin_summary["replace_weight"] = "False"
    if current_weight:
        if current_weight < 0.001:
            bin_summary["replace_weight"] = "True"

    bin_summary["nff_measured"] = nff
    bin_summary["nff_expected"] = sum(df["pff_total"])
    bin_summary["nclicked"] = nclicked
    bin_summary["pff_measured"] = pff_meas
    bin_summary["pff_expected"] = pff_exp
    bin_summary["nclicked_in_24h"] = sum(df["nclicked_in_24h"])

    # Timestamps
    bin_summary["most_recent_event_before"] = datetime_max
    bin_summary["last_correction_at"] = last_correction_at

    # Final recommended correction
    bin_summary["recommended_correction"] = str(
        round(bin_summary["recommended_correction"][0], 2)
    )
    if apply_correction:
        if not new_sourcetype_id and current_weight:
            bin_summary["new_weight"] = round(
                current_weight
                * (1 + float(bin_summary["recommended_correction"])),
                3,
            )
        elif new_sourcetype_id and current_weight == 1:
            bin_summary["new_weight"] = round(
                1 * (1 + float(bin_summary["recommended_correction"])), 3
            )

        if bin_summary["replace_weight"] == "True":
            bin_summary["new_weight"] = 0.001

    return bin_summary


def get_table_summary_revenue_like(
    df,
    data_field="click_revenue",
    target_count=50,
    priority_limit=24,
    last_correction_at=None,
):

    bin_summary = {}

    def agreement_level(x):
        x = abs(x)
        if x > 0.5:
            return "D"
        elif x <= 0.5 and x > 0.25:
            return "C"
        elif x <= 0.25 and x > 0.1:
            return "B"
        else:
            return "A"

    df = df.sort_values(by="datetime")
    datetime_max = df.datetime.max()

    if data_field == "click_revenue":
        relative_click_rev = (df["max_nz_click"] - df["nz_exp_click"]) / df[
            "nz_exp_click"
        ]
        column_name = "relative_click_rev_diff"
        df[column_name] = relative_click_rev

    elif "pnz" in data_field:
        rev_type = data_field.split("_")[0]
        measured_pnz = (
            df[f"nz_count_{rev_type}"] / df[f"conversions_count_{rev_type}"]
        )
        expected_pnz = df[f"pnz_exp_{rev_type}"]
        relative_call_pnz_diff = (measured_pnz - expected_pnz) / expected_pnz
        column_name = f"relative_{rev_type}_pnz_diff"
        df[column_name] = relative_call_pnz_diff

    # Recommended correction after last update
    bin_summary["after_last_update:average_correction"] = None
    bin_summary["after_last_update:number_of_bins"] = str(0)
    if last_correction_at:
        bins_after_last_update = df[df["datetime_min"] >= last_correction_at]
        if not bins_after_last_update.empty:
            bin_summary["after_last_update:average_correction"] = [
                round(bins_after_last_update[column_name].mean(), 2)
            ]
            bin_summary["after_last_update:number_of_bins"] = str(
                len(bins_after_last_update)
            )

    # Recommended correction from last 5 bins
    last_five_bin = df[-5:]
    last_five_bin.reset_index()

    last_five_bin_edge = last_five_bin["datetime_min"]
    in_last_priority_hours = last_five_bin_edge >= datetime.now(
        timezone.utc
    ).astimezone(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=priority_limit
    )

    last_five_rev = list(last_five_bin[column_name].round(2))
    last_five_count = list(last_five_bin["conversions_count_click"])
    color_flags = []
    for i in range(len(last_five_count)):
        good_agreement = agreement_level(last_five_rev[i])

        color_flags.append(good_agreement)
    if (
        len(df["conversions_count_click"]) == 1
        and df["conversions_count_click"].iloc[-1] < target_count
    ):
        bin_summary["flag"] = "E"
    elif df["conversions_count_click"].empty:
        bin_summary["flag"] = "E"
    else:

        if all(x == "A" for x in color_flags):
            bin_summary["flag"] = "A"
        elif "D" in color_flags:
            bin_summary["flag"] = "D"
        elif "C" in color_flags:
            bin_summary["flag"] = "C"
        elif "B" in color_flags:
            bin_summary["flag"] = "B"

    bins_in_last_priority_hours = np.array(color_flags)[in_last_priority_hours]
    if bins_in_last_priority_hours.size == 5:
        bin_summary["priority"] = "5"
    elif bins_in_last_priority_hours.size == 4:
        bin_summary["priority"] = "4"
    elif bins_in_last_priority_hours.size == 3:
        bin_summary["priority"] = "3"
    elif bins_in_last_priority_hours.size == 2:
        bin_summary["priority"] = "2"
    elif bins_in_last_priority_hours.size == 1:
        bin_summary["priority"] = "1"
    else:
        bin_summary["priority"] = "0"

    cumulative_mean = [
        np.mean(last_five_rev[i:]).round(2) for i in range(len(last_five_rev))
    ]

    bin_summary["last_5_bins:cumulative_average_correction"] = list(
        np.array(cumulative_mean)
    )
    if bin_summary["last_5_bins:cumulative_average_correction"] == []:
        bin_summary["last_5_bins:cumulative_average_correction"] = None
        bin_summary["last_5_bins_in_priority:average_correction"] = None
    else:
        average_correction_in_priority_hour = np.array(
            bin_summary["last_5_bins:cumulative_average_correction"]
        )[in_last_priority_hours]
        if len(average_correction_in_priority_hour) != 0:

            bin_summary["last_5_bins_in_priority:average_correction"] = [
                average_correction_in_priority_hour[0]
            ]
        else:
            bin_summary["last_5_bins_in_priority:average_correction"] = None
    bin_summary[f"last_5_bins:relative_{data_field}_diff"] = list(
        np.array(last_five_rev)
    )
    # Recommended correction from CUSUM
    last_segment = get_cusum_correction(
        df,
        column_name,
    )
    if last_segment is not None:

        index_in_1weeks = df[
            df["datetime_min"] >= (max(df["datetime_min"]) - timedelta(days=7))
        ].index
        last_segment = [i for i in last_segment if i in index_in_1weeks]
        if last_segment != []:
            df_cusum = df.iloc[last_segment]
            cusum_bin_index = np.array(last_segment) - len(df)
            if len(cusum_bin_index) > 1:
                bin_summary["CUSUM:bin_index"] = (
                    f"{cusum_bin_index[0]} to {cusum_bin_index[-1]}"
                )
            else:
                bin_summary["CUSUM:bin_index"] = str(cusum_bin_index[0])
            bin_summary["CUSUM:average_correction"] = [
                round(df_cusum[column_name].mean(), 2)
            ]
        else:
            bin_summary["CUSUM:bin_index"] = None
            bin_summary["CUSUM:average_correction"] = None

    else:
        bin_summary["CUSUM:bin_index"] = None
        bin_summary["CUSUM:average_correction"] = None

    # Recommended correction from < last 4 hours, < last 2 days ,
    # < last 2 weeks and all available data
    bin_summary["last_2_days:average_correction"] = None
    bin_summary["last_4_hours_after_correction:average_correction"] = None
    bin_summary["last_2_weeks:average_correction"] = None
    bin_summary["all_data:average_correction"] = None
    if not df.empty:
        df_last_4hours = df[
            df["datetime_min"]
            >= (max(df["datetime_max"]) - timedelta(hours=4))
        ]
        if last_correction_at:
            df_last_4hours = df_last_4hours[
                df_last_4hours["datetime_min"] >= last_correction_at
            ]
        if not df_last_4hours.empty:
            bin_summary["last_4_hours_after_correction:average_correction"] = [
                round(df_last_4hours[column_name].mean(), 2)
            ]

        df_last_2days = df[
            df["datetime_min"] >= (max(df["datetime_max"]) - timedelta(days=2))
        ]
        if not df_last_2days.empty:
            bin_summary["last_2_days:average_correction"] = [
                round(df_last_2days[column_name].mean(), 2)
            ]

        df_last_2weeks = df[
            df["datetime_min"]
            >= (max(df["datetime_max"]) - timedelta(days=14))
        ]
        if not df_last_2weeks.empty:
            bin_summary["last_2_weeks:average_correction"] = [
                round(df_last_2weeks[column_name].mean(), 2)
            ]
        bin_summary["all_data:average_correction"] = [
            round(df[column_name].mean(), 2)
        ]

    bin_summary["last_5_bins:bin_widths"] = list(
        df["bin_width"][-5:].apply(lambda x: str(x))
    )
    bin_summary["last_5_bins:counts_per_bin"] = last_five_count

    bin_summary["total_n_click_events"] = sum(df["conversions_count_click"])

    bin_summary["min_bin_width"] = (
        min(df["bin_width"]) if not df["bin_width"].empty else None
    )
    bin_summary["max_bin_width"] = (
        max(df["bin_width"]) if not df["bin_width"].empty else None
    )

    bin_summary["number_of_bins"] = len(df)
    bin_summary["min_n_events_per_bin"] = (
        str(min(df["conversions_count_click"]))
        if not df["conversions_count_click"].empty
        else None
    )

    bin_summary["max_n_events_per_bin"] = (
        str(max(df["conversions_count_click"]))
        if not df["conversions_count_click"].empty
        else None
    )

    # Timestamps
    bin_summary["most_recent_event_before"] = datetime_max
    bin_summary["last_correction_at"] = last_correction_at
    if last_correction_at:
        bin_summary["last_correction_at"] = last_correction_at

    # Final recommended correction
    bin_summary = get_recommended_correction(bin_summary)
    bin_summary["recommended_correction"] = str(
        round(bin_summary["recommended_correction"][0], 2)
    )

    return bin_summary


def get_recommended_correction(bin_summary):
    def not_same_sign(arr):
        is_positive = [
            True if n is not None and n >= 0 else False for n in arr
        ]
        is_negative = [True if n <= 0 else False for n in arr]
        if all(is_positive):
            return "all_postive", False
        elif all(is_negative):
            return "all_negative", False
        else:
            return None, True

    # if the total number of events are less than 50,  do not
    # recommend a correction
    if bin_summary["total_n_click_events"] <= 50:
        bin_summary["recommended_correction"] = [0.0]
    # if last_2_weeks average_correction is None, that implies, the most
    # recent bin for this state is wider than 2 weeks. In this case, take
    # the average_correction from  since the last update or the most recent
    # bin for recommended_correction.
    elif bin_summary["last_2_weeks:average_correction"] is None:
        if bin_summary["after_last_update:average_correction"] is not None:
            bin_summary["recommended_correction"] = bin_summary[
                "after_last_update:average_correction"
            ]
        elif bin_summary["last_5_bins:cumulative_average_correction"]:
            bin_summary["recommended_correction"] = [
                bin_summary["last_5_bins:cumulative_average_correction"][-1]
            ]

    else:
        cusum_correction = bin_summary["CUSUM:average_correction"]
        after_last_update_correction = bin_summary[
            "after_last_update:average_correction"
        ]
        if cusum_correction is not None:
            cusum_bin_boundary_indices = bin_summary["CUSUM:bin_index"].split(
                " to "
            )
            cusum_bin_start = float(cusum_bin_boundary_indices[0])
            cusum_len = 1
            if len(cusum_bin_boundary_indices) > 1:
                cusum_bin_end = float(cusum_bin_boundary_indices[-1])
                cusum_len = int(cusum_bin_end - cusum_bin_start)
                if float(cusum_bin_end) < -5:
                    cusum_correction = None
                if abs(cusum_bin_end) < float(
                    bin_summary["after_last_update:number_of_bins"]
                ):
                    after_last_update_correction = None
            if cusum_len <= 3:
                cusum_correction = None
        last_5_bins_correction = bin_summary[
            "last_5_bins_in_priority:average_correction"
        ]

        last_2_days_correction = bin_summary["last_2_days:average_correction"]
        last_2_weeks_correction = bin_summary[
            "last_2_weeks:average_correction"
        ]
        all_data_correction = bin_summary["all_data:average_correction"]
        all_possible_correction = [
            cusum_correction,
            last_5_bins_correction,
            last_2_days_correction,
            after_last_update_correction,
        ]
        if int(bin_summary["priority"]) == 0:
            if all(x is None for x in all_possible_correction):
                all_possible_correction.append(last_2_weeks_correction)
                all_possible_correction.append(all_data_correction)

        all_possible_correction = [
            i for i in all_possible_correction if i is not None
        ]
        all_possible_correction = [i[0] for i in all_possible_correction]
        if all_possible_correction == []:
            bin_summary["recommended_correction"] = [0.0]
        else:

            bin_summary["recommended_correction"] = [
                np.average(all_possible_correction)
            ]

    # reset recommended_correction to 0 if the
    # -0.1<recommended_correction<0.1
    if (
        abs(bin_summary["recommended_correction"][0]) <= 0.1
        or bin_summary["recommended_correction"][0] is None
    ):
        bin_summary["recommended_correction"] = [0.0]

    # cap +ve recommended_correction recommended_correction at 0.25
    if bin_summary["recommended_correction"][0] >= 0.25:
        bin_summary["recommended_correction"] = [0.25]

    # if a state had an update in the past but there isn't a bin  after the
    # update, set recommended_correction to zero until enough events are
    # accumulated for atleast a single bin
    if (
        bin_summary["last_correction_at"]
        and int(bin_summary["after_last_update:number_of_bins"]) == 1
        and bin_summary["recommended_correction"][0] == 0.0
    ):
        if bin_summary["after_last_update:average_correction"][0] < -0.15:
            bin_summary["recommended_correction"] = bin_summary[
                "after_last_update:average_correction"
            ]
    if bin_summary["recommended_correction"][0] > 0.0:
        if (
            bin_summary["last_correction_at"]
            and int(bin_summary["after_last_update:number_of_bins"]) <= 1
        ):
            bin_summary["recommended_correction"] = [0.0]

    if (
        bin_summary["last_4_hours_after_correction:average_correction"]
        is not None
    ):
        if (
            bin_summary["last_4_hours_after_correction:average_correction"][0]
            <= -0.15
            and bin_summary[
                "last_4_hours_after_correction:average_correction"
            ][0]
            < bin_summary["recommended_correction"][0]
        ):
            bin_summary["recommended_correction"] = bin_summary[
                "last_4_hours_after_correction:average_correction"
            ]
    if (
        bin_summary["last_correction_at"]
        and int(bin_summary["after_last_update:number_of_bins"]) == 0
    ):
        bin_summary["recommended_correction"] = [0.0]
    if (
        bin_summary["last_correction_at"]
        and int(bin_summary["after_last_update:number_of_bins"]) >= 1
    ):
        if (
            bin_summary["recommended_correction"][0] == 0.0
            and bin_summary["after_last_update:average_correction"][0] <= -0.1
        ):
            bin_summary["recommended_correction"] = bin_summary[
                "after_last_update:average_correction"
            ]
    if bin_summary["total_n_click_events"] <= 50:
        bin_summary["recommended_correction"] = [0.0]

    return bin_summary


def get_cusum_correction(df, column_name, window_size=3, threshold=0.1):
    if len(df) >= 5:
        pos_cusum = np.zeros(len(df))
        neg_cusum = np.zeros(len(df))
        rolling_mean = df[column_name].rolling(window=window_size).mean()

        for i in range(1, len(df)):
            if np.isclose(rolling_mean.iloc[i], 0, atol=threshold) or np.isnan(
                rolling_mean[i]
            ):
                pos_cusum[i] = 0
                neg_cusum[i] = 0
            else:
                pos_cusum[i] = max(
                    0, pos_cusum[i - 1] + (df[column_name].iloc[i] - 0)
                )
                neg_cusum[i] = min(
                    0, neg_cusum[i - 1] + (df[column_name].iloc[i] - 0)
                )

        df["pos_cusum"] = pos_cusum
        df["neg_cusum"] = neg_cusum

        def get_last_change_segment(cusum_column):
            change_points = [False] * len(df)
            change_points_selected = [False] * len(df)

            for i in range(len(cusum_column)):
                cusum = cusum_column.iloc[i]
                if abs(cusum) > threshold:
                    change_points[i] = True
                    if change_points[i - 1] is True:
                        change_points_selected[i] = False
                    else:
                        change_points_selected[i] = True

            change_index = [i for i, x in enumerate(change_points) if x]
            last_segment = []
            for i in change_index[:-1]:
                if i + 1 in change_index:
                    last_segment.append(i)
                else:
                    last_segment = []
            if i + 1 in change_index:
                last_segment.append(i + 1)
            return last_segment

        last_pos_segment = get_last_change_segment(df["pos_cusum"])
        last_neg_segment = get_last_change_segment(df["neg_cusum"])
        if last_pos_segment == []:
            last_seg = last_neg_segment
        elif last_neg_segment == []:
            last_seg = last_pos_segment
        else:
            last_seg = (
                last_pos_segment
                if last_pos_segment[0] > last_neg_segment[0]
                else last_neg_segment
            )

        return last_seg
    else:
        return


def get_tab_name(
    tab_type,
    tab_name=None,
    campaign_id=None,
    partner_id=None,
    downstream_source_type=None,
    sourcetype_id=None,
    insurance_type=None,
    binning_type=None,
    table_type=None,
    state=None,
    revenue_type=None,
):

    # tab_type: individual, table, plots
    t_name = f"revenue_{tab_type}"
    if revenue_type:
        t_name = f"{t_name}_{revenue_type}"
    if tab_type in ["individual"]:
        if tab_name == "overall":
            t_name += f"_{tab_name}"
        elif tab_name == "by campaign_id":
            t_name += f"_campaign_{campaign_id}"
        elif tab_name == "by partner_id":
            t_name += f"_partner_{partner_id}"
        elif tab_name == "by downstream_source":
            t_name += f"_source_{downstream_source_type}"
    if tab_type == "table":
        t_name += f"_{table_type}"
        if downstream_source_type:
            t_name += f"_source_{downstream_source_type}"
        elif partner_id:
            t_name += f"_partner_{partner_id}"
        if insurance_type:
            t_name += f"_insurancetype_{insurance_type}"
    if tab_type == "plots":
        if campaign_id:
            t_name += f"_campaign_{campaign_id}"
        if partner_id:
            t_name += f"_partner_{partner_id}"
        if downstream_source_type:
            t_name += f"_source_{downstream_source_type}"
        if state:
            t_name += f"_state_{state}"
    if binning_type:
        t_name += f"_{binning_type}"
    return t_name


def parse_tab_name(t_name):
    # Initialize the arguments dictionary with None
    args = {
        "tab_type": None,
        "tab_name": None,
        "campaign_id": None,
        "partner_id": None,
        "downstream_source_type": None,
        "sourcetype_id": None,
        "insurance_type": None,
        "binning_type": None,
        "table_type": None,
        "state": None,
        "revenue_type": None,
    }

    all_parts = t_name.split("_")
    args["tab_type"] = all_parts[1]
    if all_parts[2] in ["click", "lead", "call"]:
        args["revenue_type"] = all_parts[2]
    if "equalcount" in all_parts:
        args["binning_type"] = "equalcount"
    elif "equalwidth" in all_parts:
        args["binning_type"] = "equalwidth"
    if "source" in t_name:
        if "state" not in t_name:
            args["downstream_source_type"] = t_name.split("_source_")[
                -1
            ].split(f"_{args['binning_type']}")[0]
        else:
            parts = t_name.split("_source_")[-1].split(
                f"_{args['binning_type']}"
            )[0]

            args["downstream_source_type"] = parts.split("_state")[0]

    if "partner" in t_name:
        parts = t_name.split("_partner_")[-1].split(
            f"_{args['binning_type']}"
        )[0]
        if "state" not in parts:
            args["partner_id"] = parts
        else:
            args["partner_id"] = parts.split("_state")[0]
    return args


def get_category_from_tname(t_name):
    if "plots" in t_name:
        t_name = t_name.replace("revenue_plots_", "")
    elif "individual" in t_name:
        t_name = t_name.replace("revenue_individual_", "")
    t_name = t_name.split("_equal")[0]
    substrings = ["campaign_", "partner_", "source_"]
    for s in substrings:
        if s in t_name:
            t_name = t_name.replace(s, "")
    return t_name


class GeneratePlotsAndTable:
    def __init__(self, config_attrs):
        self.config_attrs = config_attrs
        self.get_paths()
        self.set_default_time_window()
        self.get_plot_limits()

    def get_paths(self):
        self.output_path = str(
            Path(src_root, self.config_attrs["output_path"])
        )
        self.summary_path = os.path.join(self.output_path, "summary")
        if not os.path.exists(self.summary_path):
            os.makedirs(self.summary_path)

    def set_default_time_window(self):
        # get default time window
        now = (
            datetime.now(timezone.utc)
            .astimezone(timezone.utc)
            .replace(tzinfo=None, second=0, microsecond=0)
        )

        five_weeks_ago = (now - timedelta(days=35)).replace(
            minute=0, second=0, microsecond=0
        )

        self.date_time_min_default, self.date_time_max_default = (
            five_weeks_ago,
            now,
        )

    def get_plot_limits(self):
        latency_plot_limits_path = os.path.join(
            self.summary_path, "plot_limits_latency.json"
        )
        if os.path.exists(latency_plot_limits_path):
            with open(latency_plot_limits_path, "r") as f:
                latency_plot_params = json.load(f)
        else:
            latency_plot_params = {}
        self.latency_plot_params = latency_plot_params

        revenue_plot_limits_path = os.path.join(
            self.summary_path, "plot_limits_revenue.json"
        )
        if os.path.exists(revenue_plot_limits_path):
            with open(revenue_plot_limits_path, "r") as f:
                revenue_plot_params = json.load(f)
        else:
            revenue_plot_params = {}
        self.revenue_plot_params = revenue_plot_params

    def generate_plots_for_latency_tab(self):
        plot_params = self.latency_plot_params

        # Plots for "Latency and Output Code" tab
        latency_df = pd.read_csv(
            os.path.join(self.output_path, "latency.txt"),
            header=0,
            delimiter=" ",
        )
        latency_df = latency_df.drop_duplicates(subset="date", keep="last")

        latency_df = sort_df_by_date(latency_df)

        # set plot params
        date_time_min = self.date_time_min_default
        date_time_max = self.date_time_max_default
        if "latency" in plot_params.keys():
            date_time_min, date_time_max = (
                plot_params["latency"]["date_time_min"],
                plot_params["latency"]["date_time_max"],
            )
        plot_latency_mean(
            latency_df,
            date_time_min,
            date_time_max,
            filename=os.path.join(self.summary_path, "latency.png"),
        )
        plot_data(
            latency_df,
            "frac_high_latency",
            date_time_min,
            date_time_max,
            filename=os.path.join(self.summary_path, "frac_high_latency.png"),
        )

        plot_data(
            latency_df,
            "n_output_code_above_100",
            date_time_min,
            date_time_max,
            filename=os.path.join(
                self.summary_path, "n_output_code_above_100.png"
            ),
        )

        df_to_json_dict(
            latency_df, os.path.join(self.summary_path, "latency.json")
        )

    def generate_plots_for_revenue_tab(self, t_name, plot_list):
        plot_params = self.revenue_plot_params
        if "equal" in t_name:
            t_name_prelim = t_name.split("_equal")[0]
        if "individual" in t_name:
            t_name_prelim = t_name_prelim.replace("_individual", "")
        elif "plots" in t_name:
            t_name_prelim = t_name_prelim.replace("_plots", "")
        revenue_df = pd.read_json(
            os.path.join(self.output_path, f"{t_name_prelim}.json"),
            orient="index",
        )

        all_kwargs = set_plot_params(
            t_name,
            plot_params,
            self.date_time_min_default,
            self.date_time_max_default,
        )
        plot_params[f"{t_name}"] = all_kwargs

        update_history_pff_file = os.path.join(
            self.output_path, "update_history_pff.json"
        )
        update_history_pff = None
        update_history_pff_data = None
        if os.path.exists(update_history_pff_file):
            with open(update_history_pff_file, "r") as update_f:
                update_history_pff = json.load(update_f)
        category = get_category_from_tname(t_name)
        for k in insurance_type_mapping:
            if category in insurance_type_mapping[k]:
                insurance_type_for_category = k
        if update_history_pff:
            if "overall" not in t_name:
                update_history_pff_data = update_history_pff[
                    insurance_type_for_category
                ]
            else:
                update_history_pff_data = []
                for k in update_history_pff.keys():
                    update_history_pff_data.extend(update_history_pff[k])
                update_history_pff_data = list(
                    np.unique(update_history_pff_data)
                )
        revenue_df_updated, send_alert = plot_all_revenue_plots(
            df=revenue_df,
            name=t_name,
            save_path=self.summary_path,
            plot_list=plot_list,
            update_history_pff=update_history_pff_data,
            **all_kwargs,
        )
        df_to_json_dict(
            revenue_df_updated,
            os.path.join(self.summary_path, f"{t_name}.json"),
        )

        pd.DataFrame(plot_params).to_json(
            os.path.join(self.summary_path, "plot_limits_revenue.json")
        )
        self.revenue_plot_params = plot_params
        return revenue_df_updated, send_alert

    def generate_table_for_state_tab(self, t_name):
        name = t_name
        t_name_parts = parse_tab_name(name)
        t_name_revenue_type = t_name_parts["revenue_type"]
        plot_params = self.revenue_plot_params

        all_kwargs = set_table_params(
            name,
            plot_params,
            self.date_time_min_default,
            self.date_time_max_default,
        )
        plot_params[name] = all_kwargs
        state_summary = {st: {} for st in list_of_states}

        if t_name_revenue_type == "click":
            downstream_source_type = t_name_parts["downstream_source_type"]

            update_history_statebases_file = os.path.join(
                self.output_path,
                f"update_history_{downstream_source_type}.json",
            )
        elif t_name_revenue_type in ["call", "lead"]:
            partner_id = t_name_parts["partner_id"]

            update_history_statebases_file = os.path.join(
                self.output_path,
                f"update_history_{partner_id}_{t_name_revenue_type}.json",
            )

        update_history_statebases = None
        if os.path.exists(update_history_statebases_file):
            with open(update_history_statebases_file, "r") as update_f:
                update_history_statebases = json.load(update_f)

        for cat in list_of_states:
            last_correction_at = None
            if (
                update_history_statebases
                and cat in update_history_statebases.keys()
            ):
                if update_history_statebases[cat] != []:
                    last_correction_at = max(update_history_statebases[cat])

            try:
                if t_name_revenue_type == "click":
                    revenue_df = pd.read_json(
                        os.path.join(
                            self.output_path,
                            f"revenue_state_{cat}_"
                            f"source_{downstream_source_type}.json",
                        ),
                        orient="index",
                    )
                elif t_name_revenue_type in ["call", "lead"]:
                    revenue_df = pd.read_json(
                        os.path.join(
                            self.output_path,
                            f"revenue_state_{cat}_partner_{partner_id}.json",
                        ),
                        orient="index",
                    )
            except Exception as e:
                logging.exception(e)
                continue

            revenue_df = resample_df_by_equal_count_bin(
                revenue_df,
                count_column=f"conversions_count_{t_name_revenue_type}",
                target_count=all_kwargs["min_count_per_bin"],
            )
            revenue_df = add_cm_data(revenue_df)
            try:
                state_summary[cat] = get_table_summary_revenue_like(
                    revenue_df,
                    target_count=all_kwargs["min_count_per_bin"],
                    priority_limit=all_kwargs["priority_limit"],
                    last_correction_at=(last_correction_at),
                )
            except Exception as e:
                logger.exception(e)
                continue

        state_summary = pd.DataFrame.from_dict(state_summary, orient="index")
        if "recommended_correction" in state_summary.keys():
            if t_name_revenue_type == "click":
                state_summary[
                    [
                        "recommended_correction",
                        "most_recent_event_before",
                    ]
                ].to_json(
                    os.path.join(
                        self.output_path,
                        "recommended_correction_stateclickrev"
                        f"_{downstream_source_type}.json",
                    ),
                    orient="index",
                )
            elif t_name_revenue_type in ["call", "lead"]:
                state_summary[
                    [
                        "recommended_correction",
                        "most_recent_event_before",
                    ]
                ].to_json(
                    os.path.join(
                        self.output_path,
                        f"recommended_correction_state{t_name_revenue_type}pnz"
                        f"_{partner_id}.json",
                    ),
                    orient="index",
                )

        if not state_summary.empty:
            state_summary = state_summary.sort_values(
                by="total_n_click_events", ascending=False
            )
            new_colum_order = ["recommended_correction"] + [
                col
                for col in state_summary.keys()
                if col != "recommended_correction"
            ]
            state_summary = state_summary[new_colum_order]

        pd.DataFrame(state_summary).to_json(
            os.path.join(self.summary_path, f"{name}.json")
        )
        self.revenue_plot_params = plot_params

    def generate_plots_for_state_tab(self, t_name):
        plot_list = ["revenue_exp_cm"]
        t_name_parts = parse_tab_name(t_name)
        if "source" in t_name:
            t_name_revenue_type = "click"
        elif "partner" in t_name:
            t_name_revenue_type = "call_lead"

        plot_params = self.revenue_plot_params
        if t_name_revenue_type == "click":
            downstream_source_type = t_name_parts["downstream_source_type"]
        elif t_name_revenue_type == "call_lead":
            partner_id = t_name_parts["partner_id"]

        state = t_name.split("state_")[-1].split("_equal")[0]

        all_kwargs = set_plot_params(
            t_name,
            plot_params,
            self.date_time_min_default,
            self.date_time_max_default,
        )
        if t_name_revenue_type == "click":
            revenue_df = pd.read_json(
                os.path.join(
                    self.output_path,
                    f"revenue_state_{state}_"
                    f"source_{downstream_source_type}.json",
                ),
                orient="index",
            )

        elif t_name_revenue_type == "call_lead":
            revenue_df = pd.read_json(
                os.path.join(
                    self.output_path,
                    f"revenue_state_{state}_partner_{partner_id}.json",
                ),
                orient="index",
            )

        plot_params[f"{t_name}"] = all_kwargs
        revenue_df_updated, _ = plot_all_revenue_plots(
            df=revenue_df,
            name=t_name,
            save_path=self.summary_path,
            plot_list=plot_list,
            **all_kwargs,
        )

        df_to_json_dict(
            revenue_df_updated,
            os.path.join(self.summary_path, f"{t_name}.json"),
        )

        pd.DataFrame(plot_params).to_json(
            os.path.join(self.summary_path, "plot_limits_revenue.json")
        )

        self.revenue_plot_params = plot_params

    def generate_table_for_sourcetypeid_tab(self, t_name, target_count=50):
        plot_params = self.revenue_plot_params
        insurance_type = t_name.split("insurancetype_")[-1].split("_equal")[0]
        name = t_name

        list_of_sourcetype_files = glob.glob(
            self.output_path + f"/revenue_sourcetype_{insurance_type}_*.json"
        )
        list_of_source_type_ids = sorted(
            [
                sf.split("/")[-1].split(".")[0].split("_")[-1]
                for sf in list_of_sourcetype_files
            ]
        )

        summary_table_per_insurance_type = {
            k: {} for k in list_of_source_type_ids
        }
        all_kwargs = set_table_params(
            name,
            plot_params,
            self.date_time_min_default,
            self.date_time_max_default,
            target_count=target_count,
        )

        plot_params[f"{name}"] = all_kwargs

        update_history_sourcetypeid_file = os.path.join(
            self.output_path,
            f"update_history_sourcetypeid_{insurance_type}.json",
        )
        update_history_sourcetypeid = None
        if os.path.exists(update_history_sourcetypeid_file):
            with open(update_history_sourcetypeid_file, "r") as update_f:
                update_history_sourcetypeid = json.load(update_f)
        weights_file = os.path.join(
            self.output_path, "local_bases_db/feature_weights_local_db.csv"
        )
        weights_pff_bases_dict = None
        if os.path.exists(weights_file):
            weights_pff_bases_df = pd.read_csv(weights_file, index_col=[0])
            weights_pff_bases_df = db_conversion_utils.filter_by_param_name(
                db_conversion_utils.filter_by_feature_group(
                    db_conversion_utils.filter_by_model_id(
                        weights_pff_bases_df, insurance_type
                    ),
                    "source_type_id",
                ),
                "pff",
            )
            weights_pff_bases_df = weights_pff_bases_df[
                ["feature_group_type", "feature_weight"]
            ]
            weights_pff_bases_dict = weights_pff_bases_df.set_index(
                "feature_group_type"
            )["feature_weight"].to_dict()

        for sourcetype_id in list_of_source_type_ids:
            current_weight = None
            if weights_pff_bases_dict:
                if sourcetype_id in weights_pff_bases_dict.keys():
                    current_weight = float(
                        weights_pff_bases_dict[sourcetype_id]
                    )
            last_correction_at = None
            if (
                update_history_sourcetypeid
                and sourcetype_id in update_history_sourcetypeid.keys()
            ):
                if update_history_sourcetypeid[sourcetype_id] != []:
                    last_correction_at = max(
                        update_history_sourcetypeid[sourcetype_id]
                    )
            try:
                revenue_df = pd.read_json(
                    os.path.join(
                        self.output_path,
                        (
                            f"revenue_sourcetype_{insurance_type}"
                            f"_{sourcetype_id}.json"
                        ),
                    ),
                    orient="index",
                )
            except FileNotFoundError:
                continue
            if last_correction_at:
                revenue_df = revenue_df[revenue_df.index >= last_correction_at]
            if revenue_df.empty:
                continue

            revenue_df = combine_df_to_a_single_bin(revenue_df)

            revenue_df = add_cm_data(revenue_df)
            try:
                summary_table_per_insurance_type[sourcetype_id] = (
                    get_table_summary_pff_like(
                        revenue_df,
                        data_field="pff",
                        last_correction_at=(last_correction_at),
                        current_weight=current_weight,
                    )
                )
            except:
                continue
        summary_table_per_insurance_type = pd.DataFrame.from_dict(
            summary_table_per_insurance_type, orient="index"
        )

        recommended_correction_to_save = summary_table_per_insurance_type[
            [
                "recommended_correction",
                "most_recent_event_before",
            ]
        ]

        recommended_correction_to_save.to_json(
            os.path.join(
                self.output_path,
                "recommended_correction_pff" f"_{insurance_type}.json",
            ),
            orient="index",
        )

        if not summary_table_per_insurance_type.empty:
            summary_table_per_insurance_type = (
                summary_table_per_insurance_type.sort_values(
                    by="nclicked", ascending=False
                )
            )
            new_colum_order = ["recommended_correction"] + [
                col
                for col in summary_table_per_insurance_type.keys()
                if col != "recommended_correction"
            ]
            summary_table_per_insurance_type = (
                summary_table_per_insurance_type[new_colum_order]
            )

        pd.DataFrame(summary_table_per_insurance_type).to_json(
            os.path.join(self.summary_path, f"{name}.json")
        )

        self.revenue_plot_params = plot_params
        return summary_table_per_insurance_type


def generate_plots(
    arguments,
    plot_list=[
        "pff",
        "cm",
        "revenue_frac",
        "revenue_exp_cm",
        "revenue_payout",
        "revenue_nz",
    ],
    tab_list=["all"],
    send_email_alert=False,
    send_slack_alert=False,
):
    config_attrs = config.load(arguments.config_file)
    generate_plots_and_table = GeneratePlotsAndTable(config_attrs)
    output_path = generate_plots_and_table.output_path

    if arguments.only_for_update:
        make_plots = False
        make_table = True
    elif arguments.only_for_plots:
        make_plots = True
        make_table = False
    else:
        make_plots = True
        make_table = True

    if make_table:
        # -----------------------------------------------------------------
        # Setting up tab for revenue-state table
        # Getting a list of different tab names
        if "all" in tab_list:
            individual_tab_name_list = []
            for binning_type in ["equalcount"]:
                for downstream_source_type in downstream_source_types:
                    individual_tab_name_list.append(
                        get_tab_name(
                            tab_type="table",
                            table_type="state",
                            downstream_source_type=downstream_source_type,
                            binning_type=binning_type,
                            revenue_type="click",
                        )
                    )
        else:
            individual_tab_name_list = []
            for t in tab_list:
                search_list = ["table_state"]
                contains = any(substring in t for substring in search_list)
                if contains:
                    individual_tab_name_list.append(t)

        for t_name in individual_tab_name_list:
            logger.info(f"Generating table for {t_name}")
            try:
                generate_plots_and_table.generate_table_for_state_tab(
                    t_name=t_name
                )
            except Exception as e:
                logger.exception(e)
                continue

        for revenue_type in ["call", "lead"]:
            if "all" in tab_list:
                individual_tab_name_list = []
                for binning_type in ["equalcount"]:
                    for partner_id in partner_ids:
                        individual_tab_name_list.append(
                            get_tab_name(
                                tab_type="table",
                                table_type="state",
                                partner_id=partner_id,
                                binning_type=binning_type,
                                revenue_type=revenue_type,
                            )
                        )
            else:
                individual_tab_name_list = []
                for t in tab_list:
                    search_list = ["table_state"]
                    contains = any(substring in t for substring in search_list)
                    if contains:
                        individual_tab_name_list.append(t)

            for t_name in individual_tab_name_list:
                logging.info(f"Generating table for {t_name}")
                try:
                    generate_plots_and_table.generate_table_for_state_tab(
                        t_name=t_name
                    )
                except Exception as e:
                    logging.exception(e)
                    continue

        # -----------------------------------------------------------------
        # Setting up tab for pff-sourcetype_id table
        # Getting a list of different tab names
        if "all" in tab_list:
            individual_tab_name_list = []
            for binning_type in ["equalcount"]:
                for insurance_type in ["auto", "home"]:

                    individual_tab_name_list.append(
                        get_tab_name(
                            tab_type="table",
                            table_type="pff",
                            insurance_type=insurance_type,
                            binning_type=binning_type,
                        )
                    )
        else:
            individual_tab_name_list = []
            for t in tab_list:
                search_list = ["pff"]
                contains = any(substring in t for substring in search_list)
                if contains:
                    individual_tab_name_list.append(t)
        for t_name in individual_tab_name_list:
            logger.info(f"Generating table for {t_name}")
            try:
                summary_table_per_insurance_type = generate_plots_and_table.generate_table_for_sourcetypeid_tab(
                    t_name
                )
                recommended_correction_numeric = pd.to_numeric(
                    summary_table_per_insurance_type["recommended_correction"],
                    errors="coerce",
                )
                summary_table_per_insurance_type_alert = (
                    summary_table_per_insurance_type[
                        abs(recommended_correction_numeric) > 0.0
                    ]
                )
                if not summary_table_per_insurance_type_alert.empty:
                    if send_slack_alert:
                        summary_table_per_insurance_type_alert.index.name = (
                            "sourcetype_id"
                        )
                        mark_down_table = (
                            summary_table_per_insurance_type_alert[
                                [
                                    "recommended_correction",
                                    "new_weight",
                                    "zscore",
                                    "nff_measured",
                                    "nclicked",
                                    "nclicked_in_24h",
                                    "correction_from_conf_int",
                                ]
                            ].to_markdown(index=True)
                        )

                        body = (
                            "recommended pff correction for new "
                            "sourectype_ids in "
                            f"{t_name.split('pff_')[1].split('_equal')[0]}\n"
                            f" ```{mark_down_table}```"
                        )
                        slack_utils.send_slack_message_by_env(
                            message=body,
                            env=config_attr["env"],
                            subject="Daily Monitor: Warnings",
                        )

            except Exception as e:
                logger.exception(e)
                continue
    if make_plots:

        # -----------------------------------------------------------------
        # Setting up tab for revenue and pff plots for combined tabs
        # Getting a list of different tab names
        if "all" in tab_list:
            individual_tab_name_list = []
            for binning_type in ["equalwidth", "equalcount"]:
                for campaign_id in campaign_ids:
                    individual_tab_name_list.append(
                        get_tab_name(
                            tab_type="plots",
                            tab_name="by campaign_id",
                            campaign_id=campaign_id,
                            binning_type=binning_type,
                        )
                    )
                for partner_id in partner_ids:
                    individual_tab_name_list.append(
                        get_tab_name(
                            tab_type="plots",
                            tab_name="by partner_id",
                            partner_id=partner_id,
                            binning_type=binning_type,
                        )
                    )
                for downstream_source_type in downstream_source_types:
                    individual_tab_name_list.append(
                        get_tab_name(
                            tab_type="plots",
                            tab_name="by downstream_source",
                            downstream_source_type=downstream_source_type,
                            binning_type=binning_type,
                        )
                    )
        else:
            individual_tab_name_list = []
            for t in tab_list:
                search_list = ["plots"]
                contains = any(substring in t for substring in search_list)
                if contains:
                    contains_state = any(
                        substring in t for substring in ["plots_state"]
                    )
                    if not contains_state:
                        individual_tab_name_list.append(t)

        individual_tab_name_list = sorted(individual_tab_name_list)
        alert_list_pff = []
        for t_name in individual_tab_name_list:

            logger.info(f"Generating plots for {t_name}")
            try:
                _, send_alert = (
                    generate_plots_and_table.generate_plots_for_revenue_tab(
                        t_name=t_name, plot_list=["revenue_exp_cm", "pff"]
                    )
                )
                if send_alert:
                    alert_list_pff.append(get_category_from_tname(t_name))
            except Exception as e:
                logger.exception(e)
                continue
        if send_email_alert or send_slack_alert:
            if alert_list_pff != []:
                pff_drops_file = os.path.join(output_path, "pff_drops.json")
                if os.path.exists(pff_drops_file):

                    with open(pff_drops_file, "r") as f:
                        alert_list_pff_dict = json.load(f)
                    last_drop_alert_at = max(alert_list_pff_dict.keys())
                    last_drop_alert = alert_list_pff_dict[last_drop_alert_at]
                else:
                    alert_list_pff_dict = {}
                    last_drop_alert_at = None
                    last_drop_alert = []
                now = (
                    datetime.now(timezone.utc)
                    .astimezone(timezone.utc)
                    .replace(tzinfo=None, microsecond=0)
                )
                alert_list_pff_dict_now = {}
                alert_list_pff_dict_now[str(now)] = alert_list_pff
                if not sorted(last_drop_alert) == sorted(alert_list_pff):
                    new_set_of_drop_list = list(
                        np.unique(
                            np.array(
                                [
                                    x
                                    for x in alert_list_pff
                                    if x not in last_drop_alert
                                ]
                            )
                        )
                    )
                    with open(pff_drops_file, "w") as f:
                        json.dump(alert_list_pff_dict_now, f, indent=4)
                    if new_set_of_drop_list != []:
                        body = ", ".join(new_set_of_drop_list)
                        body = f"pff dropped below -0.1 for {body}."
                        if send_email_alert:
                            email_utils.send_email(
                                body=body,
                                env=env_name,
                                email=config_attr["jobs"]["email"],
                                subject="Daily Monitor: Warnings",
                            )
                        if send_slack_alert:
                            slack_utils.send_slack_message_by_env(
                                message=body,
                                env=env_name,
                                subject="Daily Monitor: Warnings",
                            )

        # -----------------------------------------------------------------

        # Setting up tab for all plots for individual tabs
        # Getting a list of different tab names
        if "all" in tab_list:
            individual_tab_name_list = []
            for binning_type in ["equalwidth", "equalcount"]:
                individual_tab_name_list.append(
                    get_tab_name(
                        tab_type="individual",
                        tab_name="overall",
                        binning_type=binning_type,
                    )
                )
                for campaign_id in campaign_ids:
                    individual_tab_name_list.append(
                        get_tab_name(
                            tab_type="individual",
                            tab_name="by campaign_id",
                            campaign_id=campaign_id,
                            binning_type=binning_type,
                        )
                    )
                for partner_id in partner_ids:
                    individual_tab_name_list.append(
                        get_tab_name(
                            tab_type="individual",
                            tab_name="by partner_id",
                            partner_id=partner_id,
                            binning_type=binning_type,
                        )
                    )
                for downstream_source_type in downstream_source_types:
                    individual_tab_name_list.append(
                        get_tab_name(
                            tab_type="individual",
                            tab_name="by downstream_source",
                            downstream_source_type=downstream_source_type,
                            binning_type=binning_type,
                        )
                    )
        else:
            individual_tab_name_list = []
            for t in tab_list:
                search_list = ["table", "latency", "plots"]
                contains = any(substring in t for substring in search_list)
                if not contains:
                    individual_tab_name_list.append(t)

        individual_tab_name_list = sorted(individual_tab_name_list)
        for t_name in individual_tab_name_list:
            logger.info(f"Generating plots for {t_name}")
            try:
                generate_plots_and_table.generate_plots_for_revenue_tab(
                    t_name=t_name, plot_list=plot_list
                )
            except Exception as e:
                logger.exception(e)
                continue

        # -----------------------------------------------------------------
        if "latency" or "all" in tab_list:

            logger.info("Generating plots for latency")
            generate_plots_and_table.generate_plots_for_latency_tab()

        # -----------------------------------------------------------------
        # Setting up tab for revenue-state plots
        # Getting a list of different tab names

        if "all" in tab_list:
            individual_tab_name_list = []
            for binning_type in ["equalcount"]:
                for downstream_source_type in downstream_source_types:
                    for state in list_of_states:
                        individual_tab_name_list.append(
                            get_tab_name(
                                tab_type="plots",
                                table_type="state",
                                downstream_source_type=downstream_source_type,
                                state=state,
                                binning_type=binning_type,
                            )
                        )
                for partner_id in partner_ids:
                    for state in list_of_states:
                        individual_tab_name_list.append(
                            get_tab_name(
                                tab_type="plots",
                                table_type="state",
                                partner_id=partner_id,
                                state=state,
                                binning_type=binning_type,
                            )
                        )

        else:
            individual_tab_name_list = []
            for t in tab_list:
                search_list = ["plots_state"]
                contains = any(substring in t for substring in search_list)
                if contains:
                    individual_tab_name_list.append(t)
        for t_name in individual_tab_name_list:
            logger.info(f"Generating plots for {t_name}")
            try:
                generate_plots_and_table.generate_plots_for_state_tab(t_name)
            except Exception as e:
                logger.exception(e)
                continue

    # -----------------------------------------------------------------


if __name__ == "__main__":
    args = parse_arguments(script_name=Path(__file__).stem)
    config_attr = config.load(args.config_file)
    send_email_alert = config_attr["jobs"]["email_alert"]
    send_slack_alert = config_attr["jobs"]["slack_alert"]

    generate_plots(
        args,
        send_email_alert=send_email_alert,
        send_slack_alert=send_slack_alert,
    )
