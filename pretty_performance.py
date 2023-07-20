#!/usr/bin/env python3

# Create a set of useful charts from Linux pButtons and SystemPerformance SQLite3 files

# example:
# /path_to_file/pretty_performance.py -f yaspe_SystemPerformance.sqlite -s 10:00 -e 11:00 -p ./input.yml -i -m -c ./charts.yml -o ./pretty_yaspe

import os
import pandas as pd
import matplotlib as mpl

# mpl.use('TkAgg')
import seaborn as sns
import string

from datetime import date, datetime, timedelta
import dateutil.parser
import calendar

from matplotlib import pyplot as plt
import matplotlib.dates as mdates
from matplotlib.dates import DateFormatter
from matplotlib.dates import MO, TU, WE, TH, FR, SA, SU

import numpy as np
import glob

import argparse
import csv
import yaml

import sqlite3
from sqlite3 import Error

import logging
from functools import reduce

from pandas.plotting import register_matplotlib_converters

register_matplotlib_converters()


def smooth(y, box_pts):
    box = np.ones(box_pts) / box_pts
    y_smooth = np.convolve(y, box, mode="same")
    return y_smooth


def check_data(db, name):
    cur = db.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", [name])
    if len(cur.fetchall()) == 0:
        logging.warning("no data for:" + name)
        return False
    return True


# need this as utility, since pandas timestamps are not compatible with sqlite3 timestamps
# there's a possible other solution by using converters in sqlite, but I haven't explored that yet


def fix_index(df):
    df.index = pd.to_datetime(df["datetime"])
    df = df.drop(["datetime"], axis=1)
    df.index.name = "datetime"
    return df


# Return a dataframe with selected non-disk metrics


def get_subset_dataframe(db, subsetname):

    if not check_data(db, subsetname):
        return None
    data = pd.read_sql_query('select * from "' + subsetname + '"', db)

    if "datetime" not in data.columns.values:
        logging.debug("No datetime")
        size = data.shape[0]
        # one of those evil OS without datetime in vmstat
        # evil hack: take index from mgstat (we should have that in every pButtons and SystemPerformance) and map that
        # is going to horribly fail when the number of rows doesn't add up ---> TODO for later
        dcolumn = pd.read_sql_query("select datetime from mgstat", db)
        data.index = pd.to_datetime(dcolumn["datetime"][:size])
        data.index.name = "datetime"

    else:
        data = fix_index(data)

    # if vmstat add an extra column

    if subsetname == "vmstat":
        data["Total CPU"] = 100 - data["id"]

    return data


# Return a dataframe with the selected disk


def get_disk_dataframe(db, disk_name):

    subsetname = "iostat"
    split_on = "Device"
    plotDisks = disk_name

    if not check_data(db, subsetname):
        return None

    c = db.cursor()

    # Get list of unique disk names
    c.execute("select distinct " + split_on + ' from "' + subsetname + '"')
    rows = c.fetchall()
    # Loop through each disk... could be a bit better here, we know the names
    for column in rows:
        # If specified only plot selected disks for iostat - saves time and space
        if column[0] not in plotDisks:
            logging.debug("Skipping plot subsection: " + column[0])
        else:
            logging.debug("Including plot subsection: " + column[0])
            c.execute(
                'select * from "' + subsetname + '" where ' + split_on + "=?",
                [column[0]],
            )
            data = pd.read_sql_query(
                'select * from "' + subsetname + '" where ' + split_on + '="' + column[0] + '"',
                db,
            )
            if len(data["datetime"][0].split()) == 1:
                # another evil hack for iostat on some redhats (no complete timestamps)
                # the datetime field only has '09/13/18' instead of '09/13/18 14:39:49'
                # -> take timestamps from mgstat
                data = data.drop("datetime", axis=1)
                size = data.shape[0]
                # one of those evil OS without datetime in vmstat
                # evil hack: take index from mgstat (we should have that in every pButtons and SystemPerformance) and map that
                # is going to horribly fail when the number of rows doesn't add up ---> TODO for later
                dcolumn = pd.read_sql_query("select datetime from mgstat", db)
                ##since mgstat has only one entry per timestamp, but iostat has one entry per timestamp per device
                ##we need to duplicate the rows appropriately which is data.shape[0]/dcolumn.shape[0]) times
                # dcolumn=dcolumn.loc[dcolumn.index.repeat(size/dcolumn.shape[0])].reset_index(drop=True)

                data.index = pd.to_datetime(dcolumn["datetime"][:size])
                data.index.name = "datetime"
            else:
                data = fix_index(data)
            data = data.drop([split_on], axis=1)

    return data


