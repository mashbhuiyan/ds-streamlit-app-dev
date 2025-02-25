from configparser import ConfigParser
import json


def load(fname):
    """
    Load configuration settings from an INI file.

    Parameters
    ----------
    fname : str
        The name of the INI file to be read.

    Returns
    -------
    dict
        A dictionary containing the configuration attributes.

    Examples
    --------
    >>> config = load("config.ini")
    >>> print(config["output_path"])
    >>> print(config["campaign_ids"])
    """
    cfg = ConfigParser()
    cfg.optionxform = str
    cfg.read(fname)

    attrs = {}

    attrs["config_fname"] = fname

    attrs["output_path"] = cfg.get("General", "output-path", fallback="./")
    attrs["rtb_query_file"] = cfg.get(
        "General",
        "rtb-query-file",
    )
    attrs["click_listing_query_file"] = cfg.get(
        "General",
        "click-listing-query-file",
    )

    attrs["click_conversions_query_file"] = cfg.get(
        "General",
        "click-conversions-query-file",
    )

    attrs["date"] = cfg.get("General", "date", fallback=None)
    attrs["end_date"] = cfg.get("General", "end_date", fallback=None)

    attrs["jobs"] = {}
    attrs["jobs"]["summarize_data"] = cfg.getboolean(
        "Jobs", "summarize_data", fallback=True
    )
    attrs["jobs"]["email_alert"] = cfg.getboolean(
        "Jobs", "email_alert", fallback=True
    )

    # If True, drop of relative pff difference below -1 will be notified
    # over email
    attrs["jobs"]["email"] = cfg.get("Jobs", "email", fallback=None)

    # If True, slack alerts will be sent for recommended_correction for pff
    # bases and drop of relative pff difference below -1 will be notified.
    attrs["jobs"]["slack_alert"] = cfg.getboolean(
        "Jobs", "slack_alert", fallback=True
    )

    # If True, recommended_corrections will be written to ds_app.
    attrs["jobs"]["write_to_ds_app"] = cfg.getboolean(
        "Jobs", "write_to_ds_app", fallback=False
    )

    # If True, ds_app will be blocked for future write.
    # The block will be removed after running the update_model_bases.py.
    attrs["jobs"]["read_with_block_updates"] = cfg.getboolean(
        "Jobs", "read_with_block_updates", fallback=False
    )

    return attrs


def parse_list_of_strings(string_list):
    """
    Parse a string representation of a list into a list of strings.

    Parameters
    ----------
    string_list : str
        A string representation of a list, where elements are separated by
        commas and enclosed in square brackets (e.g., '[elem1, elem2, elem3]').

    Returns
    -------
    list
        A list of strings parsed from the input string.

    Examples
    --------
    >>> string_list = '["59", "58", "60"]'
    >>> parse_list_of_strings(string_list)
    ["59", "58", "60"]
    """

    return_list = json.loads(string_list)
    return return_list
