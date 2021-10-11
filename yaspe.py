#!/usr/bin/env python3
"""
Extract sections of SystemPerformance file to SQL table.
Chart the results


"""
import sp_check

import argparse
import locale
import os

from datetime import datetime
import dateutil.parser

# from altair_saver import save
import sqlite3
import sys
from sqlite3 import Error

import altair as alt
import pandas as pd

# Altair
# Max is 5,000 rows by default
alt.data_transformers.disable_max_rows()


def create_connection(path):
    connection = None
    try:
        connection = sqlite3.connect(path)
    except Error as e:
        print(f"The error '{e}' occurred")

    return connection


def execute_simple_query(connection, query):
    cursor = connection.cursor()
    try:
        cursor.execute(query)
        connection.commit()
    except Error as e:
        if "duplicate column name" in str(e):
            # A bit of a kludge, there are cases where mgstat adds columns on different days
            # So if append option dont assume all the columns exist
            pass
        else:
            print(f"The error '{e}' occurred")


def execute_read_query(connection, query):
    cursor = connection.cursor()
    result = None
    try:
        cursor.execute(query)
        result = cursor.fetchall()
        return result
    except Error as e:
        print(f"The error '{e}' occurred")


def execute_single_read_query(connection, query):
    cursor = connection.cursor()
    result = None
    try:
        cursor.execute(query)
        result = cursor.fetchone()
        return result
    except Error as e:
        print(f"The error '{e}' occurred")


def data_types_map(df):
    row = 0
    data_types = {}
    for _, val in df.dtypes.iteritems():
        data_types[row] = val
        row += 1
    return data_types


def create_generic_table(connection, table_name, df):
    # Build the table, headings can vary depending on OS or Caché or IRIS version or other reasons.
    create_table = f"CREATE TABLE IF NOT EXISTS {table_name} (id_key INTEGER PRIMARY KEY AUTOINCREMENT);"
    execute_simple_query(connection, create_table)

    # Loop through and create the rest of the columns based on data type
    # Create a map of the data types
    data_types = data_types_map(df)

    columns = list(df)
    row = 0

    for column in columns:
        if data_types[row] == "int64":
            q = f"ALTER TABLE {table_name} ADD COLUMN '{column}' INTEGER;"
        elif data_types[row] == "float64":
            q = f"ALTER TABLE {table_name} ADD COLUMN '{column}' REAL;"
        else:
            q = f"ALTER TABLE {table_name} ADD COLUMN '{column}' CHAR(30);"

        execute_simple_query(connection, q)
        row += 1


def insert_dict_into_table(connection, table_name, _dict):
    # Make sure not an empty  line
    if _dict:
        keys = ", ".join('"' + item + '"' for item in _dict)
        question_marks = ",".join(list("?" * len(_dict)))
        values = tuple(_dict.values())

        connection.execute(f"INSERT INTO {table_name} ({keys}) VALUES ({question_marks})", values)


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


