#!/usr/bin/env python3
"""
Extract sections of SystemPerformance file to SQL table.
Chart the results


"""

import sp_check
import split_large_file
import argparse
import os
import yaml

from datetime import datetime
from dateutil.parser import parse

# from altair_saver import save
import sqlite3
import sys
from sqlite3 import Error

import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.dates as plt_dates
import seaborn as sns


import altair as alt
import pandas as pd

from extract_sections import extract_sections
import system_review

# Altair
# Max is 5,000 rows by default
from yaspe_utilities import make_mdy_date

alt.data_transformers.disable_max_rows()


# Define a function to infer the date format
def guess_datetime_format(datetime_string):
    try:
        dt = parse(datetime_string)
        return dt.strftime("%m/%d/%Y %H:%M:%S")
    except ValueError:
        return "Unable to determine datetime format."


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


def is_column_numeric(df, column_name):
    try:
        pd.to_numeric(df[column_name])
        return True
    except (ValueError, TypeError):
        return False


def create_sections(
    connection, input_file, include_iostat, include_nfsiostat, html_filename, csv_out, output_filepath_prefix, disk_list
):

    operating_system = execute_single_read_query(
        connection, "SELECT * FROM overview WHERE field = 'operating system';"
    )[2]

    # Get the start date for date format validation
    profile_run = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'profile run';")[2]

    mgstat_df, vmstat_df, iostat_df, nfsiostat_df, perfmon_df, aix_sar_d_df = extract_sections(
        operating_system, profile_run, input_file, include_iostat, include_nfsiostat, html_filename, disk_list
    )

    # Add each section to the database

    if not mgstat_df.empty:

        # Example Dave L can do IRIS function here
        if True:
            mgstat_df.to_sql("mgstat", connection, if_exists="append", index=True, index_label="id_key")
            connection.commit()
        else:
            pass

        if csv_out:
            mgstat_output_csv = f"{output_filepath_prefix}mgstat.csv"

            # if file does not exist write header
            if not os.path.isfile(mgstat_output_csv):
                mgstat_df.to_csv(mgstat_output_csv, header="column_names", index=False, encoding="utf-8")
            else:  # else it exists so append without writing the header
                mgstat_df.to_csv(mgstat_output_csv, mode="a", header=False, index=False, encoding="utf-8")

    if not vmstat_df.empty:

        vmstat_df.to_sql("vmstat", connection, if_exists="append", index=True, index_label="id_key")
        connection.commit()

        if csv_out:
            vmstat_output_csv = f"{output_filepath_prefix}vmstat.csv"

            # if file does not exist write header
            if not os.path.isfile(vmstat_output_csv):
                vmstat_df.to_csv(vmstat_output_csv, header="column_names", index=False, encoding="utf-8")
            else:  # else it exists so append without writing the header
                vmstat_df.to_csv(vmstat_output_csv, mode="a", header=False, index=False, encoding="utf-8")

    if not perfmon_df.empty:
        perfmon_df.to_sql("perfmon", connection, if_exists="append", index=True, index_label="id_key")
        connection.commit()

        if csv_out:
            perfmon_output_csv = f"{output_filepath_prefix}perfmon.csv"

            # if file does not exist write header
            if not os.path.isfile(perfmon_output_csv):
                perfmon_df.to_csv(perfmon_output_csv, header="column_names", index=False, encoding="utf-8")
            else:  # else it exists so append without writing the header
                perfmon_df.to_csv(perfmon_output_csv, mode="a", header=False, index=False, encoding="utf-8")

    if not iostat_df.empty:
        # id_key is used when there is no time
        iostat_df.to_sql("iostat", connection, if_exists="append", index=True, index_label="id_key")
        connection.commit()

        if csv_out:
            iostat_output_csv = f"{output_filepath_prefix}iostat.csv"

            # if file does not exist write header
            if not os.path.isfile(iostat_output_csv):
                iostat_df.to_csv(iostat_output_csv, header="column_names", index=False, encoding="utf-8")
            else:  # else it exists so append without writing the header
                iostat_df.to_csv(iostat_output_csv, mode="a", header=False, index=False, encoding="utf-8")

    if not nfsiostat_df.empty:
        # id_key is used when there is no time
        nfsiostat_df.to_sql("nfsiostat", connection, if_exists="append", index=True, index_label="id_key")
        connection.commit()

        if csv_out:
            nfsiostat_output_csv = f"{output_filepath_prefix}nfsiostat.csv"

            # if file does not exist write header
            if not os.path.isfile(nfsiostat_output_csv):
                nfsiostat_df.to_csv(nfsiostat_output_csv, header="column_names", index=False, encoding="utf-8")
            else:  # else it exists so append without writing the header
                nfsiostat_df.to_csv(nfsiostat_output_csv, mode="a", header=False, index=False, encoding="utf-8")

    if not aix_sar_d_df.empty:

        aix_sar_d_df.to_sql("aix_sar_d", connection, if_exists="append", index=True, index_label="id_key")
        connection.commit()

        if csv_out:
            aix_sar_d_output_csv = f"{output_filepath_prefix}aix_sar_d.csv"

            # if file does not exist write header
            if not os.path.isfile(aix_sar_d_output_csv):
                aix_sar_d_df.to_csv(aix_sar_d_output_csv, header="column_names", index=False, encoding="utf-8")
            else:  # else it exists so append without writing the header
                aix_sar_d_df.to_csv(aix_sar_d_output_csv, mode="a", header=False, index=False, encoding="utf-8")


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


