from datetime import datetime, timedelta
import argparse

from src.parameters import ParameterInputHandler
from src.generator import DataGenerator

from src.utils import present_line, DATE_FORMAT


"""
##############################################
        HANDLE SCENARIOS
##############################################
"""

MAX_RECORDS = 10_000_000

def scenario_handler(args) -> dict[str, int | str | tuple[datetime]]:
    """
    Method contract to be included

    :param args: list of arguments.
    :return: dictionary of parameters.
    """
    param_handler = ParameterInputHandler(max_records=MAX_RECORDS)

    # Create dataset with presets
    if args.method == "test":
        present_line("Generating test data.")
        parameters = param_handler.test_parameters()
    elif args.method == "update":
        present_line("Generating update data.")
        try:
            parameters = param_handler.update_parameters(args)
        except:
            present_line("Something went wrong processing the arguments.\n"
                            "Please try again.")
            exit(1)
    elif args.parameter_file:
        present_line("Fetching data from parameter file..")
        try:
            parameters = param_handler.json_parameters(args.parameter_file)
        except Exception as e:
            present_line("Something went wrong processing the arguments.\n" \
            "Please check your parameter file and try again. See message below for details:\n")
            present_line(e)
            exit(1)
    # Create step-by-step custom dataset
    else:
        try:
            parameters = param_handler.get_parameters()
        except Exception as e:
            print(e)
            present_line("It is unclear what you did, "
                            "but you managed to break the programs ability to gather information.")
            present_line("Start over and this time do it right, please.")
            exit(1)

    return parameters


"""
##############################################
        EXECUTE PROGRAM
##############################################
"""

def range_check(low, high = None):
    """
    Return function handle of an argument type function for 
    ArgumentParser checking a int range: low <= arg <= high

    :param low: minimum acceptable argument value
    :param high: maximum acceptable argument value
    """

    # Define the function with default arguments
    def int_range_checker(arg):
        try:
            f = int(arg)
        except ValueError:
            raise argparse.ArgumentTypeError("Value must be an integer")
        if f < low or (high and f > high):
            raise argparse.ArgumentTypeError("Value must be in range [" + str(low) + " .. " + str(high)+"]")
        return f

    return int_range_checker

def help_handler():
    parser = argparse.ArgumentParser(
        prog="Dataset generator Sales Dashboard",
        description="""
            Scripts can be run in 4 scenario's: 
                1. Create a custom dataset
                    Execute the script without any arguments.
                2. Get a dataset for 1 day, to update existing data.
                    Execute the script with arguments:
                        'update' to set the update scenario
                        int for the number of records
                        int for the number of campaigns
                        int for the number of locations
                        int for the number of devices
                        int for the number of clicks
                        int for the number of page views
                        int for the number of traffic sources
                    Example: Python .\\generate_dataset.py --update -r 1000 -c 3 -t 20-03-2026 -l 10 -d 10 -cl 25 -pv 15 -ts 5
                3.  Generate a quick dataset for testing or sample data.
                    Execute the script with 'test' as argument.
                    Example: Python .\\generate_dataset.py test
                4.  Generate a quick dataset with sample data from a json file
                    Execute with -p flag
                    Example: Python .\\generate_dataset.py -p "parameter_file.json"
            """, 
            formatter_class=argparse.RawDescriptionHelpFormatter
        )
    
    parser.add_argument('-p', '--parameter_file', required=False, help="File where parameters are stored.")
    
    subparsers = parser.add_subparsers(dest='method', required=False)
    test_parser = subparsers.add_parser('test', help='Generate a quick dataset for testing or sample data.', 
                                        description="""
                                        Generate a quick dataset for testing or sample data.
                                        Execute the script with 'test' as argument.
                                        Example: Python .\\generate_dataset.py test
                                        """, formatter_class=argparse.RawDescriptionHelpFormatter)
    tstsub_parser = test_parser.add_subparsers(dest='command')
    tstsub_parser.add_parser('increment')
    update_parser = subparsers.add_parser('update', help='Get a dataset for 1 day, to update existing data.', description="""
                                        Get a dataset for 1 day, to update existing data.
                                        Execute the script with parameters.
                                        Example: Python .\\generate_dataset.py update -r 1000 -c 3 -t 20-03-2026 -l 10 -d 10 -cl 25 -pv 15 -ts 5
                                        """, formatter_class=argparse.RawDescriptionHelpFormatter)
    
    update_parser.add_argument('-r', '--records', required=True, default=100000, type=range_check(1, MAX_RECORDS),
                               help="Number of records to generate.")
    update_parser.add_argument('-c', '--campaigns', required=True, default=3, type=range_check(1, 10),
                               help="Number of campaigns to run")
    # update_parser.add_argument('-t', '--timeframe', required=True, default="02-08-2002", type=timeframe_validation(),
    #                            help="Date to update records to")
    update_parser.add_argument('-l', '--location', required=True, default=10, type=range_check(1),
                               help="Number of locations.")
    update_parser.add_argument('-d', '--devices', required=True, default=10, type=range_check(1, 100),
                               help="Number of devices.")
    update_parser.add_argument('-cl', '--clicks', required=True, default=25, type=range_check(1),
                               help="Number of clicks.")
    update_parser.add_argument('-pv', '--page_views', required=True, default=15, type=range_check(1),
                               help="Number of page_views.")
    update_parser.add_argument('-ts', '--traffic_source', required=True, default=5, type=range_check(1, 50),
                               help="Number of traffic_sources.")
    update_parser.add_argument('-cr', '--conversion_rate', required=False, default=0.85,
                               help="Percentage of sessions leading to conversion.")
    update_parser.add_argument('-f', '--input_file', required=False, default='generated_dataset.txt',
                               help="Input file.")
    args = parser.parse_args()
    return args

def main():
    args = help_handler()

    try:
        parameters = scenario_handler(args)
    except KeyboardInterrupt:
        present_line("\n\nCtrl+C detected, closing program..")
        exit(1)

    update = args.method == 'update'
    generator = DataGenerator(update=update) # optional: DataGenerator(seed=42, day_preference=True)

    # Generate data
    if args.command == 'increment':
        records = generator.generate_incremental(parameters)
    else:
        records = generator.generate_data(parameters)
    try:
        pass
    except KeyboardInterrupt:
        present_line("\n\nCtrl+C detected, data generation stops..")
        exit(1)
    except Exception as e:
        present_line(f"Data generation failed with the following error: {e}")
        present_line("\nIt is unclear what happened, "
              "but it appears the generation of data broke down,\n"
              "and might have resulted in the destruction of some cities.\n")
        present_line("Be proud of what you did, but please try again and do it right this time.")
        exit(1)

    try:
        if not args.command == 'increment':
            generator.save_data(records, 'generated_dataset.txt', date_format="%d-%m-%Y %H:%M")
    except KeyboardInterrupt:
        present_line("\n\nCtrl+C detected, data saving stops..")
        exit(1)
    except Exception:
        present_line("Something went wrong saving the data.")
        exit(1)

if __name__ == '__main__':
    main()
