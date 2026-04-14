from datetime import datetime, timedelta
import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.stats import skewnorm
import json

from src.utils import sort_by_date, present_line, load_state, DATE_FORMAT


class DataGenerator():

    """
    Generator class for generating sample data.
    """

    def __init__(
            self, 
            seed: int = 42, 
            day_preference: bool = False, 
            update = False, 
            state_path: str = 'config/state.json'
        ):
        self._rng = np.random.default_rng(seed)
        self.day_preference = day_preference
        self.state = {} # state object contains state of simulation
        self.update = update
        self.state_path = state_path
        if update:
            self.state = load_state(state_path)
            # read trend parameters from file:
            # total number of generated records (for session id start)
            # campaign locators, skewness, scale and their ids (to use same state)
            # number of campaigns
            # global start date (for left bound)
            # end date of generated records (for new start date)

    def save_state(self):
        campaigns = self.state["campaign"]
        # Convert campaign properties to lists for json conversion
        for key, value in campaigns.items():
            campaigns[key] = value.tolist()
        
        # write campaign properties to file
        with open(self.state_path, 'w') as file:
            json.dump(self.state, file)

    def _generate_skewness(self, campaign_ids: npt.NDArray[np.integer], start, end, n: int) -> npt.NDArray[np.floating]:
        """
        Sample random timestamps from a skewwed normal distribution. 
        Each campaign has its own skewness and peak location within the timeframe.

        :param campaign_effect: the effectiveness of each campaign, determining the skewness of each campaign. 
        :param campaign_ids: the array with the campaign id of each delta
        :param delta_in_seconds: the total timeframe in seconds
        :param n: number of deltas to generate

        :return: sampled datetimes, precision in seconds
        """
        campaigns = self.state["campaign"]
        # Compute skew per campaign
        skew_per_row = campaigns["skew"][campaign_ids - 1]

        locs = campaigns["offset"][campaign_ids - 1]

        # Scale, lower is smaller peaks, higher is wider peaks
        scale = campaigns["scale"][campaign_ids - 1]

        skewwed_dates = np.empty(n)
        mask = np.ones(n, dtype=bool)

        # Resample values out of bounds
        while np.any(mask):
            n_missing = mask.sum()
            samples = skewnorm.rvs(
                a=skew_per_row[mask],
                loc=locs[mask],
                scale=scale[mask],
                size=n_missing,
                random_state=self._rng
            )
            # Accept only values within [0, delta_in_seconds]
            accept = (samples >= start) & (samples <= end)
            skewwed_dates[mask] = np.where(accept, samples, skewwed_dates[mask])
            mask[mask] = np.logical_not(accept)  # resample rejected values

        return skewwed_dates.astype('datetime64[s]')

    def _introduce_day_preference(self, dates: npt.NDArray[np.datetime64], end_date: np.datetime64, campaign_ids: npt.NDArray[np.integer], n_campaigns: int) -> npt.NDArray[np.datetime64]:
        """
        Bias already calculated dates towards weekdays or weekends.

        :param dates: calculated random dates
        :param end_date: upper bound of the timeframe to stay within
        :param campaign_ids: array of campaign_ids containing id for every row
        :param n_campaigns: number of campaigns in simulation

        :return: dates unsorted biased towards closest weekday or weekend
        """
        days = np.arange(7)
        # Closer to 0 weekday bias closer to 1 weekend bias
        day_preference_per_campaign = np.array([0.2, 0.5, 0.8]) # TODO: randomize

        # Calculate weights per day per campaign
        weights = np.array([
            (1 - day_preference_per_campaign[c] if d < 5 else day_preference_per_campaign[c])
            for c in range(n_campaigns) for d in days
        ]).reshape(n_campaigns, 7)
        weights /= weights.sum(axis=1, keepdims=True)  # normalize per campaign

        # Calculate target day per row per campaign
        cum_probs = np.cumsum(weights, axis=1)
        cum_probs_per_row = cum_probs[campaign_ids - 1]

        rand = self._rng.random(len(campaign_ids))

        target_flat = (rand[:, None] < cum_probs_per_row).argmax(axis=1)

        # Shift each date to match weekday offset
        dow = np.array([d.weekday() for d in dates]) # days of the week of the generated dates
        offset = ((target_flat - dow) % 7) * timedelta(days=1)
        candidate = dates + offset

        dates = np.where(candidate < end_date, candidate, dates)

        return dates

    def _sample_campaign_ids(self, start, end, n):
        campaigns = self.state["campaign"]

        activity = skewnorm.cdf(end, campaigns["skew"], campaigns["offset"], campaigns["scale"]) - \
                    skewnorm.cdf(start, campaigns["skew"], campaigns["offset"], campaigns["scale"])

        # Campaign ID's are sampled based on their current activity in the timeframe
        weight = activity.clip(0, 1)
        weight /= weight.sum()

        campaign_ids = self._rng.choice(campaigns["id"], n, p=weight)

        return campaign_ids

    def _session_date_gen(self, start_date: int, end_date: int, n: int, n_campaigns: int) -> tuple[int, npt.NDArray[np.datetime64]]:
        """
        Generates n random dates between start_date and end_date.

        :param start_date: start of timeframe
        :param end_date: end of timeframe
        :param n: number of dates to generate
        :return: list of randomly generated dates in given frame sorted by date
        """
        campaign_ids = self._sample_campaign_ids(start_date, end_date, n)

        # Generate dates skewwed to simulate campaign effectiveness
        dates = self._generate_skewness(campaign_ids, start_date, end_date, n)

        if self.day_preference:
            dates = self._introduce_day_preference(dates, end_date, campaign_ids, n_campaigns)

        campaign_ids, sorted_dates = sort_by_date(campaign_ids, dates)

        return campaign_ids, sorted_dates
    
    def _generate_visit_duration(self, min, max, n, precision = 'm') -> npt.NDArray:
        visit_duration = self._rng.integers(min, max, n)
        visit_duration = visit_duration.view(f'timedelta64[{precision}]')
        return visit_duration

    def _generate_trend(self, number_of_records: int, min_value: int, max_value: int, campaign_ids: npt.NDArray[np.floating]) -> npt.NDArray:
        """
        Generate a linear trendline with noise, taking into account the 
        effect of the campaign.
        Can be extended with:
            - variance based on day of week
            - different base function

        :param number_of_records: number of records to generate
        :param min_value: minimum value for the trendline
        :param max_value: maximum value for the trendline
        :param campaign_effect: effect of the campaign per record
        :return: generated trend clipped to min and max values
        """
        campaigns = self.state["campaign"]
        # Map each record to its campaign effect based on campaigns_ids (1-indexed)
        campaign_effect = campaigns["effect"][campaign_ids - 1]

        # trend_base is scaled by campaign effect per record and timeline growth
        trend_base = campaign_effect * np.linspace(min_value, max_value, number_of_records, dtype=float)

        # Add noise based on the noise of the previous record
        noise = np.zeros(number_of_records)
        for i in range(1, number_of_records):
            noise[i] = 0.7 * noise[i-1] + self._rng.normal(0, 0.5)

        return np.clip(trend_base + noise, min_value, max_value)

    def _add_new_campaigns(self, start, end, n_campaigns):
        """Returns lists of campaign properties of all campaigns, new and old"""
        # Get existing campaign state, if non-existing create new
        campaign = self.state.get("campaign", {
                "id": np.array([], dtype=int),
                "effect": [],
                "offset": [],
                "skew": [],
                "scale": []
            })
        
        # Create campaign counter if not there yet
        if "n_campaigns" not in self.state:
            self.state["n_campaigns"] = 0

        # Generate ID's for the new campaigns
        campaign_id = np.arange(1, n_campaigns + 1) + self.state["n_campaigns"]
        # Randomly determine effectiveness of each new campaign
        campaign_effect = self._rng.random(n_campaigns) # IDEA: multiple campaign types and platforms with each their own effect

        # Randomly place the peaks of the new campaigns in the new timeframe
        campaign_offset = self._rng.uniform(start, end, n_campaigns)

        # Compute the skew from the effectiveness
        campaign_skew = (campaign_effect - 0.5) * 10

        # Compute scale with a maximum campaign duration of 2 years
        campaign_scale = np.timedelta64(3, 'W').astype('timedelta64[s]').astype(np.int64) * (1 - campaign_effect)

        # Update campaign state
        campaign["id"] = np.concatenate([campaign["id"], campaign_id])
        campaign["scale"] = np.concatenate([campaign["scale"], campaign_scale])
        campaign["effect"] = np.concatenate([campaign["effect"], campaign_effect])
        campaign["offset"] = np.concatenate([campaign["offset"], campaign_offset])
        campaign["skew"] = np.concatenate([campaign["skew"], campaign_skew])

        self.state["campaign"] = campaign
        self.state["n_campaigns"] += n_campaigns

    def generate_data(self, parameters):
        number_of_records = parameters["records"]
        n_campaigns = parameters["campaigns"]
        start, end = parameters["timeframe"]
        country = 'NL'
        location = parameters["location"]
        devices = parameters["devices"]
        clicks = parameters["clicks"]
        page_views = parameters["page_views"]
        traffic_sources = parameters["traffic_source"]
        conversion_rate = parameters["conversion_rate"]

        # Convert to numpy datetime for efficient calculations
        start_ts = np.datetime64(start, 's').astype(np.int64)
        end_ts = np.datetime64(end, 's').astype(np.int64)

        
        # Unique session ID
        old_records = self.state.get("last_record", 0)
        session_ids = np.arange(old_records + 1, old_records + number_of_records + 1)

        # Generate random properties for each campaign
        self._add_new_campaigns(start_ts, end_ts, n_campaigns)

        # Generate random dates and sort for chronological order of sessions
        campaign_ids, session_dates = self._session_date_gen(start_ts, end_ts, number_of_records, n_campaigns)

        # A visitor may be recurrent. Therefore the possibility for duplicate IDs is needed
        visitor_ids = self._rng.integers(1, number_of_records * 3, number_of_records)

        # Minimum and maximum visit times in minutes
        min_visit_time = 1 # minutes
        max_visit_time = 30 # minutes
        visit_duration = self._generate_visit_duration(min_visit_time, max_visit_time, number_of_records, precision='m')

        conversion = self._rng.random(number_of_records) > conversion_rate

        # Generate click trend
        click_total = self._generate_trend(number_of_records, 0, clicks, campaign_ids).astype(int)

        # Minimal 1 click when a conversion happened
        click_minimum = ((conversion == 1) & (click_total == 0)).astype(int)
        click_total += click_minimum

        # Generate pageview trend
        view_total = self._generate_trend(number_of_records, 1, page_views, campaign_ids)

        randomized_device = self._rng.integers(1, devices, number_of_records)

        randomized_city = self._rng.integers(1, location, number_of_records)

        randomized_traffic_sources = self._rng.integers(1, traffic_sources, number_of_records)

        # Update state
        self.state["last_record"] = old_records + number_of_records
        self.state["current_date"] = datetime.fromtimestamp(end_ts).strftime(DATE_FORMAT)

        generated_records = pd.DataFrame({
            "sessie_ID": session_ids,
            "campagne_ID": campaign_ids,
            "bezoeker_ID": visitor_ids,
            "starttijd_bezoek": session_dates,
            "eindtijd_bezoek": session_dates + visit_duration,
            "totale_tijd_bezoek": visit_duration.astype(int),
            "kliks_op_site_elementen": click_total.astype(int),
            "paginas_bekeken": view_total.astype(int),
            "apparaat": randomized_device,
            "land": country,
            "stad": randomized_city,
            "verkeers_bron": randomized_traffic_sources,
            "conversie": conversion.astype(int)
        })

        if len(generated_records) == number_of_records:
            present_line("Records generated")
        else:
            present_line("Something went wrong!")
            present_line("The number of records generated doesn't equal the number of records needed.")

        return generated_records

    def generate_incremental(self, parameters: dict):
        start, end = parameters["timeframe"]

        weekly_parameters = parameters.copy()
        current_start = start
        current_end = start + timedelta(days=7)
        weekly_parameters["timeframe"] = (current_start, current_end)
        records = self.generate_data(weekly_parameters)
        current_start = current_end
        current_end += timedelta(weeks=1)
        self.save_data(records, 'incremental_dataset.csv')
        self.update = True
        while current_end < end:
            weekly_parameters["timeframe"] = (current_start, current_end)
            records = self.generate_data(weekly_parameters)
            current_start = current_end
            current_end += timedelta(weeks=1)
            self.save_data(records, 'incremental_dataset.csv')

    def save_data(self, data: pd.DataFrame, save_path: str, sep: str = ';', date_format="%d-%m-%Y %H:%M"):
        present_line("Saving records..")
        # Append to file when updating
        write_mode = 'a' if self.update else 'w'
        data.to_csv(
            save_path, 
            sep=sep, 
            date_format=date_format, 
            mode=write_mode, 
            index=False, 
            header=not self.update
        )
        self.save_state()
        present_line("Records saved")
        present_line("\nHave a pretty day!\n")
