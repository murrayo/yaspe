#!/usr/bin/env python3
"""
Extract sections of SystemPerformance file to SQL table.
Chart the results


"""
import os
import sys
import locale
import argparse
import pandas as pd
import altair as alt

# from altair_saver import save
import sqlite3
from sqlite3 import Error

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


def create_sections(connection, input_file, include_iostat):

    vmstat_processing = False
    vmstat_header = ""
    vmstat_rows_list = []

    iostat_processing = False
    iostat_header = ""
    iostat_rows_list = []
    iostat_start_block = False

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
                mgstat_rows_list.append(mgstat_row_dict)
            if mgstat_processing and "Glorefs" in line:
                mgstat_header = line
                mgstat_columns = mgstat_header.split(",")
                mgstat_columns = [i.strip() for i in mgstat_columns]  # strip off carriage return etc

            if operating_system == "Linux":
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
            if operating_system == "Linux" and include_iostat:
                if "<div" in line:  # there can be no end to iostat
                    iostat_processing = False
                if "id=iostat" in line:
                    iostat_processing = True
                if iostat_processing and (len(line.split()) == 2 or len(line.split()) == 3):  # date time AM
                    date_time = line.strip()
                    iostat_start_block = False
                if iostat_processing and iostat_start_block and iostat_header != "":
                    iostat_row_dict = {}
                    line = date_time.split()[0] + " " + date_time.split()[1] + " " + line
                    values = line.split()
                    values = [i.strip() for i in values]  # strip off carriage return etc
                    values_converted = [get_number_type(v) for v in values]
                    iostat_row_dict = dict(zip(iostat_columns, values_converted))
                    iostat_rows_list.append(iostat_row_dict)
                if "Device" in line:
                    iostat_start_block = True
                if iostat_processing and iostat_header == "" and "Device" in line:
                    iostat_header = f"Date Time {line}"
                    iostat_header = iostat_header.replace(":", "")  # "Device:"
                    iostat_columns = iostat_header.split()
                    iostat_columns = [i.strip() for i in iostat_columns]  # strip off carriage return etc

    # Add each section to the database

    if mgstat_header != "":
        # Create dataframe of rows. Shortcut here to creating table columns or later charts etc
        mgstat_df = pd.DataFrame(mgstat_rows_list)

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

    if vmstat_header != "":
        vmstat_df = pd.DataFrame(vmstat_rows_list)
        create_generic_table(connection, "vmstat", vmstat_df)
        for row in vmstat_rows_list:
            insert_dict_into_table(connection, "vmstat", row)
        connection.commit()

    if perfmon_header != "":
        perfmon_df = pd.DataFrame(perfmon_rows_list)
        create_generic_table(connection, "perfmon", perfmon_df)
        for row in perfmon_rows_list:
            insert_dict_into_table(connection, "perfmon", row)
        connection.commit()

    if iostat_header != "":
        iostat_df = pd.DataFrame(iostat_rows_list)
        create_generic_table(connection, "iostat", iostat_df)
        for row in iostat_rows_list:
            insert_dict_into_table(connection, "iostat", row)
        connection.commit()


