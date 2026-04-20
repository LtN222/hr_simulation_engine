from datetime import datetime, timedelta
import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy import stats
import json

from src.utils import sort_by_date, present_line, load_state, dict_ndarray_to_list, DATE_FORMAT

from src.utils import plot_sessions_per_campaign

MAX_VISIT_TIME = 30 # minutes TODO: Get from config file

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
        self._default_campaign = {
            "id": np.array([], dtype=int), # id of the campaign
            "session": {"reach": [], "skew": [], "loc": [], "scale": []},
            "click": {"shape": [], "avg_click": [], "min_click": []},
            "pageview": {"p": []}, # Probability of visiting another page
            "duration": {"shape": [], "avg_duration": [], "min_duration": []}
        }
        self.update = update
        self.state_path = state_path

        if update:
            self.state = load_state(state_path)

    def save_state(self):
        # Convert campaign properties to lists for json conversion
        self.state["campaign"]["session"]["loc"] = self.state["campaign"]["session"]["loc"].astype('datetime64[D]').astype(str)
        self.state["campaign"] = dict_ndarray_to_list(self.state["campaign"])

        # write state to file
        with open(self.state_path, 'w') as file:
            json.dump(self.state, file, indent=4)
    
    def _add_new_campaigns(self, start, end, n_campaigns):
        """Returns lists of campaign properties of all campaigns, new and old"""
        campaign = self.state.get("campaign", self._default_campaign)
        n_existing = self.state.get("n_campaigns", 0)

        # Generate ID's for the new campaigns
        campaign_id = np.arange(1, n_campaigns + 1) + n_existing

        # Randomly determine effectiveness of each new campaign
        # # IDEA: multiple campaign types and platforms with each their own effects
        # Adoption speed, how fast does the campaign show effect
        campaign_speed = self._rng.uniform(-10, 11, n_campaigns)
        # How many sessions does the campaign generate
        campaign_reach = self._rng.random(n_campaigns)
        # Does the campaign reach the right people
        campaign_effect = self._rng.random(n_campaigns)

        # Duration of the campaign
        campaign_duration = self._rng.uniform(1, 72, n_campaigns) # in months

        # Compute scale with a campaign duration in months
        # Scale is standard deviation, curve 'dies out' after +- 3 * sd,
        # therefore deviding duration by 3 gives a good scale for the campaign
        campaign_scale = campaign_duration.astype('timedelta64[M]').astype('timedelta64[D]').astype(np.int64) / 3

        # Randomly place the peaks of the new campaigns in the new timeframe
        campaign_mean = self._rng.uniform(start, end, n_campaigns)

        # Get the starting location of the campaign
        campaign_start = stats.skewnorm.ppf(0.01, a=campaign_speed, loc=campaign_mean, scale=campaign_scale)
        # Use the offset to place the starting location in the future, makes all campaigns start at the same time
        campaign_offset = np.abs(start - campaign_start)

        page_prob = self._rng.random(n_campaigns)

        visit_shape = self._rng.uniform(1, 3, n_campaigns)
        visit_avg_duration = self._rng.uniform(1, MAX_VISIT_TIME, n_campaigns)
        visit_min_duration = self._rng.uniform(1, 5, n_campaigns)

        click_shape = self._rng.uniform(0.5, 1, n_campaigns)
        click_avg_click = self._rng.integers(1, 100, n_campaigns)
        click_min_click = self._rng.integers(0, 4, n_campaigns)

        # Update campaign state
        campaign["id"] = np.concatenate([campaign["id"], campaign_id])
        campaign["session"]["skew"] = np.concatenate([campaign["session"]["skew"], campaign_speed])
        campaign["session"]["loc"] = np.concatenate([campaign["session"]["loc"], campaign_mean + campaign_offset])
        campaign["session"]["scale"] = np.concatenate([campaign["session"]["scale"], campaign_scale])
        campaign["session"]["reach"] = np.concatenate([campaign["session"]["reach"], campaign_reach])

        campaign["pageview"]["p"] = np.concatenate([campaign["pageview"]["p"], page_prob])

        campaign["duration"]["shape"] = np.concatenate([campaign["duration"]["shape"], visit_shape])
        campaign["duration"]["avg_duration"] = np.concatenate([campaign["duration"]["avg_duration"], visit_avg_duration])
        campaign["duration"]["min_duration"] = np.concatenate([campaign["duration"]["min_duration"], visit_min_duration])

        campaign["click"]["shape"] = np.concatenate([campaign["click"]["shape"], click_shape])
        campaign["click"]["avg_click"] = np.concatenate([campaign["click"]["avg_click"], click_avg_click])
        campaign["click"]["min_click"] = np.concatenate([campaign["click"]["min_click"], click_min_click])

        self.state["n_campaigns"] = n_existing + n_campaigns
        self.state["campaign"] = campaign

    def _generate_session_times(self, n):
        # Select peak our (14 == 14:00, 14.5 == 14:30)
        peak_hour = 14 * 60

        min_per_day = np.timedelta64(1, 'D').astype('timedelta64[m]').astype(np.int64)

        accepted_hours = []
        while len(accepted_hours) < n:
            # Sample hours from normal distribution
            sample = self._rng.normal(loc=peak_hour, scale=5 * 60, size=n * 2)

            accepted_hours = sample[(sample >= 0) & (sample < min_per_day)]

        session_hours = accepted_hours[:n]

        # Return as timedelta in minutes
        return session_hours.astype('timedelta64[m]')

    def _generate_session_dates(self, campaign_ids: npt.NDArray[np.integer], start: np.int64, end: np.int64, n: int) -> npt.NDArray[np.floating]:
        """
        Sample random timestamps from a skewwed normal distribution. 
        Each campaign has its own skewness and peak location within the timeframe.

        :param campaign_effect: the effectiveness of each campaign, determining the skewness of each campaign. 
        :param campaign_ids: the array with the campaign id of each delta
        :param delta_in_seconds: the total timeframe in seconds
        :param n: number of deltas to generate

        :return: sampled datetimes, precision in seconds
        """

        session_parameters = self.state["campaign"]["session"]

        # Compute parameters per row
        skew_per_row = session_parameters["skew"][campaign_ids - 1]
        locs_per_row = session_parameters["loc"][campaign_ids - 1]
        scale_per_row = session_parameters["scale"][campaign_ids - 1]

        # Generate sessions
        skewwed_dates = np.empty(n)
        samples = stats.skewnorm.rvs(
            a=skew_per_row,
            loc=locs_per_row,
            scale=scale_per_row,
            size=n,
            random_state=self._rng
        )

        # Accept only that fall within timeframe
        accept = (samples >= start) & (samples <= end)
        skewwed_dates = np.where(accept, samples, skewwed_dates)

        # Skip resampling when all dates are accepted
        if accept.sum() == n:
            return skewwed_dates.astype('datetime64[D]')

        # Resample values that fall out of bounds
        resample = np.logical_not(accept)

        # Determine density of the campaigns
        start_density = stats.skewnorm.cdf(start, a=session_parameters["skew"], loc=session_parameters["loc"], scale=session_parameters["scale"])
        end_density = stats.skewnorm.cdf(end, a=session_parameters["skew"], loc=session_parameters["loc"], scale=session_parameters["scale"])

        # Sample percentile within timeframe
        sample_locations = self._rng.uniform(start_density[campaign_ids - 1][resample], end_density[campaign_ids - 1][resample], resample.sum())

        # Sample rest of dates using percentiles
        skewwed_dates[resample] = stats.skewnorm.ppf(sample_locations, a=skew_per_row[resample], loc=locs_per_row[resample], scale=scale_per_row[resample])

        return skewwed_dates.astype('datetime64[D]')
    
    def _generate_sessions(self, start, end, campaign_ids, n):
        session_dates = self._generate_session_dates(campaign_ids, start, end, n)
        session_times = self._generate_session_times(n)

        return session_dates + session_times

    def _introduce_day_bias(self, dates: npt.NDArray[np.datetime64], end_date: np.datetime64, campaign_ids: npt.NDArray[np.integer], n_campaigns: int) -> npt.NDArray[np.datetime64]:
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
        session_parameters = campaigns["session"]

        activity = stats.skewnorm.cdf(end, session_parameters["skew"], session_parameters["loc"], session_parameters["scale"]) - \
                    stats.skewnorm.cdf(start, session_parameters["skew"], session_parameters["loc"], session_parameters["scale"])

        # Campaign ID's are sampled based on their current activity in the timeframe
        weight = activity.clip(0, 1) * session_parameters["reach"]
        weight /= weight.sum()

        campaign_ids = self._rng.choice(campaigns["id"], n, p=weight)

        return campaign_ids

    def _generate_visit_duration(self, campaign_ids, pageviews, n, precision = 'm') -> npt.NDArray:
        duration_parameters = self.state["campaign"]["duration"]

        shape_per_row = duration_parameters["shape"][campaign_ids - 1]
        loc_per_row = duration_parameters["min_duration"][campaign_ids - 1]
        scale_per_row = duration_parameters["avg_duration"][campaign_ids - 1]

        visit_duration = stats.gamma.rvs(a=shape_per_row,
                                         loc=pageviews * loc_per_row,
                                         scale=scale_per_row, 
                                         size=n, random_state=self._rng)
        visit_duration = visit_duration.astype(f'timedelta64[{precision}]')

        return visit_duration

    def _generate_page_views(self, number_of_records: int, min_value: int, max_value: int, campaign_ids: npt.NDArray[np.floating]) -> npt.NDArray:
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
        pageviews_parameters = self.state["campaign"]["pageview"]

        p_per_row = pageviews_parameters["p"][campaign_ids - 1]

        page_views = stats.geom.rvs(p_per_row, size=number_of_records, random_state=self._rng)

        return np.clip(page_views, min_value, max_value)

    def _generate_clicks(self, pageviews, n: int, campaign_ids: npt.NDArray[np.floating]) -> npt.NDArray:
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
        # campaign_effect = campaigns["session"]["reach"][campaign_ids - 1]

        click_parameters = self.state["campaign"]["click"]

        shape_per_row = click_parameters["shape"][campaign_ids - 1]
        loc_per_row = click_parameters["min_click"][campaign_ids - 1]

        click = stats.poisson.rvs(mu=shape_per_row,
                                loc=pageviews * loc_per_row,
                                size=n, random_state=self._rng)

        return click

    def _generate_interaction(self, campaign_ids, clicks, page_views, number_of_records):
        # Generate pageview trend
        view_total = self._generate_page_views(number_of_records, 1, page_views, campaign_ids)

        # Generate visit duration trend
        visit_duration = self._generate_visit_duration(campaign_ids, view_total, number_of_records, precision='m')

        # Generate click trend
        click_total = self._generate_clicks(view_total, number_of_records, campaign_ids).astype(int)

        return visit_duration, view_total, click_total


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

        # Convert to numpy datetime for efficient calculations
        start_ts = np.datetime64(start, 'D').astype(np.int64)
        end_ts = np.datetime64(end, 'D').astype(np.int64)

        # Unique session ID
        old_records = self.state.get("last_record", 0)
        session_ids = np.arange(old_records + 1, old_records + number_of_records + 1)

        # A visitor may be recurrent. Therefore the possibility for duplicate IDs is needed
        visitor_ids = self._rng.integers(1, number_of_records * 3, number_of_records)

        # Generate random properties for each campaign
        self._add_new_campaigns(start_ts, end_ts, n_campaigns)

        # Sample campaign ids
        campaign_ids = self._sample_campaign_ids(start_ts, end_ts, number_of_records)

        # Generate random dates and sort for chronological order of sessions
        session_dates = self._generate_sessions(start_ts, end_ts, campaign_ids, number_of_records)

        # Sort for chronology
        campaign_ids, session_dates = sort_by_date(campaign_ids, session_dates)

        visit_duration, view_total, click_total = self._generate_interaction(campaign_ids, clicks, page_views, number_of_records)
        
        # The influence parameters have on conversion chance TODO: Get from config file
        conversion_influence = {
            'click': 0.35,
            'page_view': 0.15,
            'duration': 0.5
        }
        # Make sure values are normalized
        infl_sum = sum(conversion_influence.values())
        conversion_influence = {key: value/infl_sum for key, value in conversion_influence.items()}

        # Compute conversion chance
        conversion_chance = 0.0
        conversion_chance += conversion_influence['click'] * (click_total / clicks)
        conversion_chance += conversion_influence['page_view'] * (view_total / page_views)
        conversion_chance += conversion_influence['duration'] * (visit_duration.astype(np.int64) / MAX_VISIT_TIME)

        # Compute conversions
        conversion = self._rng.random(number_of_records) < conversion_chance


        # Generate random source data
        randomized_device = self._rng.integers(1, devices, number_of_records)

        randomized_city = self._rng.integers(1, location, number_of_records)

        randomized_traffic_sources = self._rng.integers(1, traffic_sources, number_of_records)


        # Update state
        self.state["last_record"] = old_records + number_of_records
        self.state["current_date"] = end.strftime(DATE_FORMAT)

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

        self.state["records_last_day"] = (generated_records['starttijd_bezoek'].dt.date == session_dates[-1].item().date()).sum().astype(str)

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
