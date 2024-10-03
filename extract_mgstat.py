import pandas as pd
from yaspe_utilities import get_number_type, get_aix_wacky_numbers, format_date


def extract_mgstat(input_file, html_filename):
    input_file = f"{input_file}.mgst"

    mgstat_header = ""
    mgstat_rows_list = []

    with open(input_file, "r", encoding="ISO-8859-1") as file:
        for line in file:
            if mgstat_header != "":
                if line.strip() != "":
                    mgstat_row_dict = {}
                    values = line.split(",")
                    values = [i.strip() for i in values]  # strip off carriage return etc
                    # Convert integers or real from strings if possible
                    values_converted = [get_number_type(v) for v in values]
                    # create a dictionary of this row and append to a list of row dictionaries for later add to table
                    mgstat_row_dict = dict(zip(mgstat_columns, values_converted))
                    # Add the file name
                    mgstat_row_dict["html name"] = html_filename

                    # Added for pretty processing
                    mgstat_row_dict["datetime"] = f'{mgstat_row_dict["Date"]} {mgstat_row_dict["Time"]}'
                    mgstat_rows_list.append(mgstat_row_dict)
            if "Glorefs" in line:
                mgstat_header = line
                mgstat_columns = mgstat_header.split(",")
                mgstat_columns = [i.strip() for i in mgstat_columns]  # strip off carriage return etc
            if "globalbuffers" in line:
                # Replace commas with newlines
                mgstat_text_description = line.replace(",", "\n")
                # aixappvk1_MHSAPP_20240917_0956.mgst,
                # MGSTATv2.9a,
                # wdcycle=40^10^80^4,
                # globalbuffers=18432MB:0^0^18432^0^0^0,
                # routinebuffers=1021MB:0^127^0^383^0^511,
                # numberofcpus=16:PowerPC^1^2,
                # productversion=IRIS for UNIX (IBM AIX for System Power System-64 OpenSSL 3.0) 2024.1 (Build 267_2U) Tue Apr 30 2024 16:10:42 EDT

    if mgstat_header != "":
        # Create dataframe of rows. Shortcut here to creating table columns or later charts etc
        mgstat_df = pd.DataFrame(mgstat_rows_list)

        # "date" and "time" are reserved words in SQL. Rename the columns to avoid clashes later.
        mgstat_df.rename(columns={"Date": "RunDate", "Time": "RunTime"}, inplace=True)

        # Remove any rows with NaN
        mgstat_df.dropna(inplace=True)

    else:
        mgstat_df = pd.DataFrame({"empty": []})
        text_description = ""

    return mgstat_df, mgstat_text_description