def create_overview(connection, input_file):

    cursor = connection.cursor()

    create_overview_table = """
    CREATE TABLE IF NOT EXISTS overview (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      field TEXT NOT NULL,
      value TEXT
    );
    """

    execute_simple_query(connection, create_overview_table)

    sp_dict = {}

    with open(input_file, "r", encoding="ISO-8859-1") as file:

        model_name = True
        windows_info_available = False

        memory_next = False
        perfmon_next = False

        up_counter = 0

        for line in file:

            # Summary

            if "VMware" in line:
                sp_dict["platform"] = "VMware"

            if "Customer: " in line:
                customer = (line.split(":")[1]).strip()
                sp_dict["customer"] = customer

            if "overview=" in line:
                sp_dict["overview"] = (line.split("=")[1]).strip()

            if "Caché Version String: " in line or "Product Version String: " in line:
                sp_dict["version string"] = (line.split(":", 1)[1]).strip()

                if "Windows" in line:
                    sp_dict["operating system"] = "Windows"
                if "Linux" in line:
                    sp_dict["operating system"] = "Linux"
                if "AIX" in line:
                    sp_dict["operating system"] = "AIX"
                if "Ubuntu Server LTS" in line:
                    sp_dict["operating system"] = "Ubuntu"

            if "Profile run " in line:
                sp_dict["profile run"] = line.strip()

            if "Run over " in line:
                sp_dict["run over"] = line.strip()

            if "on machine" in line:
                sp_dict[f"instance"] = (line.split(" on machine ", 1)[0]).strip()

            if line.startswith("up "):
                up_counter += 1
                sp_dict[f"up instance {up_counter}"] = (line.split(" ", 1)[1]).strip()

            # mgstat

            if "numberofcpus=" in line:
                sp_dict["mgstat header"] = line.strip()

                mgstat_header = sp_dict["mgstat header"].split(",")
                for item in mgstat_header:
                    if "numberofcpus" in item:
                        sp_dict["number cpus"] = item.split("=")[1].split(":")[0]

            # Linux cpu info

            if "model name	:" in line:
                if model_name:
                    model_name = False
                    sp_dict["processor model"] = (line.split(":")[1]).strip()

            # CPF file

            if "AlternateDirectory=" in line:
                sp_dict["alternate journal"] = (line.split("=")[1]).strip()
            if "CurrentDirectory=" in line:
                sp_dict["current journal"] = (line.split("=")[1]).strip()
            if "globals=" in line:
                sp_dict["globals"] = (line.split("=")[1]).strip()
            if "gmheap=" in line:
                sp_dict["gmheap"] = (line.split("=")[1]).strip()
            if "locksiz=" in line:
                sp_dict["locksiz"] = (line.split("=")[1]).strip()
            if "routines=" in line:
                sp_dict["routines"] = (line.split("=")[1]).strip()
            if "wijdir=" in line:
                sp_dict["wijdir"] = (line.split("=")[1]).strip()
            if "Freeze" in line:
                sp_dict["freeze"] = (line.split("=")[1]).strip()
            if "Asyncwij=" in line:
                sp_dict["asyncwij"] = (line.split("=")[1]).strip()
            if "wduseasyncio=" in line:
                sp_dict["wduseasyncio"] = (line.split("=")[1]).strip()

            # Linux kernel

            if "kernel.hostname" in line:
                sp_dict["linux hostname"] = (line.split("=")[1]).strip()

            if "swappiness" in line:
                sp_dict["swappiness"] = (line.split("=")[1]).strip()

            # Number hugepages = shared memory. eg 48GB/2048 = 24576
            if "vm.nr_hugepages" in line:
                sp_dict["vm.nr_hugepages"] = (line.split("=")[1]).strip()

            # Shared memory must be greater than hugepages in bytes (IRIS shared memory)
            if "kernel.shmmax" in line:
                sp_dict["kernel.shmmax"] = (line.split("=")[1]).strip()
            if "kernel.shmall" in line:
                sp_dict["kernel.shmall"] = (line.split("=")[1]).strip()

            # dirty background ratio = 5
            if "vm.dirty_background_ratio" in line:
                sp_dict["vm.dirty_background_ratio"] = (line.split("=")[1]).strip()

            # dirty ratio = 10
            if "vm.dirty_ratio" in line:
                sp_dict["vm.dirty_ratio"] = (line.split("=")[1]).strip()

            # Linux free

            if memory_next:
                sp_dict["memory MB"] = (line.split(",")[2]).strip()
                memory_next = False
            if "<div id=free>" in line:
                memory_next = True

            # Windows info
            if "Windows info" in line:
                windows_info_available = True

            if windows_info_available:
                if "Host Name:" in line:
                    sp_dict["windows host name"] = (line.split(":")[1]).strip()
                if "OS Name:" in line:
                    sp_dict["windows os name"] = (line.split(":")[1]).strip()
                if "[01]: Intel64 Family" in line:
                    sp_dict["windows processor"] = (line.split(":")[1]).strip()
                if "Time Zone:" in line:
                    sp_dict["windows time zone"] = line.strip()
                if "Total Physical Memory:" in line:
                    sp_dict["windows total memory"] = (line.split(":")[1]).strip()
                    # if decimal point instead of comma
                    sp_dict["windows total memory"] = sp_dict["windows total memory"].replace(".", ",")

                if "hypervisor" in line:
                    sp_dict["windows hypervisor"] = line.strip()

            # Windows perform

            if perfmon_next:
                sp_dict["perfmon_header"] = line.strip()
                perfmon_next = False
            if "beg_win_perfmon" in line:
                perfmon_next = True

    # Create the insert query string
    for key in sp_dict:
        cursor.execute("INSERT INTO overview (field, value) VALUES (?, ?)", (key, sp_dict[key]))
        connection.commit()

        # # Debug
        # print(f"{key} : {sp_dict[key]}")

    # # Debug
    # select_overview = "SELECT * from overview"
    # overviews = execute_read_query(connection, select_overview)
    #
    # for overview in overviews:
    #     print(f"{overview}")

    return


def linked_chart(data, column_name, title, max_y, filepath):

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

    (upper & lower).save(f"{filepath}html_{output_name}.html")


def chart_vmstat(connection, filepath):

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
    unwanted_columns = ["id_key", "Date", "Time"]
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

            linked_chart(data, column_name, title, max_y, filepath)


def chart_mgstat(connection, filepath):

    # print(f"mgstat...")

    customer = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'customer';")[2]

    # Read in to dataframe
    df = pd.read_sql_query("SELECT * FROM mgstat", connection)

    # Add a datetime column
    df["datetime"] = df["Date"] + " " + df["Time"]

    # Format the data for Altair
    # Cut down the df to just the the list of categorical data we care about (columns)
    columns_to_chart = list(df.columns)
    unwanted_columns = ["id_key", "Date", "Time"]
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

            linked_chart(data, column_name, title, max_y, filepath)


