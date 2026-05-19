import numpy as np
import numpy.typing as npt
from scipy import stats

class InteractionGenerator():
    def __init__(self, rng, max_page_views, max_clicks, max_visit_time, campaign_state, config):
        self._rng = rng
        self.max_page_views = max_page_views
        self.max_clicks = max_clicks
        self.max_visit_time = max_visit_time
        self.campaign_state = campaign_state
        self.config = config


    def _generate_page_views(self, campaign_ids: npt.NDArray[np.integer], number_of_records: int) -> npt.NDArray:
        """
        Generate the number of views per page.

        :param campaign_ids: the array with the campaign ids per row
        :param number_of_records: number of records to generate
        :return: generated trend clipped to min and max values
        """
        pageviews_parameters = self.campaign_state["pageview"]

        p_per_row = pageviews_parameters["p"][campaign_ids - 1]

        page_views = stats.geom.rvs(p_per_row, size=number_of_records, random_state=self._rng)

        return np.clip(page_views, 1, self.max_page_views)

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
        duration_parameters = self.campaign_state["duration"]

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
        click_parameters = self.campaign_state["click"]

        shape_per_row = click_parameters["shape"][campaign_ids - 1]
        loc_per_row = click_parameters["min_click"][campaign_ids - 1]

        click = stats.poisson.rvs(mu=shape_per_row,
                                loc=pageviews * loc_per_row,
                                size=number_of_records, random_state=self._rng)

        return np.clip(click, 1, self.max_clicks)

    def generate_interaction(self, campaign_ids, number_of_records):
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

    def generate_conversion(self, click_total: npt.NDArray[np.integer], view_total: npt.NDArray[np.integer], visit_duration: npt.NDArray[np.timedelta64], number_of_records: int) -> npt.NDArray:
        """
        Determines wether the interactions lead to a conversion.

        """
        # The influence parameters have on conversion chance
        conversion_influence = self.config["conversion"]

        # Make sure values are normalized
        infl_sum = sum(conversion_influence.values())
        conversion_influence = {key: value/infl_sum for key, value in conversion_influence.items()}

        # Compute conversion chance
        conversion_chance = 0.0
        conversion_chance += conversion_influence['click'] * (click_total / self.max_clicks)
        conversion_chance += conversion_influence['page_view'] * (view_total / self.max_page_views)
        conversion_chance += conversion_influence['duration'] * (visit_duration.astype(np.int64) / self.max_visit_time)

        # Compute conversions
        conversion = self._rng.random(number_of_records) < conversion_chance

        return conversion