def zoom_chart(df_master, df_master_zoom, plot_d, column_d, disk_type, disk_name):

    if disk_name == "":
        TITLE = column_d["Text"] + " " + plot_d["TITLEDATES"]
    else:
        TITLE = disk_type + " (" + disk_name + ") " + column_d["Text"] + " " + plot_d["TITLEDATES"]

    x = df_master[column_d["Name"]]
    xz = df_master_zoom[column_d["Name"]]

    plt.style.use("seaborn-v0_8-whitegrid")
    palette = plt.get_cmap(plot_d["Colormap Name"])
    color = palette(1)

    # Two plots on the same figure
    fig, (ax1, ax2) = plt.subplots(2, 1)
    plt.gcf().set_size_inches(plot_d["WIDTH"], plot_d["HEIGHT"])
    # plt.gcf().set_dpi(plot_d["DPI"])

    ax1.grid(which="major", axis="both", linestyle="--")
    ax1.set_title(TITLE, fontsize=14)
    line1 = ax1.plot(df_master[column_d["Name"]], color=color, alpha=0.7)

    if plot_d["MEDIAN"]:
        ax1.plot(
            x,
            smooth(df_master[column_d["Name"]], plot_d["movingAverage"]),
            label="Moving Average",
            color=palette(2),
            alpha=0.7,
            lw=1,
        )

    ax1.set_ylabel(column_d["Text"], fontsize=10, color=color)
    ax1.tick_params(labelsize=10)
    ax1.set_ylim(bottom=0)  # Always zero start
    if column_d["Name"] == "Total CPU_vm":
        ax1.set_ylim(top=100)
    if df_master[column_d["Name"]].max() < 10:
        ax1.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.2f}"))
    else:
        ax1.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))

    TotalMinutes = (df_master.index[-1] - df_master.index[0]).total_seconds() / 60

    # print(f"Total minutes {TotalMinutes}")

    if TotalMinutes <= 15:
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        ax1.xaxis.set_major_locator(mdates.SecondLocator(interval=int((TotalMinutes * 60) / 10)))
    elif TotalMinutes <= 180:
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax1.xaxis.set_major_locator(mdates.MinuteLocator(interval=int(TotalMinutes / 10)))
    elif TotalMinutes <= 1500:
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax1.xaxis.set_major_locator(mdates.HourLocator())
    elif TotalMinutes <= 3000:
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d-%H:%M"))
    else:
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%a %m/%d - %H:%M"))

    plt.setp(ax1.get_xticklabels(), rotation=45, ha="right")

    TITLE = column_d["Text"] + " Zoom In "

    color = palette(2)
    ax2.set_title(TITLE, fontsize=14)
    line2 = ax2.plot(df_master_zoom[column_d["Name"]], color=color, alpha=0.5)
    if plot_d["MEDIAN"]:
        ax2.plot(
            xz,
            smooth(df_master_zoom[column_d["Name"]], plot_d["movingAverage"]),
            label="Moving Average",
            color=palette(1),
            alpha=0.7,
            lw=2,
        )

    ax2.set_ylabel(column_d["Text"], fontsize=10, color=color)
    ax2.tick_params(labelsize=10)
    ax2.set_ylim(bottom=0)  # Always zero start
    if df_master_zoom[column_d["Name"]].max() < 10:
        ax2.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.2f}"))
    else:
        ax2.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))

    TotalMinutes = (df_master_zoom.index[-1] - df_master_zoom.index[0]).total_seconds() / 60

    if TotalMinutes <= 15:
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        ax2.xaxis.set_major_locator(mdates.SecondLocator(interval=int((TotalMinutes * 60) / 10)))
    elif TotalMinutes <= 180:
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax2.xaxis.set_major_locator(mdates.MinuteLocator(interval=int(TotalMinutes / 10)))
    elif TotalMinutes <= 1500:
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax2.xaxis.set_major_locator(mdates.HourLocator())
    elif TotalMinutes <= 3000:
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d-%H:%M"))
    else:
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%a %m/%d - %H:%M"))

    # print(f"Total minutes {TotalMinutes}")

    ax2.grid(which="major", axis="both", linestyle="--")
    plt.setp(ax2.get_xticklabels(), rotation=45, ha="right")
    plt.tight_layout()

    FinalFileName = (
        plot_d["outputFile_png"]
        + "_"
        + (
            plot_d["RunDate"][0].strftime("%Y-%m-%d")
            + " "
            + disk_type
            + " "
            + column_d["Text"]
            + " "
            + plot_d["ZOOM_TO"]
            + ".png"
        ).replace(" ", "_")
    )
    plt.savefig(FinalFileName, format="png", dpi=plot_d["DPI"])
    plt.close(fig)


