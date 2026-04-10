from datetime import datetime, timedelta
import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.stats import skewnorm

from src.utils import present_line, plot_campaign_effect_on_interaction, plot_sessions_per_campaign


class DataGenerator():

    """
    Generator class for generating sample data.
    """

    def __init__(self, seed: int = 42, day_preference: bool = False, update = False):
        self._rng = np.random.default_rng(seed)
        self.day_preference = day_preference
        if update:
            # read trend parameters from file:
            # total number of generated records (for session id start)
            # campaign locators, skewness, scale and their ids (to use same state)
            # number of campaigns
            # global start date (for left bound)
            # end date of generated records (for new start date)
            pass



    def _generate_skewness(self, campaign_effect: npt.NDArray[np.floating], campaign_ids: npt.NDArray[np.integer], delta_in_seconds: float, n: int, locs) -> npt.NDArray[np.floating]:
        """
        Sample random timedeltas from a skewwed normal distribution. 
        Each campaign has its own skewness and peak location within the timeframe.

        :param campaign_effect: the effectiveness of each campaign, determining the skewness of each campaign. 
        :param campaign_ids: the array with the campaign id of each delta
        :param delta_in_seconds: the total timeframe in seconds
        :param n: number of deltas to generate

        :return: sampled timedeltas in seconds 
        """
        # Compute skew per campaign
        skew_per_campaign = (campaign_effect - 0.5) * 10
        skew_per_row = skew_per_campaign[campaign_ids - 1]

        # Scale, lower is smaller peaks, higher is wider peaks
        scale = delta_in_seconds / 2 # TODO: make scale campaign dependent

        skewwed_deltas = np.empty(n)
        mask = np.ones(n, dtype=bool)

        # Resample values out of bounds
        while np.any(mask):
            n_missing = mask.sum()
            samples = skewnorm.rvs(
                a=skew_per_row[mask],
                loc=locs[mask],
                scale=scale,
                size=n_missing,
                random_state=self._rng
            )
            # Accept only values within [0, delta_in_seconds]
            accept = (samples >= 0) & (samples <= delta_in_seconds)
            skewwed_deltas[mask] = np.where(accept, samples, skewwed_deltas[mask])
            mask[mask] = np.logical_not(accept)  # resample rejected values

        return skewwed_deltas

    def _sort_by_date(self, ids: npt.NDArray[np.integer], dates: npt.NDArray[np.datetime64]) -> tuple[npt.NDArray[np.integer], npt.NDArray[np.datetime64]]:
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
    
    def _get_campaign_ids(self, n, n_campaigns, initial_campaigns = 0):
        # Randomly determine effectiveness of each campaign
        effect_per_campaign = self._rng.random(n_campaigns)
        
        # Campaign ID limited number of campaigns randomly assigned to session (more sessions for effective campaigns)
        camp_eff_norm = effect_per_campaign/effect_per_campaign.sum()
        campaign_ids = self._rng.choice(np.arange(initial_campaigns + 1, n_campaigns + 1), n, p=camp_eff_norm)

        return campaign_ids, effect_per_campaign

    def _session_date_gen(self, start_date: np.datetime64, end_date: np.datetime64, n: int, n_campaigns: int, campaign_offsets) -> tuple[int, npt.NDArray[np.datetime64]]:
        """
        Generates n random dates between start_date and end_date.

        :param start_date: start of timeframe
        :param end_date: end of timeframe
        :param n: number of dates to generate
        :return: list of randomly generated dates in given frame sorted by date
        """
        # Get time difference in seconds
        delta = end_date - start_date
        delta_in_seconds = delta.item().total_seconds()

        campaign_ids, effect_per_campaign = self._get_campaign_ids(n, n_campaigns)

        locs = campaign_offsets[campaign_ids - 1] - start_date.astype('datetime64[s]').astype(np.int64)

        # Generate deltas skewwed to simulate campaign effectiveness
        deltas = self._generate_skewness(effect_per_campaign, campaign_ids, delta_in_seconds, n, locs)

        # Compute dates from the start_date and deltas
        timedeltas = deltas.astype('timedelta64[s]')
        dates = start_date + timedeltas

        if self.day_preference:
            dates = self._introduce_day_preference(dates, end_date, campaign_ids, n_campaigns)

        campaign_ids, sorted_dates = self._sort_by_date(campaign_ids, dates)
        
        # Map each record to its campaign effect based on campaigns_ids (1-indexed)
        campaign_effect = effect_per_campaign[campaign_ids - 1]

        return campaign_ids, sorted_dates, campaign_effect
    
    def _generate_visit_duration(self, min, max, n, precision = 'm') -> npt.NDArray:
        visit_duration = self._rng.integers(min, max, n)
        visit_duration = visit_duration.view(f'timedelta64[{precision}]')
        return visit_duration


    def _generate_trend(self, number_of_records: int, min_value: int, max_value: int, campaign_effect: npt.NDArray[np.floating]) -> npt.NDArray:
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
        # trend_base is scaled by campaign effect per record and timeline growth
        trend_base = campaign_effect * np.linspace(min_value, max_value, number_of_records, dtype=float)

        # Add noise based on the noise of the previous record
        noise = np.zeros(number_of_records)
        for i in range(1, number_of_records):
            noise[i] = 0.7 * noise[i-1] + self._rng.normal(0, 0.5)

        return np.clip(trend_base + noise, min_value, max_value)

    def generate_data(self, parameters: dict[str, int | str | tuple[datetime,datetime]]) -> pd.DataFrame:
        """
        Generate synthetic session data based on user-defined parameters.

        Precondition:
            - parameters must contain the following keys:
                "records": int > 0
                "campaigns": int > 0
                "timeframe": list[str] (non-empty)
                "location": int > 0
                "devices": int > 0
                "clicks": int > 0"
                "page_views": int > 0
                "traffic_source": int > 0
            - All integer values must be positive.
            - "location" and "devices" must contain at least one element.

        Postcondition:
            - Returns a list of records.
            - Each record is a list of 16 elements.
            - The number of records equals parameters["records"].

        :param parameters: Dictionary containing dataset configuration.
        :return: A list of generated records ready for CSV export.
        """
        present_line("Generating records..")

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
        start = np.datetime64(start)
        end = np.datetime64(end)

        # Unique session ID
        session_ids = np.arange(1, number_of_records + 1)

        # Compute ofsets relative to current timeframe 
        # TODO: Needs to be extracted from csv when updating
        campaign_offsets = self._rng.uniform(
            start.astype('datetime64[s]').astype(np.int64), 
            end.astype('datetime64[s]').astype(np.int64), 
            n_campaigns).astype(np.int64)

        # Generate random dates and sort for chronological order of sessions
        campaigns_ids, session_dates, campaign_effect = self._session_date_gen(start, end, number_of_records, n_campaigns, campaign_offsets)
        plot_sessions_per_campaign(session_dates, campaigns_ids)

        """Resample for trend extension"""
        new_start = end + np.timedelta64(timedelta(seconds=1))
        new_end = end + np.timedelta64(timedelta(days=5))
        new_cmpgn_ids, new_session_dates = self._session_date_gen(new_start, new_end, 1000, new_cmpgn_ids, campaign_offsets)
        # print(new_session_dates)
        plot_sessions_per_campaign(np.concatenate([session_dates, new_session_dates]), np.concatenate([campaigns_ids, new_cmpgn_ids]))



        # A visitor may be recurrent. Therefore the possibility for duplicate IDs is needed
        visitor_ids = self._rng.integers(1, number_of_records * 3, number_of_records)


        # Minimum and maximum visit times in minutes
        min_visit_time = 1 # minutes
        max_visit_time = 30 # minutes
        visit_duration = self._generate_visit_duration(min_visit_time, max_visit_time, number_of_records, precision='m')
        
        conversion = self._rng.random(number_of_records) > conversion_rate

        # Generate click trend
        click_total = self._generate_trend(number_of_records, 0, clicks, campaign_effect).astype(int)

        # Minimal 1 click when a conversion happened
        click_minimum = ((conversion == 1) & (click_total == 0)).astype(int)
        click_total += click_minimum

        # Generate pageview trend
        view_total = self._generate_trend(number_of_records, 1, page_views, campaign_effect)

        randomized_device = self._rng.integers(1, devices, number_of_records)

        randomized_city = self._rng.integers(1, location, number_of_records)

        randomized_traffic_sources = self._rng.integers(1, traffic_sources, number_of_records)


        generated_records = pd.DataFrame({
            "sessie_ID": session_ids,
            "campagne_ID": campaigns_ids,
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

    def save_data(self, data: pd.DataFrame, save_path: str, sep: str = ';', date_format="%d-%m-%Y %H:%M"):
        present_line("Saving records..")
        data.to_csv(save_path, sep=sep, date_format=date_format, index=False)
        present_line("Records saved")
        present_line("\nHave a pretty day!\n")
