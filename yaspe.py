#!/usr/bin/env python3
"""
Extract sections of SystemPerformance file to SQL table.
Chart the results
"""

import sp_check
import cpf_disk_resolver
import split_large_file
import argparse
import os
import yaml

from datetime import datetime
from dateutil.parser import parse
from functools import lru_cache

import sqlite3
import sys
from sqlite3 import Error

import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as plt_dates

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from pandas.io.sql import DatabaseError
import warnings

from extract_sections import extract_sections
from extract_mgstat import extract_mgstat
import system_review
import yaspe_compare_overlay
import yaspe_combined_overlay

# Suppress FutureWarning messages
warnings.simplefilter(action="ignore", category=FutureWarning)


# Define a function to infer the date format
@lru_cache(maxsize=128)
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
        # Add pragma statements for performance
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA cache_size = 10000")
        connection.execute("PRAGMA temp_store = MEMORY")
    except Error as e:
        print(f"The error '{e}' occurred")

    return connection


def close_connection(connection):
    """Checkpoint the WAL, switch back to rollback journal, then close.
    Manually removes the -shm file that SQLite leaves behind even after
    switching journal modes."""
    if connection is None:
        return
    db_path = None
    try:
        db_path = connection.execute("PRAGMA database_list").fetchone()[2]
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode = DELETE")
    except Error:
        pass
    connection.close()
    if db_path:
        shm = db_path + "-shm"
        if os.path.exists(shm):
            try:
                os.remove(shm)
            except OSError:
                pass


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


def insert_dict_into_table(connection, table_name, _dict):
    # Make sure not an empty  line
    if _dict:
        keys = ", ".join('"' + item + '"' for item in _dict)
        question_marks = ",".join(list("?" * len(_dict)))
        values = tuple(_dict.values())

        connection.execute(f"INSERT INTO {table_name} ({keys}) VALUES ({question_marks})", values)


def align_table_columns(connection, table_name, df):
    """Before a to_sql append: ALTER TABLE ADD COLUMN for any DataFrame column
    the existing table lacks, so a day with new metrics doesn't abort the
    append ("table X has no column named Y"). Columns the DataFrame lacks are
    harmless — pandas inserts only the DataFrame's own columns and SQLite
    fills the rest with NULL. No-op if the table doesn't exist yet."""
    cursor = connection.cursor()
    cursor.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    if cursor.fetchone()[0] == 0:
        return
    existing = {row[1] for row in cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()}
    kind_to_sql = {"i": "INTEGER", "u": "INTEGER", "b": "INTEGER", "f": "REAL"}
    for column in df.columns:
        if column not in existing:
            sql_type = kind_to_sql.get(df[column].dtype.kind, "TEXT")
            cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{column}" {sql_type}')
    connection.commit()


def is_column_numeric(df, column_name):
    try:
        pd.to_numeric(df[column_name])
        return True
    except (ValueError, TypeError):
        return False


def create_mgstat(
    connection,
    input_file,
    html_filename,
    csv_out,
    output_filepath_prefix,
):
    # .mgst file processing

    mgstat_df, mgstat_text_description = extract_mgstat(html_filename, input_file)
    # Add each section to the database

    if not mgstat_df.empty:
        mgstat_df.to_sql("mgstat", connection, if_exists="append", index=True, index_label="id_key")
        connection.commit()

        if csv_out:
            mgstat_output_csv = f"{output_filepath_prefix}mgstat.csv"

            mgstat_df["RunDate"] = pd.to_datetime(mgstat_df["RunDate"])
            mgstat_df["RunDate"] = mgstat_df["RunDate"].dt.strftime("%m/%d/%Y")

            # if file does not exist write header
            if not os.path.isfile(mgstat_output_csv):
                mgstat_df.to_csv(mgstat_output_csv, header="column_names", index=False, encoding="utf-8")
            else:  # else it exists so append without writing the header
                mgstat_df.to_csv(mgstat_output_csv, mode="a", header=False, index=False, encoding="utf-8")

    return mgstat_text_description


def create_sections(
    connection,
    input_file,
    include_iostat,
    include_nfsiostat,
    html_filename,
    csv_out,
    output_filepath_prefix,
    disk_list,
    csv_date_format,
    all_disks=False,
):
    operating_system = execute_single_read_query(
        connection, "SELECT * FROM overview WHERE field = 'operating system';"
    )[2]

    # Get the start date for date format validation
    # profile_run = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'profile run';")[2]

    # Effective disk filter: explicit -d list wins; otherwise filter to
    # CPF-resolved IRIS devices unless --all-disks was given. On Linux/Ubuntu
    # this filters iostat devices; on Windows the CPF drive letters feed the
    # perfmon disk column filter instead. Non-IRIS files (no CPF roles in
    # overview) keep everything.
    effective_disk_list = disk_list
    if not disk_list and not all_disks and operating_system in ("Linux", "Ubuntu", "Windows"):
        auto_disk_list = get_cpf_auto_disk_list(connection)
        if auto_disk_list:
            print(f"Auto disk list from CPF (extraction): {auto_disk_list}")
            effective_disk_list = auto_disk_list

    mgstat_df, vmstat_df, iostat_df, nfsiostat_df, perfmon_df, aix_sar_d_df, free_df = extract_sections(
        operating_system, input_file, include_iostat, include_nfsiostat, html_filename, effective_disk_list
    )

    # Add each section to the database
    if not mgstat_df.empty:
        align_table_columns(connection, "mgstat", mgstat_df)
        mgstat_df.to_sql("mgstat", connection, if_exists="append", index=True, index_label="id_key")
        connection.commit()

        if csv_out:
            mgstat_output_csv = f"{output_filepath_prefix}mgstat.csv"

            if csv_date_format:
                mgstat_df["RunDate"] = pd.to_datetime(mgstat_df["RunDate"])
                mgstat_df["RunDate"] = mgstat_df["RunDate"].dt.strftime("%d/%m/%Y")

            # if file does not exist write header
            if not os.path.isfile(mgstat_output_csv):
                mgstat_df.to_csv(mgstat_output_csv, header="column_names", index=False, encoding="utf-8")
            else:  # else it exists so append without writing the header
                mgstat_df.to_csv(mgstat_output_csv, mode="a", header=False, index=False, encoding="utf-8")

    if not vmstat_df.empty:
        align_table_columns(connection, "vmstat", vmstat_df)
        vmstat_df.to_sql("vmstat", connection, if_exists="append", index=True, index_label="id_key")
        connection.commit()

        if csv_out:
            vmstat_output_csv = f"{output_filepath_prefix}vmstat.csv"

            if csv_date_format:
                vmstat_df["RunDate"] = pd.to_datetime(vmstat_df["RunDate"])
                vmstat_df["RunDate"] = vmstat_df["RunDate"].dt.strftime("%d/%m/%Y")

            # if file does not exist write header
            if not os.path.isfile(vmstat_output_csv):
                vmstat_df.to_csv(vmstat_output_csv, header="column_names", index=False, encoding="utf-8")
            else:  # else it exists so append without writing the header
                vmstat_df.to_csv(vmstat_output_csv, mode="a", header=False, index=False, encoding="utf-8")

    if not perfmon_df.empty:
        align_table_columns(connection, "perfmon", perfmon_df)
        perfmon_df.to_sql("perfmon", connection, if_exists="append", index=True, index_label="id_key")
        connection.commit()

        if csv_out:
            perfmon_output_csv = f"{output_filepath_prefix}perfmon.csv"

            # if csv_date_format:
            #     perfmon_df["RunDate"] = pd.to_datetime(perfmon_df["RunDate"])
            #     perfmon_df["RunDate"] = perfmon_df["RunDate"].dt.strftime("%d/%m/%Y")

            # if file does not exist write header
            if not os.path.isfile(perfmon_output_csv):
                perfmon_df.to_csv(perfmon_output_csv, header="column_names", index=False, encoding="utf-8")
            else:  # else it exists so append without writing the header
                perfmon_df.to_csv(perfmon_output_csv, mode="a", header=False, index=False, encoding="utf-8")

    if not iostat_df.empty:
        # id_key is used when there is no time
        align_table_columns(connection, "iostat", iostat_df)
        iostat_df.to_sql("iostat", connection, if_exists="append", index=True, index_label="id_key")
        connection.commit()

        if csv_out:
            iostat_output_csv = f"{output_filepath_prefix}iostat.csv"

            if csv_date_format:
                iostat_df["RunDate"] = pd.to_datetime(iostat_df["RunDate"])
                iostat_df["RunDate"] = iostat_df["RunDate"].dt.strftime("%d/%m/%Y")

            # if file does not exist write header
            if not os.path.isfile(iostat_output_csv):
                iostat_df.to_csv(iostat_output_csv, header="column_names", index=False, encoding="utf-8")
            else:  # else it exists so append without writing the header
                iostat_df.to_csv(iostat_output_csv, mode="a", header=False, index=False, encoding="utf-8")

    if not nfsiostat_df.empty:
        # id_key is used when there is no time
        align_table_columns(connection, "nfsiostat", nfsiostat_df)
        nfsiostat_df.to_sql("nfsiostat", connection, if_exists="append", index=True, index_label="id_key")
        connection.commit()

        if csv_out:
            nfsiostat_output_csv = f"{output_filepath_prefix}nfsiostat.csv"

            if csv_date_format:
                nfsiostat_df["RunDate"] = pd.to_datetime(nfsiostat_df["RunDate"])
                nfsiostat_df["RunDate"] = nfsiostat_df["RunDate"].dt.strftime("%d/%m/%Y")

            # if file does not exist write header
            if not os.path.isfile(nfsiostat_output_csv):
                nfsiostat_df.to_csv(nfsiostat_output_csv, header="column_names", index=False, encoding="utf-8")
            else:  # else it exists so append without writing the header
                nfsiostat_df.to_csv(nfsiostat_output_csv, mode="a", header=False, index=False, encoding="utf-8")

    if not aix_sar_d_df.empty:
        align_table_columns(connection, "aix_sar_d", aix_sar_d_df)
        aix_sar_d_df.to_sql("aix_sar_d", connection, if_exists="append", index=True, index_label="id_key")
        connection.commit()

        if csv_out:
            aix_sar_d_output_csv = f"{output_filepath_prefix}aix_sar_d.csv"

            if csv_date_format:
                aix_sar_d_df["RunDate"] = pd.to_datetime(aix_sar_d_df["RunDate"])
                aix_sar_d_df["RunDate"] = aix_sar_d_df["RunDate"].dt.strftime("%d/%m/%Y")

            # if file does not exist write header
            if not os.path.isfile(aix_sar_d_output_csv):
                aix_sar_d_df.to_csv(aix_sar_d_output_csv, header="column_names", index=False, encoding="utf-8")
            else:  # else it exists so append without writing the header
                aix_sar_d_df.to_csv(aix_sar_d_output_csv, mode="a", header=False, index=False, encoding="utf-8")

    if not free_df.empty:
        align_table_columns(connection, "free_memory", free_df)
        free_df.to_sql("free_memory", connection, if_exists="append", index=True, index_label="id_key")
        connection.commit()

        if csv_out:
            free_output_csv = f"{output_filepath_prefix}free.csv"

            if csv_date_format:
                free_df["RunDate"] = pd.to_datetime(free_df["RunDate"])
                free_df["RunDate"] = free_df["RunDate"].dt.strftime("%d/%m/%Y")

            # if file does not exist write header
            if not os.path.isfile(free_output_csv):
                free_df.to_csv(free_output_csv, header="column_names", index=False, encoding="utf-8")
            else:  # else it exists so append without writing the header
                free_df.to_csv(free_output_csv, mode="a", header=False, index=False, encoding="utf-8")


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

    # Create the insert query string; skip non-scalar values (e.g. lists)
    for key in sp_dict:
        value = sp_dict[key]
        if not isinstance(value, (str, int, float, type(None))):
            continue
        cursor.execute("INSERT INTO overview (field, value) VALUES (?, ?)", (key, value))
        connection.commit()

    return


def get_cpf_auto_disk_list(connection):
    """Devices for IRIS disk roles resolved from the CPF, as stored in the
    overview table by create_overview. Order: Database 0..N, then Primary
    Journal, Alternate Journal, WIJ. Empty list if no roles were stored."""
    devices = []
    i = 0
    while True:
        row = execute_single_read_query(
            connection, f"SELECT * FROM overview WHERE field = 'iris disk role Database {i}';"
        )
        if not row or not row[2]:
            break
        if row[2] not in devices:
            devices.append(row[2])
        i += 1
    for role in ("Primary Journal", "Alternate Journal", "WIJ"):
        row = execute_single_read_query(
            connection, f"SELECT * FROM overview WHERE field = 'iris disk role {role}';"
        )
        if row and row[2] and row[2] not in devices:
            devices.append(row[2])
    return devices


def get_chart_title_base(connection):
    """Return chart title base: 'customer (hostname / instance)' with graceful fallbacks."""
    def _query(field):
        row = execute_single_read_query(connection, f"SELECT * FROM overview WHERE field = '{field}';")
        return row[2] if row else None

    customer = _query("customer")
    if not customer:
        return ""

    hostname = _query("linux hostname") or _query("windows host name")
    if not hostname:
        return customer

    instance = _query("instance")
    if instance:
        return f"{customer} ({hostname} / {instance})"
    return f"{customer} ({hostname})"


def _find_peak_60_window(png_data, datetime_column):
    """Find the peak 60-minute window for the data. Returns (peak_start_time, peak_end_time) or (None, None)."""
    from datetime import timedelta

    if len(png_data) < 2:
        return None, None

    # Sort data by datetime to ensure proper rolling window calculation
    sorted_data = png_data.sort_values(by=datetime_column).copy()

    # Set the datetime column as index for rolling operations
    sorted_data = sorted_data.set_index(datetime_column)

    # Compute min_periods from the actual sampling interval so that a window
    # must contain at least 50 minutes of data before it can be considered the peak.
    # This prevents a short early spike (e.g. 15 min of data) from beating a genuine
    # sustained 60-minute period later in the day.
    time_diffs = sorted_data.index.to_series().diff().dropna()
    if len(time_diffs) > 0:
        median_interval_secs = time_diffs.median().total_seconds()
        min_periods = max(10, int(50 * 60 / median_interval_secs))
    else:
        min_periods = 30
    rolling_mean = sorted_data["metric"].rolling(window="60min", min_periods=min_periods).mean()

    # Find the end time of the peak 60-minute window
    peak_end_time = rolling_mean.idxmax()
    peak_start_time = peak_end_time - timedelta(minutes=60)

    return peak_start_time, peak_end_time


