import os
import logging
import ast
import math
import tempfile
import concurrent.futures

import numpy as np
import pandas as pd

from datetime import datetime, timedelta, time, timezone
from pathlib import Path

# Project imports
from src.scripts import (
    query_data,
)
from src.utils import categories_and_mapping, stat_utils, query_utils, config
from ..aws_utils import aws_utils
from src.environment.initialize_environment import environment_info
from src.utils.argument_parser_utils import parse_arguments
from src.src_root import src_root


script_start_time = datetime.now()

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

categories_and_mapping_dict = (
    categories_and_mapping.get_categories_and_mapping()
)

rev_types = categories_and_mapping_dict["rev_types"]
rev_type_color = categories_and_mapping_dict["rev_type_color"]
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
insurance_type_campaign_mapping = categories_and_mapping_dict[
    "insurance_type_campaign_mapping"
]
list_of_states = categories_and_mapping_dict["list_of_states"]


hourly_times = [time(hour=i) for i in range(24)]


class Monitor:
    def __init__(self, args):
        self.args = args
        self.config_attrs = config.load(self.args.config_file)
        self.today = None
        self.yesterday = None
        self.dates_to_monitor = []
        self.end_date = None
        self.set_today_yesterday()
        self.file_store = aws_utils.FileStore(
            bucket_name=environment_info.S3_BUCKET
        )
        self.last_day_file_s3_key = (
            f"{aws_utils.S3Prefixes.get_output_runs()}/last_day.txt"
        )
        self.output_path = str(
            Path(src_root, self.config_attrs["output_path"])
        )

    def save_to_s3_output_dir(self, file_path):
        file_name = Path(file_path).name
        self.file_store.upload_file(
            file_path, f"{aws_utils.S3Prefixes.get_output_runs()}/{file_name}"
        )

    def set_today_yesterday(self):
        self.today = datetime.now().date()
        self.yesterday = self.today - timedelta(days=1)

    def get_dates(self):
        self.set_today_yesterday()
        self.end_date = self.today

        last_day_file_obj = self.file_store.download_tmp_file(
            self.last_day_file_s3_key
        )

        if self.config_attrs["date"]:
            dates_to_monitor = [self.config_attrs["date"]]
        else:
            if last_day_file_obj is None:
                dates_to_monitor = [self.yesterday]
            else:
                last_day_file = last_day_file_obj.name
                with open(last_day_file, "r") as f:
                    last_day_line = f.read()
                try:
                    last_monitored_day_time = datetime.strptime(
                        last_day_line.split("\n")[0], "%Y-%m-%d %H:%M:%S"
                    )
                except:
                    x = last_day_line.split("\n")[0] + " 00:00:00"
                    last_monitored_day_time = datetime.strptime(
                        x, "%Y-%m-%d %H:%M:%S"
                    )

                last_monitored_day = last_monitored_day_time.date()
                self.last_monitored_time = last_monitored_day_time.time()

                next_day_to_monitor = last_monitored_day
                dates_to_monitor = [next_day_to_monitor]
                while next_day_to_monitor < self.end_date:
                    next_day_to_monitor = next_day_to_monitor + timedelta(
                        days=1
                    )
                    dates_to_monitor.append(next_day_to_monitor)
        self.dates_to_monitor = dates_to_monitor
        return (
            self.today,
            self.yesterday,
            self.dates_to_monitor,
            self.last_monitored_time,
        )

    def run_query(
        self,
        query_template,
        template_variables,
        res_filename_identification=None,
        merge=True,
    ):
        logger.info(f"Pulling data from {query_template[:-11]}")
        template_file = self.config_attrs[query_template]
        template_file_path = Path(src_root, template_file)
        template_file_path_str = str(template_file_path)
        sql_query = query_utils.render_query_template(
            template_file_path_str, template_variables
        )

        output_path = self.output_path
        logger.info(f"SQL Query: \n{sql_query}")
        filename_child = template_file_path.name
        if res_filename_identification is None:
            res_filename = os.path.join(
                output_path, filename_child.replace(".jinja2", ".json")
            )
        elif res_filename_identification == "campaign_id":
            res_filename = os.path.join(
                output_path,
                filename_child.replace(
                    ".jinja2", f"_{template_variables['campaign_id']}.json"
                ),
            )
        ssh_res = query_data.save_query_res(
            sql_query,
            filename=res_filename,
            merge=merge,
        )
        return ssh_res

    def read_query_res(
        self,
        query_template,
        template_variables=None,
        res_filename_identification=None,
    ):
        logger.info(f"Reading data from {query_template[:-11]}")

        output_path = self.output_path
        filename_child = self.config_attrs[query_template].split("/")[-1]
        if res_filename_identification is None:
            res_filename = os.path.join(
                output_path,
                filename_child.replace(".jinja2", ".json"),
            )
        elif res_filename_identification == "campaign_id":
            res_filename = os.path.join(
                output_path,
                filename_child.replace(
                    ".jinja2", f"_{template_variables['campaign_id']}.json"
                ),
            )
        try:
            res_pd = pd.read_json(res_filename, orient="records", lines=True)
        except Exception as e:
            logger.exception(
                f"Failed reading data from  {query_template[:-11]}: {e}"
            )
            res_pd = None

        return res_pd

    def get_all_click_data(self, template_variables):

        click_listing_res = self.run_query(
            "click_listing_query_file", template_variables, "campaign_id"
        )
        click_conversions_res = self.run_query(
            "click_conversions_query_file", template_variables, "campaign_id"
        )

        return click_listing_res, click_conversions_res

    def save_latency_data(self, rtb_query_res, query_date):
        latency_file_s3_key = (
            f"{aws_utils.S3Prefixes.get_output_runs()}/latency.txt"
        )
        output_path = self.output_path
        latency_file_name = os.path.join(output_path, "latency.txt")
        file_exists = os.path.isfile(latency_file_name)
        if not file_exists:
            logger.info("Fetching latency.txt from S3")
            file_exists = self.file_store.download_file(
                latency_file_s3_key, latency_file_name
            )

        rtb_query_res = add_date_time(rtb_query_res, "created_at")
        rtb_query_res = filter_by_day(rtb_query_res, query_date)
        latency = rtb_query_res["latency"]
        std = np.std(latency)
        mean, ci_l, ci_u = stat_utils.confidence_interval_percentile(latency)
        n_high_latency = sum(latency > 100)
        fract_high_latency = n_high_latency / len(latency)

        output_code = rtb_query_res["output_code"].astype("int")
        n_output_code_above_100 = sum(output_code > 100)
        if not file_exists:
            with open(latency_file_name, "w") as file:
                file.write(
                    "date mean std ci_l ci_u n_high_latency "
                    "frac_high_latency n_output_code_above_100\n"
                )

        with open(latency_file_name, "a") as f:
            f.write(
                f"{query_date} {mean} {std} {ci_l} {ci_u} "
                f"{n_high_latency} {fract_high_latency} "
                f"{n_output_code_above_100}\n",
            )

        self.file_store.upload_file(latency_file_name, latency_file_s3_key)

    def set_last_monitored_day(self, query_date):
        logger.debug(f"Set_last_monitored_day {query_date}")
        tmp_file = tempfile.NamedTemporaryFile()
        with open(tmp_file.name, "w") as f:
            f.write(str(query_date))
        self.file_store.upload_file(tmp_file.name, self.last_day_file_s3_key)

    def save_revenue_res(
        self, result_dict, filename="revenue.json", combine=True
    ):
        result_df = pd.DataFrame.from_dict(result_dict, orient="index")
        result_df.index.name = "date"
        output_path = self.output_path
        revenue_filename = os.path.join(output_path, filename)
        revenue_file_exists = os.path.exists(revenue_filename)
        revenue_file_s3_key = (
            f"{aws_utils.S3Prefixes.get_output_runs()}/{filename}"
        )
        if not revenue_file_exists:
            logger.debug(f"Fetching {revenue_filename} from S3")
            revenue_file_exists = self.file_store.download_file(
                revenue_file_s3_key, revenue_filename
            )

        if revenue_file_exists and combine:
            existing_df = pd.read_json(revenue_filename, orient="index")
            combined_df = pd.concat([existing_df, result_df])
        else:
            combined_df = result_df

        combined_df = combined_df[~combined_df.index.duplicated(keep="last")]
        combined_df = combined_df.sort_index()

        end_datetime = combined_df.index.max()
        start_datetime = combined_df.index[
            combined_df.index.get_indexer(
                [end_datetime - pd.Timedelta(days=90)], method="nearest"
            )[0]
        ]

        combined_df = combined_df[start_datetime:end_datetime]
        combined_df.to_json(revenue_filename, orient="index")
        self.file_store.upload_file(revenue_filename, revenue_file_s3_key)
        return combined_df


