from datetime import datetime
import numpy as np
import pandas as pd

from .base_generator import DataGenerator, DATE_FORMAT

class IncrementalGenerator(DataGenerator):

    """Generator for incremental data generation"""

    def __init__(self, seed = 42, day_bias = False):
        """
        Initialize the incremental generator

        :param seed: seed of the generator
        :param day_bias: wheter to add bias for weekdays or weekends
        """
        self.state = self._load_state()
        self.update = True
        super().__init__(seed, day_bias)

    def _get_updated_params(self, start: int, end: int) -> tuple[int, int]:
        """
        Get parameters for new day.

        Adds new campaigns and computes the number of records for the new day.

        :param start: start of the day
        :param end: end of the day
        :return: Number of records for day to be generated, number of generated new campaigns
        """
        n_campaigns = 1 if self._rng.random() < 0.1 else 0
        if n_campaigns > 0:
            self.campaign_manager.add_new_campaigns(start, end, n_campaigns, self.update)
            records_last_day_per_campaign = np.concatenate([self.state["records_last_day_per_campaign"], [0]])
        else:
            records_last_day_per_campaign = self.state["records_last_day_per_campaign"]

        session_parameters = self.state['campaign']['session']

        # Get activity of the campaign curves
        activity_last_day = np.nan_to_num(self.campaign_manager.get_activity(session_parameters, start - 1, end - 1))
        activity_cur_day = np.nan_to_num(self.campaign_manager.get_activity(session_parameters, start, end))

        # Calculate growth per campaign
        ratio_per_campaign = np.divide(activity_cur_day, activity_last_day, 
                                       out=np.zeros_like(activity_cur_day, dtype=float), 
                                       where=activity_last_day != 0)

        # Calculate new number of records per campaign
        campaign_trend = int((ratio_per_campaign * records_last_day_per_campaign[1:]).sum())

        # Calculate new number of records for base
        base_trend = int(records_last_day_per_campaign[0] * 1.01)

        campaign_records = int(self._rng.normal(campaign_trend, campaign_trend * 0.02)) # 2% noise
        base_records = int(self._rng.normal(base_trend, base_trend * 0.02)) # 2% noise

        return campaign_records, base_records
    
    def generate(self) -> pd.DataFrame:
        """
        Generate new data up to today.
        Data is generated day by day.

        :return: newly generated records as dataframe
        """
        # Get start date from state
        start = datetime.strptime(self.state['current_date'], DATE_FORMAT)

        # Set end date to today
        end = datetime.today()

        # Convert dates to integer (number of days since 01-01-1970)
        start_ts = np.datetime64(start, 'D').astype(np.int64)
        end_ts = np.datetime64(end, 'D').astype(np.int64)

        # Set current dates
        current_start = start_ts
        current_end = start_ts + 1

        # Update data for 1 day
        r = []
        while current_end < end_ts:
            # Set new start and end
            n_records, n_base = self._get_updated_params(current_start, current_end)

            # Collect generated data
            r.append(self.generate_data(n_records, n_base, current_start, current_end))

            # Update dates
            current_start = current_end
            current_end += 1

        # Convert generated data to dataframe
        records = pd.DataFrame({
            k: np.concatenate([d[k] for d in r]) 
            for k in r[0].keys()
        })

        return records