def _ordinal(n):
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _create_peak_60_chart(
    png_data, column_name, title, max_y, filepath, output_prefix, file_prefix, datetime_column, line_chart=True
):
    """Create a chart showing only the peak 60 minutes for the column. Returns (peak_start_time, peak_end_time)."""
    from datetime import timedelta

    # Find the peak window
    peak_start_time, peak_end_time = _find_peak_60_window(png_data, datetime_column)

    if peak_start_time is None:
        return None, None

    # Sort and filter data to peak window
    sorted_data = png_data.sort_values(by=datetime_column).copy()
    sorted_data = sorted_data.set_index(datetime_column)

    # Get the actual data boundaries
    min_data_time = sorted_data.index.min()
    max_data_time = sorted_data.index.max()

    # Adjust filter range to actual data boundaries while maintaining 60-minute window
    # If peak_start_time is before data starts, shift the window forward
    if peak_start_time < min_data_time:
        chart_start_time = min_data_time
        chart_end_time = min(min_data_time + timedelta(minutes=60), max_data_time)
    # If peak_end_time is after data ends, shift the window backward
    elif peak_end_time > max_data_time:
        chart_end_time = max_data_time
        chart_start_time = max(max_data_time - timedelta(minutes=60), min_data_time)
    else:
        chart_start_time = peak_start_time
        chart_end_time = peak_end_time

    # Filter data to the adjusted peak window
    peak_data = sorted_data.loc[chart_start_time:chart_end_time].copy()

    # Reset index to get datetime column back
    peak_data = peak_data.reset_index()

    if len(peak_data) < 2:
        # Not enough data points for a meaningful chart
        return None, None

    colormap_name = "Set1"
    plt.style.use("seaborn-v0_8-whitegrid")

    palette = plt.get_cmap(colormap_name)
    color = palette(1)

    fig, ax = plt.subplots(figsize=(16, 6))

    # Choose plot style based on line_chart option
    if line_chart:
        ax.plot(
            peak_data[datetime_column],
            peak_data["metric"],
            label=column_name,
            color=color,
            marker="",
            linestyle="-",
            alpha=0.7,
            linewidth=1,
        )
    else:
        ax.plot(
            peak_data[datetime_column],
            peak_data["metric"],
            label=column_name,
            color=color,
            marker=".",
            linestyle="none",
            alpha=0.7,
        )

    # Add min/max lines for the peak period
    abs_min = peak_data["metric"].min()
    abs_max = peak_data["metric"].max()

    # For the peak window, use percentile filtering
    p2 = peak_data["metric"].quantile(0.02)
    p99 = peak_data["metric"].quantile(0.99)

    filtered_data = peak_data[(peak_data["metric"] >= p2) & (peak_data["metric"] <= p99)]
    has_outliers = len(filtered_data) < len(peak_data)

    if has_outliers and len(filtered_data) > 0:
        adj_min = filtered_data["metric"].min()
        adj_max = filtered_data["metric"].max()

        if abs_min > 0:
            ax.axhline(y=abs_min, color="darkred", linestyle=":", alpha=0.7, label=f"Abs Min: {abs_min:,.0f}")
        if adj_min > 0:
            ax.axhline(y=adj_min, color="red", linestyle="--", alpha=0.7,
                       label=f"98th pct Min (outliers removed): {adj_min:,.0f}")
        if abs_max > 0:
            ax.axhline(y=abs_max, color="darkgreen", linestyle=":", alpha=0.7, label=f"Abs Max: {abs_max:,.0f}")
        if adj_max > 0:
            ax.axhline(y=adj_max, color="green", linestyle="--", alpha=0.7,
                       label=f"99th pct Max (outliers removed): {adj_max:,.0f}")
    else:
        if abs_min > 0:
            ax.axhline(y=abs_min, color="red", linestyle="--", alpha=0.7, label=f"Min: {abs_min:,.0f}")
        ax.axhline(y=abs_max, color="green", linestyle="--", alpha=0.7, label=f"Max: {abs_max:,.0f}")

    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", borderaxespad=0, fontsize=11)
    ax.grid(which="major", axis="both", linestyle="--")

    # Format title with peak period time range (using adjusted chart times)
    chart_start_str = chart_start_time.strftime("%H:%M")
    chart_end_str = chart_end_time.strftime("%H:%M")
    date_str = chart_start_time.strftime("%a %d-%b-%y")
    ax.set_title(f"{title} - Peak 60 min ({chart_start_str} to {chart_end_str}) - {date_str}", fontsize=16)

    ax.set_ylabel(column_name, fontsize=14)
    ax.tick_params(labelsize=14)
    plt.subplots_adjust(bottom=0.15)
    ax.set_ylim(bottom=0)
    if max_y != 0:
        ax.set_ylim(top=max_y)

    cpu_names = ["wa", "sy", "us"]
    if (
        peak_data["metric"].max() > 5
        or "%" in column_name
        or column_name in cpu_names
        or peak_data["metric"].max() == 0
    ):
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))
    elif peak_data["metric"].max() < 0.002:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.4f}"))
    else:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.3f}"))

    locator = plt_dates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(plt_dates.DateFormatter("%H:%M"))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    output_name = column_name.replace("/", "_")
    plt.tight_layout()
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}_peak60.png", format="png", dpi=150, bbox_inches="tight")
    plt.close("all")

    return peak_start_time, peak_end_time


def _create_business_hours_peak_chart(
    png_data, column_name, title, max_y, filepath, output_prefix, file_prefix, datetime_column, line_chart=True,
    bh_start=8, bh_end=18
):
    """Create a peak 60-min chart restricted to business hours (default 08:00-18:00).
    Returns (peak_start_time, peak_end_time) or (None, None)."""
    from datetime import timedelta

    sorted_data = png_data.sort_values(by=datetime_column).copy()
    sorted_data = sorted_data.set_index(datetime_column)

    # Filter to business hours only for peak detection
    bh_data = sorted_data.between_time(f"{bh_start:02d}:00", f"{bh_end:02d}:00")

    if len(bh_data) < 10:
        return None, None

    # Compute min_periods from actual sampling interval
    time_diffs = bh_data.index.to_series().diff().dropna()
    if len(time_diffs) > 0:
        median_interval_secs = time_diffs.median().total_seconds()
        min_periods = max(10, int(50 * 60 / median_interval_secs)) if median_interval_secs > 0 else 30
    else:
        min_periods = 30

    rolling_mean = bh_data["metric"].rolling(window="60min", min_periods=min_periods).mean()

    if rolling_mean.isna().all():
        return None, None

    peak_end_time = rolling_mean.idxmax()
    peak_start_time = peak_end_time - timedelta(minutes=60)

    # Clamp to actual data boundaries
    min_data_time = sorted_data.index.min()
    max_data_time = sorted_data.index.max()
    if peak_start_time < min_data_time:
        peak_start_time = min_data_time
        peak_end_time = min(min_data_time + timedelta(minutes=60), max_data_time)
    elif peak_end_time > max_data_time:
        peak_end_time = max_data_time
        peak_start_time = max(max_data_time - timedelta(minutes=60), min_data_time)

    peak_data = sorted_data.loc[peak_start_time:peak_end_time].copy().reset_index()

    if len(peak_data) < 2:
        return None, None

    colormap_name = "Set1"
    plt.style.use("seaborn-v0_8-whitegrid")

    palette = plt.get_cmap(colormap_name)
    color = palette(3)  # Distinct colour from peak60 (palette(1)) and glorefs (palette(2))

    fig, ax = plt.subplots(figsize=(16, 6))

    if line_chart:
        ax.plot(peak_data[datetime_column], peak_data["metric"],
                label=column_name, color=color, marker="", linestyle="-", alpha=0.7, linewidth=1)
    else:
        ax.plot(peak_data[datetime_column], peak_data["metric"],
                label=column_name, color=color, marker=".", linestyle="none", alpha=0.7)

    abs_min = peak_data["metric"].min()
    abs_max = peak_data["metric"].max()
    p2 = peak_data["metric"].quantile(0.02)
    p99 = peak_data["metric"].quantile(0.99)
    filtered_data = peak_data[(peak_data["metric"] >= p2) & (peak_data["metric"] <= p99)]
    has_outliers = len(filtered_data) < len(peak_data)

    if has_outliers and len(filtered_data) > 0:
        adj_min = filtered_data["metric"].min()
        adj_max = filtered_data["metric"].max()
        if abs_min > 0:
            ax.axhline(y=abs_min, color="darkred", linestyle=":", alpha=0.7, label=f"Abs Min: {abs_min:,.0f}")
        if adj_min > 0:
            ax.axhline(y=adj_min, color="red", linestyle="--", alpha=0.7,
                       label=f"98th pct Min (outliers removed): {adj_min:,.0f}")
        if abs_max > 0:
            ax.axhline(y=abs_max, color="darkgreen", linestyle=":", alpha=0.7, label=f"Abs Max: {abs_max:,.0f}")
        if adj_max > 0:
            ax.axhline(y=adj_max, color="green", linestyle="--", alpha=0.7,
                       label=f"99th pct Max (outliers removed): {adj_max:,.0f}")
    else:
        if abs_min > 0:
            ax.axhline(y=abs_min, color="red", linestyle="--", alpha=0.7, label=f"Min: {abs_min:,.0f}")
        ax.axhline(y=abs_max, color="green", linestyle="--", alpha=0.7, label=f"Max: {abs_max:,.0f}")

    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", borderaxespad=0, fontsize=11)
    ax.grid(which="major", axis="both", linestyle="--")

    chart_start_str = peak_start_time.strftime("%H:%M")
    chart_end_str = peak_end_time.strftime("%H:%M")
    date_str = peak_start_time.strftime("%a %d-%b-%y")
    ax.set_title(
        f"{title} - BH Peak {chart_start_str}-{chart_end_str} - {date_str}",
        fontsize=16,
    )

    ax.set_ylabel(column_name, fontsize=14)
    ax.tick_params(labelsize=14)
    plt.subplots_adjust(bottom=0.15)
    ax.set_ylim(bottom=0)
    if max_y != 0:
        ax.set_ylim(top=max_y)

    cpu_names = ["wa", "sy", "us"]
    if peak_data["metric"].max() > 5 or "%" in column_name or column_name in cpu_names or peak_data["metric"].max() == 0:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))
    elif peak_data["metric"].max() < 0.002:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.4f}"))
    else:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.3f}"))

    locator = plt_dates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(plt_dates.DateFormatter("%H:%M"))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    output_name = column_name.replace("/", "_")
    plt.tight_layout()
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}_bh_peak.png", format="png", dpi=150, bbox_inches="tight")
    plt.close("all")

    return peak_start_time, peak_end_time


def _create_daily_summary_chart(png_data, column_name, title, max_y, filepath, output_prefix, file_prefix, datetime_column):
    """Bar chart: 99th percentile value per calendar day. Highlights the busiest day in red."""
    sorted_data = png_data.set_index(datetime_column)["metric"].sort_index()
    daily = sorted_data.groupby(sorted_data.index.date).quantile(0.99)

    if len(daily) < 2:
        return

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(16, 6))

    colors = ["steelblue"] * len(daily)
    colors[int(daily.values.argmax())] = "tomato"

    x_pos = range(len(daily))
    bars = ax.bar(x_pos, daily.values, color=colors, alpha=0.85, edgecolor="white")
    ax.set_xticks(list(x_pos))
    ax.set_xticklabels([str(d) for d in daily.index])
    for bar, val in zip(bars, daily.values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.01,
                f"{val:,.0f}", ha="center", va="bottom", fontsize=10)

    ax.set_ylim(bottom=0)
    if max_y > 0:
        ax.set_ylim(top=max_y)

    cpu_names = ["wa", "sy", "us"]
    if daily.max() > 5 or "%" in column_name or column_name in cpu_names:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))
    else:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.3f}"))

    start_str = sorted_data.index.min().strftime("%d-%b-%y")
    end_str = sorted_data.index.max().strftime("%d-%b-%y")
    ax.set_title(f"{title} - Daily 99th pct ({start_str} to {end_str})", fontsize=16)
    ax.set_ylabel(column_name, fontsize=14)
    ax.set_xlabel("Date", fontsize=12)
    ax.tick_params(labelsize=12)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")

    output_name = column_name.replace("/", "_")
    plt.tight_layout()
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}_daily_summary.png", format="png", dpi=150, bbox_inches="tight")
    plt.close("all")


def _create_heatmap_chart(png_data, column_name, title, filepath, output_prefix, file_prefix, datetime_column):
    """Heatmap: hour-of-day (x) × date (y), colour = 99th pct. Shows consistent peak hours across days."""
    sorted_data = png_data.set_index(datetime_column)["metric"].sort_index()
    df = sorted_data.to_frame("metric")
    df["date"] = df.index.date
    df["hour"] = df.index.hour

    pivot = df.groupby(["date", "hour"])["metric"].quantile(0.99).unstack(fill_value=0)

    if pivot.shape[0] < 2:
        return

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(16, max(4, pivot.shape[0] * 0.7)))

    im = ax.imshow(pivot.values, aspect="auto", cmap="YlOrRd", interpolation="nearest")
    ax.set_xticks(range(24))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(24)], rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([pd.Timestamp(d).strftime("%a %d-%b") for d in pivot.index], fontsize=11)

    cbar = plt.colorbar(im, ax=ax, fraction=0.02, pad=0.02)
    cbar.set_label(f"{column_name} (99th pct)", fontsize=11)

    start_str = sorted_data.index.min().strftime("%d-%b-%y")
    end_str = sorted_data.index.max().strftime("%d-%b-%y")
    ax.set_title(f"{title} - Hourly 99th pct Heatmap ({start_str} to {end_str})", fontsize=16)
    ax.set_xlabel("Hour of day", fontsize=12)

    output_name = column_name.replace("/", "_")
    plt.tight_layout()
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}_heatmap.png", format="png", dpi=150, bbox_inches="tight")
    plt.close("all")


def _create_5min_avg_chart(png_data, column_name, title, max_y, filepath, output_prefix, file_prefix, datetime_column, avg_minutes=5):
    """Long-period chart smoothed to a rolling N-minute average (default 5 min). Same layout as the 30-min chart."""
    from datetime import timedelta

    sorted_data = png_data.set_index(datetime_column)["metric"].sort_index()
    time_diffs = sorted_data.index.to_series().diff().dropna()
    if len(time_diffs) > 0:
        interval_secs = time_diffs.median().total_seconds()
        window = max(2, int(avg_minutes * 60 / interval_secs)) if interval_secs > 0 else max(2, avg_minutes)
    else:
        interval_secs = 0
        window = max(2, avg_minutes)

    smoothed = sorted_data.rolling(window=window, center=True, min_periods=1).mean()

    if interval_secs >= 60:
        sample_label = f"{int(round(interval_secs / 60))}m samples"
    elif interval_secs > 0:
        sample_label = f"{int(round(interval_secs))}s samples"
    else:
        sample_label = "samples"

    plt.style.use("seaborn-v0_8-whitegrid")
    palette = plt.get_cmap("Set1")
    color = palette(1)
    fig, ax = plt.subplots(figsize=(16, 6))

    ax.plot(sorted_data.index, sorted_data.values, color=color, alpha=0.15, linewidth=0.5, label="_raw")
    ax.plot(smoothed.index, smoothed.values, color=color, alpha=0.85, linewidth=1.5,
            label=f"{column_name} ({sample_label}, {avg_minutes} min avg)")

    ax.set_ylim(bottom=0)
    if max_y != 0:
        ax.set_ylim(top=max_y)

    cpu_names = ["wa", "sy", "us"]
    if png_data["metric"].max() > 5 or "%" in column_name or column_name in cpu_names or png_data["metric"].max() == 0:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))
    elif png_data["metric"].max() < 0.002:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.4f}"))
    else:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.3f}"))

    start_date = png_data[datetime_column].min()
    end_date = png_data[datetime_column].max()
    start_str = start_date.strftime("%d-%b-%y")
    end_str = end_date.strftime("%d-%b-%y")
    ax.set_title(f"{title} - {start_str} to {end_str} ({avg_minutes} min avg)", fontsize=16)

    _shade_days(ax, start_date, end_date)

    ax.xaxis.set_major_locator(plt_dates.HourLocator(byhour=[12]))
    ax.xaxis.set_major_formatter(mpl.ticker.FuncFormatter(
        lambda x, pos: f"{plt_dates.num2date(x).strftime('%a')} {_ordinal(plt_dates.num2date(x).day)}"
    ))
    ax.xaxis.set_minor_locator(plt_dates.HourLocator(byhour=[0]))
    ax.tick_params(axis="x", which="major", length=4, grid_linewidth=0)
    ax.tick_params(axis="x", which="minor", length=6, labelsize=0, grid_linewidth=0)

    ax.set_ylabel(column_name, fontsize=14)
    ax.tick_params(labelsize=14)
    ax.tick_params(axis="x", which="major", labelsize=6)
    ax.grid(which="major", axis="y", linestyle="--")
    ax.xaxis.grid(False)
    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", borderaxespad=0, fontsize=11)
    plt.subplots_adjust(bottom=0.2)

    output_name = column_name.replace("/", "_")
    plt.tight_layout()
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}_{avg_minutes}min_avg.png",
                format="png", dpi=150, bbox_inches="tight")
    plt.close("all")