def chart_perfmon(connection, filepath):

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
    unwanted_columns = ["id_key", "Time"]
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
            max_y = to_chart_df["metric"].max()

            data = to_chart_df

            linked_chart(data, column_name, title, max_y, filepath)


def chart_iostat(connection, filepath, operating_system):

    # print(f"iostat...")

    customer = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'customer';")[2]

    # Read in to dataframe, drop any bad rows
    df = pd.read_sql_query("SELECT * FROM iostat", connection)
    df.dropna(inplace=True)

    df["datetime"] = df["Date"] + " " + df["Time"]

    # Format the data for Altair
    # Cut down the df to just the the list of categorical data we care about (columns)
    columns_to_chart = list(df.columns)
    unwanted_columns = ["id_key", "Date", "Time"]
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

                linked_chart(data, column_name, title, max_y, filepath)


def mainline(input_file, include_iostat, append_to_database, existing_database):

    input_error = False

    # What are we doing?
    if append_to_database:
        database_action = "Append only"
    elif existing_database:
        database_action = "Chart only"
    else:
        database_action = "Create and Chart"

    print(f"{database_action}")

    # get the path
    if existing_database:
        head_tail = os.path.split(existing_database)
    else:
        head_tail = os.path.split(input_file)
    filepath = head_tail[0]
    # filename = head_tail[1]

    # Delete the database and recreate
    if database_action == "Create and Chart":
        if os.path.exists(f"{filepath}/SystemPerformance.sqlite"):
            os.remove(f"{filepath}/SystemPerformance.sqlite")

    # Connect to database (Create database file if it does not exist already)
    connection = create_connection(f"{filepath}/SystemPerformance.sqlite")

    # Is this the first time in?
    cursor = connection.cursor()
    cursor.execute(''' SELECT count(name) FROM sqlite_master WHERE type='table' AND name='overview' ''')

    # if the count is 1, then table exists
    if cursor.fetchone()[0] == 1:
        if database_action != "Chart only":
            create_sections(connection, input_file, include_iostat)

    else:
        if database_action == "Chart only":
            input_error = True
            print(f"No data to chart")
        else:
            create_overview(connection, input_file)
            create_sections(connection, input_file, include_iostat)

    connection.close()

    # Charting is separate

    if "Chart" in database_action and not input_error:

        output_file_path = f"{filepath}/metrics/"
        if not os.path.isdir(output_file_path):
            os.mkdir(output_file_path)

        connection = create_connection(f"{filepath}/SystemPerformance.sqlite")

        operating_system = execute_single_read_query(
            connection, "SELECT * FROM overview WHERE field = 'operating system';"
        )[2]

        output_file_path = f"{filepath}/metrics/mgstat/"
        if not os.path.isdir(output_file_path):
            os.mkdir(output_file_path)
        chart_mgstat(connection, output_file_path)

        if operating_system == "Linux":

            output_file_path = f"{filepath}/metrics/vmstat/"
            if not os.path.isdir(output_file_path):
                os.mkdir(output_file_path)
            chart_vmstat(connection, output_file_path)

            if include_iostat:
                output_file_path = f"{filepath}/metrics/iostat/"
                if not os.path.isdir(output_file_path):
                    os.mkdir(output_file_path)
                chart_iostat(connection, output_file_path, operating_system)

        if operating_system == "Windows":
            output_file_path = f"{filepath}/metrics/perfmon/"
            if not os.path.isdir(output_file_path):
                os.mkdir(output_file_path)
            chart_perfmon(connection, output_file_path)

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
        help="Input html filename with full path",
        action="store",
        metavar='"/path/file.html"',
    )

    parser.add_argument(
        "-x", "--iostat", dest="include_iostat", help="Also plot iostat data (can take a long time)", action="store_true"
    )

    parser.add_argument(
        "-a", "--append", dest="append_to_database", help="Do not overwrite database, append to existing database", action="store_true"
    )

    parser.add_argument(
        "-e",
        "--existing_database",
        help="Chart existing database, full path to existing database directory",
        action="store",
        metavar='"/path"',
    )

    args = parser.parse_args()

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
        if args.existing_database is None:
            print('Error: -i "Input html filename with full path required"')
            sys.exit()
        else:
            try:
                if os.path.getsize(args.existing_database) > 0:
                    existing_database = f"{args.existing_database}/SystemPerformance.sqlite"
                else:
                    print('Error: -i "Existing database filename with full path required"')
                    sys.exit()
            except OSError as e:
                print("Could not process files because: {}".format(str(e)))
                sys.exit()

    try:
        mainline(input_file, args.include_iostat, args.append_to_database, existing_database)
    except OSError as e:
        print("Could not process files because: {}".format(str(e)))
