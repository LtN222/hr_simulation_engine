import json
import time
import matplotlib.pyplot as plt
import pandas as pd
import numpy.typing as npt
import numpy as np

DATE_FORMAT = "%d-%m-%Y"

"""
##############################################
        PRESENTATION SUGAR
##############################################
"""

def present_line(line: str) -> None:
    """
    Slows down print statements bij .5 seconds,
    to make it easier to follow for first time users.
    :param line: string to print to console.
    """
    print(line)
    time.sleep(0.5)

def plot_campaign_effect_on_interaction(generated_records: pd.DataFrame, campaigns: int):
    print(generated_records.head())
    print(generated_records.tail())
    for i in range(campaigns):
        campaign = generated_records[generated_records['campagne_ID'] == i+1]

        clicks = campaign['kliks_op_site_elementen']

        plt.plot(clicks)
    plt.show()
    for i in range(campaigns):
        campaign = generated_records[generated_records['campagne_ID'] == i+1]

        clicks = campaign['paginas_bekeken']

        plt.plot(clicks)
    plt.show()

def plot_sessions_per_campaign(session_dates, campaigns_ids):
    # 1. Zet je list om naar een Pandas Series
    dates_series = pd.Series(session_dates)
    dates = pd.Series(session_dates).groupby(campaigns_ids).apply(list)
    dagelijkse_counts = dates_series.dt.date.value_counts().sort_index()

    # 3. Plot de Verdeling (De 'Piek' in de tijd)
    plt.figure(figsize=(12, 5))

    plt.subplot(1, 2, 1)
    dagelijkse_counts.plot(kind='line', color='blue', title='Sessies per Dag')
    for date in dates:
        dt = pd.Series(date).dt.date.value_counts().sort_index()
        dt.plot()
    plt.ylabel('Aantal sessies')
    plt.grid(True, alpha=0.3)

    # 4. Plot de S-Curve (Cumulatieve groei)
    plt.subplot(1, 2, 2)
    dagelijkse_counts.cumsum().plot(kind='line', color='orange', linewidth=2, title='Totale Groei (S-Curve)')
    plt.ylabel('Totaal aantal sessies')
    plt.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


def sort_by_date(ids: npt.NDArray[np.integer], dates: npt.NDArray[np.datetime64]) -> tuple[npt.NDArray[np.integer], npt.NDArray[np.datetime64]]:
    """
    Sort dates together with its campaign_ids.

    :param ids: ids that are coupled with the dates
    :param dates: dates to be sorted

    :return: sorted ids, sorted dates
    """
    # Get the indexorder of the sorted array
    idx = np.argsort(dates)

    # Sort the arrays
    sorted_ids = ids[idx]
    sorted_dates = dates[idx]

    return sorted_ids, sorted_dates

def load_json(path: str):
    try:
        with open(path, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        raise FileNotFoundError(f"{path} can not be found. " \
                    "Please make sure the file exists and try again.")

def dict_list_to_ndarray(dictionary: dict[str, npt.NDArray | dict]):
    for key, value in dictionary.items():
        if type(value) == dict:
            dictionary[key] = dict_list_to_ndarray(value)
        elif type(value) == npt.NDArray: continue
        else: 
            dictionary[key] = np.array(value)

    return dictionary

def dict_ndarray_to_list(dictionary: dict[str, npt.NDArray | dict]):
    for key, value in dictionary.items():
        if type(value) == dict:
            dictionary[key] = dict_ndarray_to_list(value)
        elif type(value) == list: continue
        else: 
            dictionary[key] = value.tolist()

    return dictionary
