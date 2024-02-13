import locale
from datetime import datetime, timedelta
import itertools
import dateutil
import dateutil.parser


def check_keyword_exists(data, keyword):
    if isinstance(data, dict):
        if keyword in data:
            return True
        return any(check_keyword_exists(value, keyword) for value in data.values())
    elif isinstance(data, list):
        return any(check_keyword_exists(value, keyword) for value in data)
    else:
        return False


def get_number_type(s):
    # Don't know if a European number or US
    locale.setlocale(locale.LC_ALL, "en_US.UTF-8")

    try:
        return int(s)
    except (ValueError, TypeError):
        try:
            return locale.atof(s)
        except (ValueError, TypeError):
            return s


def get_aix_wacky_numbers(s):
    try:
        return int(s)
    except (ValueError, TypeError):
        try:
            if "K" in s:
                value = s.split("K")[0]
                return int(float(value) * 1000)
            elif "M" in s:
                value = s.split("M")[0]
                return int(float(value) * 1000000)
            elif "S" in s:
                value = s.split("S")[0]
                return int(float(value) * 1000)
            return locale.atof(s)
        except (ValueError, TypeError):
            return s


def format_date(known_datetime, date_str):
    """
    :param known_datetime: The known datetime object to use as a reference for formatting.
    :param date_str: The date string to format.
    :return: The formatted date string.

    The `format_date` method takes a known datetime object and a date string as parameters.
    It returns a formatted date string.

    The method converts the known datetime to a date object and splits the date string into
    day, month, and year components. It generates all permutations of the components and iterates over each permutation.

    For each permutation, it checks if the year is two digits and adds 2000 to get the four digit year.
    It then validates the day, month, and year.

    If the day, month, and year are valid, it creates a date object using the permutation.
    If the generated date is within 24 hours of the known date, it returns the formatted date string
    in the format "%Y/%m/%d".

    If no valid date is found, it defaults to returning the string "2000/12/01".
    """
    # Convert known_datetime to date
    known_date = known_datetime.date()

    # Split the date string into components and convert to int
    dmy = list(map(int, date_str.split("/")))

    # Generate all permutations of the day/month/year
    permutations = list(itertools.permutations(dmy))

    for perm in permutations:
        day, month, year = perm

        # If year is two digits, add 2000 to get the four digit year
        if year < 100:
            year += 2000

        # Validate day, month, year
        if day > 31 or month > 12 or year < known_date.year:
            continue

        try:
            # Create date object for current permutation
            perm_date = datetime(year=year, month=month, day=day).date()
        except ValueError:
            # Skip this permutation and move on to the next if this is not a valid date
            continue

        # If perm_date is within 24 hours of known_date, return it
        if abs(perm_date - known_date).days <= 1:
            return perm_date.strftime("%Y/%m/%d")

    # Default to 1 Dec 2000 if no valid date found - at least you will get a chart
    return "2000/12/01"