def create_sections(connection, input_file, include_iostat, html_filename, csv_out, output_filepath_prefix):
    vmstat_processing = False
    vmstat_header = ""
    vmstat_rows_list = []

    iostat_processing = False
    iostat_header = ""
    iostat_rows_list = []
    iostat_device_block_processing = False
    iostat_am_pm = False
    iostat_date_included = False

    mgstat_processing = False
    mgstat_header = ""
    mgstat_rows_list = []

    perfmon_processing = False
    perfmon_header = ""
    perfmon_rows_list = []

    operating_system = execute_single_read_query(
        connection, "SELECT * FROM overview WHERE field = 'operating system';"
    )[2]

    with open(input_file, "r", encoding="ISO-8859-1") as file:

        for line in file:
            if "<!-- beg_mgstat -->" in line:
                mgstat_processing = True
            if "<!-- end_mgstat -->" in line:
                mgstat_processing = False
            if mgstat_processing and mgstat_header != "":
                mgstat_row_dict = {}
                values = line.split(",")
                values = [i.strip() for i in values]  # strip off carriage return etc
                # Convert integers or real from strings if possible
                values_converted = [get_number_type(v) for v in values]
                # create a dictionary of this row and append to a list of row dictionaries for later add to table
                mgstat_row_dict = dict(zip(mgstat_columns, values_converted))
                # Add the file name
                mgstat_row_dict["html name"] = html_filename
                mgstat_rows_list.append(mgstat_row_dict)
            if mgstat_processing and "Glorefs" in line:
                mgstat_header = line
                mgstat_columns = mgstat_header.split(",")
                mgstat_columns = [i.strip() for i in mgstat_columns]  # strip off carriage return etc

            if operating_system == "Linux" or operating_system == "Ubuntu":
                if "<!-- beg_vmstat -->" in line:
                    vmstat_processing = True
                if "<!-- end_vmstat -->" in line:
                    vmstat_processing = False
                if vmstat_processing and vmstat_header != "":
                    vmstat_row_dict = {}
                    values = line.split()
                    values = [i.strip() for i in values]  # strip off carriage return etc
                    values_converted = [get_number_type(v) for v in values]
                    vmstat_row_dict = dict(zip(vmstat_columns, values_converted))
                    vmstat_row_dict["html name"] = html_filename
                    vmstat_rows_list.append(vmstat_row_dict)
                if vmstat_processing and "us sy id wa" in line:
                    # vmstat has column names on same line as html
                    vmstat_header = line.split("<pre>")[1].strip()
                    vmstat_header = vmstat_header.split(" r ")[1]
                    vmstat_header = f"Date Time r {vmstat_header}"
                    vmstat_columns = vmstat_header.split()
                    vmstat_columns = [i.strip() for i in vmstat_columns]  # strip off carriage return etc

            if operating_system == "Windows":
                if "id=perfmon" in line:
                    perfmon_processing = True
                if "<!-- end_win_perfmon -->" in line:
                    perfmon_processing = False
                if perfmon_processing and perfmon_header != "":
                    perfmon_row_dict = {}
                    values = line.split(",")
                    values = [i.strip() for i in values]  # strip off carriage return etc
                    values = list(map(lambda x: x[1:-1].replace('"', ""), values))
                    values = list(map(lambda x: 0.0 if x == " " else x, values))
                    values_converted = [get_number_type(v) for v in values]
                    perfmon_row_dict = dict(zip(perfmon_columns, values_converted))
                    perfmon_row_dict["html name"] = html_filename
                    perfmon_rows_list.append(perfmon_row_dict)
                if perfmon_processing and "Memory" in line:
                    perfmon_header = line
                    # get rid of characters that screw with queries or charting
                    perfmon_header = [s for s in perfmon_header if s.isalnum() or s.isspace() or (s == ",")]
                    perfmon_header = "".join(perfmon_header)
                    perfmon_header = perfmon_header.replace(" ", "_")

                    perfmon_columns = perfmon_header.split(",")
                    perfmon_columns = [i.strip() for i in perfmon_columns]  # strip off carriage return etc

            # iostat has a lot of variations, start as needed
            if (operating_system == "Linux" or operating_system == "Ubuntu") and include_iostat:

                if iostat_processing and "<div" in line:  # iostat does not flag end
                    iostat_processing = False
                else:
                    # Found iostat
                    if "id=iostat" in line:
                        iostat_processing = True
                    # Is there a date and time line (not in some cases)
                    if iostat_processing and len(line.split()) == 2:
                        # If a date is found then device block ended
                        iostat_device_block_processing = False
                        iostat_date_included = True
                        date_time = line.strip()
                    if iostat_processing and len(line.split()) == 3:  # date time AM
                        iostat_am_pm = True
                        # If a date is found then device block ended
                        iostat_device_block_processing = False
                        iostat_date_included = True
                        date_time = line.strip()
                    # If there is no date then this is the next likely header, device block ended
                    if "avg-cpu" in line:
                        iostat_device_block_processing = False
                    # Add devices to database
                    if iostat_processing and iostat_device_block_processing and iostat_header != "":
                        iostat_row_dict = {}
                        # if European "," for ".", do that first
                        line = line.replace(",", ".")
                        # get rid of multiple whitespaces, then use comma separator so the AM/PM is preserved if its there
                        line = " ".join(line.split())
                        line = line.replace(" ", ",")
                        if iostat_date_included:
                            if iostat_am_pm:
                                line = (
                                        date_time.split()[0]
                                        + ","
                                        + date_time.split()[1]
                                        + " "
                                        + date_time.split()[2]
                                        + ","
                                        + line
                                )
                            else:
                                line = date_time.split()[0] + "," + str(date_time.split()[1]) + "," + line
                        values = line.split(",")
                        values = [i.strip() for i in values]  # strip off carriage return etc
                        values_converted = [get_number_type(v) for v in values]
                        iostat_row_dict = dict(zip(iostat_columns, values_converted))
                        iostat_row_dict["html name"] = html_filename
                        iostat_rows_list.append(iostat_row_dict)
                    # Header line found, next line is start of device block
                    if "Device" in line:
                        iostat_device_block_processing = True
                    # First time in create column names
                    if iostat_processing and iostat_header == "" and "Device" in line:
                        if iostat_date_included:
                            iostat_header = f"Date Time {line}"
                        else:
                            iostat_header = f"{line}"
                        iostat_header = iostat_header.replace(":", "")  # "Device:" used later on logic
                        iostat_columns = iostat_header.split()
                        iostat_columns = [i.strip() for i in iostat_columns]  # strip off carriage return etc

    # Add each section to the database

    if mgstat_header != "":
        # Create dataframe of rows. Shortcut here to creating table columns or later charts etc
        mgstat_df = pd.DataFrame(mgstat_rows_list)
        # Remove any rows with NaN
        mgstat_df.dropna(inplace=True)

        # Want to just dump a dataframe to a table and avoid all the roll-your-own steps ;)
        # SQLAlchemy is included in pandas
        #
        # conn = sqlite3.connect('SystemPerformance.sqlite')
        # mgstat_df.to_sql('mgstat', conn, if_exists='replace', index=False)
        #
        # else create the table and load data as below

        create_generic_table(connection, "mgstat", mgstat_df)

        # Add the rows to the table, loop through the list of dictionaries
        for row in mgstat_rows_list:
            insert_dict_into_table(connection, "mgstat", row)

        connection.commit()

        if csv_out:
            mgstat_output_csv = f"{output_filepath_prefix}mgstat.csv"

            # if file does not exist write header
            if not os.path.isfile(mgstat_output_csv):
                mgstat_df.to_csv(mgstat_output_csv, header='column_names', index=False, encoding='utf-8')
            else:  # else it exists so append without writing the header
                mgstat_df.to_csv(mgstat_output_csv, mode='a', header=False, index=False, encoding='utf-8')

    if vmstat_header != "":
        vmstat_df = pd.DataFrame(vmstat_rows_list)
        vmstat_df.dropna(inplace=True)

        create_generic_table(connection, "vmstat", vmstat_df)
        for row in vmstat_rows_list:
            insert_dict_into_table(connection, "vmstat", row)
        connection.commit()

        if csv_out:
            vmstat_output_csv = f"{output_filepath_prefix}vmstat.csv"

            # if file does not exist write header
            if not os.path.isfile(vmstat_output_csv):
                vmstat_df.to_csv(vmstat_output_csv, header='column_names', index=False, encoding='utf-8')
            else:  # else it exists so append without writing the header
                vmstat_df.to_csv(vmstat_output_csv, mode='a', header=False, index=False, encoding='utf-8')

    if perfmon_header != "":
        perfmon_df = pd.DataFrame(perfmon_rows_list)
        perfmon_df.dropna(inplace=True)
        create_generic_table(connection, "perfmon", perfmon_df)
        for row in perfmon_rows_list:
            insert_dict_into_table(connection, "perfmon", row)
        connection.commit()

        if csv_out:
            perfmon_output_csv = f"{output_filepath_prefix}vmstat.csv"

            # if file does not exist write header
            if not os.path.isfile(perfmon_output_csv):
                perfmon_df.to_csv(perfmon_output_csv, header='column_names', index=False, encoding='utf-8')
            else:  # else it exists so append without writing the header
                perfmon_df.to_csv(perfmon_output_csv, mode='a', header=False, index=False, encoding='utf-8')

    if iostat_header != "":
        iostat_df = pd.DataFrame(iostat_rows_list)
        iostat_df.dropna(inplace=True)
        create_generic_table(connection, "iostat", iostat_df)
        for row in iostat_rows_list:
            insert_dict_into_table(connection, "iostat", row)
        connection.commit()
        if csv_out:
            iostat_output_csv = f"{output_filepath_prefix}iostat.csv"

            # if file does not exist write header
            if not os.path.isfile(iostat_output_csv):
                iostat_df.to_csv(iostat_output_csv, header='column_names', index=False, encoding='utf-8')
            else:  # else it exists so append without writing the header
                iostat_df.to_csv(iostat_output_csv, mode='a', header=False, index=False, encoding='utf-8')


