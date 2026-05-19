import numpy as np
import numpy.typing as npt
from scipy import stats
from datetime import timedelta


class SessionGenerator():

    """Class for generating sessions"""

    def __init__(self, rng: np.random.Generator, campaign_parameters: dict):
        """
        Session generator initialization.
        
        :param rng: random number generator
        :param campaign_parameters: parameters of the campaigns
        """
        self._rng = rng
        self.parameters = campaign_parameters
    
    def generate_base(self, start: int, stop: int, number_of_records: int) -> npt.NDArray[np.datetime64]:
        """
          Generates a base trend.

          The base trend is generated based on a linear distribution. 

          Each day is assigned a weight linearly.
          The sessions are randomly sampled from this distribution.

          :param start: start of timeframe in days since 1-1-1970
          :param stop: start of timeframe in days since 1-1-1970
          :param number_of_records: number of records to generate
          :return: days of the sessions of the base trend
        """

        # trend_base is scaled by timeline growth
        days = np.arange(start, stop, dtype=int)

        # Distribute weights evenly over linear space
        n_days = stop - start
        weight = np.linspace(0.1, 1, n_days)
        weight /= weight.sum()

        # Choose days for the base trend based on linear weight distribution
        trend_base = self._rng.choice(days, p=weight, size=number_of_records)

        return trend_base.astype('datetime64[D]') + self._generate_session_times(number_of_records)
    
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
        # Compute parameters per row
        skew_per_row = self.parameters["skew"][campaign_ids - 1]
        locs_per_row = self.parameters["loc"][campaign_ids - 1]
        scale_per_row = self.parameters["scale"][campaign_ids - 1]

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
        start_density = stats.skewnorm.cdf(start, a=self.parameters["skew"], loc=self.parameters["loc"], scale=self.parameters["scale"])
        end_density = stats.skewnorm.cdf(end, a=self.parameters["skew"], loc=self.parameters["loc"], scale=self.parameters["scale"])

        # Sample percentile within timeframe
        sample_locations = self._rng.uniform(start_density[campaign_ids - 1][resample], end_density[campaign_ids - 1][resample], resample.sum())

        # Sample rest of dates using percentiles
        skewwed_dates[resample] = stats.skewnorm.ppf(sample_locations, a=skew_per_row[resample], loc=locs_per_row[resample], scale=scale_per_row[resample])

        return skewwed_dates.astype('datetime64[D]')

    def generate_sessions(self, campaign_ids: npt.NDArray[np.integer], number_of_records: int, start: int, end: int) -> npt.NDArray[np.datetime64]:
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