"""Small helpers for selecting a single, reportable dominant driver."""

import pandas as pd


def driver_key_for(dimension, driver_name):
    if dimension is None or dimension.empty or not driver_name:
        return None
    matches = dimension[dimension["Driver_Name"] == driver_name]
    if matches.empty:
        return None
    key_column = next(column for column in dimension if column.endswith("Driver_Key"))
    return int(matches.iloc[0][key_column])