def simple_chart(data, column_name, title, max_y, filepath, output_prefix, **kwargs):

    # Check column only has numeric data (strings can sneak in with AIX)
    if not is_column_numeric(data, "metric"):
        print(f"Non numeric data in in column: {column_name} for chart {title}:\n{data.head(2)}")
        return
    # else:
    #     print(column_name)
    #     print(f'_{data["metric"].max()}_ : {type(data["metric"].max())}')

    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    # # Convert datetime string to datetime type (data is a _view_ of full dataframe, create a copy to update here)
    # # Apply the function to the DataFrame column
    # data["datetime"] = data["datetime"].apply(guess_datetime_format)
    # print(data["datetime"].head(3))

    png_data = data.copy()
    png_data.loc[:, "datetime"] = pd.to_datetime(
        data["datetime"].apply(guess_datetime_format), format="%m/%d/%Y %H:%M:%S"
    )

    colormap_name = "Set1"
    plt.style.use("seaborn-v0_8-whitegrid")

    plt.figure(num=None, figsize=(16, 6))
    plt.tight_layout()

    palette = plt.get_cmap(colormap_name)

    color = palette(1)

    fig, ax = plt.subplots()
    plt.gcf().set_size_inches(16, 6)
    # plt.gcf().set_dpi(300)

    ax.plot(
        png_data["datetime"],
        png_data["metric"],
        label=column_name,
        color=color,
        marker=".",
        linestyle="none",
        alpha=0.7,
    )
    ax.grid(which="major", axis="both", linestyle="--")
    ax.set_title(title, fontsize=14)
    ax.set_ylabel(column_name, fontsize=10)
    ax.tick_params(labelsize=10)
    ax.set_ylim(bottom=0)  # Always zero start
    if max_y != 0:
        ax.set_ylim(top=max_y)

    if png_data["metric"].max() > 10 or "%" in column_name:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))
    elif png_data["metric"].max() < 0.002:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.4f}"))
    else:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.3f}"))

    locator = plt_dates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(plt_dates.AutoDateFormatter(locator=locator, defaultfmt="%H:%M"))

    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    # plt.tight_layout()

    output_name = column_name.replace("/", "_")
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}.png", format="png", dpi=100)
    plt.close("all")