def create_overview(connection, sp_dict):
    cursor = connection.cursor()

    create_overview_table = """
    CREATE TABLE IF NOT EXISTS overview (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      field TEXT NOT NULL,
      value TEXT
    );
    """

    execute_simple_query(connection, create_overview_table)

    # Create the insert query string
    for key in sp_dict:
        cursor.execute("INSERT INTO overview (field, value) VALUES (?, ?)", (key, sp_dict[key]))
        connection.commit()

    return


def linked_chart(data, column_name, title, max_y, filepath, output_prefix, **kwargs):
    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    # # A simple png - note for this to work in a container Chrome must be installed in the container
    # chart = (
    #     alt.Chart(data)
    #     .mark_point(filled=True, size=25)
    #     .encode(
    #         alt.X("datetime:T", title="Time"),
    #         alt.Y("metric", title=column_name, scale=alt.Scale(domain=(0, max_y))),
    #         alt.Color("Type", title="Metric"),
    #         tooltip=["metric"],
    #     )
    #     .properties(height=400, width=800, title=title)
    #     .configure_legend(
    #         strokeColor="gray", fillColor="#EEEEEE", padding=10, cornerRadius=10, orient="top-right"
    #     )
    #     .configure_title(fontSize=14, color="black")
    # )
    # chart.save(f"{filepath}png_{column_name}.png")

    # A linked chart
    # First we’ll create an interval selection using the selection_interval() function (in this case for x axis only)

    brush = alt.selection(type="interval", encodings=["x"])

    # Create the chart
    base = (
        alt.Chart(data)
            .mark_line()
            .encode(
            # alt.X("datetime:T", title="Time", axis=alt.Axis(format='%e %b, %Y')),
            alt.X("datetime:T", title="Time"),
            alt.Y("metric", title=column_name, scale=alt.Scale(domain=(0, max_y))),
            alt.Color("Type", title="Metric"),
            tooltip=["metric"],
        )
            .properties(height=400, width=800, title=title)
    )

    # Upper is zoomed area X axis
    upper = base.encode(alt.X("datetime:T", title="Time Zoom", scale=alt.Scale(domain=brush)))

    # Lower chart bind the brush in our chart by setting the selection property
    lower = base.properties(height=100, title="").add_selection(brush)

    alt.hconcat(upper & lower).configure_title(fontSize=14, color="black").configure_legend(
        strokeColor="gray", fillColor="#EEEEEE", padding=10, cornerRadius=10, orient="right"
    )

    output_name = column_name.replace("/", "_")

    (upper & lower).save(f"{filepath}{output_prefix}{file_prefix}{output_name}.html")