def drop_negative_revenue(df):
    df["abs_revenue"] = df["revenue"].abs()

    df.sort_values(
        by=["click_listing_id", "rev_type", "revenue"], inplace=True
    )

    grouped = df.groupby(["click_listing_id", "abs_revenue"])

    rows_to_drop = []

    for _, group in grouped:
        positive_revenue = group[group["revenue"] > 0]
        negative_revenue = group[group["revenue"] < 0]

        if len(negative_revenue) > 0:

            if len(negative_revenue) == len(positive_revenue):

                rows_to_drop += list(negative_revenue.index)
                rows_to_drop += list(positive_revenue.index)
            elif len(positive_revenue) > len(negative_revenue):
                rows_to_drop += list(negative_revenue.index)
                rows_to_drop += list(
                    positive_revenue.index[: len(negative_revenue)]
                )
            else:
                rows_to_drop += list(negative_revenue.index)

    df.drop(rows_to_drop, inplace=True)

    df.drop(columns="abs_revenue", inplace=True)
    return df


def join_data_frames(click_listing_db, click_conversions_db, rtb_bids_db):
    logger.info("Joining DataFrames")
    click_listing_db.rename(columns={"id": "click_listing_id"}, inplace=True)
    click_listing_db.rename(
        columns={"created_at": "listing_created_at"}, inplace=True
    )

    click_conversions_db = click_conversions_db.drop(["id"], axis=1)
    click_conversions_db.rename(
        columns={"created_at": "conversions_created_at"}, inplace=True
    )

    merged_df = pd.merge(
        click_conversions_db,
        click_listing_db,
        on="click_listing_id",
        how="outer",
        suffixes=("_conversions", "_listing"),
    )

    merged_df["listing_created_at"] = merged_df[
        "listing_created_at_listing"
    ].fillna(merged_df["listing_created_at_conversions"])

    merged_df.drop(
        ["listing_created_at_listing", "listing_created_at_conversions"],
        axis=1,
        inplace=True,
    )

    merged_df = add_date_time(merged_df, "listing_created_at")

    rtb_bids_db = rtb_bids_db.drop(["id", "created_at"], axis=1)

    merged_df = pd.merge(
        merged_df,
        rtb_bids_db,
        on="click_ping_id",
        how="outer",
        suffixes=("_click", "_rtb"),
    )

    merged_df["conversions_delay"] = (
        merged_df["conversions_created_at"] - merged_df["listing_created_at"]
    ).apply(lambda x: x.total_seconds())
    merged_df["conversions_delay"] = merged_df["conversions_delay"].fillna(0)

    response_text = merged_df["response_text"]
    response_text = [
        ast.literal_eval(x) if isinstance(x, str) else None
        for x in response_text
    ]
    state = [
        x["state"] if x is not None and "state" in x.keys() else None
        for x in response_text
    ]
    merged_df["state"] = state
    output_code = [
        (
            x["output_code"]
            if x is not None and "output_code" in x.keys()
            else None
        )
        for x in response_text
    ]
    merged_df["output_code"] = output_code

    merged_df = drop_negative_revenue(merged_df)

    return merged_df