def simple_chart_no_time(data, column_name, title, max_y, filepath, output_prefix, **kwargs):
    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    # Convert datetime string to datetime type (data is a _view_ of full dataframe, create a copy to update here)
    png_data = data.copy()

    colormap_name = "Set1"
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.figure(num=None, figsize=(16, 6))
    palette = plt.get_cmap(colormap_name)

    color = palette(1)

    fig, ax = plt.subplots()
    plt.gcf().set_size_inches(16, 6)
    # plt.gcf().set_dpi(300)

    ax.plot(
        png_data["id_key"], png_data["metric"], label=column_name, color=color, marker=".", linestyle="-", alpha=0.7
    )
    ax.grid(which="major", axis="both", linestyle="--")
    ax.set_title(title, fontsize=14)
    ax.set_ylabel(column_name, fontsize=10)
    ax.tick_params(labelsize=10)
    ax.set_ylim(bottom=0)  # Always zero start
    if max_y != 0:
        ax.set_ylim(top=max_y)

    if png_data["metric"].max() > 10 or "%" in column_name:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))
    elif png_data["metric"].max() < 0.002:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.4f}"))
    else:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.3f}"))

    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    plt.tight_layout()

    output_name = column_name.replace("/", "_per_").replace(" ", "_")
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}.png", format="png", dpi=100)
    plt.close("all")


def linked_chart(data, column_name, title, max_y, filepath, output_prefix, **kwargs):
    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    # First we’ll create an interval selection using the selection_interval() function (in this case for x axis only)

    brush = alt.selection_interval(encodings=["x"])

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
        .properties(height=500, width=1333, title=title)
    )

    # Upper is zoomed area X axis
    upper = base.encode(alt.X("datetime:T", title="Time Zoom", scale=alt.Scale(domain=brush)))

    # Lower chart bind the brush in our chart by setting the selection property
    lower = base.properties(height=150, title="").add_params(brush)

    alt.hconcat(upper & lower).configure_title(fontSize=14, color="black").configure_legend(
        strokeColor="gray", fillColor="#EEEEEE", padding=10, cornerRadius=10, orient="right"
    )

    output_name = column_name.replace("/", "_")

    (upper & lower).save(f"{filepath}{output_prefix}{file_prefix}{output_name}.html", scale_factor=2.0)


def interactive_chart(data, column_name, title, max_y, filepath, output_prefix, **kwargs):
    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    output_name = column_name.replace(" ", "_").replace("/", "_per_")

    # Create the chart
    alt.Chart(data).mark_line().encode(
        alt.X("datetime:T", title="Time"),
        alt.Y("metric", title=column_name, scale=alt.Scale(domain=(0, max_y))),
        alt.Color("Type", title="Metric"),
        tooltip=["metric"],
    ).properties(height=500, width=1333, title=title).interactive().save(
        f"{filepath}{output_prefix}{file_prefix}int_{output_name}.html", scale_factor=2.0
    )


def linked_chart_no_time(data, column_name, title, max_y, filepath, output_prefix, **kwargs):
    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    brush = alt.selection_interval(encodings=["x"])

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
        .properties(height=500, width=1333, title=title)
    )

    # Upper is zoomed area X axis
    upper = base.encode(alt.X("id_key:Q", title="Count Zoom", scale=alt.Scale(domain=brush)))

    # Lower chart bind the brush in our chart by setting the selection property
    lower = base.properties(height=150, title="").add_params(brush)

    alt.hconcat(upper & lower).configure_title(fontSize=14, color="black").configure_legend(
        strokeColor="gray", fillColor="#EEEEEE", padding=10, cornerRadius=10, orient="right"
    )

    output_name = column_name.replace(" ", "_").replace("/", "_per_")

    (upper & lower).save(f"{filepath}{output_prefix}{file_prefix}{output_name}.html", scale_factor=2.0)