def linked_chart_no_time(data, column_name, title, max_y, filepath, output_prefix, **kwargs):
    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    brush = alt.selection(type="interval", encodings=["x"])

    # Create the chart
    base = (
        alt.Chart(data)
            .mark_line()
            .encode(
            alt.X("id_key:Q", title="Count"),
            alt.Y("metric", title=column_name, scale=alt.Scale(domain=(0, max_y))),
            alt.Color("Type", title="Metric"),
            tooltip=["metric:N"],
        )
            .properties(height=400, width=800, title=title)
    )

    # Upper is zoomed area X axis
    upper = base.encode(alt.X("id_key:Q", title="Count Zoom", scale=alt.Scale(domain=brush)))

    # Lower chart bind the brush in our chart by setting the selection property
    lower = base.properties(height=100, title="").add_selection(brush)

    alt.hconcat(upper & lower).configure_title(fontSize=14, color="black").configure_legend(
        strokeColor="gray", fillColor="#EEEEEE", padding=10, cornerRadius=10, orient="right"
    )

    output_name = column_name.replace("/", "_")

    (upper & lower).save(f"{filepath}{output_prefix}{file_prefix}{output_name}.html")


def chart_vmstat(connection, filepath, output_prefix):
    # print(f"vmstat...")
    # Get useful
    customer = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'customer';")[2]
    number_cpus = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'number cpus';")[2]
    processor = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'processor model';")[2]

    # Read in to dataframe
    df = pd.read_sql_query("SELECT * FROM vmstat", connection)

    # Add a new total CPU column, add a datetime column
    df["Total CPU"] = 100 - df["id"]
    df["datetime"] = df["Date"] + " " + df["Time"]

    # Format the data for Altair
    # Cut down the df to just the the list of categorical data we care about (columns)
    columns_to_chart = list(df.columns)
    unwanted_columns = ["id_key", "Date", "Time", "html name"]
    columns_to_chart = [ele for ele in columns_to_chart if ele not in unwanted_columns]

    vmstat_df = df[columns_to_chart]

    # unpivot the dataframe; first column is date time column, column name is next, then the value in that column
    vmstat_df = vmstat_df.melt("datetime", var_name="Type", value_name="metric")

    # print(f"{vmstat_df.sample(3)}")
    #                 datetime      Type         metric
    # 33774  06/18/21 08:59:02     bo          104.0
    # 43902  06/18/21 08:47:50     us            1.0
    # 12710  06/18/21 09:07:59   free        60652.0

    # For each column create a linked html chart
    for column_name in columns_to_chart:
        if column_name == "datetime":
            pass
        else:
            if column_name in ("Total CPU", "r"):
                title = f"{column_name} - {customer}"
                title += f"\n{number_cpus} cores ({processor})"
            else:
                title = f"{column_name} - {customer}"

            to_chart_df = vmstat_df.loc[vmstat_df["Type"] == column_name]

            if column_name in ("Total CPU", "wa", "id", "us", "sy"):
                max_y = 100
            else:
                # Remove outliers first, will result in nan for zero values, so needs more work
                # to_chart_df = to_chart_df[((to_chart_df.metric - to_chart_df.metric.mean()) / to_chart_df.metric.std()).abs() < 3]
                max_y = to_chart_df["metric"].max()

            data = to_chart_df

            linked_chart(data, column_name, title, max_y, filepath, output_prefix)