def get_revenue_payout_dict(dataframe, campaign_ids_list=None):
    return_dict = {}

    return_dict["revenue_total"] = dataframe["revenue"].sum(skipna=True)
    (
        _,
        return_dict["revenue_total_variance"],
    ) = stat_utils.get_mean_and_variance(dataframe["revenue"])

    for rev_type in rev_types:
        dataframe_by_type = filter_by_revtype(dataframe, rev_type)
        revenue_for_type = dataframe_by_type["revenue"]
        return_dict[f"revenue_{rev_type}"] = revenue_for_type.sum(skipna=True)
        count = dataframe_by_type["revenue"].notna().sum()

        return_dict[f"conversions_count_{rev_type}"] = count

        (
            _,
            return_dict[f"revenue_{rev_type}_variance"],
        ) = stat_utils.get_mean_and_variance(revenue_for_type)

    # Filtering type 1
    first_instance_indices = dataframe.drop_duplicates(
        subset="click_listing_id", keep="first"
    ).index
    dataframe_filtered = dataframe.loc[first_instance_indices]

    payout_list = dataframe_filtered["payout"]
    payout, payout_n = payout_list.sum(), len(payout_list)

    return_dict["payout"] = payout
    return_dict["listing_count"] = payout_n
    return_dict["n_clicked"] = payout_n

    return_dict["conversions_count"] = (
        dataframe_filtered["revenue"].notna().sum()
    )
    return_dict["n_output_code_non_zero"] = sum(
        dataframe_filtered["output_code"] > 0
    )

    return_dict["pff_total"] = 0.0

    response_text = dataframe_filtered["response_text"]
    dataframe_campaingn_id = np.array(
        dataframe_filtered["campaign_id"]
    ).astype(int)

    expected_revenue = {f"revenue_exp_{k}": 0.0 for k in rev_types}
    expected_revenue["revenue_exp_total"] = 0.0
    expected_revenue_list = {f"revenue_exp_{k}": [] for k in rev_types}
    expected_revenue_list["revenue_exp_total"] = []

    for i, x in enumerate(response_text):
        if isinstance(x, str):
            resp_text = ast.literal_eval(x)
        else:
            continue
        if "campaign_revenue" in resp_text.keys():
            campaign_id_available = resp_text["campaign_revenue"].keys()
        else:
            continue
        campaign_ids_per_category = np.array(campaign_ids_list).astype(str)
        for campaign_id in campaign_ids_per_category:
            if campaign_id in campaign_id_available:
                if campaign_id == str(dataframe_campaingn_id[i]):
                    expected_revenue["revenue_exp_total"] += resp_text[
                        "campaign_revenue"
                    ][campaign_id]
                    expected_revenue_list["revenue_exp_total"].append(
                        resp_text["campaign_revenue"][campaign_id]
                    )

                    campaign_breakdown = resp_text["campaign_breakdown"][
                        campaign_id
                    ]
                    pff = campaign_breakdown["pff"]
                    return_dict["pff_total"] += pff

                    for rev_type in rev_types:
                        pnz = campaign_breakdown[f"pnz_{rev_type}"]
                        nz = campaign_breakdown[f"nz_rev_{rev_type}"]
                        exp_revenue_i = pff * pnz * nz
                        expected_revenue[
                            f"revenue_exp_{rev_type}"
                        ] += exp_revenue_i
                        expected_revenue_list[
                            f"revenue_exp_{rev_type}"
                        ].append(exp_revenue_i)

    # Filtering type 2
    idx = dataframe.loc[
        dataframe.groupby(["click_listing_id", "rev_type"])["revenue"].idxmax()
    ].index
    dataframe_filtered = dataframe.loc[idx]

    response_text = dataframe_filtered["response_text"]
    dataframe_campaingn_id = np.array(
        dataframe_filtered["campaign_id"]
    ).astype(int)

    for k in rev_types:
        expected_revenue[f"nz_exp_{k}"] = 0.0
    for k in rev_types:
        expected_revenue[f"pnz_exp_{k}"] = 0.0

    measured_revenue = {f"max_nz_{k}": 0.0 for k in rev_types}
    for k in rev_types:
        measured_revenue[f"nz_count_{k}"] = 0

    for i, x in enumerate(response_text):
        data_filtered_i = dataframe_filtered.iloc[i]
        revenue_type_i = data_filtered_i["rev_type"]
        revenue_i = data_filtered_i["revenue"]
        if not math.isnan(revenue_i):
            measured_revenue[f"max_nz_{revenue_type_i}"] += revenue_i
            measured_revenue[f"nz_count_{revenue_type_i}"] += 1

        if isinstance(x, str):
            resp_text = ast.literal_eval(x)
        else:
            continue
        if "campaign_revenue" in resp_text.keys():
            campaign_id_available = resp_text["campaign_revenue"].keys()
        else:
            continue
        campaign_ids_per_category = np.array(campaign_ids_list).astype(str)
        for campaign_id in campaign_ids_per_category:
            if campaign_id in campaign_id_available:
                if campaign_id == str(dataframe_campaingn_id[i]):

                    campaign_breakdown = resp_text["campaign_breakdown"][
                        campaign_id
                    ]

                    if not math.isnan(revenue_i):
                        expected_revenue[
                            f"nz_exp_{revenue_type_i}"
                        ] += campaign_breakdown[f"nz_rev_{revenue_type_i}"]
                        expected_revenue[
                            f"pnz_exp_{revenue_type_i}"
                        ] += campaign_breakdown[f"pnz_{revenue_type_i}"]

    return_dict = return_dict | measured_revenue
    for rev_type in rev_types:
        (
            _,
            expected_revenue[f"revenue_exp_{rev_type}_variance"],
        ) = stat_utils.get_mean_and_variance(
            expected_revenue_list[f"revenue_exp_{rev_type}"]
        )
    (
        _,
        expected_revenue["revenue_exp_total_variance"],
    ) = stat_utils.get_mean_and_variance(
        expected_revenue_list["revenue_exp_total"]
    )

    return_dict = return_dict | expected_revenue

    return return_dict