def free_chart(df_master, plot_d, columns_to_show, TITLE, y_label_l, y_label_r, y_max_l, y_max_r, zoom):

    # print(f'Dataframe: {df_master}')

    # What are the attribtes of this chart
    Right_axis_used = False
    for column_d in columns_to_show:
        if column_d["axis"] == "right":
            Right_axis_used = True
            break

    # print(f'Columns: {columns_to_show}')

    TotalMinutes = (df_master.index[-1] - df_master.index[0]).total_seconds() / 60
    axis_greater_than_10_left = False
    axis_greater_than_10_right = False

    # Start the plot

    plt.style.use("seaborn-v0_8-whitegrid")
    palette = plt.get_cmap(plot_d["Colormap Name"])

    fig, ax1 = plt.subplots()
    plt.gcf().set_size_inches(plot_d["WIDTH"], plot_d["HEIGHT"])
    # plt.gcf().set_dpi(plot_d["DPI"])

    ax1.grid(which="major", axis="both", linestyle="--")
    ax1.set_title(TITLE, fontsize=14)

    # This where the left hand plot happens
    colour_count = 1

    YAxisMaxL = 0
    YAxisMaxR = 0

    for column_d in columns_to_show:

        if column_d["axis"] == "left":
            if plot_d["limit_yaxis"] and y_max_l == 0:
                # To remove outliers from chart limit x axis to 3 sigma
                YAxis3Sigma = df_master[column_d["Name"]].mean() + 3 * df_master[column_d["Name"]].std()
                if YAxis3Sigma > YAxisMaxL:
                    YAxisMaxL = YAxis3Sigma
                if YAxisMaxL > 10:
                    axis_greater_than_10_left = True
            else:
                if df_master[column_d["Name"]].max() > 10:
                    axis_greater_than_10_left = True

            ax1.plot(
                df_master[column_d["Name"]],
                label=column_d["Text"],
                color=palette(colour_count),
                alpha=0.5,
                linestyle=column_d["Style"],
                linewidth=column_d["Linewidth"],
                markersize=column_d["Markersize"],
                marker=column_d["Markerstyle"],
            )
            colour_count = colour_count + 1

    if plot_d["limit_yaxis"]:
        ax1.set_title("3 Sigma " + TITLE, fontsize=14)
    else:
        ax1.set_title(TITLE, fontsize=14)

    ax1.set_ylabel(y_label_l, fontsize=14)
    ax1.tick_params(labelsize=14)
    ax1.set_ylim(bottom=0)  # Always zero start

    if plot_d["limit_yaxis"] and y_max_l == 0:
        y_max_l = YAxisMaxL

    if y_max_l > 0:
        ax1.set_ylim(top=y_max_l)
    if axis_greater_than_10_left:
        ax1.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))
    else:
        ax1.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.2f}"))

    if TotalMinutes <= 15:
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        ax1.xaxis.set_major_locator(mdates.SecondLocator(interval=int((TotalMinutes * 60) / 10)))
    elif TotalMinutes <= 180:
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax1.xaxis.set_major_locator(mdates.MinuteLocator(interval=int(TotalMinutes / 10)))
    elif TotalMinutes <= 1500:
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax1.xaxis.set_major_locator(mdates.HourLocator())
    elif TotalMinutes <= 3000:
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d-%H:%M"))
    else:
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%a %m/%d - %H:%M"))

    ax1.legend(loc="upper left", fontsize=14)

    if Right_axis_used:

        ax2 = ax1.twinx()
        for column_d in columns_to_show:
            if column_d["axis"] == "right":
                if plot_d["limit_yaxis"] and y_max_r == 0:
                    # To remove outliers from chart limit x axis to 3 sigma
                    YAxis3Sigma = df_master[column_d["Name"]].mean() + 3 * df_master[column_d["Name"]].std()
                    if YAxis3Sigma > YAxisMaxR:
                        YAxisMaxR = YAxis3Sigma
                    if YAxisMaxR > 10:
                        axis_greater_than_10_right = True
                else:
                    if df_master[column_d["Name"]].max() > 10:
                        axis_greater_than_10_right = True

                ax2.plot(
                    df_master[column_d["Name"]],
                    label=column_d["Text"],
                    color=palette(colour_count),
                    alpha=0.5,
                    linestyle=column_d["Style"],
                    linewidth=column_d["Linewidth"],
                    markersize=column_d["Markersize"],
                    marker=column_d["Markerstyle"],
                )
                colour_count = colour_count + 1

        ax2.set_ylabel(y_label_r, fontsize=14)
        ax2.tick_params(labelsize=14)
        ax2.set_ylim(bottom=0)  # Always zero start

        if plot_d["limit_yaxis"] and y_max_r == 0:
            y_max_r = YAxisMaxR

        if y_max_r > 0:
            ax2.set_ylim(top=y_max_r)
        if axis_greater_than_10_right:
            ax2.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.0f}"))
        else:
            ax2.yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter("{x:,.2f}"))

        ax2.grid(None)

        if TotalMinutes <= 15:
            ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            ax2.xaxis.set_major_locator(mdates.SecondLocator(interval=int((TotalMinutes * 60) / 10)))
        elif TotalMinutes <= 180:
            ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
            ax2.xaxis.set_major_locator(mdates.MinuteLocator(interval=int(TotalMinutes / 10)))
        elif TotalMinutes <= 1500:
            ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
            ax2.xaxis.set_major_locator(mdates.HourLocator())
        elif TotalMinutes <= 3000:
            ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d-%H:%M"))
        else:
            ax2.xaxis.set_major_formatter(mdates.DateFormatter("%a %m/%d - %H:%M"))

        ax2.legend(loc="upper right", fontsize=14)

    plt.setp(ax1.get_xticklabels(), rotation=45, ha="right", fontsize=10)
    plt.tight_layout()

    FinalFileName = (
        plot_d["outputFile_png"]
        + "_"
        + (TITLE + ".png").replace(": ", "_").replace(",", "_").replace(" ", "_").replace("__", "_")
    )

    plt.savefig(FinalFileName, format="png", dpi=plot_d["DPI"])
    plt.close(fig)


