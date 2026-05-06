from datetime import datetime, timedelta
import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy import stats
import json

from src.utils import sort_by_date, present_line, DATE_FORMAT
from src import utils

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

        self.update = update
        self.day_preference = day_preference

        self._default_campaign = {
            "id": np.array([], dtype=int), # id of the campaign
            "session": {"reach": [], "skew": [], "loc": [], "scale": []}, # Properties of session trends per campaign
            "click": {"shape": [], "avg_click": [], "min_click": []}, # Properties of clicktrend per campaign
            "pageview": {"p": []}, # Probability of visiting another page per campaign
            "duration": {"shape": [], "avg_duration": [], "min_duration": []} # properties of the durations 
        }

        self.state_path = state_path

        self.state = {} # state object contains state of simulation

        # Initialize default state values
        self.state["campaign"] = self._default_campaign.copy()

        if update:
            self._load_state()

    def _load_state(self):
        """
        Load state from file and convert to numpy arrays.
        """
        try:
            self.state = utils.load_json(self.state_path)
        except FileNotFoundError:
            present_line("Please make sure you have generated initial data before running update.")
            exit(1)
        self.state = utils.dict_list_to_ndarray(self.state)
        self.state["campaign"]["session"]["loc"] = self.state["campaign"]["session"]["loc"].astype('datetime64[D]').astype(np.int64)
        return self.state

    def _save_state(self):
        """
        Write the updated state to file.
        """
        # Convert campaign properties to lists for json conversion
        self.state["campaign"]["session"]["loc"] = self.state["campaign"]["session"]["loc"].astype('datetime64[D]').astype(str)
        self.state = utils.dict_ndarray_to_list(self.state)

        # write state to file
        with open(self.state_path, 'w') as file:
            json.dump(self.state, file, indent=4)

    def _add_new_campaigns(self, start: int, end: int, n_campaigns: int):
        """
        Adds properties of new campaigns to state.
        Defines the shape of the following trends:
         - Sessions:
            - number of sessions per campaign
            - how long the campaign generates sessions
            - where the peak of the campaign resides in time
         - Page views:
            - probability of visiting another page
         - Visit duration:

        
        :param start: Start of the campaign in days since 1-1-1970
        :param end: End of the campaign in days since 1-1-1970
        :param n_campaigns: Number of new campaigns to add to the trend
        """
        campaign = self.state.get("campaign", self._default_campaign)
        n_existing = self.state.get("n_campaigns", 0)

        # Generate ID's for the new campaigns
        campaign_id = np.arange(1, n_campaigns + 1) + n_existing

        """
        ####################################
            Campaign session properties
        ####################################
        """
        # Randomly determine effectiveness of each new campaign
        # # IDEA: multiple campaign types and platforms with each their own effects
        # Adoption speed, how fast does the campaign show effect
        campaign_speed = self._rng.uniform(-10, 11, n_campaigns)
        # How many sessions does the campaign generate
        campaign_reach = self._rng.random(n_campaigns)

        # Duration of the campaign
        campaign_duration = self._rng.uniform(1, 12, n_campaigns) # in months

        # Compute scale with a campaign duration in months
        # Scale is standard deviation, curve 'dies out' after +- 3 * sd,
        # therefore deviding duration by 3 gives a good scale for the campaign
        campaign_scale = campaign_duration.astype('timedelta64[M]').astype('timedelta64[D]').astype(np.int64) / 3

        # Randomly place the peaks of the new campaigns in the new timeframe
        campaign_mean = self._rng.uniform(start, end, n_campaigns)

        campaign_offset = 0
        # Only when updating data place start of campaign at start of timeframe
        if self.update:
            # Get the starting location of the campaign
            campaign_start = stats.skewnorm.ppf(0.001, a=campaign_speed, loc=campaign_mean, scale=campaign_scale)
            # Use the offset to place the starting location in the future, makes all campaigns start at the same time
            campaign_offset = start - campaign_start

        """
        ####################################
               Page view properties
        ####################################
        """
        # Probability of visiting the next page
        page_prob = self._rng.random(n_campaigns)

        """
        ####################################
             Visit duration properties
        ####################################
        """
        # Shape of the visit curve per campaign
        visit_shape = self._rng.uniform(1, 3, n_campaigns)
        # Generate average visit duration per page
        visit_avg_duration = self._rng.uniform(1, MAX_VISIT_TIME, n_campaigns)
        # Generate minimum visit duration per page
        visit_min_duration = self._rng.uniform(1, 5, n_campaigns)

        """
        ####################################
             Click properties
        ####################################
        """
        # Average number of clicks per page per campaign
        click_shape = self._rng.uniform(0.5, 1, n_campaigns)
        # Minimum number of clicks per page per campaign
        click_min_click = self._rng.integers(0, 4, n_campaigns)

        """
        ###################################
               Update campaign state
        ###################################
        """
        # Set ids
        campaign["id"] = np.concatenate([campaign["id"], campaign_id])

        # Update sessions
        campaign["session"]["skew"] = np.concatenate([campaign["session"]["skew"], campaign_speed])
        campaign["session"]["loc"] = np.concatenate([campaign["session"]["loc"], campaign_mean + campaign_offset])
        campaign["session"]["scale"] = np.concatenate([campaign["session"]["scale"], campaign_scale])
        campaign["session"]["reach"] = np.concatenate([campaign["session"]["reach"], campaign_reach])

        # Update pageviews
        campaign["pageview"]["p"] = np.concatenate([campaign["pageview"]["p"], page_prob])

        # Update durations
        campaign["duration"]["shape"] = np.concatenate([campaign["duration"]["shape"], visit_shape])
        campaign["duration"]["avg_duration"] = np.concatenate([campaign["duration"]["avg_duration"], visit_avg_duration])
        campaign["duration"]["min_duration"] = np.concatenate([campaign["duration"]["min_duration"], visit_min_duration])

        # Update clicks
        campaign["click"]["shape"] = np.concatenate([campaign["click"]["shape"], click_shape])
        campaign["click"]["min_click"] = np.concatenate([campaign["click"]["min_click"], click_min_click])

        # Update state
        self.state["n_campaigns"] = n_existing + n_campaigns
        self.state["campaign"] = campaign

    def _generate_session_times(self, number_of_records: int) -> npt.NDArray[np.timedelta64]:
        """
        This function implements a bias towards realistic session times over the day.

        Sample random times for each record.
        The times follow a normal distribution over the day, with 14 O'clock as mean.

        :param number_of_records: number of records to generate
        :return: Sampled times as timedelta in minutes
        """
        # Select peak our (14 == 14:00, 14.5 == 14:30)
        peak_hour = 14 * 60

        min_per_day = np.timedelta64(1, 'D').astype('timedelta64[m]').astype(np.int64)

        accepted_hours = []
        while len(accepted_hours) < number_of_records:
            # Sample hours from normal distribution
            sample = self._rng.normal(loc=peak_hour, scale=5 * 60, size=number_of_records * 2)

            # Accept only samples that fall within one day
            accepted_hours = sample[(sample >= 0) & (sample < min_per_day)]

        # Only keep samples that are needed
        session_hours = np.array(accepted_hours[:number_of_records])

        # Return as timedelta in minutes
        return session_hours.astype('timedelta64[m]')

    def _generate_session_dates(self, campaign_ids: npt.NDArray[np.integer], number_of_records: int, start: int, end: int) -> npt.NDArray[np.datetime64]:
        """
        Sample random timestamps from a skewwed normal distribution. 
        Each campaign has its own skewness and peak location.

        :param campaign_ids: the array with the campaign ids per row
        :param number_of_records: the number of records to create
        :param start: start of the timeframe to generate dates in
        :param end: end of the timeframe to generate dates in

        :return: sampled dates, precision in days
        """
        session_parameters = self.state["campaign"]["session"]

        # Compute parameters per row
        skew_per_row = session_parameters["skew"][campaign_ids - 1]
        locs_per_row = session_parameters["loc"][campaign_ids - 1]
        scale_per_row = session_parameters["scale"][campaign_ids - 1]

        # Generate sessions
        skewwed_dates = np.empty(number_of_records)
        samples = stats.skewnorm.rvs(
            a=skew_per_row,
            loc=locs_per_row,
            scale=scale_per_row,
            size=number_of_records,
            random_state=self._rng
        )

        # Accept only that fall within timeframe
        accept = (samples >= start) & (samples <= end)
        skewwed_dates = np.where(accept, samples, skewwed_dates)

        # Skip resampling when all dates are accepted
        if accept.sum() == number_of_records:
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

    def _generate_sessions(self, campaign_ids: npt.NDArray[np.integer], number_of_records: int, start: int, end: int) -> npt.NDArray[np.datetime64]:
        """
        Generates session dates and times seperately and puts them together into a single datetime object.

        :param campaign_ids: the array with the campaign ids per row
        :param number_of_records: the number of records to create
        :param start: start of the timeframe to generate dates in
        :param end: end of the timeframe to generate dates in

        :return: sampled session datetimes, precision in minutes
        """
        session_dates = self._generate_session_dates(campaign_ids, number_of_records, start, end)
        session_times = self._generate_session_times(number_of_records)

        return session_dates + session_times

    def _introduce_day_bias(self, dates: npt.NDArray[np.datetime64], end_date: np.datetime64, campaign_ids: npt.NDArray[np.integer], n_campaigns: int) -> npt.NDArray[np.datetime64]:
        """
        Bias already calculated dates towards weekdays or weekends.
        TODO FUNCTION IS OUTDATED NEEDS TO BE UPDATED OR REMOVED

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

    def get_activity(self, param: dict[str, npt.NDArray[np.floating]], start: int, end: int) -> npt.NDArray[np.floating]:
        """
        Get the activity of all campaigns between `start` and `end`.

        :param param: dictionary with skewnorm parameters: 'skew', 'loc' and 'scale'
        :return: activity of all campaigns
        """
        return stats.skewnorm.cdf(end, param["skew"], param["loc"], param["scale"]) - \
                stats.skewnorm.cdf(start, param["skew"], param["loc"], param["scale"])

    def _sample_campaign_ids(self, number_of_records: int, start: int, end: int) -> npt.NDArray[np.floating]:
        """
        Sample campaign id of each row according to its activity and reach.
        This follows the idea that the number of sessions for a particular campaign
        mirrors its reach and activity in the timeframe.

        :param number_of_records: the number of records to create
        :param start: start of the timeframe to generate dates in, in days since epoch (01-01-1970)
        :param end: end of the timeframe to generate dates in, in days since epoch (01-01-1970)

        :return: sampled campaign ids per row
        """
        campaigns = self.state["campaign"]
        session_parameters = campaigns["session"]

        activity = self.get_activity(session_parameters, start, end)

        # Campaign ID's are sampled based on their current activity in the timeframe
        weight = activity.clip(0, 1) * session_parameters["reach"]
        weight /= weight.sum()

        campaign_ids = self._rng.choice(campaigns["id"], number_of_records, p=weight)

        return campaign_ids

    def _generate_page_views(self, campaign_ids: npt.NDArray[np.integer], number_of_records: int) -> npt.NDArray:
        """
        Generate the number of views per page.

        :param campaign_ids: the array with the campaign ids per row
        :param number_of_records: number of records to generate
        :return: generated trend clipped to min and max values
        """
        pageviews_parameters = self.state["campaign"]["pageview"]

        p_per_row = pageviews_parameters["p"][campaign_ids - 1]

        page_views = stats.geom.rvs(p_per_row, size=number_of_records, random_state=self._rng)

        return np.clip(page_views, 1, self.state['max_page_views'])

    def _generate_visit_duration(self, campaign_ids: npt.NDArray[np.integer], number_of_records: int, pageviews: int, precision: str = 'm') -> npt.NDArray:
        """
        Generate duration of session. 
        This follows a gamma distribution. This keeps visit times positive and around the mean.

        :param campaign_ids: the array with the campaign ids per row
        :param number_of_records: number of records to generate
        :param pageviews: number of pages viewed per session
        :return: array of visit durations per row
        """
        # Get parameters for duration
        duration_parameters = self.state["campaign"]["duration"]

        # Extend parameters per campaign to rows they belong to
        shape_per_row = duration_parameters["shape"][campaign_ids - 1]
        loc_per_row = duration_parameters["min_duration"][campaign_ids - 1]
        scale_per_row = duration_parameters["avg_duration"][campaign_ids - 1]

        # Draw durations from distribution
        visit_duration = stats.gamma.rvs(a=shape_per_row,
                                         loc=pageviews * loc_per_row,
                                         scale=scale_per_row, 
                                         size=number_of_records, 
                                         random_state=self._rng)
        # Convert the sampled floats to timedelta's with requested precision
        visit_duration = visit_duration.astype(f'timedelta64[{precision}]')

        return visit_duration

    def _generate_clicks(self, campaign_ids: npt.NDArray[np.integer], number_of_records: int, pageviews: int) -> npt.NDArray:
        """
        Generate the number of clicks of a session.

        :param campaign_ids: the array with the campaign ids per row
        :param number_of_records: number of records to generate
        :param pageviews: number of pages viewed per session
        :return: generated trend clipped to min and max values
        """
        click_parameters = self.state["campaign"]["click"]

        shape_per_row = click_parameters["shape"][campaign_ids - 1]
        loc_per_row = click_parameters["min_click"][campaign_ids - 1]

        click = stats.poisson.rvs(mu=shape_per_row,
                                loc=pageviews * loc_per_row,
                                size=number_of_records, random_state=self._rng)

        return np.clip(click, 1, self.state['max_clicks'])

    def _generate_interaction(self, campaign_ids, number_of_records):
        """
        Generate the interactions per session in 3 stages.
        1. Generate the page views
        2. Generate the visit durations
        3. Generate the clicks

        :param campaign_ids: the array with the campaign ids per row
        :param number_of_records: number of records to generate
        :return: visit durations, pages viewed, clicks
        """
        # Generate pageview trend
        view_total = self._generate_page_views(campaign_ids, number_of_records)

        # Generate visit duration trend
        visit_duration = self._generate_visit_duration(campaign_ids, number_of_records, view_total)

        # Generate click trend
        click_total = self._generate_clicks(campaign_ids, number_of_records, view_total)

        return visit_duration, view_total, click_total

    def _generate_conversion(self, click_total: npt.NDArray[np.integer], view_total: npt.NDArray[np.integer], visit_duration: npt.NDArray[np.timedelta64], number_of_records: int) -> npt.NDArray:
        """
        Determines wether the interactions lead to a conversion.

        """
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
        conversion_chance += conversion_influence['click'] * (click_total / self.state['max_clicks'])
        conversion_chance += conversion_influence['page_view'] * (view_total / self.state['max_page_views'])
        conversion_chance += conversion_influence['duration'] * (visit_duration.astype(np.int64) / MAX_VISIT_TIME)

        # Compute conversions
        conversion = self._rng.random(number_of_records) < conversion_chance

        return conversion

    def _generate_base(self, start, stop, number_of_records: int) -> npt.NDArray:
        """
          Generates a base trend. TODO: needs to be updated
        """

        # trend_base is scaled by timeline growth
        n_days = stop - start
        days = np.arange(start, stop, dtype=int)

        weight = np.linspace(0.1, 1, n_days)
        weight /= weight.sum()

        trend_base = self._rng.choice(days, p=weight, size=number_of_records)

        return trend_base.astype('datetime64[D]')

    def generate_data(self, n_campaign_records, n_base_records, n_campaigns, start, end):
        """ 
        Main generator function.
        This function generates data for all `number_of_records` records from `start` to `end`.

        :param number_of_records: number of records to generate
        :param n_campaigns: number of campaigns to generate
        :param start: start date of record generation
        :param end: end date of record generation
        :return: generated data as dataframe
        """
        country = 'NL'
        number_of_records = n_campaign_records + n_base_records
        print(number_of_records, n_base_records, n_campaign_records)

        # Convert to numpy datetime for efficient calculations
        start_ts = np.datetime64(start, 'D').astype(np.int64)
        end_ts = np.datetime64(end, 'D').astype(np.int64)

        # Unique session ID
        old_records = self.state.get("last_record", 0)
        session_ids = np.arange(old_records + 1, old_records + number_of_records + 1)

        # A visitor may be recurrent. Therefore the possibility for duplicate IDs is needed
        visitor_ids = self._rng.integers(1, number_of_records * 3, number_of_records)

        # Generate random properties for each new campaign
        if not self.update:
            self._add_new_campaigns(start_ts, end_ts, n_campaigns)

        # Sample campaign ids
        campaign_ids = self._sample_campaign_ids(n_campaign_records, start_ts, end_ts)

        # Generate random dates and sort for chronological order of sessions
        session_dates = self._generate_sessions(campaign_ids, n_campaign_records, start_ts, end_ts)

        # Generate base trend
        base_session_dates = self._generate_base(start_ts, end_ts, n_base_records)
        session_dates = np.concatenate([session_dates, base_session_dates])
        campaign_ids = np.concatenate([campaign_ids, np.zeros(n_base_records, dtype=int)])

        # Sort for chronology
        campaign_ids, session_dates = sort_by_date(campaign_ids, session_dates)

        # Generate interactions (clicks, page views, durations)
        visit_duration, view_total, click_total = self._generate_interaction(campaign_ids, number_of_records)
        
        conversion = self._generate_conversion(click_total, view_total, visit_duration, number_of_records)

        # Generate random source data
        randomized_device = self._rng.integers(1, self.state['max_devices'], number_of_records)

        randomized_city = self._rng.integers(1, self.state['max_location'], number_of_records)

        randomized_traffic_sources = self._rng.integers(1, self.state['max_traffic_sources'], number_of_records)

        # Update state
        self.state["last_record"] = old_records + number_of_records
        self.state["current_date"] = end.strftime(DATE_FORMAT)

        generated_records = pd.DataFrame({
            "sessie_ID": session_ids,
            "campagne_ID": campaign_ids,
            "bezoeker_ID": visitor_ids,
            "starttijd_bezoek": session_dates,
            "eindtijd_bezoek": (session_dates + visit_duration),
            "totale_tijd_bezoek": visit_duration.astype(int),
            "kliks_op_site_elementen": click_total.astype(int),
            "paginas_bekeken": view_total.astype(int),
            "apparaat": randomized_device,
            "land": country,
            "stad": randomized_city,
            "verkeers_bron": randomized_traffic_sources,
            "conversie": conversion.astype(int)
        })

        last_day = session_dates[-1].item().date()

        last_day_records = generated_records[generated_records['starttijd_bezoek'].dt.date == last_day]

        campaign_id_index = np.concatenate(([0], self.state["campaign"]["id"]))
        records_per_campaign = last_day_records.groupby('campagne_ID').size().reindex(campaign_id_index, fill_value=0).to_numpy()

        self.state["records_last_day"] = len(last_day_records)
        self.state["records_last_day_per_campaign"] = records_per_campaign

        if len(generated_records) != number_of_records:
            present_line("Something went wrong!")
            present_line("The number of records generated doesn't equal the number of records needed.")

        return generated_records

    def get_params(self, parameters) -> tuple[int, int, int, int]:
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

        # Place rest in state
        self.state['max_location'] = parameters["location"]
        self.state['max_devices'] = parameters["devices"]
        self.state['max_clicks'] = parameters["clicks"]
        self.state['max_page_views'] = parameters["page_views"]
        self.state['max_traffic_sources'] = parameters["traffic_source"]

        return n_campaign_records, n_base, n_campaigns, start, end

    def get_updated_params(self, start: datetime, end: datetime) -> tuple[int, int]:
        """
        Get parameters for new day.

        Adds new campaigns and computes the number of records for the new day.

        :param start: start of the day
        :param end: end of the day
        :return: Number of records for day to be generated, number of generated new campaigns
        """

        start_ts = np.datetime64(start, 'D').astype(np.int64)
        end_ts = np.datetime64(end, 'D').astype(np.int64)

        n_campaigns = 1 if self._rng.random() < 0.1 else 0
        if n_campaigns > 0:
            self._add_new_campaigns(start_ts, end_ts, n_campaigns)
            records_last_day_per_campaign = np.concatenate([self.state["records_last_day_per_campaign"], [0]])
        else:
            records_last_day_per_campaign = self.state["records_last_day_per_campaign"]

        session_parameters = self.state['campaign']['session']

        # Get activity of the campaign curves
        activity_last_day = np.nan_to_num(self.get_activity(session_parameters, start_ts - 1, end_ts - 1))
        activity_cur_day = np.nan_to_num(self.get_activity(session_parameters, start_ts, end_ts))

        # Calculate growth per campaign
        ratio_per_campaign = np.divide(activity_cur_day, activity_last_day, out=np.zeros_like(activity_cur_day, dtype=float), where=activity_last_day!=0)

        # Calculate new number of records per campaign
        campaign_trend = int((ratio_per_campaign * records_last_day_per_campaign[1:]).sum())

        # Calculate new number of records for base
        base_trend = int(records_last_day_per_campaign[0] * 1.01)

        campaign_records = int(self._rng.normal(campaign_trend, campaign_trend * 0.02)) # 2% noise
        base_records = int(self._rng.normal(base_trend, base_trend * 0.02)) # 2% noise

        return campaign_records, base_records, n_campaigns
    
    def generate_incremental(self) -> pd.DataFrame:
        """
        Generate new data up to today.
        Data is generated day by day.

        :return: newly generated records as dataframe
        """
        # Get start date from state
        start = datetime.strptime(self.state['current_date'], DATE_FORMAT)

        # Set end date to today
        end = datetime.today()

        # Set current dates
        current_start = start
        current_end = start + timedelta(days=1)

        # Update data for 1 day
        records = pd.DataFrame()
        while current_end < end:
            # Set new start and end
            n_records, n_base, n_campaigns = self.get_updated_params(current_start, current_end)

            # Add generated data to dataframe
            records = pd.concat([records, self.generate_data(n_records, n_base, n_campaigns, current_start, current_end)])

            # Update dates
            current_start = current_end
            current_end += timedelta(days=1)

        return records

    def generate(self, parameters: dict) -> pd.DataFrame:
        """
        Starting point of generator. 
        Generates data up to current day or generates data in given timeframe.

        :param parameters: Dictionary of parameters to use when generating historical data
        :return: Generated data as dataframe
        """
        if self.update:
            return self.generate_incremental()
        else:
            n_records, n_base, n_campaigns, start, end = self.get_params(parameters)
            return self.generate_data(n_records, n_base, n_campaigns, start, end)

    def save_data(self, data: pd.DataFrame, save_path: str, sep: str = ';', date_format="%d-%m-%Y %H:%M"):
        """
        Saves generated records to file.

        :param data:
        :param save_path:
        :param sep:
        :param date_format:
        """
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

        # Save the current state to file
        self._save_state()

        present_line("Records saved")
        present_line("\nHave a pretty day!\n")