def simple_chart_stacked(data, column_names, title, max_y, filepath, output_prefix, **kwargs):

    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    png_data = data.copy()
    png_data.loc[:, "datetime"] = pd.to_datetime(
        data["datetime"].apply(guess_datetime_format), format="%m/%d/%Y %H:%M:%S"
    )

    # Get the column data, TBD make more useful with any column_names is a dictionary of variable names
    wa = png_data["wa"]
    sy = png_data["sy"]
    us = png_data["us"]

    colormap_name = "Set1"
    plt.style.use("seaborn-v0_8-whitegrid")

    plt.figure(num=None, figsize=(16, 6))
    plt.tight_layout()

    palette = plt.get_cmap(colormap_name)

    color = palette(1)

    fig, ax = plt.subplots()
    plt.gcf().set_size_inches(16, 6)
    # plt.gcf().set_dpi(300)

    ax.stackplot(png_data["datetime"], sy, wa, us, labels=["sy", "wa", "us"], alpha=0.7, baseline="zero")

    ax.grid(which="major", axis="both", linestyle="--")
    ax.set_title(title, fontsize=14)
    ax.set_ylabel("CPU Utilisation %", fontsize=10)
    ax.legend(loc="upper left", reverse=True)
    ax.tick_params(labelsize=10)
    ax.set_ylim(bottom=0)  # Always zero start
    if max_y != 0:
        ax.set_ylim(top=max_y)

    ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))

    locator = plt_dates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(plt_dates.AutoDateFormatter(locator=locator, defaultfmt="%H:%M"))

    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    # plt.tight_layout()

    output_name = "Stacked CPU"
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}.png", format="png", dpi=100)
    plt.close("all")


def simple_chart_stacked_iostat(data, column_names, device, title, max_y, filepath, output_prefix, **kwargs):

    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    png_data = data.copy()
    png_data.loc[:, "datetime"] = pd.to_datetime(
        data["datetime"].apply(guess_datetime_format), format="%m/%d/%Y %H:%M:%S"
    )

    # Get the column data, TBD make more useful with any column_names is a dictionary of variable names

    # get the / out of file names
    # png_data.rename(columns={'r/s': 'Reads', 'w/s': 'Writes'}, inplace=True)
    reads = png_data["r/s"]
    writes = png_data["w/s"]

    colormap_name = "Set1"
    plt.style.use("seaborn-v0_8-whitegrid")

    plt.figure(num=None, figsize=(16, 6))
    plt.tight_layout()

    palette = plt.get_cmap(colormap_name)

    color = palette(1)

    fig, ax = plt.subplots()
    plt.gcf().set_size_inches(16, 6)
    # plt.gcf().set_dpi(300)

    ax.stackplot(png_data["datetime"], reads, writes, labels=["r/s", "w/s"], alpha=0.7, baseline="zero")

    ax.grid(which="major", axis="both", linestyle="--")
    ax.set_title(title, fontsize=14)
    ax.set_ylabel("Total IOPS", fontsize=10)
    ax.legend(loc="upper left", reverse=True)
    ax.tick_params(labelsize=10)
    ax.set_ylim(bottom=0)  # Always zero start
    if max_y != 0:
        ax.set_ylim(top=max_y)

    ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))

    locator = plt_dates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(plt_dates.AutoDateFormatter(locator=locator, defaultfmt="%H:%M"))

    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    # plt.tight_layout()

    output_name = "Stacked IOPS"
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}_{device}_z_{output_name}.png", format="png", dpi=100)
    plt.close("all")


