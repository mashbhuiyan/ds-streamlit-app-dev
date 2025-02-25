import numpy as np
import scipy.stats as stats


def confidence_interval_tscore(data, confidence_level=0.90):
    """
    Calculate the confidence interval using the t-score method.

    This function computes the mean of the data, calculates the standard
    error of the mean (SEM), and then determines the confidence interval (CI)
    using the t-score method.

    Parameters
    ----------
    data : array_like
        An array or list-like object containing numeric data.
    confidence_level : float, optional
        The desired confidence level for the interval (default is 0.90).

    Returns
    -------
    tuple
        A tuple containing three values: mean, lower bound of the CI, and upper
        bound of the CI.

    Examples
    --------
    >>> data = [1, 2, 3, 4, 5]
    >>> mean, ci_lower, ci_upper = confidence_interval_tscore(data)
    >>> print(f"Mean: {mean}, CI: ({ci_lower}, {ci_upper})")
    Mean: 3.0, CI: (1.036756838522439, 4.963243161477561)
    """
    mean = np.mean(data)
    sem = stats.sem(data)
    ci_lower, ci_upper = stats.t.interval(
        confidence_level, len(data) - 1, loc=mean, scale=sem
    )
    return mean, ci_lower, ci_upper


def confidence_interval_zscore(data, confidence_level=0.90):
    """
    Calculate the confidence interval using the z-score method.

    This function computes the mean of the data, calculates the standard
    error of the mean (SEM), and then determines the confidence interval (CI)
    using the z-score method.

    Parameters
    ----------
    data : array_like
        An array or list-like object containing numeric data.
    confidence_level : float, optional
        The desired confidence level for the interval (default is 0.90).

    Returns
    -------
    tuple
        A tuple containing three values: mean, lower bound of the CI, and upper
        bound of the CI.

    Examples
    --------
    >>> data = np.arange(50)
    >>> mean, ci_lower, ci_upper = confidence_interval_zscore(data)
    >>> print(f"Mean: {mean}, CI: ({ci_lower}, {ci_upper})")
    Mean: 24.5, CI: (21.109047378699383, 27.890952621300613)
    """
    mean = np.mean(data)
    sem = stats.sem(data)

    ci_lower, ci_upper = stats.norm.interval(
        confidence_level, loc=mean, scale=sem
    )

    return mean, ci_lower, ci_upper


def confidence_interval_by_z_or_t(data, confidence_level=0.90):
    length = len(data)
    if length >= 30:
        return confidence_interval_zscore(data, confidence_level)
    else:
        return confidence_interval_tscore(data, confidence_level)


def confidence_interval_percentile(data, confidence_level=0.90):
    """
    Calculate the confidence interval using the percentile method.

    This function computes the confidence interval (CI) using the percentile
    method. It sorts the data, calculates the percentiles corresponding to the
    confidence level, and determines the lower and upper bounds of the CI.

    Parameters
    ----------
    data : array_like
        An array or list-like object containing numeric data.
    confidence_level : float, optional
        The desired confidence level for the interval (default is 0.90).

    Returns
    -------
    tuple
        A tuple containing three values: mean, lower bound of the CI and upper
        bound of the CI.

    Examples
    --------
    >>> data = [1, 2, 3, 4, 5]
    >>> ci_lower, ci_upper = confidence_interval_percentile(data)
    >>> print(f"CI: ({ci_lower}, {ci_upper})")
    CI: (1.05, 4.95)
    """
    data = np.sort(data)
    mean = np.mean(data)
    alpha = 1 - confidence_level
    ci_l = np.percentile(data, 100 * alpha / 2)
    ci_u = np.percentile(data, 100 * (1 - alpha / 2))
    return mean, ci_l, ci_u


def get_mean_and_variance(data, ddof=0):
    data = np.array(data)
    if len(data) == 0:
        return 0.0, 0.0
    else:
        return np.mean(data), np.var(data, ddof)
