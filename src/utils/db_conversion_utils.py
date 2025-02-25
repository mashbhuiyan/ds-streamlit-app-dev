def filter_by_model_id(dataframe, model_id):
    return dataframe[dataframe["model_id"] == model_id]


def filter_by_param_name(dataframe, param_name):
    return dataframe[dataframe["param_name"] == param_name]


def filter_by_state_group_type(dataframe, state_group_type):
    return dataframe[dataframe["state_group_type"] == state_group_type]


def filter_by_feature_group(dataframe, feature_group):
    return dataframe[dataframe["feature_group"] == feature_group]