def _create_day_overlay_chart(png_data, column_name, title, max_y, filepath, output_prefix, file_prefix, datetime_column, line_chart=True):
    """All days overlaid on a 00:00–24:00 x-axis, one colour per day. Shows consistency of the daily profile."""
    from datetime import timedelta

    sorted_data = png_data.copy().set_index(datetime_column).sort_index()
    dates = sorted(set(sorted_data.index.date))

    if len(dates) < 2:
        return

    plt.style.use("seaborn-v0_8-whitegrid")
    cmap = plt.get_cmap("tab10")
    fig, ax = plt.subplots(figsize=(16, 6))

    for i, date in enumerate(dates):
        day_data = sorted_data[sorted_data.index.date == date]["metric"]
        if day_data.empty:
            continue

        # Smooth per day with ~30-min window
        win = max(2, min(len(day_data), 60))
        day_smooth = day_data.rolling(window=win, center=True, min_periods=1).mean()

        # Map to a reference date so all days share the same x-axis
        x_ref = [pd.Timestamp("2000-01-01") + timedelta(seconds=(ts - pd.Timestamp(date)).total_seconds())
                 for ts in day_data.index]
        ax.plot(x_ref, day_smooth.values, color=cmap(i % 10), alpha=0.8, linewidth=1.2,
                label=pd.Timestamp(date).strftime("%a %d-%b"))

    ax.set_ylim(bottom=0)
    if max_y > 0:
        ax.set_ylim(top=max_y)

    cpu_names = ["wa", "sy", "us"]
    if png_data["metric"].max() > 5 or "%" in column_name or column_name in cpu_names or png_data["metric"].max() == 0:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))
    elif png_data["metric"].max() < 0.002:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.4f}"))
    else:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.3f}"))

    locator = plt_dates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(plt_dates.DateFormatter("%H:%M"))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    start_str = sorted_data.index.min().strftime("%d-%b-%y")
    end_str = sorted_data.index.max().strftime("%d-%b-%y")
    ax.set_title(f"{title} - Day Overlay ({start_str} to {end_str})", fontsize=16)
    ax.set_ylabel(column_name, fontsize=14)
    ax.set_xlabel("Time of day", fontsize=12)
    ax.tick_params(labelsize=13)
    ax.grid(which="major", axis="both", linestyle="--")
    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", borderaxespad=0, fontsize=11)

    output_name = column_name.replace("/", "_")
    plt.tight_layout()
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}_day_overlay.png", format="png", dpi=150, bbox_inches="tight")
    plt.close("all")


def _create_day_overlay_html(png_data, column_name, title, max_y, filepath, output_prefix, file_prefix, datetime_column):
    """Interactive Plotly day-overlay chart: one trace per calendar day on a shared 00:00-24:00 x-axis.
    Hover shows actual date + time + value. Includes the overview/zoom panel."""
    from datetime import timedelta

    sorted_data = png_data.copy().set_index(datetime_column).sort_index()
    dates = sorted(set(sorted_data.index.date))

    if len(dates) < 2:
        return

    colors = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    ]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=False,
        row_heights=[0.75, 0.25],
        vertical_spacing=0.05,
    )

    for i, date in enumerate(dates):
        day_data = sorted_data[sorted_data.index.date == date]["metric"]
        if day_data.empty:
            continue

        # Smooth with ~30-min window
        win = max(2, min(len(day_data), 60))
        day_smooth = day_data.rolling(window=win, center=True, min_periods=1).mean()

        # Map to a reference date for shared x-axis, store actual datetime in customdata
        x_ref = [pd.Timestamp("2000-01-01") + timedelta(seconds=(ts - pd.Timestamp(date)).total_seconds())
                 for ts in day_data.index]
        actual_times = [ts.strftime("%a %d-%b %H:%M:%S") for ts in day_data.index]

        color = colors[i % len(colors)]
        label = pd.Timestamp(date).strftime("%a %d-%b")

        fig.add_trace(go.Scatter(
            x=x_ref, y=day_smooth.values,
            mode="lines", name=label,
            line=dict(width=1.5, color=color),
            customdata=actual_times,
            hovertemplate="%{customdata}<br>" + column_name + ": %{y:,.0f}<extra></extra>",
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=x_ref, y=day_smooth.values,
            mode="lines", name=label,
            line=dict(width=0.8, color=color),
            showlegend=False,
            hoverinfo="skip",
        ), row=2, col=1)

    yaxis_range = [0, max_y] if max_y > 0 else [0, None]
    start_str = sorted_data.index.min().strftime("%d-%b-%y")
    end_str = sorted_data.index.max().strftime("%d-%b-%y")

    fig.update_layout(
        title=dict(text=f"{title} - Day Overlay ({start_str} to {end_str})", font=dict(size=16), x=0.5, xanchor="center"),
        xaxis=dict(title="Time of day", tickfont=dict(size=13),
                   tickformat="%H:%M"),
        xaxis2=dict(title="Drag box here to zoom ↑",
                    tickfont=dict(size=11), tickformat="%H:%M"),
        yaxis=dict(title=column_name, range=yaxis_range, tickfont=dict(size=13), rangemode="tozero"),
        yaxis2=dict(rangemode="tozero", showticklabels=False),
        legend=dict(bgcolor="#EEEEEE", bordercolor="gray", borderwidth=1,
                    font=dict(size=12), orientation="v",
                    title=dict(text="Click to show/hide day", font=dict(size=11, color="grey"))),
        height=650,
        hovermode="x",
        template="plotly_white",
    )

    output_name = column_name.replace("/", "_")
    fig.write_html(
        f"{filepath}{output_prefix}{file_prefix}{output_name}_day_overlay.html",
        include_plotlyjs="cdn",
        post_script=_OVERVIEW_ZOOM_JS,
        full_html=True,
    )


def _create_per_day_bh_peak_charts(png_data, column_name, title, max_y, filepath, output_prefix, file_prefix, datetime_column, line_chart=True, bh_start=8, bh_end=18):
    """For each calendar day in a long-period dataset, create a business-hours peak 60-min chart."""
    sorted_data = png_data.copy().set_index(datetime_column).sort_index()
    dates = sorted(set(sorted_data.index.date))

    for date in dates:
        day_data = sorted_data[sorted_data.index.date == date].reset_index()
        if len(day_data) < 10:
            continue

        date_str = pd.Timestamp(date).strftime("%a %d-%b-%y")
        day_title = f"{title} - {date_str}"
        day_file_prefix = f"{file_prefix}{pd.Timestamp(date).strftime('%Y%m%d')}_"

        _create_business_hours_peak_chart(
            day_data, column_name, day_title, max_y, filepath, output_prefix,
            day_file_prefix, datetime_column, line_chart, bh_start, bh_end,
        )


def _create_glorefs_peak_chart(
    png_data,
    column_name,
    title,
    max_y,
    filepath,
    output_prefix,
    file_prefix,
    datetime_column,
    glorefs_peak_window,
    line_chart=True,
):
    """Create a chart showing the Glorefs peak 60-minute window for this column."""

    glorefs_start, glorefs_end = glorefs_peak_window

    if glorefs_start is None or glorefs_end is None:
        return

    # Sort and filter data to glorefs peak window
    sorted_data = png_data.sort_values(by=datetime_column).copy()
    sorted_data = sorted_data.set_index(datetime_column)

    # Get the actual min and max datetime in this metric's data
    min_data_time = sorted_data.index.min()
    max_data_time = sorted_data.index.max()

    # Adjust the glorefs window to fit within this metric's data range
    # This handles cases where glorefs peak crosses midnight but this metric doesn't span that range
    adjusted_start = max(glorefs_start, min_data_time)
    adjusted_end = min(glorefs_end, max_data_time)

    # If the adjusted window is invalid (start >= end), skip this chart
    if adjusted_start >= adjusted_end:
        return

    # Filter data to the adjusted Glorefs peak window
    try:
        peak_data = sorted_data.loc[adjusted_start:adjusted_end].copy()
    except KeyError:
        # Time range doesn't overlap with this data
        return

    # Reset index to get datetime column back
    peak_data = peak_data.reset_index()

    if len(peak_data) < 2:
        # Not enough data points for a meaningful chart
        return

    colormap_name = "Set1"
    plt.style.use("seaborn-v0_8-whitegrid")

    palette = plt.get_cmap(colormap_name)
    color = palette(2)  # Different color to distinguish from regular peak chart

    fig, ax = plt.subplots(figsize=(16, 6))

    # Choose plot style based on line_chart option
    if line_chart:
        ax.plot(
            peak_data[datetime_column],
            peak_data["metric"],
            label=column_name,
            color=color,
            marker="",
            linestyle="-",
            alpha=0.7,
            linewidth=1,
        )
    else:
        ax.plot(
            peak_data[datetime_column],
            peak_data["metric"],
            label=column_name,
            color=color,
            marker=".",
            linestyle="none",
            alpha=0.7,
        )

    # Add min/max lines for the glorefs peak period
    abs_min = peak_data["metric"].min()
    abs_max = peak_data["metric"].max()

    # For the peak window, use percentile filtering
    p2 = peak_data["metric"].quantile(0.02)
    p99 = peak_data["metric"].quantile(0.99)

    filtered_data = peak_data[(peak_data["metric"] >= p2) & (peak_data["metric"] <= p99)]
    has_outliers = len(filtered_data) < len(peak_data)

    if has_outliers and len(filtered_data) > 0:
        adj_min = filtered_data["metric"].min()
        adj_max = filtered_data["metric"].max()

        if abs_min > 0:
            ax.axhline(y=abs_min, color="darkred", linestyle=":", alpha=0.7, label=f"Abs Min: {abs_min:,.0f}")
        if adj_min > 0:
            ax.axhline(y=adj_min, color="red", linestyle="--", alpha=0.7,
                       label=f"98th pct Min (outliers removed): {adj_min:,.0f}")
        if abs_max > 0:
            ax.axhline(y=abs_max, color="darkgreen", linestyle=":", alpha=0.7, label=f"Abs Max: {abs_max:,.0f}")
        if adj_max > 0:
            ax.axhline(y=adj_max, color="green", linestyle="--", alpha=0.7,
                       label=f"99th pct Max (outliers removed): {adj_max:,.0f}")
    else:
        if abs_min > 0:
            ax.axhline(y=abs_min, color="red", linestyle="--", alpha=0.7, label=f"Min: {abs_min:,.0f}")
        ax.axhline(y=abs_max, color="green", linestyle="--", alpha=0.7, label=f"Max: {abs_max:,.0f}")

    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", borderaxespad=0, fontsize=11)
    ax.grid(which="major", axis="both", linestyle="--")

    # Format title with Glorefs peak period time range (using adjusted times)
    peak_start_str = adjusted_start.strftime("%H:%M")
    peak_end_str = adjusted_end.strftime("%H:%M")
    date_str = adjusted_start.strftime("%a %d-%b-%y")
    ax.set_title(f"{title} - Glorefs Peak ({peak_start_str} to {peak_end_str}) - {date_str}", fontsize=16)

    ax.set_ylabel(column_name, fontsize=14)
    ax.tick_params(labelsize=14)
    plt.subplots_adjust(bottom=0.15)
    ax.set_ylim(bottom=0)
    if max_y != 0:
        ax.set_ylim(top=max_y)

    cpu_names = ["wa", "sy", "us"]
    if (
        peak_data["metric"].max() > 5
        or "%" in column_name
        or column_name in cpu_names
        or peak_data["metric"].max() == 0
    ):
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))
    elif peak_data["metric"].max() < 0.002:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.4f}"))
    else:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.3f}"))

    locator = plt_dates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(plt_dates.DateFormatter("%H:%M"))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    output_name = column_name.replace("/", "_")
    plt.tight_layout()
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}_glorefs_peak.png", format="png", dpi=150, bbox_inches="tight")
    plt.close("all")



_DAY_OVERLAY_ALWAYS = {"Total CPU", "Glorefs", "PhyRds"}

_OVERVIEW_ZOOM_JS = """
(function() {
var gd = document.querySelector('.plotly-graph-div');
var syncing = false;
var zoomRange = null;

function noHighlightShapes() {
    return (gd.layout.shapes || []).filter(function(s) { return !s._yaspe_highlight; });
}

function applyHighlight(r0, r1) {
    var shapes = noHighlightShapes().concat([{
        _yaspe_highlight: true,
        type: 'rect', xref: 'x2', yref: 'y2 domain',
        x0: r0, x1: r1, y0: 0, y1: 1,
        fillcolor: 'rgba(255,165,0,0.3)',
        line: {color: 'rgba(255,140,0,0.7)', width: 1},
        layer: 'above'
    }]);
    syncing = true;
    Plotly.relayout(gd, {shapes: shapes}).then(function() { syncing = false; });
}

function resetAll() {
    zoomRange = null;
    syncing = true;
    Plotly.relayout(gd, {
        'xaxis.autorange': true,
        'xaxis2.autorange': true,
        shapes: noHighlightShapes()
    }).then(function() { syncing = false; btn.style.display = 'none'; });
}

gd.on('plotly_relayout', function(eventdata) {
    if (syncing) return;
    var r0 = eventdata['xaxis2.range[0]'];
    var r1 = eventdata['xaxis2.range[1]'];
    if (r0 !== undefined && r1 !== undefined) {
        // User dragged on overview: zoom top chart, snap overview back, draw highlight
        zoomRange = [r0, r1];
        syncing = true;
        Plotly.relayout(gd, {
            'xaxis.range[0]': r0, 'xaxis.range[1]': r1,
            'xaxis.autorange': false,
            'xaxis2.autorange': true
        }).then(function() { syncing = false; applyHighlight(r0, r1); btn.style.display = 'block'; });
        return;
    }
    // Double-click on either chart: reset both axes and clear highlight
    if (eventdata['xaxis.autorange'] === true || eventdata['xaxis2.autorange'] === true) {
        resetAll();
        return;
    }
    // Direct zoom on top chart: mirror to highlight on overview
    var m0 = eventdata['xaxis.range[0]'];
    var m1 = eventdata['xaxis.range[1]'];
    if (m0 !== undefined && m1 !== undefined) {
        zoomRange = [m0, m1];
        applyHighlight(m0, m1);
        btn.style.display = 'block';
    }
});

// Reset Zoom button — reliable alternative to double-click
var btn = document.createElement('button');
btn.textContent = 'Reset Zoom';
btn.style.cssText = 'position:absolute;top:8px;left:8px;z-index:999;padding:6px 14px;font-size:13px;font-weight:bold;color:#fff;background:#e63946;border:none;border-radius:4px;cursor:pointer;display:none;box-shadow:0 2px 6px rgba(0,0,0,0.3);';
btn.addEventListener('click', resetAll);
gd.style.position = 'relative';
gd.appendChild(btn);
})();
"""