def simple_chart_histogram_iostat(png_data, device, title, filepath, output_prefix, **kwargs):

    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    # Get the column data, TBD make more useful with any column_names is a dictionary of variable names

    # get the / out of file names
    # png_data.rename(columns={'r/s': 'Reads', 'w/s': 'Writes'}, inplace=True)
    reads = png_data["r_await"]

    # For writes only look at non-zero values
    # Create a boolean mask based on the condition "column2" is not equal to 0
    mask = png_data["w/s"] != 0

    # Use the boolean mask to filter values in "column1"
    writes = png_data.loc[mask, "w_await"]

    colormap_name = "Set1"
    plt.style.use("seaborn-v0_8-whitegrid")

    plt.figure(num=None, figsize=(16, 6))
    plt.tight_layout()

    palette = plt.get_cmap(colormap_name)

    color = palette(1)

    # Reads

    fig, ax = plt.subplots()
    plt.gcf().set_size_inches(16, 6)
    # plt.gcf().set_dpi(300)

    ax.hist(reads, bins=10, edgecolor="black")

    ax.grid(which="major", axis="both", linestyle="--")
    ax.set_title(title, fontsize=14)
    ax.set_xlabel("Latency (r_await)", fontsize=10)
    ax.set_ylabel("Frequency", fontsize=10)

    ax.tick_params(labelsize=10)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    # plt.tight_layout()

    output_name = f"Read Latency Histogram"
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}_{device}_z_{output_name}.png", format="png", dpi=100)
    plt.close("all")

    # Writes

    fig, ax = plt.subplots()
    plt.gcf().set_size_inches(16, 6)
    # plt.gcf().set_dpi(300)

    ax.hist(writes, bins=10, edgecolor="black")

    ax.grid(which="major", axis="both", linestyle="--")
    ax.set_title(title, fontsize=14)
    ax.set_xlabel("Latency (w_await) non-zero w/s values only", fontsize=10)
    ax.set_ylabel("Frequency", fontsize=10)

    ax.tick_params(labelsize=10)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    # plt.tight_layout()

    output_name = f"Write Latency Histogram"
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}_{device}_z_{output_name}.png", format="png", dpi=100)
    plt.close("all")


def chart_vmstat(connection, filepath, output_prefix, png_out):
    # print(f"vmstat...")
    # Get useful
    customer = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'customer';")[2]
    number_cpus = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'number cpus';")[2]
    processor = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'processor model';")[2]

    if execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'operating system';")[2] == "AIX":
        aix_cpus = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'AIX SMT';")[2]
        processor += f" SMT {aix_cpus}"

    # Read in to dataframe
    df = pd.read_sql_query("SELECT * FROM vmstat", connection)

    # Add a new total CPU column, add a datetime column
    df["Total CPU"] = 100 - df["id"]
    df["datetime"] = df["RunDate"] + " " + df["RunTime"]

    # Create stacked CPU chart if columns exist
    if png_out:
        if "sy" in df.columns and "wa" in df.columns and "us" in df.columns:
            title = f"CPU utilisation % - {customer}"
            title += f"\n{number_cpus} cores ({processor})"
            simple_chart_stacked(df, "sy, wa, us", title, 100, filepath, output_prefix)

    # Format the data for Altair
    # Cut down the df to just the list of categorical data we care about (columns)
    columns_to_chart = list(df.columns)
    unwanted_columns = ["id_key", "RunDate", "RunTime", "html name", "hr"]
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

            if png_out:
                simple_chart(data, column_name, title, max_y, filepath, output_prefix)
            else:
                linked_chart(data, column_name, title, max_y, filepath, output_prefix)


def chart_mgstat(connection, filepath, output_prefix, png_out):
    # print(f"mgstat...")

    customer = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'customer';")[2]

    # Read in to dataframe
    df = pd.read_sql_query("SELECT * FROM mgstat", connection)

    # hack until good way to detect date format is mmm/dd/yyyy or not
    if False:
        df["RunDate"] = df.apply(lambda row: make_mdy_date(row["RunDate"]), axis=1)

    # Add a datetime column
    df["datetime"] = df["RunDate"] + " " + df["RunTime"]

    # Format the data for Altair
    # Cut down the df to just the the list of categorical data we care about (columns)
    columns_to_chart = list(df.columns)
    unwanted_columns = ["id_key", "RunDate", "RunTime", "html name"]
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

            if png_out:
                simple_chart(data, column_name, title, max_y, filepath, output_prefix)
            else:
                linked_chart(data, column_name, title, max_y, filepath, output_prefix)