def make_mdy_date(date_in):

    # update "%Y-%m-%d" to suit
    date_in = dateutil.parser.parse(date_in)
    date_out = datetime.strptime(str(date_in.date()), "%Y-%m-%d").strftime("%m/%d/%Y")

    # print(f"{date_in}   {date_out}")

    return date_out

def chart_mgstat(connection, filepath, output_prefix):
    # print(f"mgstat...")

    customer = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'customer';")[2]

    # Read in to dataframe
    df = pd.read_sql_query("SELECT * FROM mgstat", connection)

    # hack until good way to detect date format is mmm/dd/yyyy or not
    if False:
        df["Date"] = df.apply(
            lambda row: make_mdy_date(row["Date"]), axis=1
        )

    # Add a datetime column
    df["datetime"] = df["Date"] + " " + df["Time"]

    # Format the data for Altair
    # Cut down the df to just the the list of categorical data we care about (columns)
    columns_to_chart = list(df.columns)
    unwanted_columns = ["id_key", "Date", "Time", "html name"]
    columns_to_chart = [ele for ele in columns_to_chart if ele not in unwanted_columns]

    mgstat_df = df[columns_to_chart]

    # unpivot the dataframe; first column is date time column, column name is next, then the value in that column
    mgstat_df = mgstat_df.melt("datetime", var_name="Type", value_name="metric")

    # For each column create a chart
    for column_name in columns_to_chart:
        if column_name == "datetime":
            pass
        else:
            title = f"{column_name} - {customer}"
            to_chart_df = mgstat_df.loc[mgstat_df["Type"] == column_name]

            # Remove outliers first, will result in nan for zero values, so needs more work
            # to_chart_df = to_chart_df[((to_chart_df.metric - to_chart_df.metric.mean()) / to_chart_df.metric.std()).abs() < 3]
            max_y = to_chart_df["metric"].max()

            data = to_chart_df

            linked_chart(data, column_name, title, max_y, filepath, output_prefix)