def _maybe_day_overlay_html(data, column_name, title, max_y, filepath, output_prefix, file_prefix, day_overlay=False):
    """Emit a day-overlay HTML chart when data spans more than 25 hours.

    Created only when day_overlay=True OR the column is in _DAY_OVERLAY_ALWAYS.
    """
    if not day_overlay and column_name not in _DAY_OVERLAY_ALWAYS:
        return
    x_column = "datetime_parsed" if "datetime_parsed" in data.columns else "datetime"
    time_range = data[x_column].max() - data[x_column].min()
    if time_range.total_seconds() > 25 * 60 * 60:
        _create_day_overlay_html(data, column_name, title, max_y, filepath, output_prefix, file_prefix, x_column)


def _apply_ref_lines(fig, data, min_max, threshold, row):
    """Add min/max percentile and threshold reference lines to a Plotly figure.
    row=None for single-panel figures, row=1 for the top panel of a 2-row subplot."""
    kw = dict(row=row, col=1) if row is not None else {}

    if min_max:
        metric = data["metric"]
        abs_min = metric.min()
        abs_max = metric.max()
        p2 = metric.quantile(0.02)
        p99 = metric.quantile(0.99)
        filtered = metric[(metric >= p2) & (metric <= p99)]
        has_outliers = len(filtered) < len(metric)

        ann = dict(bgcolor="rgba(255,255,255,0.85)", bordercolor="lightgrey", borderwidth=1)

        if has_outliers and len(filtered) > 0:
            adj_min = filtered.min()
            adj_max = filtered.max()
            fig.add_hline(y=abs_min, line=dict(color="darkred", dash="dot", width=1),
                          annotation_text=f"Abs Min: {abs_min:,.0f}", annotation_position="top left",
                          annotation=ann, **kw)
            fig.add_hline(y=adj_min, line=dict(color="red", dash="dash", width=1),
                          annotation_text=f"98th pct Min: {adj_min:,.0f}", annotation_position="top right",
                          annotation=ann, **kw)
            fig.add_hline(y=abs_max, line=dict(color="darkgreen", dash="dot", width=1),
                          annotation_text=f"Abs Max: {abs_max:,.0f}", annotation_position="top left",
                          annotation=ann, **kw)
            fig.add_hline(y=adj_max, line=dict(color="green", dash="dash", width=1),
                          annotation_text=f"99th pct Max: {adj_max:,.0f}", annotation_position="top right",
                          annotation=ann, **kw)
        else:
            fig.add_hline(y=abs_min, line=dict(color="red", dash="dash", width=1),
                          annotation_text=f"Min: {abs_min:,.0f}", annotation_position="top right",
                          annotation=ann, **kw)
            fig.add_hline(y=abs_max, line=dict(color="green", dash="dash", width=1),
                          annotation_text=f"Max: {abs_max:,.0f}", annotation_position="top right",
                          annotation=ann, **kw)

    if threshold is not None:
        thresh_val, thresh_label = threshold
        thresh_color = "red" if data["metric"].max() > thresh_val else "orange"
        fig.add_hline(y=thresh_val, line=dict(color=thresh_color, dash="dashdot", width=1.5),
                      annotation_text=thresh_label, annotation_position="top left",
                      annotation=dict(bgcolor="rgba(255,255,255,0.85)", bordercolor="lightgrey", borderwidth=1),
                      **kw)


def linked_chart(data, column_name, title, max_y, filepath, output_prefix, **kwargs):
    """Interactive HTML chart: drag a box on the overview (bottom) to zoom the main chart (top).
    The overview resets to full range after each zoom. Double-click overview to reset both."""
    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"
    min_max = kwargs.get("min_max", False)
    threshold = kwargs.get("threshold")  # Optional (value, label) tuple
    write_png = kwargs.get("write_png", False)
    write_html = kwargs.get("write_html", True)
    png_path = kwargs.get("png_path", filepath)
    day_overlay = kwargs.get("day_overlay", False)
    chart_label = kwargs.get("chart_label", [])  # List of strings for right-side annotation

    x_column = "datetime_parsed" if "datetime_parsed" in data.columns else "datetime"

    # Pick hover format based on magnitude
    metric_max = data["metric"].max()
    if metric_max > 5 or metric_max == 0:
        hover_fmt = "%{y:,.0f}"
    elif metric_max < 0.002:
        hover_fmt = "%{y:,.4f}"
    else:
        hover_fmt = "%{y:,.3f}"

    yaxis_range = [0, max_y] if max_y > 0 else [0, None]
    output_name = column_name.replace("/", "_")

    # PNG-only: single-panel figure, no overview row
    if write_png and not write_html:
        png_fig = go.Figure()
        png_fig.add_trace(go.Scatter(
            x=data[x_column], y=data["metric"],
            mode="lines", name=column_name,
            line=dict(width=1),
        ))
        _apply_ref_lines(png_fig, data, min_max, threshold, row=None)
        png_fig.update_layout(
            title=dict(text=title, font=dict(size=16), x=0.5, xanchor="center"),
            xaxis=dict(title="", tickfont=dict(size=13)),
            yaxis=dict(title=column_name, range=yaxis_range, tickfont=dict(size=13), rangemode="tozero"),
            legend=dict(bgcolor="#EEEEEE", bordercolor="gray", borderwidth=1, font=dict(size=13)),
            height=500, width=1400,
            template="plotly_white",
        )
        png_fig.write_image(
            f"{png_path}{output_prefix}{file_prefix}{output_name}.png",
            scale=2, width=1400, height=500,
        )
        return

    # HTML (or PNG+HTML): two-panel figure with overview row
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=False,
        row_heights=[0.75, 0.25],
        vertical_spacing=0.05,
    )

    fig.add_trace(go.Scatter(
        x=data[x_column], y=data["metric"],
        mode="lines", name=column_name,
        line=dict(width=1),
        hovertemplate=f"%{{x|%H:%M:%S}}<br>{column_name}: {hover_fmt}<extra></extra>",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=data[x_column], y=data["metric"],
        mode="lines", fill="tozeroy",
        name=column_name,
        line=dict(width=0.5, color="steelblue"),
        fillcolor="rgba(70,130,180,0.25)",
        showlegend=False,
        hoverinfo="skip",
    ), row=2, col=1)

    _apply_ref_lines(fig, data, min_max, threshold, row=1)

    _annotations = []
    if chart_label:
        _annotations.append(dict(
            text="<br>".join(chart_label),
            xref="paper", yref="paper",
            x=1.01, y=0.0,
            xanchor="left", yanchor="bottom",
            showarrow=False,
            font=dict(size=11),
            bgcolor="#f0f0f0",
            bordercolor="gray",
            borderwidth=1,
            borderpad=4,
        ))

    fig.update_layout(
        title=dict(text=title, font=dict(size=16), x=0.5, xanchor="center"),
        xaxis=dict(title="", tickfont=dict(size=13)),
        xaxis2=dict(title="Drag box here to zoom ↑", tickfont=dict(size=11)),
        yaxis=dict(title=column_name, range=yaxis_range, tickfont=dict(size=13), rangemode="tozero"),
        yaxis2=dict(rangemode="tozero", showticklabels=False),
        legend=dict(bgcolor="#EEEEEE", bordercolor="gray", borderwidth=1, font=dict(size=13)),
        height=650,
        hovermode="x",
        template="plotly_white",
        annotations=_annotations,
        margin=dict(r=160) if chart_label else {},
    )

    if write_html:
        fig.write_html(
            f"{filepath}{output_prefix}{file_prefix}{output_name}.html",
            include_plotlyjs="cdn",
            post_script=_OVERVIEW_ZOOM_JS,
            full_html=True,
        )

    if write_png:
        png_fig = go.Figure()
        png_fig.add_trace(go.Scatter(
            x=data[x_column], y=data["metric"],
            mode="lines", name=column_name,
            line=dict(width=1),
        ))
        _apply_ref_lines(png_fig, data, min_max, threshold, row=None)
        png_fig.update_layout(
            title=dict(text=title, font=dict(size=16), x=0.5, xanchor="center"),
            xaxis=dict(title="", tickfont=dict(size=13)),
            yaxis=dict(title=column_name, range=yaxis_range, tickfont=dict(size=13), rangemode="tozero"),
            legend=dict(bgcolor="#EEEEEE", bordercolor="gray", borderwidth=1, font=dict(size=13)),
            height=500, width=1400,
            template="plotly_white",
        )
        png_fig.write_image(
            f"{png_path}{output_prefix}{file_prefix}{output_name}.png",
            scale=2, width=1400, height=500,
        )

    if write_html:
        _maybe_day_overlay_html(data, column_name, title, max_y, filepath, output_prefix, file_prefix, day_overlay)


def linked_chart_no_time(data, column_name, title, max_y, filepath, output_prefix, **kwargs):
    """Interactive HTML chart for index-based data: drag overview (bottom) to zoom main chart (top)."""
    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"
    write_png = kwargs.get("write_png", False)
    write_html = kwargs.get("write_html", True)
    png_path = kwargs.get("png_path", filepath)

    yaxis_range = [0, max_y] if max_y > 0 else [0, None]
    output_name = column_name.replace(" ", "_").replace("/", "_per_")

    # PNG-only: single-panel figure, no overview row
    if write_png and not write_html:
        png_fig = go.Figure()
        png_fig.add_trace(go.Scatter(
            x=data["id_key"], y=data["metric"],
            mode="lines", name=column_name,
            line=dict(width=1),
        ))
        png_fig.update_layout(
            title=dict(text=title, font=dict(size=16), x=0.5, xanchor="center"),
            xaxis=dict(title="Sample", tickfont=dict(size=13)),
            yaxis=dict(title=column_name, range=yaxis_range, tickfont=dict(size=13), rangemode="tozero"),
            legend=dict(bgcolor="#EEEEEE", bordercolor="gray", borderwidth=1, font=dict(size=13)),
            height=500, width=1400,
            template="plotly_white",
        )
        png_fig.write_image(
            f"{png_path}{output_prefix}{file_prefix}{output_name}.png",
            scale=2, width=1400, height=500,
        )
        return

    # HTML (or PNG+HTML): two-panel figure with overview row
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=False,
        row_heights=[0.75, 0.25],
        vertical_spacing=0.05,
    )

    fig.add_trace(go.Scatter(
        x=data["id_key"], y=data["metric"],
        mode="lines", name=column_name,
        line=dict(width=1),
        hovertemplate="Sample %{x}<br>%{y:,.2f}<extra></extra>",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=data["id_key"], y=data["metric"],
        mode="lines", name=column_name,
        line=dict(width=1, color="lightsteelblue"),
        showlegend=False,
        hoverinfo="skip",
    ), row=2, col=1)

    fig.update_layout(
        title=dict(text=title, font=dict(size=16), x=0.5, xanchor="center"),
        xaxis=dict(title="", tickfont=dict(size=13)),
        xaxis2=dict(title="Drag box here to zoom ↑", tickfont=dict(size=11)),
        yaxis=dict(title=column_name, range=yaxis_range, tickfont=dict(size=13), rangemode="tozero"),
        yaxis2=dict(rangemode="tozero", showticklabels=False),
        legend=dict(bgcolor="#EEEEEE", bordercolor="gray", borderwidth=1, font=dict(size=13)),
        height=650,
        hovermode="x",
        template="plotly_white",
    )

    if write_html:
        fig.write_html(
            f"{filepath}{output_prefix}{file_prefix}{output_name}.html",
            include_plotlyjs="cdn",
            post_script=_OVERVIEW_ZOOM_JS,
            full_html=True,
        )

    if write_png:
        png_fig = go.Figure()
        png_fig.add_trace(go.Scatter(
            x=data["id_key"], y=data["metric"],
            mode="lines", name=column_name,
            line=dict(width=1),
        ))
        png_fig.update_layout(
            title=dict(text=title, font=dict(size=16), x=0.5, xanchor="center"),
            xaxis=dict(title="Sample", tickfont=dict(size=13)),
            yaxis=dict(title=column_name, range=yaxis_range, tickfont=dict(size=13), rangemode="tozero"),
            legend=dict(bgcolor="#EEEEEE", bordercolor="gray", borderwidth=1, font=dict(size=13)),
            height=500, width=1400,
            template="plotly_white",
        )
        png_fig.write_image(
            f"{png_path}{output_prefix}{file_prefix}{output_name}.png",
            scale=2, width=1400, height=500,
        )





def _shade_days(ax, start_date, end_date):
    """Shade alternate days with a faint blue band so day boundaries are visible on multi-day charts."""
    from datetime import timedelta
    day = start_date.date()
    end_day = end_date.date()
    idx = 0
    while day <= end_day:
        day_start = pd.Timestamp(day)
        day_end = day_start + timedelta(days=1)
        if idx % 2 == 0:
            ax.axvspan(day_start, day_end, facecolor="#d6eaf8", alpha=0.25, zorder=0)
        day += timedelta(days=1)
        idx += 1