def chart_perfmon(connection, filepath, output_prefix, png_out):
    # print(f"perfmon...")

    customer = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'customer';")[2]
    number_cpus = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'number cpus';")[2]

    # Read in to dataframe, drop any bad rows
    df = pd.read_sql_query("SELECT * FROM perfmon", connection)
    df.dropna(inplace=True)

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

            if png_out:
                simple_chart(data, column_name, title, max_y, filepath, output_prefix)
            else:
                linked_chart(data, column_name, title, max_y, filepath, output_prefix)


def chart_iostat(connection, filepath, output_prefix, operating_system, png_out, disk_list):
    # print(f"iostat...")

    customer = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'customer';")[2]

    # Read in to dataframe, drop any bad rows
    df = pd.read_sql_query("SELECT * FROM iostat", connection)
    df.dropna(inplace=True)

    if "r/s" in df.columns and "w/s" in df.columns:
        df["Total IOPS"] = df["r/s"] + df["w/s"]

    # If there is no date and time in iostat then just use index as x axis
    if "RunDate" in df.columns:
        df["datetime"] = df["RunDate"] + " " + df["RunTime"]

        # Format the data for Altair
        # Cut down the df to just the list of categorical data we care about (columns)
        columns_to_chart = list(df.columns)
        unwanted_columns = ["id_key", "RunDate", "RunTime", "html name"]
        columns_to_chart = [ele for ele in columns_to_chart if ele not in unwanted_columns]

        iostat_df = df[columns_to_chart]
        devices = iostat_df["Device"].unique()

        # If a disk list has been passed in. Validate the list.

        if disk_list:
            disk_list = list(set(disk_list).intersection(devices))
            if disk_list:
                # print(f"Only devices: {disk_list}")
                devices = disk_list

        # Chart each disk
        for device in devices:

            device_df = iostat_df.loc[iostat_df["Device"] == device]

            # Create stacked read write chart if columns exist
            if png_out:
                if "r/s" in device_df.columns and "w/s" in device_df.columns:
                    title = f"{device} : Total IOPS - {customer}"
                    simple_chart_stacked_iostat(device_df, "r/s, w/s", device, title, 0, filepath, output_prefix)

                if "r_await" in device_df.columns and "w_await" in device_df.columns:
                    title = f"{device} : Latency - {customer}"
                    simple_chart_histogram_iostat(device_df, device, title, filepath, output_prefix)

            # unpivot the dataframe; first column is date time column, column name is next, then the value in that
            # column
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

                    if png_out:
                        simple_chart(data, column_name, title, max_y, filepath, output_prefix, file_prefix=device)
                    else:
                        linked_chart(data, column_name, title, max_y, filepath, output_prefix, file_prefix=device)

                        if False:
                            interactive_chart(
                                data, column_name, title, max_y, filepath, output_prefix, file_prefix=device
                            )

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

                    if png_out:
                        pass
                    else:
                        linked_chart_no_time(
                            data, column_name, title, max_y, filepath, output_prefix, file_prefix=device
                        )