def chart_perfmon(connection, filepath, output_prefix):
    # print(f"perfmon...")

    customer = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'customer';")[2]
    number_cpus = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'number cpus';")[2]

    # Read in to dataframe, drop any bad rows
    df = pd.read_sql_query("SELECT * FROM perfmon", connection)
    df.dropna(inplace=True)

    # The first column is a date time with timezone
    df.columns = df.columns[:1].tolist() + ["datetime"] + df.columns[2:].tolist()

    # In some cases time is a separate column
    if df.columns[2] == "Time":
        df["datetime"] = df["datetime"] + " " + df["Time"]

    # preprocess time to remove decimal precision
    df["datetime"] = df["datetime"].apply(lambda x: x.split(".")[0])

    # Format the data for Altair
    # Cut down the df to just the the list of categorical data we care about (columns)
    columns_to_chart = list(df.columns)
    unwanted_columns = ["id_key", "Time", "html name"]
    columns_to_chart = [ele for ele in columns_to_chart if ele not in unwanted_columns]

    perfmon_df = df[columns_to_chart]

    # unpivot the dataframe; first column is date time column, column name is next, then the value in that column
    perfmon_df = perfmon_df.melt("datetime", var_name="Type", value_name="metric")

    # For each column create a chart
    for column_name in columns_to_chart:
        if column_name == "datetime":
            pass
        else:
            if "Total_Processor_Time" in column_name or "Processor_Queue_Length" in column_name:
                title = f"{column_name} - {customer}"
                title += f"\n {number_cpus} cores"
            else:
                title = f"{column_name} - {customer}"

            to_chart_df = perfmon_df.loc[perfmon_df["Type"] == column_name]

            # Remove outliers first, will result in nan for zero values, so needs more work
            # to_chart_df = to_chart_df[((to_chart_df.metric - to_chart_df.metric.mean()) / to_chart_df.metric.std()).abs() < 3]
            if "_Time" in column_name:
                max_y = 100
            else:
                max_y = to_chart_df["metric"].max()

            data = to_chart_df

            linked_chart(data, column_name, title, max_y, filepath, output_prefix)


def chart_iostat(connection, filepath, output_prefix, operating_system):
    # print(f"iostat...")

    customer = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'customer';")[2]

    # Read in to dataframe, drop any bad rows
    df = pd.read_sql_query("SELECT * FROM iostat", connection)
    df.dropna(inplace=True)

    # If there is no date and time in iostat then just use index as x axis
    if "Date" in df.columns:

        df["datetime"] = df["Date"] + " " + df["Time"]

        # Format the data for Altair
        # Cut down the df to just the the list of categorical data we care about (columns)
        columns_to_chart = list(df.columns)
        unwanted_columns = ["id_key", "Date", "Time", "html name"]
        columns_to_chart = [ele for ele in columns_to_chart if ele not in unwanted_columns]

        iostat_df = df[columns_to_chart]
        devices = iostat_df["Device"].unique()

        # Chart each disk
        for device in devices:

            device_df = iostat_df.loc[iostat_df["Device"] == device]

            # unpivot the dataframe; first column is date time column, column name is next, then the value in that column
            device_df = device_df.melt("datetime", var_name="Type", value_name="metric")

            # For each column create a chart
            for column_name in columns_to_chart:
                if column_name == "datetime" or column_name == "Device":
                    pass
                else:
                    title = f"{device} : {column_name} - {customer}"
                    save_name = [s for s in column_name if s.isalnum() or s.isspace()]
                    save_name = "".join(save_name)

                    to_chart_df = device_df.loc[device_df["Type"] == column_name]

                    # Remove outliers first, will result in nan for zero values, so needs more work
                    # to_chart_df = to_chart_df[((to_chart_df.metric - to_chart_df.metric.mean()) / to_chart_df.metric.std()).abs() < 3]
                    max_y = to_chart_df["metric"].max()

                    data = to_chart_df

                    linked_chart(data, column_name, title, max_y, filepath, output_prefix, file_prefix=device)

    else:
        # No date or time, chart all columns, index is x axis

        columns_to_chart = list(df.columns)
        unwanted_columns = ["id_key", "html name"]
        columns_to_chart = [ele for ele in columns_to_chart if ele not in unwanted_columns]

        iostat_df = df
        devices = iostat_df["Device"].unique()

        # Chart each disk
        for device in devices:
            device_df = iostat_df.loc[iostat_df["Device"] == device]

            # unpivot the dataframe; first column is index, column name is next, then the value in that column
            device_df = device_df.melt("id_key", var_name="Type", value_name="metric")

            # For each column create a chart
            for column_name in columns_to_chart:
                if not column_name == "Device":
                    title = f"{device} : {column_name} - {customer}"
                    save_name = [s for s in column_name if s.isalnum() or s.isspace()]
                    save_name = "".join(save_name)

                    to_chart_df = device_df.loc[device_df["Type"] == column_name]

                    # Remove outliers first, will result in nan for zero values, so needs more work
                    # to_chart_df = to_chart_df[((to_chart_df.metric - to_chart_df.metric.mean()) / to_chart_df.metric.std()).abs() < 3]
                    max_y = to_chart_df["metric"].max()

                    data = to_chart_df

                    linked_chart_no_time(data, column_name, title, max_y, filepath, output_prefix, file_prefix=device)