def simple_chart(data, column_name, title, max_y, filepath, output_prefix, **kwargs):
    """
    Create a simple chart. Returns (peak_start, peak_end) if this is a Glorefs chart with peak enabled,
    otherwise returns (None, None).
    """
    # Check column only has numeric data (strings can sneak in with AIX)
    if not is_column_numeric(data, "metric"):
        print(f"Non numeric data in in column: {column_name} for chart {title}:\n{data.head(2)}")
        return None, None

    file_prefix = kwargs.get("file_prefix", "")
    min_max = kwargs.get("min_max", False)
    peak_chart = kwargs.get("peak_chart", True)
    glorefs_peak_window = kwargs.get("glorefs_peak_window")  # Can be None or (start, end) tuple
    day_overlay = kwargs.get("day_overlay", False)
    line_chart = kwargs.get("line_chart", True)  # Use line charts by default
    threshold = kwargs.get("threshold")  # Optional (value, label) tuple for a reference line
    business_hours_chart = kwargs.get("business_hours_chart", False)  # Generate business-hours peak chart
    bh_charts = kwargs.get("bh_charts", False)  # Generate per-day BH peak charts for multi-day data
    long_period_smooth = kwargs.get("long_period_smooth", 30)
    chart_label = kwargs.get("chart_label", [])  # List of strings for right-side annotation
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    # Make a copy of the data for plotting
    png_data = data.copy()

    # Use the pre-processed datetime column if available
    if "datetime_parsed" in png_data.columns:
        # Simply use the already parsed datetime column
        pass
    else:
        # Convert datetime string to datetime type
        png_data.loc[:, "datetime"] = pd.to_datetime(
            data["datetime"].apply(guess_datetime_format), format="%m/%d/%Y %H:%M:%S"
        )

    colormap_name = "Set1"
    plt.style.use("seaborn-v0_8-whitegrid")

    palette = plt.get_cmap(colormap_name)
    color = palette(1)

    fig, ax = plt.subplots(figsize=(16, 6))

    # For plotting, use datetime_parsed if it exists, otherwise use datetime
    datetime_column = "datetime_parsed" if "datetime_parsed" in png_data.columns else "datetime"

    # Calculate time period duration
    time_range = png_data[datetime_column].max() - png_data[datetime_column].min()
    is_long_period = time_range.total_seconds() > (25 * 60 * 60)  # More than 25 hours
    is_medium_period = time_range.total_seconds() > (8 * 60 * 60)  # More than 8 hours

    # For long periods, smooth with a 30-min rolling mean and show raw data faintly behind it
    if is_long_period:
        sorted_for_smooth = png_data.set_index(datetime_column)["metric"].sort_index()
        time_diffs = sorted_for_smooth.index.to_series().diff().dropna()
        if len(time_diffs) > 0:
            interval_secs = time_diffs.median().total_seconds()
            window = max(2, int(long_period_smooth * 60 / interval_secs)) if interval_secs > 0 else 60
        else:
            interval_secs = 0
            window = 60
        # Format the original sample interval for the legend label
        if interval_secs >= 60:
            sample_label = f"{int(round(interval_secs / 60))}m samples"
        elif interval_secs > 0:
            sample_label = f"{int(round(interval_secs))}s samples"
        else:
            sample_label = "samples"
        smoothed = sorted_for_smooth.rolling(window=window, center=True, min_periods=1).mean()
        ax.plot(sorted_for_smooth.index, sorted_for_smooth.values,
                color=color, alpha=0.15, linewidth=0.5, label="_raw")
        ax.plot(smoothed.index, smoothed.values,
                color=color, alpha=0.85, linewidth=1.5, label=f"{column_name} ({sample_label}, {long_period_smooth} min avg)")
    # Choose plot style based on line_chart option
    elif line_chart:
        ax.plot(
            png_data[datetime_column],
            png_data["metric"],
            label=column_name,
            color=color,
            marker="",
            linestyle="-",
            alpha=0.7,
            linewidth=1,
        )
    else:
        ax.plot(
            png_data[datetime_column],
            png_data["metric"],
            label=column_name,
            color=color,
            marker=".",
            linestyle="none",
            alpha=0.7,
        )

    # Add min/max legend if requested
    if min_max and not is_long_period:
        # Only show min/max for periods <= 25 hours
        # Calculate absolute min/max
        abs_min = png_data["metric"].min()
        abs_max = png_data["metric"].max()

        # For shorter periods, use percentile filtering
        # Detect outliers using 2nd and 99th percentile method (better for system metrics)
        p2 = png_data["metric"].quantile(0.02)  # 2nd percentile
        p99 = png_data["metric"].quantile(0.99)  # 99th percentile

        # Filter out outliers (keep values between 2nd and 99th percentile)
        filtered_data = png_data[(png_data["metric"] >= p2) & (png_data["metric"] <= p99)]

        # Check if we have outliers
        has_outliers = len(filtered_data) < len(png_data)

        if has_outliers and len(filtered_data) > 0:
            adj_min = filtered_data["metric"].min()
            adj_max = filtered_data["metric"].max()

            # Suppress lines that sit on zero — they just clutter the x-axis
            if abs_min > 0:
                ax.axhline(y=abs_min, color="darkred", linestyle=":", alpha=0.7, label=f"Abs Min: {abs_min:,.0f}")
            if adj_min > 0:
                ax.axhline(y=adj_min, color="red", linestyle="--", alpha=0.7,
                           label=f"98th pct Min (outliers removed): {adj_min:,.0f}")
            if abs_max > 0:
                ax.axhline(y=abs_max, color="darkgreen", linestyle=":", alpha=0.7, label=f"Abs Max: {abs_max:,.0f}")
            if adj_max > 0:
                ax.axhline(y=adj_max, color="green", linestyle="--", alpha=0.7,
                           label=f"99th pct Max (outliers removed): {adj_max:,.0f}")
        else:
            if abs_min > 0:
                ax.axhline(y=abs_min, color="red", linestyle="--", alpha=0.7, label=f"Min: {abs_min:,.0f}")
            ax.axhline(y=abs_max, color="green", linestyle="--", alpha=0.7, label=f"Max: {abs_max:,.0f}")

        ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", borderaxespad=0, fontsize=11)

    ax.grid(which="major", axis="both", linestyle="--")

    # Adjust title and x-axis formatting based on time period
    if is_long_period:
        # For long periods, add date range to title and use day of week on x-axis
        start_date = png_data[datetime_column].min()
        end_date = png_data[datetime_column].max()
        start_str = start_date.strftime("%d-%b-%y")
        end_str = end_date.strftime("%d-%b-%y")
        ax.set_title(f"{title} - {start_str} to {end_str}", fontsize=16)

        _shade_days(ax, start_date, end_date)

        from datetime import timedelta
        # Major ticks at noon: label centred in each day band, no grid line
        ax.xaxis.set_major_locator(plt_dates.HourLocator(byhour=[12]))
        ax.xaxis.set_major_formatter(mpl.ticker.FuncFormatter(
            lambda x, pos: f"{plt_dates.num2date(x).strftime('%a')} {_ordinal(plt_dates.num2date(x).day)}"
        ))
        # Minor ticks at midnight: short boundary marks, no label, no grid line
        ax.xaxis.set_minor_locator(plt_dates.HourLocator(byhour=[0]))
        ax.tick_params(axis="x", which="major", length=4, grid_linewidth=0)
        ax.tick_params(axis="x", which="minor", length=6, labelsize=0, grid_linewidth=0)
    else:
        # For short periods, add date to title in DD-MMM-YY format, use only time on x-axis
        start_date = png_data[datetime_column].min()
        date_str = start_date.strftime("%a %d-%b-%y")
        ax.set_title(f"{title} - {date_str}", fontsize=16)
        locator = plt_dates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(plt_dates.DateFormatter("%H:%M"))

        # Keep rotation for time labels (they can be crowded)
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    ax.set_ylabel(column_name, fontsize=14)
    ax.tick_params(labelsize=14)
    if is_long_period:
        # Restore small label size and suppress x-axis grid lines (shading handles day separation)
        ax.tick_params(axis="x", which="major", labelsize=6)
        ax.xaxis.grid(False)
    plt.subplots_adjust(bottom=0.2)
    ax.set_ylim(bottom=0)  # Always zero start
    if max_y != 0:
        ax.set_ylim(top=max_y)

    cpu_names = ["wa", "sy", "us"]

    if png_data["metric"].max() > 5 or "%" in column_name or column_name in cpu_names or png_data["metric"].max() == 0:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))
    elif png_data["metric"].max() < 0.002:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.4f}"))
    else:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.3f}"))

    if threshold is not None:
        thresh_val, thresh_label = threshold
        color = "red" if png_data["metric"].max() > thresh_val else "orange"
        ax.axhline(y=thresh_val, color=color, linestyle="-.", linewidth=1.5, alpha=0.8, label=thresh_label)
        ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", borderaxespad=0, fontsize=11)

    output_name = column_name.replace("/", "_")
    if chart_label:
        label_text = "\n".join(chart_label)
        fig.text(1.01, 0.0, label_text, transform=ax.transAxes,
                 fontsize=10, va="bottom", ha="left",
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="#f0f0f0", edgecolor="gray", alpha=0.8))
    plt.tight_layout()
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}.png", format="png", dpi=150, bbox_inches="tight")
    plt.close("all")

    # Track peak times for Glorefs
    peak_start_time, peak_end_time = None, None

    # Create peak 60-minute chart if conditions are met:
    # - peak_chart is True
    # - min_max is True
    # - Data is more than 8 hours but less than 25 hours
    if peak_chart and min_max and is_medium_period and not is_long_period:
        peak_start_time, peak_end_time = _create_peak_60_chart(
            png_data, column_name, title, max_y, filepath, output_prefix, file_prefix, datetime_column, line_chart
        )

    # Create Glorefs peak chart if glorefs_peak_window is provided and valid
    # This shows how this metric behaved during the peak Glorefs period
    if (
        isinstance(glorefs_peak_window, tuple)
        and glorefs_peak_window[0] is not None
        and min_max
        and is_medium_period
        and not is_long_period
    ):
        _create_glorefs_peak_chart(
            png_data,
            column_name,
            title,
            max_y,
            filepath,
            output_prefix,
            file_prefix,
            datetime_column,
            glorefs_peak_window,
            line_chart,
        )

    # Business hours peak chart for selected key metrics (Total CPU, Glorefs)
    if business_hours_chart and peak_chart and is_medium_period and not is_long_period:
        _create_business_hours_peak_chart(
            png_data, column_name, title, max_y, filepath, output_prefix, file_prefix, datetime_column, line_chart
        )

    # Long-period (>25h) supplementary charts
    if is_long_period and min_max:
        _create_5min_avg_chart(png_data, column_name, title, max_y, filepath, output_prefix, file_prefix, datetime_column)
        _create_daily_summary_chart(png_data, column_name, title, max_y, filepath, output_prefix, file_prefix, datetime_column)
        _create_heatmap_chart(png_data, column_name, title, filepath, output_prefix, file_prefix, datetime_column)
        if day_overlay or column_name in _DAY_OVERLAY_ALWAYS:
            _create_day_overlay_chart(png_data, column_name, title, max_y, filepath, output_prefix, file_prefix, datetime_column, line_chart)
        # day_overlay HTML is handled by linked_chart via _maybe_day_overlay_html
        if bh_charts:
            _create_per_day_bh_peak_charts(png_data, column_name, title, max_y, filepath, output_prefix, file_prefix, datetime_column, line_chart)

    # Return peak times (useful for Glorefs to pass to other charts)
    return peak_start_time, peak_end_time


def simple_chart_no_time(data, column_name, title, max_y, filepath, output_prefix, **kwargs):
    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    # Convert datetime string to datetime type (data is a _view_ of full dataframe, create a copy to update here)
    png_data = data.copy()

    colormap_name = "Set1"
    plt.style.use("seaborn-v0_8-whitegrid")

    palette = plt.get_cmap(colormap_name)
    color = palette(1)

    fig, ax = plt.subplots(figsize=(16, 6))

    ax.plot(
        png_data["id_key"], png_data["metric"], label=column_name, color=color, marker=".", linestyle="-", alpha=0.7
    )
    ax.grid(which="major", axis="both", linestyle="--")
    ax.set_title(title, fontsize=16)
    ax.set_ylabel(column_name, fontsize=14)
    ax.tick_params(labelsize=14)
    plt.subplots_adjust(bottom=0.15)
    ax.set_ylim(bottom=0)  # Always zero start
    if max_y != 0:
        ax.set_ylim(top=max_y)

    cpu_names = ["wa", "sy", "us"]
    if png_data["metric"].max() > 5 or "%" in column_name or column_name in cpu_names or png_data["metric"].max() == 0:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))
    elif png_data["metric"].max() < 0.002:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.4f}"))
    else:
        ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.3f}"))

    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    plt.tight_layout()

    output_name = column_name.replace("/", "_per_").replace(" ", "_")
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}.png", format="png", dpi=150)
    plt.close("all")


def simple_chart_stacked(data, column_names, title, max_y, filepath, output_prefix, **kwargs):
    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    png_data = data.copy()

    # Use the pre-processed datetime column if available
    if "datetime_parsed" in png_data.columns:
        # Use the already parsed datetime as the index
        png_data.set_index("datetime_parsed", inplace=True)
    else:
        # Fall back to original conversion if not available
        png_data.loc[:, "datetime"] = pd.to_datetime(
            data["datetime"].apply(guess_datetime_format), format="%m/%d/%Y %H:%M:%S"
        )
        png_data.set_index("datetime", inplace=True)

    if png_data.empty:
        return

    colormap_name = "Set1"
    plt.style.use("seaborn-v0_8-whitegrid")

    palette = plt.get_cmap(colormap_name)
    color = palette(1)

    fig, ax = plt.subplots(figsize=(16, 6))

    ax.stackplot(png_data.index, png_data["sy"], png_data["wa"], png_data["us"], labels=["sy", "wa", "us"], alpha=0.7)

    ax.grid(which="major", axis="both", linestyle="--")
    date_str = png_data.index[0].strftime("%a %d-%b-%y")
    ax.set_title(f"{title} - {date_str}", fontsize=16)
    ax.set_ylabel("CPU Utilisation %", fontsize=14)
    ax.legend(loc="upper left", reverse=True, fontsize=14)
    ax.tick_params(labelsize=14)
    plt.subplots_adjust(bottom=0.15)
    ax.set_ylim(bottom=0)  # Always zero start
    if max_y != 0:
        ax.set_ylim(top=max_y)

    ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))

    locator = plt_dates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(plt_dates.AutoDateFormatter(locator=locator, defaultfmt="%H:%M"))

    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    output_name = "Stacked CPU"
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}z_{output_name}.png", format="png", dpi=150)
    plt.close("all")


def simple_chart_stacked_iostat(data, columns_to_stack, device, title, max_y, filepath, output_prefix, **kwargs):
    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    png_data = data.copy()

    # Use the pre-processed datetime column if available
    if "datetime_parsed" in png_data.columns:
        # Use the already parsed datetime as the index
        png_data.set_index("datetime_parsed", inplace=True)
    else:
        # Fall back to original conversion if not available
        png_data.loc[:, "datetime"] = pd.to_datetime(
            data["datetime"].apply(guess_datetime_format), format="%m/%d/%Y %H:%M:%S"
        )
        png_data.set_index("datetime", inplace=True)

    # {'r/s': 'Reads per sec', 'w/s': 'Writes per sec'}
    column_0 = list(columns_to_stack.keys())[0]
    column_0_legend = columns_to_stack[column_0]
    column_1 = list(columns_to_stack.keys())[1]
    column_1_legend = columns_to_stack[column_1]

    colormap_name = "Set1"
    plt.style.use("seaborn-v0_8-whitegrid")

    palette = plt.get_cmap(colormap_name)
    color = palette(1)

    fig, ax = plt.subplots(figsize=(16, 6))
    ax.stackplot(
        png_data.index,
        png_data[column_0],
        png_data[column_1],
        labels=[column_0_legend, column_1_legend],
        alpha=0.7,
    )

    ax.grid(which="major", axis="both", linestyle="--")
    date_str = png_data.index[0].strftime("%a %d-%b-%y")
    ax.set_title(f"{title} - {date_str}", fontsize=16)
    ax.set_ylabel("Total IOPS", fontsize=14)
    ax.legend(loc="upper left", reverse=True)
    ax.tick_params(labelsize=14)
    plt.subplots_adjust(bottom=0.15)
    ax.set_ylim(bottom=0)  # Always zero start
    if max_y != 0:
        ax.set_ylim(top=max_y)

    ax.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))

    locator = plt_dates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(plt_dates.AutoDateFormatter(locator=locator, defaultfmt="%H:%M"))

    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    output_name = "Stacked IOPS"
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}_{device}_z_{output_name}.png", format="png", dpi=150)
    plt.close("all")