def execute_single_read_query(connection, query):
    cursor = connection.cursor()
    result = None
    try:
        cursor.execute(query)
        result = cursor.fetchone()
        return result
    except Error as error:
        print(f"The error '{error}' occurred")


def mainline(db_filename, zoom_start, zoom_end, plot_d, config, include_iostat_plots, include_mgstat_plots):

    disk_list_d = plot_d["Disk List"]

    db = sqlite3.connect(db_filename)

    # Get the start date for date format validation
    profile_run = execute_single_read_query(db, "SELECT * FROM overview WHERE field = 'profile run';")[2]
    run_start = profile_run.split("on ")[1]
    run_start = run_start[:-1]
    run_start_date = dateutil.parser.parse(run_start).strftime("%Y-%m-%d")

    # iostat section only

    print(f"{include_iostat_plots}")

    if include_iostat_plots:

        # Output zoom charts
        for key in disk_list_d.keys():
            print(key + " " + disk_list_d[key])

            # Get disk metrics
            df_master = get_disk_dataframe(db, disk_list_d[key])

            df_master_zoom = df_master.between_time(zoom_start, zoom_end)

            # Create headings
            RunDate = df_master.head(1).index.tolist()
            plot_d["RunDate"] = RunDate

            RunDateStart = df_master.head(1).index.tolist()
            RunDateStart = RunDateStart[0].strftime("%d/%m/%Y")

            # Day of the week
            StartDay = calendar.day_name[pd.to_datetime(RunDateStart, dayfirst=True).weekday()]

            TITLEDATES = plot_d["Site Name"] + ": " + StartDay + " " + RunDate[0].strftime("%d %b %Y")

            plot_d["TITLEDATES"] = TITLEDATES

            # print(TITLEDATES)
            # print("Median r/s : %s" % df_master['r/s'].median())
            # print("Max r/s    : %s" % df_master['r/s'].max())
            # print("Median w/s : %s" % df_master['w/s'].median())
            # print("Max w/s    : %s" % df_master['w/s'].max())
            # print("\nZoom to "+zoom_start+" to "+zoom_end)
            # print("Median r/s : %s" % df_master_zoom['r/s'].median())
            # print("Max r/s    : %s" % df_master_zoom['r/s'].max())
            # print("Median w/s : %s" % df_master_zoom['w/s'].median())
            # print("Max w/s    : %s" % df_master_zoom['w/s'].max())

            # Print major charts for each disk

            column_d = {"Text": "Read IOPS", "Name": "r/s"}
            zoom_chart(df_master, df_master_zoom, plot_d, column_d, key, disk_list_d[key])

            column_d = {"Text": "Write IOPS", "Name": "w/s"}
            zoom_chart(df_master, df_master_zoom, plot_d, column_d, key, disk_list_d[key])

            column_d = {"Text": "Read latency (ms)", "Name": "r_await"}
            zoom_chart(df_master, df_master_zoom, plot_d, column_d, key, disk_list_d[key])

            column_d = {"Text": "Write latency (ms)", "Name": "w_await"}
            zoom_chart(df_master, df_master_zoom, plot_d, column_d, key, disk_list_d[key])

    # Process ad-hoc reports

    if any(config.values()):
        #
        # Get vmstat
        df_master_vm = get_subset_dataframe(db, "vmstat")
        df_master_vm = df_master_vm.add_suffix("_vm")

        # Resample
        # This resample at same sample size and base=0
        # df_master_vm = df_master_vm.reset_index().set_index('datetime').resample('5S').mean()
        # will realign starting on 0, eg 00:01:06 will end up as 12:01:05 am

        # Resample to 1 sec

        # Get rid of duplicates. e.g. if appending
        df_master_vm = df_master_vm.loc[~df_master_vm.index.duplicated(), :]

        # df_master_vm = df_master_vm.reset_index().set_index("datetime").resample("1S", convention='start').interpolate(method="linear")
        df_master_vm = df_master_vm.reset_index().set_index("datetime").resample("1S").interpolate(method="linear")

        # Get mgstat
        df_master_mg = get_subset_dataframe(db, "mgstat")
        df_master_mg = df_master_mg.add_suffix("_mg")
        # Get rid of duplicates. e.g. if appending
        df_master_mg = df_master_mg.loc[~df_master_mg.index.duplicated(), :]
        df_master_mg = (
            df_master_mg.reset_index()
            .set_index("datetime")
            .resample("1S", convention="start")
            .interpolate(method="linear")
        )

        # for iostat get and database (_db) Primary journal (_pri) WIJ (_wij)
        for key in disk_list_d.keys():
            print(f"Disk Type {key} Disk {disk_list_d[key]}")

            # Get selected disk metrics
            if key == "Database":
                df_master_db = get_disk_dataframe(db, disk_list_d[key])
                df_master_db = df_master_db.add_suffix("_db")
            elif key == "Primary Journal":
                df_master_Pri = get_disk_dataframe(db, disk_list_d[key])
                df_master_Pri = df_master_Pri.add_suffix("_pri")
            elif key == "WIJ":
                df_master_WIJ = get_disk_dataframe(db, disk_list_d[key])
                df_master_WIJ = df_master_WIJ.add_suffix("_wij")
            elif key == "IRIS":
                df_master_IRIS = get_disk_dataframe(db, disk_list_d[key])
                df_master_IRIS = df_master_IRIS.add_suffix("_iris")

        dataframes = [df_master_db, df_master_Pri, df_master_WIJ, df_master_IRIS]

        df_merged_disks = reduce(lambda left, right: pd.merge(left, right, on="datetime"), dataframes)

        # It is possible that you get duplicate rows in the index, I have seen this with iostat, which results in error;
        # raise ValueError("cannot reindex from a duplicate axis")
        # You can display them with:
        # print(df_merged_disks[df_merged_disks.index.duplicated()])
        # But I dont really care if there is the odd glitch, just remove them:

        df_merged_disks = df_merged_disks[~df_merged_disks.index.duplicated()]

        df_merged_disks = (
            df_merged_disks.reset_index()
            .set_index("datetime")
            .resample("1S", convention="start")
            .interpolate(method="linear")
        )

        # Check the date formats match before merge
        date_vm = df_master_vm.head(1).index.tolist()
        date_mg = df_master_mg.head(1).index.tolist()
        date_disk = df_merged_disks.head(1).index.tolist()

        if (
            run_start_date
            == date_mg[0].strftime("%Y-%m-%d")
            == date_vm[0].strftime("%Y-%m-%d")
            == date_disk[0].strftime("%Y-%m-%d")
        ):
            print(f"Dates OK")
        else:
            # run_start_date is in Y-m-d format
            # = dateutil.parser.parse(run_start).strftime('%Y-%m-%d')

            if date_mg[0].strftime("%Y-%m-%d") != run_start_date:
                print(
                    f"mgstat date mismatch corrected: "
                    f"{date_mg[0].strftime('%Y-%m-%d')} start date: {run_start_date}"
                )
                # swap dd mm to mm dd
                df_master_mg.index = df_master_mg.index.strftime("%Y-%d-%m %H:%M:%S")
                df_master_mg.index = pd.to_datetime(df_master_mg.index, format="%Y-%m-%d %H:%M:%S")
            if date_vm[0].strftime("%Y-%m-%d") != run_start_date:
                print(
                    f"vmstat date mismatch corrected: "
                    f"{date_disk[0].strftime('%Y-%m-%d')} start date: {run_start_date}"
                )
                df_master_vm.index = df_master_vm.index.strftime("%Y-%d-%m %H:%M:%S")
                df_master_vm.index = pd.to_datetime(df_master_vm.index, format="%Y-%m-%d %H:%M:%S")
            if date_disk[0].strftime("%Y-%m-%d") != run_start_date:
                print(
                    f"iostat date mismatch corrected: "
                    f"{date_disk[0].strftime('%Y-%m-%d')} start date: {run_start_date}"
                )
                df_merged_disks.index = df_merged_disks.index.strftime("%Y-%d-%m %H:%M:%S")
                df_merged_disks.index = pd.to_datetime(df_merged_disks.index, format="%Y-%m-%d %H:%M:%S")

        # Merge in mgstat
        df_bigmerge = pd.merge(df_merged_disks, df_master_mg, how="left", left_index=True, right_index=True)

        # Merge in vmstat
        df_bigmerge = pd.merge(df_bigmerge, df_master_vm, how="left", left_index=True, right_index=True)

        # Text fields are not resampled so are nan
        # df_bigmerge = df_bigmerge.dropna()

        df_bigmerge_zoom = df_bigmerge.between_time(zoom_start, zoom_end)

        if plot_d["output csv"]:
            # to make a smaller file round to integers... cannot convert, for example a_wait to integer... re-think this...
            # cols = df_bigmerge.columns
            # df_bigmerge[cols] = df_bigmerge[cols].apply(pd.to_numeric, errors='ignore').astype(np.int64)
            df_bigmerge.to_csv(plot_d["outputFile_png"] + "_000_merged.csv", sep=",")
            df_bigmerge_zoom.to_csv(plot_d["outputFile_png"] + "_000_merged_zoom.csv", sep=",")

        # Create headings
        RunDate = df_bigmerge.head(1).index.tolist()
        plot_d["RunDate"] = RunDate

        RunDateStart = df_bigmerge.head(1).index.tolist()
        RunDateStart = RunDateStart[0].strftime("%d/%m/%Y")

        # Day of the week
        StartDay = calendar.day_name[pd.to_datetime(RunDateStart, dayfirst=True).weekday()]

        TITLEDATES = plot_d["Site Name"] + ": " + StartDay + " " + RunDate[0].strftime("%d %b %Y")

        plot_d["TITLEDATES"] = TITLEDATES

        # Couple of standard reports
        if include_mgstat_plots:

            print(f"Standard reports:")

            column_d = {"Text": "CPU Utilisation %", "Name": "Total CPU_vm"}
            zoom_chart(df_bigmerge, df_bigmerge_zoom, plot_d, column_d, "", "")

            column_d = {"Text": "Glorefs", "Name": "Glorefs_mg"}

            zoom_chart(df_bigmerge, df_bigmerge_zoom, plot_d, column_d, "", "")

            column_d = {"Text": "Gloupds", "Name": "Gloupds_mg"}
            zoom_chart(df_bigmerge, df_bigmerge_zoom, plot_d, column_d, "", "")

            column_d = {"Text": "Rdratio", "Name": "Rdratio_mg"}
            zoom_chart(df_bigmerge, df_bigmerge_zoom, plot_d, column_d, "", "")

            column_d = {"Text": "CPU wait", "Name": "wa_vm"}
            zoom_chart(df_bigmerge, df_bigmerge_zoom, plot_d, column_d, "", "")

        # For each chart in the chart extras file
        for c_id, c_info in config.items():
            print("Creating chart:", c_id)

            # DEBUG
            # print(c_info['Title'])
            # print(c_info['y_label_l'])
            # print(c_info['y_label_r'])
            # if c_info['zoom']:
            #    print("Zoom")
            # else:
            #    print("No Zoom")
            # # For nested columns
            # columns_to_show = []
            # for col_id, col_info in c_info['columns_to_show'].items():
            #    columns_to_show.append(c_info['columns_to_show'][col_id])
            #    print(c_info['columns_to_show'][col_id])
            # print(columns_to_show)

            columns_to_show = []
            for col_id, col_info in c_info["columns_to_show"].items():
                columns_to_show.append(c_info["columns_to_show"][col_id])

            zoom = c_info["zoom"]
            if c_info["zoom"]:
                TITLE = c_info["Title"] + " " + plot_d["ZOOM_TITLE"] + " " + plot_d["TITLEDATES"]
                free_chart(
                    df_bigmerge_zoom,
                    plot_d,
                    columns_to_show,
                    TITLE,
                    c_info["y_label_l"],
                    c_info["y_label_r"],
                    c_info["y_max_l"],
                    c_info["y_max_r"],
                    zoom,
                )
            else:
                TITLE = c_info["Title"] + " " + plot_d["TITLEDATES"]
                free_chart(
                    df_bigmerge,
                    plot_d,
                    columns_to_show,
                    TITLE,
                    c_info["y_label_l"],
                    c_info["y_label_r"],
                    c_info["y_max_l"],
                    c_info["y_max_r"],
                    zoom,
                )


