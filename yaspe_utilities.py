import locale
from datetime import datetime
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


def check_date(section, run_start_date, date_to_check):
    # print(f"{section} Known start date {run_start_date} Date to check {date_to_check}")
    # print(f"Known start month = {run_start_date.month}")
    # print(f"Date to check month = {dateutil.parser.parse(date_to_check).month}")

    if int(date_to_check[:2]) > 2000:
        print(f"{section} Check date format (yyyy/xx/xx?): {date_to_check}")
        return False

    if run_start_date.month != dateutil.parser.parse(date_to_check).month:
        print(f"{section} month convert dd/mm/yy date to mm/dd/yy {date_to_check} > {make_mdy_date(date_to_check)}")
        return True

    if int(date_to_check[:2]) > 12:
        print(f"{section} convert dd/mm/yy date to mm/dd/yy {date_to_check} > {make_mdy_date(date_to_check)}")
        return True
    else:
        delta = run_start_date - dateutil.parser.parse(date_to_check)

        if delta.days > 1:
            print(f"{section} convert dd/mm/yy date to mm/dd/yy {date_to_check}  > {make_mdy_date(date_to_check)}")
            return True

    return False


def make_mdy_date(date_in):
    # Flip ambiguous dd/mm/yyyy dates eg. 09/11/2021 where 11 is in fact Nov not Sept.
    # Default dates in charting usually fall in to expecting mm/dd/yyyy format

    # Input is a date string. Can be any legal format, returns a datetime.datetime object
    date_parsed = dateutil.parser.parse(date_in)

    # Output date_in.date() will be %Y-%m-%d, eg 2021-09-11 - plan is to flip the month and day eg output 11/09/2021
    # date_out = datetime.strptime(str(date_in.date()), "%Y-%m-%d").strftime("%d/%m/%Y")
    day = datetime.strptime(str(date_parsed.date()), "%Y-%m-%d").strftime("%d")
    month = datetime.strptime(str(date_parsed.date()), "%Y-%m-%d").strftime("%m")
    year = datetime.strptime(str(date_parsed.date()), "%Y-%m-%d").strftime("%Y")

    if int(date_in[:2]) > 12:
        date_out = f"{month}/{day}/{year}"
    else:
        date_out = f"{day}/{month}/{year}"

    return date_out