def simple_chart_histogram_iostat(png_data, columns_to_histogram, device, title, filepath, output_prefix, **kwargs):
    file_prefix = kwargs.get("file_prefix", "")
    if file_prefix != "":
        file_prefix = f"{file_prefix}_"

    # Column name : check for non-zero column {'r_await': 'r/s', 'w_await' : 'w/s'}
    column_0 = list(columns_to_histogram.keys())[0]
    column_0_non_zero = columns_to_histogram[column_0]
    column_1 = list(columns_to_histogram.keys())[1]
    column_1_non_zero = columns_to_histogram[column_1]

    # For writes only look at non-zero values
    # Create a boolean mask based on the condition "column2" is not equal to 0
    mask0 = png_data[column_0_non_zero] != 0
    mask1 = png_data[column_1_non_zero] != 0

    # Use the boolean mask to filter values in "column1"
    reads = png_data.loc[mask0, column_0]
    writes = png_data.loc[mask1, column_1]

    colormap_name = "Set1"
    plt.style.use("seaborn-v0_8-whitegrid")

    plt.figure(num=None, figsize=(16, 6))
    plt.tight_layout()

    palette = plt.get_cmap(colormap_name)

    color = palette(1)

    # Reads

    fig, ax = plt.subplots()
    plt.gcf().set_size_inches(16, 6)

    ax.hist(reads, bins=10, edgecolor="black")

    ax.grid(which="major", axis="both", linestyle="--")
    ax.set_title(f"Read {title}", fontsize=16)
    ax.set_xlabel(f"Latency ms ({column_0}) non-zero {column_0_non_zero} values only", fontsize=10)
    ax.set_ylabel("Frequency", fontsize=14)

    ax.tick_params(labelsize=14)
    plt.subplots_adjust(bottom=0.15)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    output_name = "Read Latency Histogram"
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}_{device}_z_{output_name}.png", format="png", dpi=150)
    plt.close("all")

    # Writes

    fig, ax = plt.subplots()
    plt.gcf().set_size_inches(16, 6)

    ax.hist(writes, bins=10, edgecolor="black")

    ax.grid(which="major", axis="both", linestyle="--")
    ax.set_title(f"Write {title}", fontsize=16)
    ax.set_xlabel(f"Latency ms ({column_1}) non-zero {column_1_non_zero} values only", fontsize=10)
    ax.set_ylabel("Frequency", fontsize=14)

    ax.tick_params(labelsize=14)
    plt.subplots_adjust(bottom=0.15)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    output_name = "Write Latency Histogram"
    plt.savefig(f"{filepath}{output_prefix}{file_prefix}_{device}_z_{output_name}.png", format="png", dpi=150)
    plt.close("all")


def chart_vmstat(
    connection,
    filepath,
    output_prefix,
    png_out,
    png_html_out,
    peak_chart=True,
    glorefs_peak_window=None,
    line_chart=True,
    day_overlay=False,
    bh_charts=False,
    long_period_smooth=5,
):
    # print(f"vmstat...")
    # Get useful
    customer = get_chart_title_base(connection)
    number_cpus = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'number cpus';")[2]
    processor = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'processor model';")[2]

    if execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'operating system';")[2] == "AIX":
        aix_cpus = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'AIX SMT';")[2]
        processor += f" SMT {aix_cpus}"

    # Read in to dataframe, drop any bad rows
    try:
        df = pd.read_sql_query("SELECT * FROM vmstat", connection)
    except DatabaseError as e:
        # Check if the error message indicates a missing table
        if "no such table" in str(e):
            return None
        else:
            # For other types of Error, handle them accordingly
            raise e
    df.dropna(inplace=True)
    df.drop_duplicates(subset=["RunDate", "RunTime"], keep="last", inplace=True)

    # Add a new total CPU column, add a datetime column
    df["Total CPU"] = 100 - df["id"]
    df["datetime"] = df["RunDate"] + " " + df["RunTime"]

    # *** NEW CODE: Pre-process datetime conversion once ***
    # Create a cached datetime column
    df["datetime_parsed"] = pd.to_datetime(df["datetime"].apply(guess_datetime_format), format="%m/%d/%Y %H:%M:%S")
    df.sort_values("datetime_parsed", inplace=True)

    png_filepath, html_filepath = _split_filepath(filepath, png_html_out)

    # Create stacked CPU chart if columns exist
    if png_out or png_html_out:
        if "sy" in df.columns and "wa" in df.columns and "us" in df.columns:
            title = f"CPU utilisation % - {customer}"
            title += f"\n{number_cpus} cores ({processor})"
            simple_chart_stacked(df, "sy, wa, us", title, 100, png_filepath, output_prefix)

    # Format the data for Altair
    # Cut down the df to just the list of categorical data we care about (columns)
    columns_to_chart = list(df.columns)
    unwanted_columns = ["id_key", "RunDate", "RunTime", "html name", "hr", "datetime_parsed"]  # Add datetime_parsed
    columns_to_chart = [ele for ele in columns_to_chart if ele not in unwanted_columns]

    vmstat_df = df[columns_to_chart + ["datetime_parsed"]]  # Add datetime_parsed to preserved columns

    # unpivot the dataframe; first column is date time column, column name is next, then the value in that column
    vmstat_df = vmstat_df.melt(id_vars=["datetime", "datetime_parsed"], var_name="Type", value_name="metric")

    # For each column create a linked html chart
    for column_name in columns_to_chart:
        min_max = False  # Put legend on chart
        if column_name == "datetime":
            pass
        else:
            if column_name in ("Total CPU", "r"):
                title = f"{column_name} - {customer}"
                title += f"\n{number_cpus} cores ({processor})"
            else:
                title = f"{column_name} - {customer}"

            to_chart_df = vmstat_df.loc[vmstat_df["Type"] == column_name]

            if column_name in ("Total CPU", "wa", "sy", "us", "r"):
                min_max = True

            if column_name in ("Total CPU", "wa", "id", "us", "sy"):
                max_y = 100
            else:
                # Remove outliers first, will result in nan for zero values, so needs more work
                # to_chart_df = to_chart_df[((to_chart_df.metric - to_chart_df.metric.mean()) / to_chart_df.metric.std()).abs() < 3]
                max_y = to_chart_df["metric"].max()

            data = to_chart_df

            # Reference threshold lines for key CPU metrics
            threshold = None
            if column_name in ("Total CPU", "us"):
                threshold = (80, "80% CPU threshold")
            elif column_name == "wa":
                threshold = (10, "10% iowait threshold")

            if png_out or png_html_out:
                simple_chart(
                    data,
                    column_name,
                    title,
                    max_y,
                    png_filepath,
                    output_prefix,
                    min_max=min_max,
                    peak_chart=peak_chart,
                    glorefs_peak_window=glorefs_peak_window,
                    line_chart=line_chart,
                    threshold=threshold,
                    business_hours_chart=min_max,
                    day_overlay=day_overlay,
                    bh_charts=bh_charts,
                    long_period_smooth=long_period_smooth,
                )
                if png_html_out:
                    linked_chart(data, column_name, title, max_y, html_filepath, output_prefix,
                                 min_max=min_max, threshold=threshold, day_overlay=day_overlay)
            else:
                linked_chart(data, column_name, title, max_y, filepath, output_prefix,
                             min_max=min_max, threshold=threshold, day_overlay=day_overlay)


def chart_mgstat(
    connection, filepath, output_prefix, png_out, png_html_out, mgstat_file, peak_chart=True, line_chart=True, day_overlay=False, bh_charts=False, long_period_smooth=5,
):
    """
    Chart mgstat data. Returns the Glorefs peak window (start, end) if available, otherwise (None, None).
    """
    # print(f"mgstat...")

    glorefs_peak_window = (None, None)  # Will be populated if Glorefs peak chart is created

    png_filepath, html_filepath = _split_filepath(filepath, png_html_out)

    if not mgstat_file:
        customer = get_chart_title_base(connection)
    else:
        print("mgstat only")
        customer = "mgstat"

    # Read in to dataframe, drop any bad rows
    try:
        df = pd.read_sql_query("SELECT * FROM mgstat", connection)
    except DatabaseError as e:
        # Check if the error message indicates a missing table
        if "no such table" in str(e):
            return glorefs_peak_window
        else:
            # For other types of Error, handle them accordingly
            raise e
    df.dropna(inplace=True)
    df.drop_duplicates(subset=["RunDate", "RunTime"], keep="last", inplace=True)

    # Add a datetime column
    df["datetime"] = df["RunDate"] + " " + df["RunTime"]

    # *** NEW CODE: Pre-process datetime conversion once ***
    # Create a cached datetime column - do this once for all charts
    df["datetime_parsed"] = pd.to_datetime(df["datetime"].apply(guess_datetime_format), format="%m/%d/%Y %H:%M:%S")
    df.sort_values("datetime_parsed", inplace=True)

    # Format the data for Altair
    # Cut down the df to just the list of categorical data we care about (columns)
    columns_to_chart = list(df.columns)
    unwanted_columns = [
        "id_key",
        "RunDate",
        "RunTime",
        "html name",
        "datetime_parsed",
    ]  # Add datetime_parsed to unwanted
    columns_to_chart = [ele for ele in columns_to_chart if ele not in unwanted_columns]

    # Include datetime_parsed in the dataframe we'll be charting, but not as a column to chart
    mgstat_df = df[columns_to_chart + ["datetime_parsed"]]

    # unpivot the dataframe; first column is date time column, column name is next, then the value in that column
    # Include both datetime and datetime_parsed in the melt operation as id_vars (not to be melted)
    mgstat_df = mgstat_df.melt(id_vars=["datetime", "datetime_parsed"], var_name="Type", value_name="metric")

    # For each column create a chart
    for column_name in columns_to_chart:
        min_max = False
        if column_name == "datetime":
            pass
        else:
            title = f"{column_name} - {customer}"
            to_chart_df = mgstat_df.loc[mgstat_df["Type"] == column_name]

            # Remove outliers first, will result in nan for zero values, so needs more work
            # to_chart_df = to_chart_df[((to_chart_df.metric - to_chart_df.metric.mean()) / to_chart_df.metric.std()).abs() < 3]
            max_y = to_chart_df["metric"].max()

            data = to_chart_df
            if column_name in (
                "Glorefs",
                "RemGrefs",
                "Gloupds",
                "RemGupds",
                "Jrnwrts",
                "PhyRds",
                "PhyWrs",
                "RouCMs",
                "RouLaS",
                "WIJwri",
            ):
                min_max = True

            if png_out or png_html_out:
                peak_start, peak_end = simple_chart(
                    data,
                    column_name,
                    title,
                    max_y,
                    png_filepath,
                    output_prefix,
                    min_max=min_max,
                    peak_chart=peak_chart,
                    line_chart=line_chart,
                    business_hours_chart=min_max,
                    day_overlay=day_overlay,
                    bh_charts=bh_charts,
                    long_period_smooth=long_period_smooth,
                )
                # Capture Glorefs peak window
                if column_name == "Glorefs" and peak_start is not None:
                    glorefs_peak_window = (peak_start, peak_end)
                if png_html_out:
                    linked_chart(data, column_name, title, max_y, html_filepath, output_prefix,
                                 min_max=min_max, day_overlay=day_overlay)
            else:
                linked_chart(data, column_name, title, max_y, filepath, output_prefix,
                             min_max=min_max, day_overlay=day_overlay)

    return glorefs_peak_window


def chart_perfmon(
    connection,
    filepath,
    output_prefix,
    png_out,
    png_html_out,
    peak_chart=True,
    glorefs_peak_window=None,
    line_chart=True,
    day_overlay=False,
    bh_charts=False,
    long_period_smooth=5,
):
    # print(f"perfmon...")

    customer = get_chart_title_base(connection)
    number_cpus = execute_single_read_query(connection, "SELECT * FROM overview WHERE field = 'number cpus';")[2]

    # Read in to dataframe, drop any bad rows
    try:
        df = pd.read_sql_query("SELECT * FROM perfmon", connection)
    except DatabaseError as e:
        # Check if the error message indicates a missing table
        if "no such table" in str(e):
            return None
        else:
            # For other types of Error, handle them accordingly
            raise e
    df.dropna(inplace=True)
    df.drop_duplicates(subset=["datetime"], keep="last", inplace=True)

    # *** NEW CODE: Pre-process datetime conversion once ***
    # Assume perfmon already has a "datetime" column, otherwise create it
    if "datetime" not in df.columns and "Time" in df.columns:
        df["datetime"] = df["Time"]  # Adjust based on actual perfmon data structure

    # Parse the datetime column once for all charts
    df["datetime_parsed"] = pd.to_datetime(df["datetime"].apply(guess_datetime_format), format="%m/%d/%Y %H:%M:%S")
    df.sort_values("datetime_parsed", inplace=True)

    # Format the data for Altair
    # Cut down the df to just the list of categorical data we care about (columns)
    columns_to_chart = list(df.columns)
    unwanted_columns = ["id_key", "Time", "html name", "datetime_parsed"]  # Add datetime_parsed to unwanted
    columns_to_chart = [ele for ele in columns_to_chart if ele not in unwanted_columns]

    # Include datetime_parsed in the dataframe we'll be charting, but not as a column to chart
    perfmon_df = df[columns_to_chart + ["datetime_parsed"]]

    # unpivot the dataframe; include both datetime and datetime_parsed as id_vars
    perfmon_df = perfmon_df.melt(id_vars=["datetime", "datetime_parsed"], var_name="Type", value_name="metric")

    # For each column create a chart
    # Define columns that should have min_max enabled
    perfmon_min_max_patterns = [
        "ProcessorTotal_Processor_Time",
        "SystemProcesses",
        "SystemProcessor_Queue_Length",
        "PhysicalDiskTotalAvg_Disk_secRead",
        "PhysicalDiskTotalAvg_Disk_secWrite",
        "TotalDisk_Readssec",
        "TotalDisk_Transferssec",
        "TotalDisk_Writessec",
    ]

    png_filepath, html_filepath = _split_filepath(filepath, png_html_out)

    for column_name in columns_to_chart:
        if column_name == "datetime":
            pass
        else:
            # Check if min_max should be enabled for this column
            min_max = any(pattern in column_name for pattern in perfmon_min_max_patterns)

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

            if png_out or png_html_out:
                simple_chart(
                    data, column_name, title, max_y, png_filepath, output_prefix,
                    min_max=min_max, peak_chart=peak_chart, glorefs_peak_window=glorefs_peak_window,
                    line_chart=line_chart, business_hours_chart=min_max, day_overlay=day_overlay,
                    bh_charts=bh_charts, long_period_smooth=long_period_smooth,
                )
                if png_html_out:
                    linked_chart(data, column_name, title, max_y, html_filepath, output_prefix,
                                 min_max=min_max, day_overlay=day_overlay)
            else:
                linked_chart(data, column_name, title, max_y, filepath, output_prefix,
                             min_max=min_max, day_overlay=day_overlay)