def mainline(input_file, include_iostat, append_to_database, existing_database, output_prefix, csv_out, system_out):
    input_error = False

    # What are we doing?
    if append_to_database:
        database_action = f"Append only: {input_file}"
    elif existing_database:
        database_action = "Chart only"
    else:
        database_action = "Create and Chart"

    print(f"{database_action}")

    # get the file paths and file names
    if existing_database:
        filepath_filename = os.path.split(existing_database)
    else:
        filepath_filename = os.path.split(input_file)

    filepath = filepath_filename[0]
    filename = filepath_filename[1]

    # if no path it is the current path
    if filepath == "":
        filepath = "."

    # get the prefix
    html_filename = filename.split('.')[0]

    if output_prefix is None:
        output_prefix = f"{html_filename}_"
    else:
        if output_prefix != "":
            output_prefix = f"{output_prefix}_"

    output_filepath_prefix = f"{filepath}/{output_prefix}"

    if existing_database:
        sql_filename = existing_database
    else:
        sql_filename = f"{output_filepath_prefix}SystemPerformance.sqlite"

        # Delete the database and recreate
        if database_action == "Create and Chart":
            if os.path.exists(sql_filename):
                os.remove(sql_filename)

    # Connect to database (Create database file if it does not exist already)
    connection = create_connection(sql_filename)

    # Is this the first time in?
    cursor = connection.cursor()
    cursor.execute(""" SELECT count(name) FROM sqlite_master WHERE type='table' AND name='overview' """)

    # if the count is 1, then table exists
    if cursor.fetchone()[0] == 1:
        if database_action != "Chart only":
            create_sections(connection, input_file, include_iostat, html_filename, csv_out, output_filepath_prefix)

    else:
        if database_action == "Chart only":
            input_error = True
            print(f"No data to chart")
        else:

            # Create a system summary
            sp_dict = sp_check.system_check(input_file)

            if system_out:
                output_log = sp_check.build_log(sp_dict)

                with open(f"{output_filepath_prefix}overview.txt", "w") as text_file:
                    print(f"{output_log}", file=text_file)

                # Simple dump of all data in overview
                overview_df = pd.DataFrame(list(sp_dict.items()), columns=["key", "value"])
                overview_df.to_csv(f"{output_filepath_prefix}overview_all.csv", header=True, index=False, sep=',', mode='w')

            create_overview(connection, sp_dict)
            create_sections(connection, input_file, include_iostat, html_filename, csv_out, output_filepath_prefix)

    connection.close()

    # Charting is separate

    if "Chart" in database_action and not input_error:

        output_file_path_base = f"{output_filepath_prefix}metrics"

        if not os.path.isdir(output_file_path_base):
            os.mkdir(output_file_path_base)

        connection = create_connection(sql_filename)

        operating_system = execute_single_read_query(
            connection, "SELECT * FROM overview WHERE field = 'operating system';"
        )[2]

        # mgstat
        output_file_path = f"{output_file_path_base}/mgstat/"

        if not os.path.isdir(output_file_path):
            os.mkdir(output_file_path)
        chart_mgstat(connection, output_file_path, output_prefix)

        # vmstat and iostat
        if operating_system == "Linux" or operating_system == "Ubuntu":

            output_file_path = f"{output_file_path_base}/vmstat/"
            if not os.path.isdir(output_file_path):
                os.mkdir(output_file_path)
            chart_vmstat(connection, output_file_path, output_prefix)

            if include_iostat:
                output_file_path = f"{output_file_path_base}/iostat/"
                if not os.path.isdir(output_file_path):
                    os.mkdir(output_file_path)
                chart_iostat(connection, output_file_path, output_prefix, operating_system)

        if operating_system == "Windows":
            output_file_path = f"{output_file_path_base}/perfmon/"
            if not os.path.isdir(output_file_path):
                os.mkdir(output_file_path)
            chart_perfmon(connection, output_file_path, output_prefix)

        connection.close()

    return