def combine_date_and_time(date_obj, time_obj):
    combined_datetime = datetime.combine(date_obj, time_obj)
    return combined_datetime


def add_date_time(dataframe, datetime_column):
    date_time = dataframe[datetime_column]
    date = [date.date() for date in date_time]
    time = [date.time() for date in date_time]
    dataframe["date"] = date
    dataframe["time"] = time
    return dataframe


def filter_by_day(dataframe, day):

    return dataframe[dataframe["date"] == day]


def filter_by_day_and_hour(dataframe, datetime_column, day, hour):
    datetime = combine_date_and_time(day, hour)
    by_day = filter_by_day(dataframe, day)
    return by_day[
        (by_day[datetime_column].dt.to_pydatetime() >= datetime)
        & (
            by_day[datetime_column].dt.to_pydatetime()
            < datetime + timedelta(hours=1)
        )
    ]


def filter_by_state(dataframe, state):
    return dataframe[dataframe["state"] == state]


def filter_by_sourcetypeid(dataframe, source_type_id):
    return dataframe[dataframe["source_type_id"] == source_type_id]


def filter_by_insurancetype(
    dataframe, insurance_type, available_campaigns=None
):
    campaigns = np.array(
        insurance_type_campaign_mapping[insurance_type]
    ).astype(float)
    if available_campaigns:
        campaigns = list(
            set(campaigns) & set([float(x) for x in available_campaigns])
        )
    return dataframe[dataframe["campaign_id"].isin(campaigns)]