def chart_iostat(
    connection,
    filepath,
    output_prefix,
    operating_system,
    png_out,
    png_html_out,
    disk_list,
    peak_chart=True,
    glorefs_peak_window=None,
    line_chart=True,
    iostat_subfolders=False,
    day_overlay=False,
    bh_charts=False,
    long_period_smooth=5,
    device_labels=None,
):
    # print(f"iostat...")

    customer = get_chart_title_base(connection)

    import re as _re

    def _device_slug(device):
        label = (device_labels or {}).get(device, "")
        if not label:
            return device
        slug = _re.sub(r"[^a-z0-9_-]", "_", label.lower())
        slug = _re.sub(r"_+", "_", slug).strip("_")
        full = f"{device}_{slug}"
        if len(full) > 60:
            return full[:50] + "_and_more"
        return full

    def _device_chart_label(device):
        """Return list of label strings for side annotation, or [] if no label."""
        label = (device_labels or {}).get(device, "")
        if not label:
            return []
        parts = [s.strip() for s in label.split(",")]
        if len(parts) > 20:
            return parts[:20] + ["And more..."]
        return parts

    # Read in to dataframe, drop any bad rows
    try:
        df = pd.read_sql_query("SELECT * FROM iostat", connection)
    except DatabaseError as e:
        # Check if the error message indicates a missing table
        if "no such table" in str(e):
            return None
        else:
            # For other types of Error, handle them accordingly
            raise e
    df.dropna(inplace=True)
    if "RunDate" in df.columns and "RunTime" in df.columns and "Device" in df.columns:
        df.drop_duplicates(subset=["RunDate", "RunTime", "Device"], keep="last", inplace=True)

    if "r/s" in df.columns and "w/s" in df.columns:
        df["Total IOPS"] = df["r/s"] + df["w/s"]

    # If there is no date and time in iostat then just use index as x axis
    if "RunDate" in df.columns:
        df["datetime"] = df["RunDate"] + " " + df["RunTime"]

        # *** NEW CODE: Pre-process datetime conversion once ***
        # Create a cached datetime column - do this once for all charts
        df["datetime_parsed"] = pd.to_datetime(df["datetime"].apply(guess_datetime_format), format="%m/%d/%Y %H:%M:%S")
        df.sort_values(["datetime_parsed", "Device"], inplace=True)

        # Format the data for Altair
        # Cut down the df to just the list of categorical data we care about (columns)
        columns_to_chart = list(df.columns)
        unwanted_columns = ["id_key", "RunDate", "RunTime", "html name", "datetime_parsed"]  # Add datetime_parsed
        columns_to_chart = [ele for ele in columns_to_chart if ele not in unwanted_columns]

        iostat_df = df[columns_to_chart + ["datetime_parsed"]]  # Include datetime_parsed
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

            if iostat_subfolders:
                device_dirname = _device_slug(device)
                device_filepath = f"{filepath}{device_dirname}/"
                if not os.path.isdir(device_filepath):
                    os.mkdir(device_filepath)
            else:
                device_filepath = filepath

            dev_png_fp, dev_html_fp = _split_filepath(device_filepath, png_html_out)

            # Create stacked read write chart if columns exist
            if png_out or png_html_out:
                _chart_label = _device_chart_label(device)
                if operating_system == "AIX":
                    # Something wrong with the way stacked charts come out base is not zero and a fake base rises l-r

                    if "read rps" in device_df.columns and "write wps" in device_df.columns:
                        title = f"{device} : Total IOPS - {customer}"
                        columns_to_stack = {"read rps": "Reads per sec", "write wps": "Writes per sec"}
                        simple_chart_stacked_iostat(
                            device_df, columns_to_stack, device, title, 0, dev_png_fp, output_prefix
                        )

                        if "read avg serv" in device_df.columns and "write avg serv" in device_df.columns:
                            title = f"{device} : Latency - {customer}"
                            columns_to_histogram = {"read avg serv": "read rps", "write avg serv": "write wps"}
                            simple_chart_histogram_iostat(
                                device_df, columns_to_histogram, device, title, dev_png_fp, output_prefix
                            )

                else:
                    if "r/s" in device_df.columns and "w/s" in device_df.columns:
                        _stacked_title = f"{device} : Total IOPS - {customer}"
                        columns_to_stack = {"r/s": "Reads per sec", "w/s": "Writes per sec"}
                        simple_chart_stacked_iostat(
                            device_df, columns_to_stack, device, _stacked_title, 0, dev_png_fp, output_prefix
                        )

                        if "r_await" in device_df.columns and "w_await" in device_df.columns:
                            _lat_title = f"{device} : Latency - {customer}"
                            # Column name : check for non-zero column
                            columns_to_histogram = {"r_await": "r/s", "w_await": "w/s"}
                            simple_chart_histogram_iostat(
                                device_df, columns_to_histogram, device, _lat_title, dev_png_fp, output_prefix
                            )

            # unpivot the dataframe; include both datetime and datetime_parsed as id_vars
            device_df = device_df.melt(
                id_vars=["datetime", "datetime_parsed", "Device"], var_name="Type", value_name="metric"
            )

            # For each column create a chart
            for column_name in columns_to_chart:
                if column_name in ["datetime", "Device"]:
                    pass
                else:
                    _chart_label = _device_chart_label(device)
                    title = f"{device} : {column_name} - {customer}"

                    to_chart_df = device_df.loc[device_df["Type"] == column_name]

                    # Remove outliers first, will result in nan for zero values, so needs more work
                    # to_chart_df = to_chart_df[((to_chart_df.metric - to_chart_df.metric.mean()) / to_chart_df.metric.std()).abs() < 3]
                    max_y = to_chart_df["metric"].max()

                    data = to_chart_df

                    min_max = False
                    if column_name in ("r/s", "w/s", "r_await", "w_await"):
                        min_max = True

                    # Reference threshold: storage latency target for IRIS
                    threshold = None
                    if column_name in ("r_await", "w_await"):
                        threshold = (1, "1 ms latency target")

                    if png_out or png_html_out:
                        simple_chart(
                            data,
                            column_name,
                            title,
                            max_y,
                            dev_png_fp,
                            output_prefix,
                            file_prefix=device,
                            min_max=min_max,
                            peak_chart=peak_chart,
                            glorefs_peak_window=glorefs_peak_window,
                            line_chart=line_chart,
                            threshold=threshold,
                            business_hours_chart=min_max,
                            day_overlay=day_overlay,
                            bh_charts=bh_charts,
                            long_period_smooth=long_period_smooth,
                            chart_label=_chart_label,
                        )
                        if png_html_out:
                            linked_chart(data, column_name, title, max_y, dev_html_fp, output_prefix,
                                         file_prefix=device, min_max=min_max, threshold=threshold,
                                         day_overlay=day_overlay, chart_label=_chart_label)
                    else:
                        linked_chart(data, column_name, title, max_y, device_filepath, output_prefix,
                                     file_prefix=device, min_max=min_max, threshold=threshold,
                                     day_overlay=day_overlay, chart_label=_chart_label)

    else:
        # No date or time, chart all columns, index is x axis

        columns_to_chart = list(df.columns)
        unwanted_columns = ["id_key", "html name"]
        columns_to_chart = [ele for ele in columns_to_chart if ele not in unwanted_columns]

        iostat_df = df
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

            if iostat_subfolders:
                device_dirname = _device_slug(device)
                device_filepath = f"{filepath}{device_dirname}/"
                if not os.path.isdir(device_filepath):
                    os.mkdir(device_filepath)
            else:
                device_filepath = filepath

            dev_png_fp, dev_html_fp = _split_filepath(device_filepath, png_html_out)

            # unpivot the dataframe; first column is index, column name is next, then the value in that column
            device_df = device_df.melt("id_key", var_name="Type", value_name="metric")

            # For each column create a chart
            for column_name in columns_to_chart:
                if not column_name == "Device":
                    _chart_label = _device_chart_label(device)
                    title = f"{device} : {column_name} - {customer}"

                    to_chart_df = device_df.loc[device_df["Type"] == column_name]

                    # Remove outliers first, will result in nan for zero values, so needs more work
                    # to_chart_df = to_chart_df[((to_chart_df.metric - to_chart_df.metric.mean()) / to_chart_df.metric.std()).abs() < 3]
                    max_y = to_chart_df["metric"].max()

                    data = to_chart_df

                    if png_out:
                        simple_chart_no_time(
                            data, column_name, title, max_y, device_filepath, output_prefix, file_prefix=device
                        )
                    elif png_html_out:
                        simple_chart_no_time(
                            data, column_name, title, max_y, dev_png_fp, output_prefix, file_prefix=device
                        )
                        linked_chart_no_time(
                            data, column_name, title, max_y, dev_html_fp, output_prefix, file_prefix=device
                        )
                    else:
                        linked_chart_no_time(data, column_name, title, max_y,
                                             device_filepath, output_prefix, file_prefix=device)


def chart_nfsiostat(connection, filepath, output_prefix, operating_system, png_out, png_html_out, peak_chart=True, line_chart=True, iostat_subfolders=False):
    # print(f"iostat...")

    customer = get_chart_title_base(connection)

    # Read in to dataframe, drop any bad rows
    try:
        df = pd.read_sql_query("SELECT * FROM nfsiostat", connection)
    except DatabaseError as e:
        # Check if the error message indicates a missing table
        if "no such table" in str(e):
            return None
        else:
            # For other types of Error, handle them accordingly
            raise e
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

        if iostat_subfolders:
            device_filepath = _make_chart_dir(filepath.rstrip("/"), device.replace("/", "_"))
        else:
            device_filepath = filepath

        dev_png_fp, dev_html_fp = _split_filepath(device_filepath, png_html_out)

        # unpivot the dataframe; first column is index, column name is next, then the value in that column
        device_df = device_df.melt("id_key", var_name="Type", value_name="metric")

        # For each column create a chart
        for column_name in columns_to_chart:
            if not column_name == "Device":
                title = f"{device} : {column_name} - {customer}"

                to_chart_df = device_df.loc[device_df["Type"] == column_name]

                # Remove outliers first, will result in nan for zero values, so needs more work
                # to_chart_df = to_chart_df[((to_chart_df.metric - to_chart_df.metric.mean()) / to_chart_df.metric.std()).abs() < 3]
                max_y = to_chart_df["metric"].max()

                data = to_chart_df

                pfx = "" if iostat_subfolders else device.replace("/", "_")

                if png_out or png_html_out:
                    simple_chart_no_time(data, column_name, title, max_y, dev_png_fp, output_prefix, file_prefix=pfx)
                    if png_html_out:
                        linked_chart_no_time(data, column_name, title, max_y, dev_html_fp, output_prefix, file_prefix=pfx)
                else:
                    linked_chart_no_time(data, column_name, title, max_y,
                                         device_filepath, output_prefix, file_prefix=pfx)


def chart_aix_sar_d(
    connection,
    filepath,
    output_prefix,
    operating_system,
    png_out,
    png_html_out,
    disk_list,
    peak_chart=True,
    line_chart=True,
    iostat_subfolders=False,
    day_overlay=False,
):
    customer = get_chart_title_base(connection)

    # Read in to dataframe, drop any bad rows
    try:
        df = pd.read_sql_query("SELECT * FROM aix_sar_d", connection)
    except DatabaseError as e:
        # Check if the error message indicates a missing table
        if "no such table" in str(e):
            return None
        else:
            # For other types of Error, handle them accordingly
            raise e
    df.dropna(inplace=True)
    df.drop_duplicates(subset=["RunDate", "RunTime", "device"], keep="last", inplace=True)

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

    min_max = False

    # Chart each disk
    for device in devices:
        device_df = aix_sar_d_df.loc[aix_sar_d_df["device"] == device]

        if iostat_subfolders:
            device_filepath = _make_chart_dir(filepath.rstrip("/"), device)
        else:
            device_filepath = filepath

        dev_png_fp, dev_html_fp = _split_filepath(device_filepath, png_html_out)

        # unpivot the dataframe; first column is index, column name is next, then the value in that column
        device_df = device_df.melt("datetime", var_name="Type", value_name="metric")

        # For each column create a chart
        for column_name in columns_to_chart:
            if column_name == "datetime" or column_name == "device":
                pass
            else:
                title = f"{device} : {column_name} - {customer}"

                to_chart_df = device_df.loc[device_df["Type"] == column_name]

                # Remove outliers first, will result in nan for zero values, so needs more work
                # to_chart_df = to_chart_df[((to_chart_df.metric - to_chart_df.metric.mean()) / to_chart_df.metric.std()).abs() < 3]
                max_y = to_chart_df["metric"].max()

                data = to_chart_df

                pfx = "" if iostat_subfolders else device

                if png_out or png_html_out:
                    simple_chart(data, column_name, title, max_y, dev_png_fp, output_prefix,
                                 file_prefix=pfx, peak_chart=peak_chart, line_chart=line_chart,
                                 min_max=min_max, business_hours_chart=min_max, day_overlay=day_overlay,
                                 bh_charts=bh_charts, long_period_smooth=long_period_smooth)
                    if png_html_out:
                        linked_chart(data, column_name, title, max_y, dev_html_fp, output_prefix,
                                     file_prefix=pfx, min_max=min_max, day_overlay=day_overlay)
                else:
                    linked_chart(data, column_name, title, max_y, device_filepath, output_prefix,
                                 file_prefix=pfx, min_max=min_max, day_overlay=day_overlay)


def chart_free_memory(connection, filepath, output_prefix, png_out, png_html_out, peak_chart=True, line_chart=True, day_overlay=False):
    customer = get_chart_title_base(connection)

    # Read in to dataframe, drop any bad rows
    try:
        df = pd.read_sql_query("SELECT * FROM free_memory", connection)
    except DatabaseError as e:
        # Check if the error message indicates a missing table
        if "no such table" in str(e):
            return None
        else:
            # For other types of Error, handle them accordingly
            raise e
    df.dropna(inplace=True)
    df.drop_duplicates(subset=["RunDate", "RunTime"], keep="last", inplace=True)

    # Add a datetime column
    df["datetime"] = df["RunDate"] + " " + df["RunTime"]

    # Pre-process datetime conversion once
    df["datetime_parsed"] = pd.to_datetime(df["datetime"].apply(guess_datetime_format), format="%m/%d/%Y %H:%M:%S")
    df.sort_values("datetime_parsed", inplace=True)

    # Format the data for charting
    columns_to_chart = list(df.columns)
    unwanted_columns = ["id_key", "RunDate", "RunTime", "html name", "datetime_parsed"]
    columns_to_chart = [ele for ele in columns_to_chart if ele not in unwanted_columns]

    free_df = df[columns_to_chart + ["datetime_parsed"]]

    # unpivot the dataframe
    free_df = free_df.melt(id_vars=["datetime", "datetime_parsed"], var_name="Type", value_name="metric")

    png_filepath, html_filepath = _split_filepath(filepath, png_html_out)

    # For each column create a chart
    for column_name in columns_to_chart:
        if column_name == "datetime":
            pass
        else:
            title = f"Memory: {column_name} - {customer}"
            to_chart_df = free_df.loc[free_df["Type"] == column_name]

            max_y = to_chart_df["metric"].max()
            data = to_chart_df

            # Add min/max lines for key memory metrics
            min_max = column_name in ("used", "free", "available")

            if png_out or png_html_out:
                simple_chart(
                    data, column_name, title, max_y, png_filepath, output_prefix,
                    min_max=min_max, peak_chart=peak_chart, line_chart=line_chart,
                    business_hours_chart=min_max, day_overlay=day_overlay,
                )
                if png_html_out:
                    linked_chart(data, column_name, title, max_y, html_filepath, output_prefix,
                                 min_max=min_max, day_overlay=day_overlay)
            else:
                linked_chart(data, column_name, title, max_y, filepath, output_prefix,
                             min_max=min_max, day_overlay=day_overlay)


