import pandas as pd
import numpy as np

from .base_generator import DataGenerator

class HistoricalGenerator(DataGenerator):

    def __init__(self, parameters, seed = 42, day_bias = False):
        self.state = {}
        self.state['max_location'] = parameters["location"]
        self.state['max_devices'] = parameters["devices"]
        self.state['max_clicks'] = parameters["clicks"]
        self.state['max_page_views'] = parameters["page_views"]
        self.state['max_traffic_sources'] = parameters["traffic_source"]
        self.state['country'] = np.array(parameters["country"])
        self.update = False
        super().__init__(seed, day_bias)

        self.n_records, self.n_base, self.start, self.end = self._get_params(parameters)

    def _get_params(self, parameters) -> tuple[int, int, int, int]:
        """
        Store the parameters in state and return the parameters that need to be used directly.

        :param parameters: parameters as a dictionary
        :return: number of records to be generated, number of campaigns, start date, end date.
        """
        number_of_records = parameters["records"]
        n_base = int(number_of_records * 0.01) # 1% of records for basetrend
        n_campaign_records = number_of_records - n_base
        n_campaigns = parameters["campaigns"]
        start, end = parameters["timeframe"]

        # Convert dates to integer (number of days since 01-01-1970)
        start_ts = np.datetime64(start, 'D').astype(np.int64)
        end_ts = np.datetime64(end, 'D').astype(np.int64)

        # Generate random properties for each new campaign
        self.campaign_manager.add_new_campaigns(start_ts, end_ts, n_campaigns)

        return n_campaign_records, n_base, start_ts, end_ts

    def generate(self) -> pd.DataFrame:
        """
        Starting point of generator. 
        Generates data up to current day or generates data in given timeframe.

        :param parameters: Dictionary of parameters to use when generating historical data
        :return: Generated data as dataframe
        """
        return pd.DataFrame(self.generate_data(self.n_records, self.n_base, self.start, self.end))