def filter_by_revtype(dataframe, rev_type):
    if rev_type == "click":
        ret_df = dataframe[
            (dataframe["rev_type"] == rev_type) * (dataframe["revenue"] > 0)
        ]
    else:
        ret_df = dataframe[dataframe["rev_type"] == rev_type]
    return ret_df


def filter_by_partner(dataframe, partner_id, available_campaigns=None):
    campaigns = np.array(partner_campaign_mapping[partner_id]).astype(float)
    if available_campaigns:
        campaigns = list(
            set(campaigns) & set([float(x) for x in available_campaigns])
        )
    return dataframe[dataframe["campaign_id"].isin(campaigns)]


def filter_by_downstreamsource(
    dataframe, source_type, available_campaigns=None
):
    campaigns = np.array(
        downstreamsource_campaign_mapping[source_type]
    ).astype(float)
    if available_campaigns:
        campaigns = list(
            set(campaigns) & set([float(x) for x in available_campaigns])
        )

    return dataframe[dataframe["campaign_id"].isin(campaigns)]


def get_time_delay(dataframe):
    time_diff = dataframe["conversions_delay"]
    if len(time_diff) != 0.0:
        mean_time_diff = np.mean(time_diff)
        median_time_diff = np.median(time_diff)
        max_time_diff = max(time_diff)
        min_time_diff = min(time_diff)
    else:
        mean_time_diff = 0.0
        median_time_diff = 0.0
        max_time_diff = 0.0
        min_time_diff = 0.0
    return {
        "min": min_time_diff,
        "max": max_time_diff,
        "mean": mean_time_diff,
        "median": median_time_diff,
    }