def _make_chart_dir(base, name):
    path = f"{base}/{name}/"
    if not os.path.isdir(path):
        os.mkdir(path)
    return path


def _split_filepath(fp, png_html_out):
    """When -P is active, return separate png/ and html/ subdirs; otherwise return fp for both."""
    if not png_html_out:
        return fp, fp
    return _make_chart_dir(fp.rstrip("/"), "png"), _make_chart_dir(fp.rstrip("/"), "html")


def mainline(
    input_file,
    include_iostat,
    include_nfsiostat,
    append_to_database,
    existing_database,
    output_prefix,
    csv_out,
    png_out,
    png_html_out,
    system_out,
    disk_list,
    split_on,
    csv_date_format,
    mgstat_file,
    peak_chart=True,
    line_chart=True,
    iostat_subfolders=True,
    smooth_minutes=5,
    day_overlay=False,
    bh_charts=False,
    long_period_smooth=5,
    context=None,
    llm_context=False,
    resample_interval=None,
    combined_overlay=False,
    all_disks=False,
):
    input_error = False
    sp_dict = None

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
    extended_charts = os.path.isfile(f"{filepath}/site_survey_input.yml")

    # get the prefix
    html_filename = os.path.splitext(filename)[0]

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

    # mgstat file means processing a .mgst file, not SystemPerformance HTML
    if mgstat_file:
        if database_action != "Chart only":
            print(f"mgstat .mgst file selected")
            mgstat_text_description = create_mgstat(
                connection, input_file, html_filename, csv_out, output_filepath_prefix
            )

            if mgstat_text_description != "":
                with open(f"{output_filepath_prefix}overview.txt", "w") as text_file:
                    print(f"{mgstat_text_description}", file=text_file)

    else:
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
                    csv_date_format,
                    all_disks,
                )

        else:
            if database_action == "Chart only":
                input_error = True
                print(f"No data to chart")
            else:
                # Create a system summary
                sp_dict = sp_check.system_check(input_file)

                # Resolve IRIS storage roles from CPF + filesystem info
                iris_roles = cpf_disk_resolver.resolve_iris_disk_roles(sp_dict)
                mount_map = cpf_disk_resolver._build_mount_map(sp_dict, sp_dict)
                device_to_mount = {}
                for mount_point, device in mount_map.items():
                    if device not in device_to_mount or len(mount_point) < len(device_to_mount[device]):
                        device_to_mount[device] = mount_point

                # Store database devices: one key per device, indexed
                for i, (device, names) in enumerate(iris_roles["Database"]):
                    sp_dict[f"iris disk role Database {i}"] = device
                    sp_dict[f"iris disk role Database {i} names"] = ",".join(names)
                    sp_dict[f"iris_disk_role_mount Database {i}"] = device_to_mount.get(device, "")

                # Store single-device roles
                for role in ("Primary Journal", "Alternate Journal", "WIJ"):
                    device = iris_roles[role]
                    if device:
                        sp_dict[f"iris disk role {role}"] = device
                        sp_dict[f"iris_disk_role_mount {role}"] = device_to_mount.get(device, "")

                if system_out:
                    output_log, yaspe_yaml = sp_check.build_log(sp_dict)

                    # Text overview plus YAML summary appended at the end
                    with open(f"{output_filepath_prefix}overview.txt", "w") as text_file:
                        print(f"{output_log}", file=text_file)
                        print("", file=text_file)
                        print(yaspe_yaml, file=text_file)

                    # Simple dump of all data in overview (scalar values only)
                    overview_df = pd.DataFrame(
                        [(k, v) for k, v in sp_dict.items() if isinstance(v, (str, int, float, type(None)))],
                        columns=["key", "value"]
                    )
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
                    csv_date_format,
                    all_disks,
                )

        close_connection(connection)
        connection = None

    # LLM context export
    if llm_context and not input_error and not mgstat_file:
        llm_conn = create_connection(sql_filename)
        try:
            if not sp_dict:
                try:
                    rows = execute_read_query(llm_conn, "SELECT field, value FROM overview")
                    sp_dict = {r[0]: r[1] for r in rows} if rows else {}
                except Exception:
                    sp_dict = {}
            import llm_context as _llm_context
            bundle_path, prompt_path = _llm_context.export_llm_context(
                connection=llm_conn,
                sp_dict=sp_dict,
                filepath=filepath,
                resample_interval=resample_interval,
                context=context,
            )
            print(f"LLM context bundle: {bundle_path}")
            print(f"LLM analysis prompt: {prompt_path}")
        finally:
            close_connection(llm_conn)

    # Charting is separate
    if "Chart" in database_action and not input_error:
        output_file_path_base = f"{output_filepath_prefix}metrics"
        if not os.path.isdir(output_file_path_base):
            os.mkdir(output_file_path_base)

        if connection is None:
            connection = create_connection(sql_filename)

        try:
            if not mgstat_file:
                operating_system = execute_single_read_query(
                    connection, "SELECT * FROM overview WHERE field = 'operating system';"
                )[2]

            glorefs_peak_window = chart_mgstat(
                connection, _make_chart_dir(output_file_path_base, "mgstat"),
                output_prefix, png_out, png_html_out, mgstat_file, peak_chart, line_chart, day_overlay, bh_charts, long_period_smooth,
            )

            # No need to go further for .mgst file
            if mgstat_file:
                return

            is_unix = operating_system in ("Linux", "Ubuntu", "AIX")
            is_linux = operating_system in ("Linux", "Ubuntu")

            device_labels = {}
            # Auto-detect disk list from CPF roles if none was supplied
            if is_linux and not disk_list:
                auto_devices = []

                # Database devices (may be multiple)
                i = 0
                while True:
                    row = execute_single_read_query(
                        connection,
                        f"SELECT * FROM overview WHERE field = 'iris disk role Database {i}';"
                    )
                    if not row or not row[2]:
                        break
                    device = row[2]
                    names_row = execute_single_read_query(
                        connection,
                        f"SELECT * FROM overview WHERE field = 'iris disk role Database {i} names';"
                    )
                    label = names_row[2].replace(",", ", ") if names_row and names_row[2] else f"Database {i}"
                    if device not in device_labels:
                        auto_devices.append(device)
                        device_labels[device] = label
                    i += 1

                # Single-device roles
                for role in ("Primary Journal", "Alternate Journal", "WIJ"):
                    row = execute_single_read_query(
                        connection,
                        f"SELECT * FROM overview WHERE field = 'iris disk role {role}';"
                    )
                    if row and row[2]:
                        device = row[2]
                        if device not in device_labels:
                            auto_devices.append(device)
                            device_labels[device] = role

                if auto_devices:
                    disk_list = auto_devices
                    print(f"  Auto disk list from CPF: {disk_list}")

            if is_unix:
                if extended_charts:
                    system_review.system_charts(filepath)

                chart_vmstat(
                    connection, _make_chart_dir(output_file_path_base, "vmstat"),
                    output_prefix, png_out, png_html_out, peak_chart, glorefs_peak_window, line_chart, day_overlay, bh_charts, long_period_smooth,
                )

                if is_linux:
                    chart_free_memory(
                        connection, _make_chart_dir(output_file_path_base, "free_memory"),
                        output_prefix, png_out, png_html_out, peak_chart, line_chart, day_overlay,
                    )

                if include_iostat:
                    chart_iostat(
                        connection, _make_chart_dir(output_file_path_base, "iostat"),
                        output_prefix, operating_system, png_out, png_html_out,
                        disk_list, peak_chart, glorefs_peak_window, line_chart, iostat_subfolders, day_overlay, bh_charts, long_period_smooth,
                        device_labels=device_labels,
                    )

                    if operating_system == "AIX":
                        chart_aix_sar_d(
                            connection, _make_chart_dir(output_file_path_base, "sar_d"),
                            output_prefix, operating_system, png_out, png_html_out,
                            disk_list, peak_chart, line_chart, iostat_subfolders, day_overlay,
                        )

                if include_nfsiostat:
                    chart_nfsiostat(
                        connection, _make_chart_dir(output_file_path_base, "nfsiostat"),
                        output_prefix, operating_system, png_out, png_html_out, peak_chart, line_chart,
                        iostat_subfolders,
                    )

            if operating_system == "Windows":
                chart_perfmon(
                    connection, _make_chart_dir(output_file_path_base, "perfmon"),
                    output_prefix, png_out, png_html_out, peak_chart, glorefs_peak_window, line_chart, day_overlay,
                )

        finally:
            close_connection(connection)

        if combined_overlay or not png_out:
            yaspe_combined_overlay.run(sql_filename, output_file_path_base, smooth_minutes=smooth_minutes)


    return


# Start here, entry point for command line

if __name__ == "__main__":
    input_file = ""
    existing_database = ""

    parser = argparse.ArgumentParser(
        prog="yaspe", description="Performance file review.", epilog='Be safe, "quote the path"'
    )

    current_version = "0.13.6"
    parser.add_argument("-v", "--version", action="version", version=current_version)

    parser.add_argument(
        "-i",
        "--input_file",
        help="Input HTML or .mgst filename with full path.",
        action="store",
        metavar='"/path/file.html"',
    )

    parser.add_argument(
        "-x",
        "--iostat",
        dest="include_iostat",
        help="Also chart iostat data (this can take a long time).",
        action="store_true",
    )

    parser.add_argument(
        "-n",
        "--nfsiostat",
        dest="include_nfsiostat",
        help="Also chart nfsiostat data.",
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
        help="Output filename prefix, defaults to HTML file name, blank (-o '') is legal.",
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
        help="Create CSV files of each HTML files metrics, append if csv file exists.",
        action="store_true",
    )

    parser.add_argument(
        "-p",
        "--png",
        dest="png_out",
        help="Create PNG charts of metrics. No HTML. HTML is the default if PNG not selected.",
        action="store_true",
    )

    parser.add_argument(
        "-P",
        "--PNG",
        dest="png_html_out",
        help="Create PNG and HTML charts of metrics. Charts are written into png/ and html/ subdirectories within each metric folder.",
        action="store_true",
    )

    parser.add_argument(
        "--dots",
        dest="dot_chart",
        help="Create PNG charts as dot charts instead of line charts (default is lines).",
        action="store_true",
    )

    parser.add_argument(
        "-s",
        "--system",
        dest="system_out",
        help="Output system overview.",
        action="store_true",
    )

    parser.add_argument(
        "-m",
        "--mgstat_file",
        dest="mgstat_file",
        help="This is an mgstat file log file (with extension .mgst).",
        action="store_true",
    )

    parser.add_argument(
        "-D",
        "--DDMMYYYY",
        dest="csv_date_format",
        help="Date format for csv files is DDMMYYYY",
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
        "--all-disks",
        dest="all_disks",
        help="Store every iostat device in SQLite. Default: when a CPF is found, "
             "only IRIS-related disks (databases, journals, WIJ) are stored.",
        action="store_true",
    )

    parser.add_argument(
        "--iostat_no_subfolders",
        dest="iostat_subfolders",
        help="Save all iostat charts flat (no per-device subfolders).",
        action="store_false",
        default=True,
    )

    parser.add_argument(
        "-l",
        "--large_file_split_on_string",
        dest="split_on",
        help='Split large input file on first occurrence of this string. Blank -l "" defaults to "div id=iostat"',
        action="store",
        metavar='"string to split on"',
    )

    parser.add_argument(
        "--peak_chart",
        dest="peak_chart",
        help="Create additional peak 60-minute charts for metrics with min_max enabled when data is 8-25 hours. Default is True.",
        action="store_true",
        default=True,
    )

    parser.add_argument(
        "--no_peak_chart",
        dest="peak_chart",
        help="Disable peak 60-minute charts.",
        action="store_false",
    )

    parser.add_argument(
        "-C",
        "--compare-dir",
        dest="compare_dir",
        help="Compare all HTML files in a directory: produce vmstat and mgstat overlay charts.",
        action="store",
        metavar='"/path/to/directory"',
    )

    parser.add_argument(
        "-B",
        "--combined",
        dest="combined_overlay",
        help="Also create a combined vmstat+mgstat overlay HTML chart alongside all other charts. Also runs automatically in default HTML and -P modes; combined_overlay.html is written to {prefix}_metrics/.",
        action="store_true",
    )

    parser.add_argument(
        "--smooth-minutes",
        dest="smooth_minutes",
        help="Rolling average window in minutes for --combined chart (default: 5, 0 = raw).",
        type=float,
        default=5,
        metavar="N",
    )

    parser.add_argument(
        "--day-overlay",
        dest="day_overlay",
        help="Create day-overlay charts for all metrics when data spans more than 25 hours. "
             "Total CPU, Glorefs, and PhyRds always get day-overlay charts regardless of this flag.",
        action="store_true",
    )

    parser.add_argument(
        "--bh-charts",
        dest="bh_charts",
        help="Create per-day business-hours peak charts for multi-day data (slow; off by default).",
        action="store_true",
    )

    parser.add_argument(
        "--long-period-smooth",
        dest="long_period_smooth",
        help="Rolling average window in minutes for multi-day charts (default: 5).",
        type=int,
        default=5,
        metavar="N",
    )

    parser.add_argument(
        "--context",
        dest="context",
        help='Optional context note included in the LLM context bundle '
             '(e.g. "users reported slowness Tuesday").',
        action="store",
        default=None,
        metavar='"context string"',
    )

    parser.add_argument(
        "--llm-context",
        dest="llm_context",
        help="Export an anonymized markdown context bundle plus analysis prompt "
             "for LLM-based performance review (implies -s).",
        action="store_true",
    )

    parser.add_argument(
        "--resample",
        dest="resample_interval",
        help="Resample interval for timeseries in the LLM context bundle. "
             "Default: auto — 5min for up to 2 days of data, 15min for 3-4, "
             "30min for 5+. Examples: 5min, 10min, 30min.",
        action="store",
        default=None,
        metavar="INTERVAL",
    )

    args = parser.parse_args()

    if args.compare_dir is not None:
        yaspe_compare_overlay.run(args.compare_dir)
        sys.exit(0)

    # Validate input file
    if args.input_file is not None:
        try:
            if os.path.getsize(args.input_file) > 0:
                input_file = args.input_file
            else:
                print('Error: -i "Input HTML filename with full path required"')
                sys.exit()
        except OSError as e:
            print("Could not process files because: {}".format(str(e)))
            sys.exit()

    else:
        # if no input file validate existing database to chart
        if args.existing_database is None:
            print('Error: -i "Input HTML filename with full path required"')
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

    if args.llm_context:
        args.system_out = True

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
            args.png_html_out,
            args.system_out,
            args.disk_list,
            args.split_on,
            args.csv_date_format,
            args.mgstat_file,
            args.peak_chart,
            not args.dot_chart,  # line_chart is True by default (when dot_chart is False)
            args.iostat_subfolders,
            args.smooth_minutes,
            args.day_overlay,
            args.bh_charts,
            args.long_period_smooth,
            args.context,
            args.llm_context,
            args.resample_interval,
            args.combined_overlay,
            all_disks=args.all_disks,
        )
    except OSError as e:
        print("Could not process files because: {}".format(str(e)))
