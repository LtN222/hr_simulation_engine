import numpy as np
import numpy.typing as npt
from scipy import stats

MAX_VISIT_TIME = 30 # minutes TODO: Get from config file

class CampaignManager():
    
    def __init__(self, rng: np.random.Generator, campaign_state: dict):
        self._rng = rng
        self.campaign_state = campaign_state

    def add_new_campaigns(self, start: int, end: int, n_campaigns: int, update: bool = False):
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
        n_existing = self.campaign_state.get("n_campaigns", 0)

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
        if update:
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
        self.campaign_state["id"] = np.concatenate([self.campaign_state["id"], campaign_id])

        # Update sessions
        self.campaign_state["session"]["skew"] = np.concatenate([self.campaign_state["session"]["skew"], campaign_speed])
        self.campaign_state["session"]["loc"] = np.concatenate([self.campaign_state["session"]["loc"], campaign_mean + campaign_offset])
        self.campaign_state["session"]["scale"] = np.concatenate([self.campaign_state["session"]["scale"], campaign_scale])
        self.campaign_state["session"]["reach"] = np.concatenate([self.campaign_state["session"]["reach"], campaign_reach])

        # Update pageviews
        self.campaign_state["pageview"]["p"] = np.concatenate([self.campaign_state["pageview"]["p"], page_prob])

        # Update durations
        self.campaign_state["duration"]["shape"] = np.concatenate([self.campaign_state["duration"]["shape"], visit_shape])
        self.campaign_state["duration"]["avg_duration"] = np.concatenate([self.campaign_state["duration"]["avg_duration"], visit_avg_duration])
        self.campaign_state["duration"]["min_duration"] = np.concatenate([self.campaign_state["duration"]["min_duration"], visit_min_duration])

        # Update clicks
        self.campaign_state["click"]["shape"] = np.concatenate([self.campaign_state["click"]["shape"], click_shape])
        self.campaign_state["click"]["min_click"] = np.concatenate([self.campaign_state["click"]["min_click"], click_min_click])

        # Update campaign count
        self.campaign_state["n_campaigns"] = n_existing + n_campaigns

    def get_activity(self, param: dict[str, npt.NDArray[np.floating]], start: int, end: int) -> npt.NDArray[np.floating]:
        """
        Get the activity of all campaigns between `start` and `end`.

        :param param: dictionary with skewnorm parameters: 'skew', 'loc' and 'scale'
        :return: activity of all campaigns
        """
        return stats.skewnorm.cdf(end, param["skew"], param["loc"], param["scale"]) - \
                stats.skewnorm.cdf(start, param["skew"], param["loc"], param["scale"])

    def sample_campaign_ids(self, number_of_records: int, start: int, end: int) -> npt.NDArray[np.floating]:
        """
        Sample campaign id of each row according to its activity and reach.
        This follows the idea that the number of sessions for a particular campaign
        mirrors its reach and activity in the timeframe.

        :param number_of_records: the number of records to create
        :param start: start of the timeframe to generate dates in, in days since epoch (01-01-1970)
        :param end: end of the timeframe to generate dates in, in days since epoch (01-01-1970)

        :return: sampled campaign ids per row
        """
        activity = self.get_activity(self.campaign_state["session"], start, end)

        # Campaign ID's are sampled based on their current activity in the timeframe
        weight = activity.clip(0, 1) * self.campaign_state["session"]["reach"]
        weight /= weight.sum()

        campaign_ids = self._rng.choice(self.campaign_state["id"], number_of_records, p=weight)

        return campaign_ids