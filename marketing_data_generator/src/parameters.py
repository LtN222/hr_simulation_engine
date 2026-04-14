from datetime import datetime
from src.utils import present_line
import math

DATE_FORMAT = "%d-%m-%Y"

class ParameterInputHandler():
    def __init__(self, max_records = 100000):
        self.max_limit = max_records
        pass

    
    def _get_number_of_records_needed(self) -> int:
        """
        Sets the arguments for prompting the user for the number of records
        that need to be generated.

        Passes the arguments to validate_input().
        Receives a validated integer value in return.

        :return: A validated integer provided by the user.
        """
        # max_limit = 10_000 # Limit number of records to generate, to prevent long runtime. (Can be higer when Numpy and Pandas have been implemented)
        message = f"How many records are needed? (limited to {self.max_limit}): "

        return self._validate_input(message, self.max_limit)


    def _get_number_of_campaigns_needed(self) -> int:
        """
        Sets the arguments for prompting the user for the number of campaigns
        that need to be included in the generated data.

        Passes the arguments to validate_input().
        Receives a validated integer value in return.

        :return: A validated integer provided by the user.
        """
        message = (f"For how many campaigns will data be needed?\n"
                f"The number of records will be equally devided over the campaigns: ")
        return self._validate_input(message)


    def _get_timeframe_date(self, message: str, before_date: datetime | None = None) -> datetime:
        """
        Prompt the user for a string input and validate it.

        Postcondition:
            - Returns a string in format dd-mm-yyyy.

        :param message: The message shown to the user during input.
        :return: A validated string, representing a date.
        """
        return self._validate_input(message, before_date=before_date, dtype=datetime)
        # while True:
        #     date = input(message)

        #     error_message = ("Invalid format, please try again.\n"
        #                     "Make sure you use the right format and a valid date.\n"
        #                     "Example: \n   November first 2020 becomes: 01-11-2020")

        #     try:
        #         date = datetime.strptime(date, DATE_FORMAT)

        #         if date.year < 1900 or date > datetime.today():
        #             error_message = ("Provided year is invalid.\n"
        #                             "Please try again.")
        #             raise ValueError

        #         # Validate start_date <= end_date
        #         if before_date is not None:
        #             if before_date <= date:
        #                 return date # Validation successful
        #             else:
        #                 error_message = (f"Invalid date, start date ({before_date.strftime(DATE_FORMAT)}) is before end date.\n"
        #                                 "Please try again.")
        #                 raise ValueError
        #         else:
        #             return date

        #     except:  # Validation failed
        #         present_line(error_message)


    def _get_timeframe(self) -> tuple[datetime]:
        """
        Sets the arguments for prompting the user for a window in time
        in which the datapoints need to be generated.

        Passes the arguments to get_timeframe_date().
        Receives a validated string value in return.

        :return: A list of validated strings provided by the user.
        """
        present_line("Please enter the timeframe parameters.")
        start_date = self._get_timeframe_date("What is the start date of the timeframe (dd-mm-yyyy): ")
        end_date = self._get_timeframe_date("What is the end date of the timeframe (dd-mm-yyyy): ", start_date)
        return (start_date, end_date)


    def _get_location(self) -> int:
        """
        Method is currently in a limited state, due to early stages of development.

        :return: A validated integer.
        """
        present_line("Country currently limited to: the Netherlands.")
        message= "What is the number of locations that need to be included: "
        return self._validate_input(message)


    def _get_devices(self) -> int:
        """
        Method is currently in a limited state, due to early stages of development.

        :return: A validated integer.
        """
        message = "What is the number of different devices that need to be included: "
        return self._validate_input(message)


    def _get_clicks_range(self) -> int:
        """
        Sets the arguments for prompting the user for a limit
        on the range of clicks for each record.

        Passes the arguments to validate_input().
        Receives a validated integer value in return.

        :return: A validated integer provided by the user.
        """
        message = f"What is the maximum number of clicks for each record: "
        return self._validate_input(message)


    def _get_page_visit_range(self) -> int:
        """
        Sets the arguments for prompting the user for a limit
        on the page visits for each record.

        Passes the arguments to validate_input().
        Receives a validated integer value in return.

        :return: A validated integer provided by the user.
        """
        message = f"What is the maximum number of page visits for each record: "
        return self._validate_input(message)


    def _get_traffic_source(self) -> int:
        """
        :return: A validated integer provided by the user.
        """
        message = f"What is the maximum number of traffic sources for each record: "
        return self._validate_input(message)
    

    def _get_conversion_rate(self) -> float:
        """
        :return: A validated float provided by the user.
        """
        message = f"What is the conversion chance for each record (between 0 and 1): "
        return self._validate_input(message, limit=1.0, dtype=float)


    def _validate_float(self, input, limit = 1.0):
        """
        Validate that given input is a float
        
        :param input: value to validate
        :param limit: upper bound of the variable
        :return: A validated float
        """
        # Check if input is a number by casting to int
        try:
            value = float(input)
        except:
            raise ValueError("Value must be a floating point.")
        # Check if input value is valid
        if 0 >= value: # 0 means no records are needed, therefore this is considered invalid input
            raise ValueError(f"Value must be higher than 0.")
        elif value > limit:
            raise ValueError(f"Value is higher than {limit}.")
        else: # input is valid
            return value
        
    def _validate_int(self, input, limit = math.inf):
        """
        Validate that given input is a float
        
        :param input: value to validate
        :param limit: upper bound of the variable
        :return: A validated float
        """
        # Check if input is a number by casting to int
        try:
            value = int(input)
        except:
            raise ValueError("Value must be an integer.")

        # Check if input value is valid
        if 0 >= value: # 0 means no records are needed, therefore this is considered invalid input
            raise ValueError(f"Value must be higher than 0.")
        elif value > limit:
            raise ValueError(f"Value is higher than {limit}.")
        else: # input is valid
            return value
        
    def _validate_date(self, input, before_date: datetime):
        try:
            date = datetime.strptime(input, DATE_FORMAT)
        except:
            raise ValueError(
                    "Make sure you use the right format and a valid date.\n"
                    f"Example: \n   November first 2020 becomes: {datetime(2020, 11, 1).strftime(DATE_FORMAT)}")
    
        if date.year < 1900:
            raise ValueError("Provided year is invalid.")
        
        if date > datetime.today():
            raise ValueError("Provided date is in the future.")

        # Validate start_date <= end_date
        if before_date is not None:
            if before_date <= date:
                return date # Validation successful
            else:
                raise ValueError(f"Invalid date, start date ({before_date.strftime(DATE_FORMAT)}) is before end date.\n")
        else:
            return date


    def _validate_input(self, message: str, limit = math.inf, dtype = None, before_date = None) -> int | float:
        """
        Prompt the user for an integer input and validate it.

        Precondition:
            - limit must be a positive integer (> 0).

        Postcondition:
            - Returns an integer x such that 0 < x <= limit.

        :param message: The message shown to the user during input.
        :param limit: Maximum allowed value (inclusive).
        :param dtype: Expected datatype of the input
        :return: A validated integer within the allowed range.
        """
        while True:
            value = input(message)
            try: # Cast successful
                if dtype == int:
                    return self._validate_int(value, limit)
                if dtype == float:
                    return self._validate_float(value)
                if dtype == datetime:
                    return self._validate_date(value, before_date)
                else: 
                    return self._validate_int(value, limit)
            except ValueError as e: # Cast failed
                present_line(f"Invalid input. {e} Please try again.")


    def _confirm_parameters(self, parameters: dict[str, int | str | list[str]]) -> bool:
        """
        Uses show_parameters() to print current parameters to console,
        and prompts user to validate current parameters.

        The user input is repeatedly requested for an input,
        until a valid char is entered.

        :param parameters: Dictionary containing the current parameters.

        :return: True if user agrees, False otherwise.
        """
        self._show_parameters(parameters)

        while True:
            correct = input("Are these settings correct? (y/n): ").lower()
            if correct == 'y': # User agrees -> continue to next phase
                return True
            elif correct == 'n': # User disagrees -> restart program
                return False
            else: # Handle invalid input
                present_line("Invalid input, try again.")


    def _show_parameters(self, parameters: dict[str, int | str | list[str]]) -> None:
        """
        Prints parameters to console, to inform user of current parameters.
        """
        present_line("\n")
        present_line("Please confirm parameters.")
        present_line(f"Number of records to be generated: {parameters['records']}.")
        present_line(f"Number of campaigns to be included: {parameters['campaigns']}.")
        present_line(f"Timeframe set to {parameters['timeframe'][0]} - {parameters['timeframe'][1]}.")
        present_line(f"Location data set to: {parameters['location']}")
        present_line(f"Device data set to: {parameters['devices']}")
        present_line(f"Traffic source data set to: {parameters['traffic_source']}")
        present_line(f"Limit for clicks set to: {parameters['clicks']}")
        present_line(f"Limit for page views set to: {parameters['page_views']}")
        present_line(f"Conversion rate set to: {parameters['conversion_rate']}")


    def get_parameters(self) -> dict[str, int | str | list[str]]:
        """
        Uses helper methods to gather parameters to generate a dataset.

        Methods used to gather parameter:
            get_number_of_records_needed()
            get_number_of_campaigns_needed()
            get_timeframe()
            get_location()
            get_devices()
            get_clicks_range()
            get_page_visit_range()
            get_traffic_source()

        Asks user to confirm current parameters, using confirm_parameters().

        :return: a dictionary containing all parameters.
        """
        parameters = dict()
        while True:
            present_line("Please enter parameters.")

            parameters["records"] = self._get_number_of_records_needed()
            parameters["campaigns"] = self._get_number_of_campaigns_needed()
            parameters["timeframe"] = self._get_timeframe()
            parameters["location"] = self._get_location()
            parameters["devices"] = self._get_devices()
            parameters["clicks"] = self._get_clicks_range()
            parameters["page_views"] = self._get_page_visit_range()
            parameters["traffic_source"] = self._get_traffic_source()
            parameters["conversion_rate"] = self._get_conversion_rate()

            # Ask user to agree to current parameters
            if self._confirm_parameters(parameters): # User agrees -> continue to next phase
                present_line("Parameters accepted.")
                break
            else: # User disagrees -> restart program
                present_line("Please input new parameters.")

        return parameters

    def test_parameters(self) -> dict[str, int | str | tuple[datetime]]:
        """
        Method contract to be included
        :return:
        """
        timeframe = (datetime.strptime("01-01-2001", DATE_FORMAT), datetime.strptime("01-08-2002", DATE_FORMAT))
        parameters = dict()
        parameters["records"] = 100000
        parameters["campaigns"] = 3
        parameters["timeframe"] = timeframe
        parameters["location"] = 10
        parameters["devices"] = 10
        parameters["clicks"] = 25
        parameters["page_views"] = 15
        parameters["traffic_source"] = 5
        parameters["conversion_rate"] = 0.85

        return parameters

    def update_parameters(self, args) -> dict[str, int | str | tuple[datetime]]:
        """
        Method contract to be included
        :param args:
        :return:
        """
        # DEBATEABLE: standard update to today from last day read from state.
        timeframe = (datetime.strptime(args.timeframe[0], DATE_FORMAT), datetime.strptime(args.timeframe[1], DATE_FORMAT))
        print(timeframe)
        parameters = dict()
        parameters["records"] = args.records
        parameters["campaigns"] = args.campaigns
        parameters["timeframe"] = timeframe
        parameters["location"] = args.location
        parameters["devices"] = args.devices
        parameters["clicks"] = args.clicks
        parameters["page_views"] = args.page_views
        parameters["traffic_source"] = args.traffic_source
        parameters["conversion_rate"] = self._validate_float(args.conversion_rate)

        return parameters

    def json_parameters(self, file: str):
        """
        Method contract to be included
        :param args:
        :return:
        """
        import json

        keys = {
            "records",
            "campaigns",
            "timeframe",
            "location",
            "devices",
            "clicks",
            "page_views",
            "traffic_source",
            "conversion_rate"
        }

        # Opening JSON file
        with open(file) as json_file:
            data: dict = json.load(json_file)

            # Validate all keys exist
            data_keys = set(data.keys())
            if data_keys != keys:
                if keys.issubset(data_keys):
                    invalid = data_keys.difference(keys)
                    raise Exception(f"Invalid keys are present. Invalid keys: {invalid}")
                else:
                    missing = keys.difference(data_keys)
                    raise Exception(f"Not all keys are present. Missing keys: {missing}")

            # Validate all keys have correct data type
            for key in keys:
                # Skip timeframe
                if key == "timeframe": continue
                if key == "conversion_rate": 
                    data[key] = self._validate_float(data[key])
                else: 
                    data[key] = self._validate_int(data[key])

            data['timeframe'] = tuple(datetime.strptime(date, DATE_FORMAT) for date in data['timeframe'])

            start_date, end_date = data['timeframe']
            if not start_date < end_date:
                raise Exception(f"Timeframe is not sorted, \
                                {start_date.strftime(DATE_FORMAT)} is a date after {end_date.strftime(DATE_FORMAT)}.")

        return data