class ParallelizeLoops:
    def __init__(
        self, unique_days, joined_df_combined, all_campaign_ids, monitor_obj
    ):
        self.unique_days = unique_days
        self.joined_df_combined = joined_df_combined
        self.all_campaign_ids = all_campaign_ids
        self.monitor_obj = monitor_obj

    def state_summary_parallel(self, st):
        result_dict_source = {d: {} for d in self.unique_days}
        logger.info(f"Summarizing state = {st}")
        joined_df_by_state = filter_by_state(self.joined_df_combined, st)
        for day in self.unique_days:
            for hour in hourly_times:
                datetime_key = combine_date_and_time(day, hour)
                joined_df_by_state_by_day = filter_by_day_and_hour(
                    joined_df_by_state, "listing_created_at", day, hour
                )
                res_dict = get_revenue_payout_dict(
                    joined_df_by_state_by_day,
                    self.all_campaign_ids,
                )
                if res_dict["listing_count"] != 0:
                    result_dict_source[datetime_key] = res_dict
        if not all(
            isinstance(value, dict) and not value
            for value in result_dict_source.values()
        ):

            self.monitor_obj.save_revenue_res(
                result_dict_source, f"revenue_state_{st}.json"
            )

        for source_type in downstream_source_types:
            result_dict_source = {d: {} for d in self.unique_days}
            logger.info(
                f"Summarizing state = {st}, source_type= {source_type}"
            )
            joined_df_by_state_by_source = filter_by_downstreamsource(
                joined_df_by_state, source_type, self.all_campaign_ids
            )
            for day in self.unique_days:
                for hour in hourly_times:
                    datetime_key = combine_date_and_time(day, hour)
                    joined_df_by_state_by_source_by_day = (
                        filter_by_day_and_hour(
                            joined_df_by_state_by_source,
                            "listing_created_at",
                            day,
                            hour,
                        )
                    )
                    res_dict = get_revenue_payout_dict(
                        joined_df_by_state_by_source_by_day,
                        self.all_campaign_ids,
                    )
                    if res_dict["listing_count"] != 0:
                        result_dict_source[datetime_key] = res_dict
            if not all(
                isinstance(value, dict) and not value
                for value in result_dict_source.values()
            ):

                self.monitor_obj.save_revenue_res(
                    result_dict_source,
                    f"revenue_state_{st}_source_{source_type}.json",
                )

        for partner_id in partner_ids:
            result_dict_source = {d: {} for d in self.unique_days}
            logger.info(f"Summarizing state = {st}, partner_id= {partner_id}")
            joined_df_by_state_by_partner = filter_by_partner(
                joined_df_by_state, partner_id, self.all_campaign_ids
            )
            for day in self.unique_days:
                for hour in hourly_times:
                    datetime_key = combine_date_and_time(day, hour)
                    joined_df_by_state_by_partner_by_day = (
                        filter_by_day_and_hour(
                            joined_df_by_state_by_partner,
                            "listing_created_at",
                            day,
                            hour,
                        )
                    )
                    res_dict = get_revenue_payout_dict(
                        joined_df_by_state_by_partner_by_day,
                        self.all_campaign_ids,
                    )
                    if res_dict["listing_count"] != 0:
                        result_dict_source[datetime_key] = res_dict
            if not all(
                isinstance(value, dict) and not value
                for value in result_dict_source.values()
            ):

                self.monitor_obj.save_revenue_res(
                    result_dict_source,
                    f"revenue_state_{st}_partner_{partner_id}.json",
                )

    def sourcetypeid_summary_parallel(self, source_type_id):
        joined_df_by_sourcetype = filter_by_sourcetypeid(
            self.joined_df_combined, source_type_id
        )
        for insurance_type in insurance_types:
            result_dict_source_type = {d: {} for d in self.unique_days}

            logger.info(
                f"Summarizing source_type_id = {int(source_type_id)},"
                f" insurance_type = {insurance_type} "
            )

            joined_df_by_sourcetype_by_insurancetype = filter_by_insurancetype(
                joined_df_by_sourcetype, insurance_type
            )
            for day in self.unique_days:
                for hour in hourly_times:
                    datetime_key = combine_date_and_time(day, hour)
                    joined_df_by_sourcetype_by_insurancetype_by_day = (
                        filter_by_day_and_hour(
                            joined_df_by_sourcetype_by_insurancetype,
                            "listing_created_at",
                            day,
                            hour,
                        )
                    )
                    res_dict = get_revenue_payout_dict(
                        joined_df_by_sourcetype_by_insurancetype_by_day,
                        insurance_type_campaign_mapping[insurance_type],
                    )
                    if res_dict["listing_count"] != 0:
                        result_dict_source_type[datetime_key] = res_dict
            if not all(
                isinstance(value, dict) and not value
                for value in result_dict_source_type.values()
            ):

                self.monitor_obj.save_revenue_res(
                    result_dict_source_type,
                    f"revenue_sourcetype_{insurance_type}"
                    f"_{int(source_type_id)}.json",
                )

    def downstreamsource_summary_parallel(self, source_type):
        result_dict_source = {d: {} for d in self.unique_days}
        logger.info(
            f"Summarizing source_type = {source_type}, campaign_ids "
            f"= {downstreamsource_campaign_mapping[source_type]}"
        )
        joined_df_by_downstreamsource = filter_by_downstreamsource(
            self.joined_df_combined, source_type, self.all_campaign_ids
        )
        for day in self.unique_days:
            for hour in hourly_times:
                datetime_key = combine_date_and_time(day, hour)
                joined_df_by_downstreamsource_by_day = filter_by_day_and_hour(
                    joined_df_by_downstreamsource,
                    "listing_created_at",
                    day,
                    hour,
                )
                res_dict = get_revenue_payout_dict(
                    joined_df_by_downstreamsource_by_day,
                    downstreamsource_campaign_mapping[source_type],
                )
                if res_dict["listing_count"] != 0:
                    result_dict_source[datetime_key] = res_dict
        if not all(
            isinstance(value, dict) and not value
            for value in result_dict_source.values()
        ):

            self.monitor_obj.save_revenue_res(
                result_dict_source, f"revenue_source_{source_type}.json"
            )

    def partnerid_summary_parallel(self, partner_id):
        result_dict_partner = {d: {} for d in self.unique_days}
        logger.info(
            f"Summarizing partner_id = {partner_id}, "
            f"campaign_ids = {partner_campaign_mapping[partner_id]}"
        )
        joined_df_by_partner = filter_by_partner(
            self.joined_df_combined, partner_id, self.all_campaign_ids
        )
        for day in self.unique_days:
            for hour in hourly_times:
                datetime_key = combine_date_and_time(day, hour)
                joined_df_by_partner_per_day = filter_by_day_and_hour(
                    joined_df_by_partner, "listing_created_at", day, hour
                )
                res_dict = get_revenue_payout_dict(
                    joined_df_by_partner_per_day,
                    partner_campaign_mapping[partner_id],
                )
                if res_dict["listing_count"] != 0:
                    result_dict_partner[datetime_key] = res_dict
        if not all(
            isinstance(value, dict) and not value
            for value in result_dict_partner.values()
        ):
            self.monitor_obj.save_revenue_res(
                result_dict_partner, f"revenue_partner_{partner_id}.json"
            )