def chart_nfsiostat(connection, filepath, output_prefix, operating_system, png_out):
    # print(f"iostat...")

    customer = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'customer';")[2]

    # Read in to dataframe, drop any bad rows
    df = pd.read_sql_query("SELECT * FROM nfsiostat", connection)
    df.dropna(inplace=True)

    # No date or time, chart all columns, index is x axis
    columns_to_chart = list(df.columns)
    unwanted_columns = ["id_key", "html name", "Host", "Device", "Mounted on"]
    columns_to_chart = [ele for ele in columns_to_chart if ele not in unwanted_columns]

    nfsiostat_df = df
    devices = nfsiostat_df["Device"].unique()

    # Chart each disk
    for device in devices:
        device_df = nfsiostat_df.loc[nfsiostat_df["Device"] == device]

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

                if png_out:
                    simple_chart_no_time(
                        data, column_name, title, max_y, filepath, output_prefix, file_prefix=device.replace("/", "_")
                    )
                else:
                    linked_chart_no_time(
                        data, column_name, title, max_y, filepath, output_prefix, file_prefix=device.replace("/", "_")
                    )


def chart_aix_sar_d(connection, filepath, output_prefix, operating_system, png_out, disk_list):

    customer = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'customer';")[2]

    # Read in to dataframe, drop any bad rows
    df = pd.read_sql_query("SELECT * FROM aix_sar_d", connection)
    df.dropna(inplace=True)

    # df["datetime"] = df["RunDate"] + " " + df["RunTime"]

    columns_to_chart = list(df.columns)
    unwanted_columns = ["id_key", "RunDate", "RunTime", "html name", "device"]
    columns_to_chart = [ele for ele in columns_to_chart if ele not in unwanted_columns]

    aix_sar_d_df = df
    devices = aix_sar_d_df["device"].unique()

    # If a disk list has been passed in. Validate the list.
    if disk_list:
        disk_list = list(set(disk_list).intersection(devices))
        if disk_list:
            # print(f"Only devices: {disk_list}")
            devices = disk_list

    # Chart each disk
    for device in devices:
        device_df = aix_sar_d_df.loc[aix_sar_d_df["device"] == device]

        # unpivot the dataframe; first column is index, column name is next, then the value in that column
        device_df = device_df.melt("datetime", var_name="Type", value_name="metric")

        # For each column create a chart
        for column_name in columns_to_chart:
            if column_name == "datetime" or column_name == "device":
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

                if png_out:
                    simple_chart(data, column_name, title, max_y, filepath, output_prefix, file_prefix=device)
                else:
                    linked_chart(data, column_name, title, max_y, filepath, output_prefix, file_prefix=device)

                    if False:
                        interactive_chart(data, column_name, title, max_y, filepath, output_prefix, file_prefix=device)