if __name__ == "__main__":

    # help="set log level:DEBUG,INFO,WARNING,ERROR,CRITICAL. The default is INFO"
    loglevel = "INFO"
    logging.basicConfig(level=loglevel)

    parser = argparse.ArgumentParser(
        description="Create charts from Linux pButtons and SystemPerformance data already stored in sqlite3 file"
    )
    parser.add_argument("-f", "--db_filename", help="db path and file name", required=True)
    parser.add_argument("-s", "--zoom_start", help="Start time for zoom", required=False)
    parser.add_argument("-e", "--zoom_end", help="Stop time for zoom", required=False)
    parser.add_argument("-p", "--paramater_file", help="Input for standard definitions", required=True)
    parser.add_argument(
        "-i", "--include_iostat_plots", help="Include standard default iostat plots", action="store_true"
    )
    parser.add_argument("-m", "--include_mgstat_plots", help="Include standard mgstat plots", action="store_true")
    parser.add_argument("-x", "--output_csv_file", help="output csv file", action="store_true")
    parser.add_argument("-c", "--chart_file", help="Chart file definitions", required=False)
    parser.add_argument("-o", "--output_dir", help="override output directory", required=False)
    parser.add_argument(
        "-l", "--limit_yaxis", help="limit y axis to 3 sigma maximum", required=False, action="store_true"
    )
    args = parser.parse_args()

    if args.db_filename is not None:
        db_filename = args.db_filename
    else:
        print('Error: -f "sqlite3 (from yaspe) file path and file name required"')
        exit(1)

    if args.zoom_start is not None:
        zoom_start = args.zoom_start
    else:
        zoom_start = "13:00"

    if args.zoom_end is not None:
        zoom_end = args.zoom_end
    else:
        zoom_end = "14:00"

    if args.output_dir is not None:
        output_dir_override = args.output_dir
    else:
        output_dir_override = ""

    config = {}
    if args.chart_file is not None:
        if os.path.isfile(args.chart_file):
            with open(args.chart_file, "r") as ymlfile:
                config = yaml.safe_load(ymlfile)
        else:
            print('Error: -c "config yml file not found"')
            exit(1)

    plot_d = {}
    if args.paramater_file is not None:
        if os.path.isfile(args.paramater_file):
            with open(args.paramater_file, "r") as ymlfile:
                plot_d = yaml.safe_load(ymlfile)
        else:
            print('Error: -p "parameter yml file not found"')
            exit(1)
    else:
        print('Error: -p "parameter yml file required"')
        exit(1)

    # Set some constants
    plot_d["output csv"] = args.output_csv_file
    plot_d["limit_yaxis"] = args.limit_yaxis

    plot_d["ZOOM_TITLE"] = zoom_start.replace(":", "") + " to " + zoom_end.replace(":", "")
    plot_d["ZOOM_TO"] = zoom_start.replace(":", "") + "_" + zoom_end.replace(":", "")

    # Create output path and prefix, use current cmd line location if none specified in parameter
    outpath = os.path.dirname(db_filename)
    if outpath == "":
        outpath = os.getcwd()
    outputfile = os.path.basename(db_filename)
    outputfileName = outputfile.split(".")[0]

    plot_d["outpath"] = outpath
    plot_d["outputfile"] = outputfile
    plot_d["outputfileName"] = outputfileName

    # Create directories for generated charts
    if output_dir_override == "":
        if not os.path.exists(outpath + "/charts_pretty"):
            os.makedirs(outpath + "/charts_pretty")
        outputFile_png = outpath + "/charts_pretty/" + outputfileName
        plot_d["outputFile_png"] = outputFile_png
    else:
        if not os.path.exists(outpath + "/" + output_dir_override):
            os.makedirs(outpath + "/" + output_dir_override)
        outputFile_png = outpath + "/" + output_dir_override + "/" + outputfileName
        plot_d["outputFile_png"] = outputFile_png

    try:
        mainline(
            db_filename, zoom_start, zoom_end, plot_d, config, args.include_iostat_plots, args.include_mgstat_plots
        )
    except OSError as e:
        print("Could not process files because: {}".format(str(e)))