# Start here

if __name__ == "__main__":

    input_file = ""
    existing_database = ""

    parser = argparse.ArgumentParser(
        prog="yaspe", description="Performance file review", epilog='Be safe, "quote the path"'
    )

    parser.add_argument(
        "-i",
        "--input_file",
        help="Input html filename with full path.",
        action="store",
        metavar='"/path/file.html"',
    )

    parser.add_argument(
        "-x",
        "--iostat",
        dest="include_iostat",
        help="Also plot iostat data (can take a long time).",
        action="store_true",
    )

    parser.add_argument(
        "-a",
        "--append",
        dest="append_to_database",
        help="Do not overwrite database, append to existing database.",
        action="store_true",
    )

    parser.add_argument(
        "-o",
        "--output_prefix",
        dest="output_prefix",
        help="Output filename prefix, defaults to html file name, blank (-o '') is legal.",
        action="store",
        metavar='"output file prefix"',
    )

    parser.add_argument(
        "-e",
        "--existing_database",
        help="Chart existing database, full path and filename to existing database.",
        action="store",
        metavar='"/path/filename_SystemPerformance.sqlite"',
    )

    parser.add_argument(
        "-c",
        "--csv",
        dest="csv_out",
        help="Create csv files of each html files metrics, append if csv file exists.",
        action="store_true",
    )

    parser.add_argument(
        "-s",
        "--system",
        dest="system_out",
        help="Output system overview. ",
        action="store_true",
    )

    args = parser.parse_args()

    # Validate input file
    if args.input_file is not None:
        try:
            if os.path.getsize(args.input_file) > 0:
                input_file = args.input_file
            else:
                print('Error: -i "Input html filename with full path required"')
                sys.exit()
        except OSError as e:
            print("Could not process files because: {}".format(str(e)))
            sys.exit()

    else:

        # if no input file validate existing database to chart
        if args.existing_database is None:
            print('Error: -i "Input html filename with full path required"')
            sys.exit()
        else:
            try:
                if os.path.getsize(args.existing_database) > 0:
                    existing_database = args.existing_database
                else:
                    print('Error: -o "Existing database filename with full path required"')
                    sys.exit()
            except OSError as e:
                print("Could not process files because: {}".format(str(e)))
                sys.exit()

    # This section is a precursor to config file replacement/override of parameters
    disk_dictionary = {"Database": "dm-9",
                       "Primary Journal": "sdg1",
                       "Alternate Journal": "sdh1",
                       "WIJ": "dm-10",
                       "IRIS": "dm-10"}

    try:
        mainline(input_file, args.include_iostat, args.append_to_database, existing_database, args.output_prefix,
                 args.csv_out, args.system_out)
    except OSError as e:
        print("Could not process files because: {}".format(str(e)))
        