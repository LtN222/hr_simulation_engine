from datetime import datetime
import argparse

from src.parameters import ParameterInputHandler
from src.generator.historical_generator import HistoricalGenerator
from src.generator.incremental_generator import IncrementalGenerator

from src.utils import present_line
import utils


"""
##############################################
        HANDLE SCENARIOS
##############################################
"""

MAX_RECORDS = 10_000_000

def scenario_handler(args) -> dict[str, int | str | tuple[datetime]]:
    """
    Handle the different possible scenarios and get the appropiate parameters.

    :param args: list of arguments.
    :return: dictionary of parameters.
    """
    param_handler = ParameterInputHandler(max_records=MAX_RECORDS)

    # Create dataset with presets
    if args.method == "test":
        present_line("Generating test data.")
        parameters = param_handler.test_parameters()
    elif args.method == "update": parameters = {}
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

def help_handler():
    """
    Parses the arguments and provides a help documentation.

    :returns: argument namespace containing parsed argument options.
    """
    parser = argparse.ArgumentParser(
        prog="Dataset generator Sales Dashboard",
        description="""
            Scripts can be run in 4 scenario's: 
                1.  Create a custom dataset
                    Execute the script without any arguments.
                2.  Update the dataset up to today, to update existing data.
                    Example: Python .\\generate_dataset.py update
                3.  Generate a quick dataset for testing or sample data.
                    Execute the script with 'test' as argument.
                    Example: Python .\\generate_dataset.py test
                4.  Generate an historical dataset with sample data from a json file
                    Execute with -p flag
                    Example: Python .\\generate_dataset.py -p "parameter_file.json"
            """, 
            formatter_class=argparse.RawDescriptionHelpFormatter
        )
    
    parser.add_argument('-p', '--parameter_file', required=False, help="File where parameters are stored.")
    parser.add_argument('-o', '--output_file', required=False, default='generated_dataset.csv', help='File to store generated data to')

    subparsers = parser.add_subparsers(dest='method', required=False)
    test_parser = subparsers.add_parser('test', help='Generate a quick dataset for testing or sample data.', 
                                        description="""
                                        Generate a quick dataset for testing or sample data.
                                        Execute the script with 'test' as argument.
                                        Example: Python .\\generate_dataset.py test
                                        """, formatter_class=argparse.RawDescriptionHelpFormatter)
    update_parser = subparsers.add_parser('update', help='Update the dataset to today.', description="""
                                        Update existing dataset to today.
                                        Execute the script with parameters.
                                        Example: Python .\\generate_dataset.py update
                                        """, formatter_class=argparse.RawDescriptionHelpFormatter)
    update_parser.add_argument('-i', '--input_file', required=False, default='generated_dataset.csv', help='Starting point for updated data')

    args = parser.parse_args()
    return args

def main():
    seed = 42
    days_bias = True

    args = help_handler()

    # Fetch generation parameters
    try:
        parameters = scenario_handler(args)
    except KeyboardInterrupt:
        present_line("\n\nCtrl+C detected, closing program..")
        exit(1)

    update = args.method == 'update'
    if update:
        generator = IncrementalGenerator(seed=seed, day_bias=days_bias)
    else:
        generator = HistoricalGenerator(parameters, seed=seed, day_bias=days_bias)

    # Generate data
    try:
        records = generator.generate()
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

    # Save data and state
    try:
        generator.save_data(records, args.output_file, date_format="%d-%m-%Y %H:%M")
    except KeyboardInterrupt:
        present_line("\n\nCtrl+C detected, data saving stops..")
        exit(1)
    except Exception as e:
        present_line("Something went wrong saving the data.")
        present_line(f"See below for details: \n\n {e}")
        exit(1)

if __name__ == '__main__':
    main()