def do_monitoring(arguments):
    monitor_obj = Monitor(arguments)
    today, yesterday, dates_to_monitor, last_monitored_time = (
        monitor_obj.get_dates()
    )
    config_attrs = monitor_obj.config_attrs
    all_campaign_ids = categories_and_mapping_dict["campaign_ids"]

    if arguments.query_data:
        for i, query_date in enumerate(dates_to_monitor):
            query_date_time = f"{query_date} {last_monitored_time}"
            start_date_time = query_date_time
            end_date_time = min(
                datetime.strptime(start_date_time, "%Y-%m-%d %H:%M:%S")
                + timedelta(days=1),
                datetime.now().astimezone(timezone.utc).replace(tzinfo=None)
                - timedelta(minutes=1),
            )

            logger.info(f"Query Data for {query_date}")

            rtb_res = monitor_obj.run_query(
                "rtb_query_file",
                {
                    "start_date_time": start_date_time,
                    "end_date_time": end_date_time,
                    "all_campaigns": ", ".join(map(str, all_campaign_ids)),
                },
            )
            try:
                monitor_obj.save_latency_data(
                    rtb_query_res=rtb_res, query_date=query_date
                )
            except Exception as e:
                logger.exception(e)
                continue
            max_date_time = max(rtb_res["created_at"])

            for campaign_id in all_campaign_ids:
                template_variables = {
                    "start_date_time": start_date_time,
                    "end_date_time": end_date_time,
                    "campaign_id": campaign_id,
                }
                click_listing_res, click_conversions_res = (
                    monitor_obj.get_all_click_data(template_variables)
                )
                if click_listing_res is not None:
                    max_date_time = max(
                        max_date_time,
                        max(click_listing_res["created_at"]),
                    )
                if click_conversions_res is not None:
                    max_date_time = max(
                        max_date_time,
                        max(click_conversions_res["created_at"]),
                    )

            monitor_obj.set_last_monitored_day(
                max_date_time.replace(microsecond=0)
            )
        logger.info(
            f"Total time to Query data: {datetime.now()-script_start_time}"
        )
    if config_attrs["jobs"]["summarize_data"]:
        if arguments.only_for_update:
            for_plots = False
            for_table = True
        elif arguments.only_for_plots:
            for_plots = True
            for_table = False
        else:
            for_plots = True
            for_table = True

        logger.info("Summarizing Results.")
        rtb_res = monitor_obj.read_query_res("rtb_query_file")
        click_listing_res_combined = None
        click_conversions_res_combined = None

        logger.info("Summary by campaign_id")
        for campaign_id in all_campaign_ids:
            logger.info(f"Summarizing campaign_id = {campaign_id}")
            template_variables = {
                "campaign_id": campaign_id,
            }
            click_listing_res = monitor_obj.read_query_res(
                "click_listing_query_file", template_variables, "campaign_id"
            )
            click_conversions_res = monitor_obj.read_query_res(
                "click_conversions_query_file",
                template_variables,
                "campaign_id",
            )
            try:
                joined_df = join_data_frames(
                    click_listing_res, click_conversions_res, rtb_res
                )
            except Exception as e:
                logger.exception(f"Failed joining data: {e}")
                continue
            unique_days = sorted(
                np.unique(
                    [d.date() for d in click_listing_res["listing_created_at"]]
                )
            )
            result_dict_campaign = {d: {} for d in unique_days}

            if click_listing_res_combined is None:
                click_listing_res_combined = click_listing_res
            else:
                click_listing_res_combined = pd.concat(
                    [click_listing_res_combined, click_listing_res], axis=0
                )

            if click_conversions_res_combined is None:
                click_conversions_res_combined = click_conversions_res
            else:
                click_conversions_res_combined = pd.concat(
                    [click_conversions_res_combined, click_conversions_res],
                    axis=0,
                )

            for day in unique_days:
                for hour in hourly_times:
                    datetime_key = combine_date_and_time(day, hour)
                    joined_df_per_datetime_bin = filter_by_day_and_hour(
                        joined_df, "listing_created_at", day, hour
                    )
                    res_dict = get_revenue_payout_dict(
                        joined_df_per_datetime_bin, [campaign_id]
                    )

                    if res_dict["listing_count"] != 0:
                        result_dict_campaign[datetime_key] = res_dict

            monitor_obj.save_revenue_res(
                result_dict_campaign,
                filename=f"revenue_campaign_{campaign_id}.json",
            )

        try:
            joined_df_combined = join_data_frames(
                click_listing_res_combined,
                click_conversions_res_combined,
                rtb_res,
            )
        except Exception as e:
            logger.exception(f"Failed to join: {e}")

        unique_days = sorted(
            np.unique(
                [
                    d.date()
                    for d in click_listing_res_combined["listing_created_at"]
                ]
            )
        )

        summary_bins = unique_days

        parallelize_loops = ParallelizeLoops(
            unique_days, joined_df_combined, all_campaign_ids, monitor_obj
        )
        if for_table:
            unique_source_type_ids = np.unique(
                joined_df_combined["source_type_id"]
            )
            unique_source_type_ids = unique_source_type_ids[
                ~np.isnan(unique_source_type_ids)
            ]

            logger.info("Summary by source_type_id")
            start_loop = datetime.now()
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=8
            ) as executor:
                futures = [
                    executor.submit(
                        parallelize_loops.sourcetypeid_summary_parallel,
                        source_type_id,
                    )
                    for source_type_id in unique_source_type_ids
                ]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Error processing: {e}")

            logger.info(
                "Completed summary by source_type_id "
                f"in {datetime.now()-start_loop}"
            )
            logger.info("Summary by state (nz)")

            start_loop = datetime.now()
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=8
            ) as executor:
                futures = [
                    executor.submit(
                        parallelize_loops.state_summary_parallel,
                        st,
                    )
                    for st in list_of_states
                ]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Error processing: {e}")

            logger.info(
                f"Completed summary by state in {datetime.now()-start_loop}"
            )

        if for_plots:
            logger.info("Summary by partner_id")

            start_loop = datetime.now()

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=8
            ) as executor:
                futures = [
                    executor.submit(
                        parallelize_loops.partnerid_summary_parallel,
                        partner_id,
                    )
                    for partner_id in partner_ids
                ]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Error processing: {e}")

            logger.info(
                "Completed summary by partner id in "
                f"{datetime.now()-start_loop}"
            )

            logger.info("Summary by downstream_source_type")

            start_loop = datetime.now()
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=8
            ) as executor:
                futures = [
                    executor.submit(
                        parallelize_loops.downstreamsource_summary_parallel,
                        source_type,
                    )
                    for source_type in downstream_source_types
                ]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Error processing: {e}")

            logger.info(
                "Completed summary by downstream_source_type "
                f"in {datetime.now()-start_loop}"
            )

            logger.info("Summary overall")
            result_dict_overall = {d: {} for d in unique_days}

            for day in summary_bins:
                for hour in hourly_times:
                    datetime_key = combine_date_and_time(day, hour)
                    joined_df_per_day_combined = filter_by_day_and_hour(
                        joined_df_combined, "listing_created_at", day, hour
                    )
                    res_dict = get_revenue_payout_dict(
                        joined_df_per_day_combined, all_campaign_ids
                    )
                    if res_dict["listing_count"] != 0:
                        result_dict_overall[datetime_key] = res_dict
            monitor_obj.save_revenue_res(
                result_dict_overall, "revenue_overall.json"
            )

    logger.info(f"Total Runtime: {datetime.now() - script_start_time}")


if __name__ == "__main__":
    arguments = parse_arguments(script_name=Path(__file__).stem)
    do_monitoring(arguments)
