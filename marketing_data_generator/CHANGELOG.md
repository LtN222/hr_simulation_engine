# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Limitations (PoC)
- Country set to Netherlands
- Total visit duration is only in whole minutes
- Conversion is limited to 1/0 (yes or no)

### Known Bugs
- Crashes when given timeframe of 1 date (most likely due to the trend logic)
- Current trend is too weak:
  - Ceiling of click range is reached in every month, should be lower for visibility
  - Current floor of click range rises too slow
  - Either the ceiling should drop at start and grow with trend, or floor should grow faster in the beginning
  - Traffic source of 1 option should be included in trend (number of clicks is on site elements; traffic source accounts for 'clicks on ad')
  - Number of sessions should grow over time (purpose of a marketing campaign is to attract visitors, so number of sessions should increase over time; not just clicks on site)

### Suggestions for Future Versions
- **Structure** (Approved, included in planning): Split generate_data() logic into helper methods **ADDED**
- **Optimization** (up for debate): Use Numpy and Pandas in generate_data() for more control and efficiency (allows for correlations, skewness, trends etc.) **ADDED**
- **Deterministic Result** (up for debate): Base results on a generator seed, to recreate result if needed **ADDED**
- **Framework** (up for debate): Switch to OOP (might be overkill for this use case); split methods into separate files (requires extra install steps for user) **ADDED**
- **Update Functionality** (up for debate): Remove update functionality (regenerate); read input trend and extrapolate
- **Error Handling** (up for debate): Include python error message in error message, or something more human readable but more explicit then what it is now

### Planning
- **Version 0.11**: Continue trend in 'update' scenario (current trend only works from first to last day for each execution; meaning there will be no measurable trend for any 1 day execution used to generate update data)
- **Version 0.11**: Redesign trend logic
- **Version 1.0**: Complete documentation
- **Version 1.1**: Implement trend in generated data

## [0.10] - 2026-03-24

### Added
- Campaign logic added to trend generation
- Option to read parameter values from JSON file (needs validation)
- Conversion rate parameter
- Seed for random generation
- Possibility for day preference per campaign

### Changed
- Trend logic changed using numpy to generate linear trend with noise
- Created helper functions for data generation
- Moved presentation sugar to utils file
- Refactored random numpy generation from `numpy.random.random()` to `numpy.random.default_rng()`
- Moved generator logic to generator file
- Maximum number of records moved to variable

## [0.9] - 2026-03-XX

### Added
- Numpy trend generation for 3 times speed improvement

### Changed
- Expanded session time to include minutes through datetime object
- Validation through datetime object
- Argument parsing via argparse
- Parameter user input for custom dataset moved to class

### Fixed
- Session dates not in chronological order

## [0.8] - 2026-02-XX

### Added
- Option to run script with test argument for quick testing or generate sample data (no prompts)
- Option to run script with arguments to generate update data (no prompts)
- Simple/dirty logic to include a trend (linear trend over whole runtime)

### Changed
- Switch positions of campaign_ID and session_ID in output file
- Column names translated to Dutch
- Change locations output to INT
- Add prompt for number of locations
- Make page views depended on clicks
- Change devices output to INT
- Add prompt for number of devices

### Fixed
- Data generation fails if start date == end date
- Remove limits on parameters, except for get_number_of_records_needed()
- Campagne_ID not showing in first records

## [0.7] - 2026-02-XX

### Changed
- Random date logic to use Pandas and Numpy
- Timeframe from month to specific date (include change in prompt)

### Added
- Date input validation

## [0.6] - 2026-02-XX

### Changed
- Logic in generate_data() redesigned for stability
- Delay for all print statements for readability

### Fixed
- Logic for random date_day allows the generation of a day in the future

## [0.5] - 2026-02-XX

### Changed
- `random.random()` to `random.randint()` in generate_data()

## [0.4] - 2026-02-XX

### Added
- Traffic source labels
- Devices labels

### Changed
- Parts of session date in separate columns

## [0.3] - 2026-02-XX

### Added
- Click range method
- Page visit range method
- Range for clicks - input
- Range for page views - input

## [0.2] - 2026-02-XX

### Added
- Sanity check: Check if number of column names for first line in output file to be the same as number of columns for data
- Method contracts
- Type annotations for methods

### Fixed
- When timeframe > current month, year can only be 2025

## [0.1] - 2026-02-20

Initial release (PoC).

### Added
- Basic dataset generation functionality
- Author: Joshua Mallee (joshua.mallee@heeyoo.nl)