def mainline(
    input_file,
    include_iostat,
    include_nfsiostat,
    append_to_database,
    existing_database,
    output_prefix,
    csv_out,
    png_out,
    system_out,
    disk_list,
    split_on,
):
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

    # This is a hidden option for now. Only activated if the yml file exists
    extended_charts = False
    if os.path.isfile(f"{filepath}/site_survey_input.yml"):
        extended_charts = True
        # print("Extended charts included...")
    else:
        # print(f"Extended charts not included...")
        pass

    # get the prefix
    html_filename = filename.split(".")[0]

    if output_prefix is None:
        output_prefix = f"{html_filename}_"
    else:
        if output_prefix != "":
            output_prefix = f"{output_prefix}_"

    output_filepath_prefix = f"{filepath}/{output_prefix}"

    if split_on is not None:
        split_large_file.split_large_file(input_file, split_string=split_on)

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
            create_sections(
                connection,
                input_file,
                include_iostat,
                include_nfsiostat,
                html_filename,
                csv_out,
                output_filepath_prefix,
                disk_list,
            )

    else:
        if database_action == "Chart only":
            input_error = True
            print(f"No data to chart")
        else:

            # Create a system summary
            sp_dict = sp_check.system_check(input_file)

            if system_out:
                output_log, yaspe_yaml = sp_check.build_log(sp_dict)

                with open(f"{output_filepath_prefix}overview.txt", "w") as text_file:
                    print(f"{output_log}", file=text_file)

                # Simple dump of all data in overview
                overview_df = pd.DataFrame(list(sp_dict.items()), columns=["key", "value"])
                overview_df.to_csv(
                    f"{output_filepath_prefix}overview_all.csv", header=True, index=False, sep=",", mode="w"
                )

                # yaml file for pretty input
                with open(f"{output_filepath_prefix}overview.yaml", "w") as text_file:
                    print(f"{yaspe_yaml}", file=text_file)

            create_overview(connection, sp_dict)
            create_sections(
                connection,
                input_file,
                include_iostat,
                include_nfsiostat,
                html_filename,
                csv_out,
                output_filepath_prefix,
                disk_list,
            )

    connection.close()

    # Charting is separate

    if "Chart" in database_action and not input_error:

        # print("Charting...")

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
        chart_mgstat(connection, output_file_path, output_prefix, png_out)

        # vmstat and iostat
        if operating_system == "Linux" or operating_system == "Ubuntu" or operating_system == "AIX":

            # Detailed system charts for performance reports
            if extended_charts:
                system_review.system_charts(filepath)

            output_file_path = f"{output_file_path_base}/vmstat/"
            if not os.path.isdir(output_file_path):
                os.mkdir(output_file_path)
            chart_vmstat(connection, output_file_path, output_prefix, png_out)

            if include_iostat:
                output_file_path = f"{output_file_path_base}/iostat/"
                if not os.path.isdir(output_file_path):
                    os.mkdir(output_file_path)
                chart_iostat(connection, output_file_path, output_prefix, operating_system, png_out, disk_list)

                if operating_system == "AIX":
                    output_file_path = f"{output_file_path_base}/sar_d/"
                    if not os.path.isdir(output_file_path):
                        os.mkdir(output_file_path)
                    chart_aix_sar_d(connection, output_file_path, output_prefix, operating_system, png_out, disk_list)

            if include_nfsiostat:
                output_file_path = f"{output_file_path_base}/nfsiostat/"
                if not os.path.isdir(output_file_path):
                    os.mkdir(output_file_path)
                chart_nfsiostat(connection, output_file_path, output_prefix, operating_system, png_out)

        if operating_system == "Windows":
            output_file_path = f"{output_file_path_base}/perfmon/"
            if not os.path.isdir(output_file_path):
                os.mkdir(output_file_path)
            chart_perfmon(connection, output_file_path, output_prefix, png_out)

        connection.close()

    return


# Start here, entry point for command line

if __name__ == "__main__":

    input_file = ""
    existing_database = ""

    parser = argparse.ArgumentParser(
        prog="yaspe", description="Performance file review.", epilog='Be safe, "quote the path"'
    )

    current_version = "0.2.21"
    parser.add_argument("-v", "--version", action="version", version=current_version)

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
        "-n",
        "--nfsiostat",
        dest="include_nfsiostat",
        help="Also plot nfsiostat data.",
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
        "-p",
        "--png",
        dest="png_out",
        help="Create png files of metrics. Instead of html",
        action="store_true",
    )

    parser.add_argument(
        "-s",
        "--system",
        dest="system_out",
        help="Output system overview. ",
        action="store_true",
    )

    parser.add_argument(
        "-d",
        "--disk_list",
        nargs="+",
        default=[],
        help="List of disks, if not entered all are processed. No commas or quotes, e.g. -d dm-0 dm-1",
    )

    parser.add_argument(
        "-l",
        "--large_file_split_on_string",
        dest="split_on",
        help='Split large input file on first occurrence of this string. Blank -l "" defaults to "div id=iostat"',
        action="store",
        metavar='"string to split on"',
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

    # yaml input
    site_survey_input = {}

    try:
        mainline(
            input_file,
            args.include_iostat,
            args.include_nfsiostat,
            args.append_to_database,
            existing_database,
            args.output_prefix,
            args.csv_out,
            args.png_out,
            args.system_out,
            args.disk_list,
            args.split_on,
        )
    except OSError as e:
        print("Could not process files because: {}".format(str(e)))
