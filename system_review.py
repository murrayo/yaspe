import os
import pandas as pd

import yaml
import chart_output, chart_templates, yaspe_utilities


def what_date_format(df, date_format_string, column_name, name):

    # Force date format based on strftime()
    if date_format_string == "mm/dd/yyyy":
        df[column_name] = pd.to_datetime(df["datetime"], format="%m/%d/%Y %I:%M:%S %p", infer_datetime_format=True)
    elif date_format_string == "dd/mm/yyyy":
        df[column_name] = pd.to_datetime(df["datetime"], format="%d/%m/%Y %I:%M:%S %p", infer_datetime_format=True)
    else:
        print(date_format_string)
        print(f"{name} date format error cannot be determined")
        # exit()

    df.set_index("datetime", inplace=True)

    start_date = df.index[0].strftime("%a, %b %d, %Y %H:%M:%S")
    end_date = df.index[-1].strftime("%a, %b %d, %Y %H:%M:%S")

    date_string = f"{start_date} - {end_date}"

    return df, date_string


def system_charts(base_file_path):

    csv_needed = False

    print("System Review Started...")

    # Parameters.

    site_survey_input = {}

    if os.path.isfile(f"{base_file_path}/site_survey_input.yml"):
        with open(f"{base_file_path}/site_survey_input.yml", "r") as ymlfile:
            site_survey_input = yaml.safe_load(ymlfile)
    else:
        print(f"Error: Input file required")

    # Output files
    if yaspe_utilities.check_keyword_exists(site_survey_input, "chart sub folder"):
        charts_path = site_survey_input["Chart"]["chart sub folder"]
    else:
        charts_path = "System review"

    output_file_path_txt = f"{base_file_path}/{charts_path}/txt"

    # add csv and text folders
    if not os.path.exists(output_file_path_txt):
        os.makedirs(output_file_path_txt)

    # Business hours
    if site_survey_input["Business Hours"]["use business hours"]:
        business_hours_start = str(site_survey_input["Business Hours"]["start of day"])
        business_hours_end = str(site_survey_input["Business Hours"]["end of day"])

        business_hours_start = f"{business_hours_start[0:2]}:{business_hours_start[2:4]}:00"
        business_hours_end = f"{business_hours_end[0:2]}:{business_hours_end[2:4]}:00"

    iostat_file_name = f'{base_file_path}/{site_survey_input["System"]["iostat filename"]}'
    vmstat_file_name = f'{base_file_path}/{site_survey_input["System"]["vmstat filename"]}'
    mgstat_file_name = f'{base_file_path}/{site_survey_input["System"]["mgstat filename"]}'

    for input_filename in [iostat_file_name, vmstat_file_name, mgstat_file_name]:
        try:
            if os.path.exists(input_filename):
                pass
            else:
                print(f"Input file does not exist {input_filename}")
                exit()
        except Exception as e:
            print("Error occurred looking for input file:", e)
            exit()

    # ------------------------------------------------------------------------------------
    # Get vmstat data

    vmstat_title = ""
    number_cpus = 0

    if "yaspe" in site_survey_input:
        number_cpus = site_survey_input["yaspe"]["CPUs"]

        vmstat_title += f"{str(number_cpus)} vCPU"
        vmstat_title += f'{site_survey_input["yaspe"]["Processor model"].split("(R)")[2]} - '

    df = pd.read_csv(vmstat_file_name, sep=",", encoding="ISO-8859-1")

    # Clean the data and create datetime index
    df = df.dropna(axis=1, how="all")

    # validate date format
    vmstat_date_format = f'{site_survey_input["System"]["vmstat date format"]}'
    df, date_string = what_date_format(df, vmstat_date_format, "datetime", "vmstat")

    df["Total CPU"] = 100 - df["id"]

    # Chart vmstat
    chart_output.chart_vmstat(
        df,
        site_survey_input,
        base_file_path=base_file_path,
        charts_path=charts_path,
        extra_subtitle=vmstat_title,
        number_cpus=number_cpus,
    )

    if (df.index[-1] - df.index[0]).total_seconds() / 60 / 60 > 24.1:
        single_day = False
    else:
        single_day = True

    # Find peak CPU window
    if not site_survey_input["Peak minutes"] == 0 and single_day:
        peak_zoom = True

        peak_minutes = site_survey_input["Peak minutes"]
        peak_minutes_sample = f'{str(site_survey_input["Peak minutes"])}T'

    else:
        peak_zoom = False

    # Redo charts for business hours
    if site_survey_input["Business Hours"]["use business hours"] and single_day:
        df_zoom = df.between_time(business_hours_start, business_hours_end)

        chart_output.chart_vmstat(
            df_zoom,
            site_survey_input,
            base_file_path=base_file_path,
            charts_path=charts_path,
            title_comment=f"Business Hours",
            extra_subtitle=f"{vmstat_title}",
            number_cpus=number_cpus,
        )

    if peak_zoom:
        # Resample the data at x-minute frequency
        resampled_data = df["Total CPU"].resample(peak_minutes_sample)

        # Calculate the mean for each x-minute period
        mean_values = resampled_data.mean()

        # Find the time period with the highest mean
        highest_mean_period = mean_values.idxmax()

        # Define start and end times for the period with the highest mean
        start_time = highest_mean_period
        end_time = start_time + pd.Timedelta(minutes=peak_minutes)

        cpu_start_time = start_time

        # Create a new DataFrame with the highest mean 10-minute period
        df_zoom = df.loc[start_time:end_time]

        # Chart functions
        chart_output.chart_vmstat(
            df_zoom,
            site_survey_input,
            base_file_path=base_file_path,
            charts_path=charts_path,
            title_comment=f"Peak CPU Total {peak_minutes}-min window",
            extra_subtitle=f"{vmstat_title}",
            number_cpus=number_cpus,
        )

    # ------------------------------------------------------------------------------------
    # mgstat

    # Get mgstat data
    df = pd.read_csv(mgstat_file_name, sep=",", encoding="ISO-8859-1")

    # Clean the data and create datetime index
    df = df.dropna(axis=1, how="all")

    # validate date format
    mgstat_date_format = f'{site_survey_input["System"]["mgstat date format"]}'

    df, date_string = what_date_format(df, mgstat_date_format, "datetime", "mgstat")

    chart_output.chart_mgstat(df, site_survey_input, base_file_path=base_file_path, charts_path=charts_path)

    if site_survey_input["Business Hours"]["use business hours"] and single_day:
        df_zoom = df.between_time(business_hours_start, business_hours_end)

        chart_output.chart_mgstat(
            df_zoom,
            site_survey_input,
            base_file_path=base_file_path,
            charts_path=charts_path,
            title_comment="Business Hours",
        )

    # Find peak Gloref window
    if peak_zoom:
        # Resample the data at x-minute frequency
        resampled_data = df["Glorefs"].resample(peak_minutes_sample)

        # Calculate the mean for each x-minute period
        mean_values = resampled_data.mean()

        # Find the time period with the highest mean
        highest_mean_period = mean_values.idxmax()

        # Define start and end times for the period with the highest mean
        start_time = highest_mean_period
        end_time = start_time + pd.Timedelta(minutes=peak_minutes)

        gloref_start_time = start_time

        # Create a new DataFrame with the highest mean x-minute period
        df_zoom = df.loc[start_time:end_time]

        # Chart functions
        chart_output.chart_mgstat(
            df_zoom,
            site_survey_input,
            base_file_path=base_file_path,
            charts_path=charts_path,
            title_comment=f"Peak Glorefs {peak_minutes}-min window",
        )

    # What about when CPU was at peak
    if peak_zoom:
        start_time = cpu_start_time
        end_time = start_time + pd.Timedelta(minutes=peak_minutes)

        # Create a new DataFrame with the highest mean 10-minute period
        df_zoom = df.loc[start_time:end_time]

        # Chart functions
        chart_output.chart_mgstat(
            df_zoom,
            site_survey_input,
            base_file_path=base_file_path,
            charts_path=charts_path,
            title_comment=f"While Peak CPU {peak_minutes}-min window",
        )

    # ------------------------------------------------------------------------------------
    # Get iostat data
    # importlib.reload(chart_templates)
    df = pd.read_csv(iostat_file_name, sep=",", encoding="ISO-8859-1")

    # Clean the data and create datetime index
    df = df.dropna(axis=1, how="all")

    # determine date format
    iostat_date_format = f'{site_survey_input["System"]["iostat date format"]}'

    df, date_string = what_date_format(df, iostat_date_format, "datetime", "iostat")

    # Remove duplicate rows (e.g. from append)
    df = df.drop_duplicates(subset=["RunDate", "RunTime", "Device"])

    disk_list = site_survey_input["Disk List"]
    device_human_names = list(disk_list.keys())
    device_names = list(disk_list.values())

    # Get details of one or more selected disks
    iostat_columns = site_survey_input["iostat columns"]

    df = df[df["Device"].isin(device_names)][["Device"] + iostat_columns]

    # Create pivot table
    df_pivot = df.pivot(columns="Device", values=iostat_columns)

    # Collapse the pivot table down to flat column headings
    df_pivot.columns = df_pivot.columns.map(" ".join)

    # rename from device mapper (dm-3) to english (database)
    for key, value in disk_list.items():
        df_pivot.rename(columns=lambda s: s.replace(value, key), inplace=True)

    # Combine reads and writes

    # Check if columns passed contains all elements of needed columns
    read_plus_write = True
    if all(elem in set(iostat_columns) for elem in set(["w/s", "r/s"])):
        for device, value in disk_list.items():
            df_pivot[f"reads plus writes {device}"] = df_pivot[f"w/s {device}"] + df_pivot[f"r/s {device}"]
    else:
        read_plus_write = False

    read_plus_write_kb = True
    if all(elem in set(iostat_columns) for elem in set(["wkB/s", "rkB/s"])):
        for device, value in disk_list.items():
            df_pivot[f"read plus write throughput {device}"] = df_pivot[f"rkB/s {device}"] + df_pivot[f"wkB/s {device}"]
    else:
        read_plus_write_kb = False

    if csv_needed:
        if read_plus_write:
            prop_list = iostat_columns + ["reads plus writes"]
        else:
            prop_list = iostat_columns

        for device, value in disk_list.items():
            for prop in prop_list:
                df_pivot[f"{prop} {device}"].describe(percentiles=[0.95, 0.98]).to_csv(
                    f"{output_file_path_txt}/describe {device} {prop.replace('/', '_')} Full day.csv"
                )

    # Review full day metrics
    chart_templates.iostat_metrics(
        df_pivot, site_survey_input, disk_list, "Full Day", base_file_path=base_file_path, charts_path=charts_path
    )

    # Chart functions
    chart_output.chart_iostat(df_pivot, site_survey_input, base_file_path=base_file_path, charts_path=charts_path)

    if peak_zoom:
        df_pivot_zoom = df_pivot.between_time(business_hours_start, business_hours_end)

    # Redo stats for business hours
    if peak_zoom:
        # Chart functions
        chart_output.chart_iostat(
            df_pivot_zoom,
            site_survey_input,
            base_file_path=base_file_path,
            charts_path=charts_path,
            title_comment="Business Hours",
        )

    # What about when Glorefs was at peak
    if peak_zoom:
        start_time = gloref_start_time
        end_time = start_time + pd.Timedelta(minutes=peak_minutes)

        # Create a new DataFrame with the highest mean 10-minute period
        df_pivot_zoom = df_pivot.loc[start_time:end_time]

        # Chart functions
        chart_output.chart_iostat(
            df_pivot_zoom,
            site_survey_input,
            base_file_path=base_file_path,
            charts_path=charts_path,
            title_comment=f"While peak Glorefs {peak_minutes}-min window",
        )

    # What about when reads at peak
    if peak_zoom:

        if "r/s Database" in df_pivot.columns:
            # Resample the data at x-minute frequency
            resampled_data = df_pivot["r/s Database"].resample(peak_minutes_sample)

            # Calculate the mean for each x-minute period
            mean_values = resampled_data.mean()

            # Find the time period with the highest mean
            highest_mean_period = mean_values.idxmax()

            # Define start and end times for the period with the highest mean
            start_time = highest_mean_period
            end_time = start_time + pd.Timedelta(minutes=peak_minutes)

            read_start_time = start_time

            # Create a new DataFrame with the highest mean x-minute period
            df_pivot_zoom = df_pivot.loc[start_time:end_time]

            # Chart functions
            chart_output.chart_iostat(
                df_pivot_zoom,
                site_survey_input,
                base_file_path=base_file_path,
                charts_path=charts_path,
                title_comment=f"Peak Database Reads {peak_minutes}-min window",
            )

    # What about when writes at peak, need to pick only no-zero values
    if peak_zoom:

        if "w/s Database" in df_pivot.columns:
            # Resample the data at x-minute frequency
            filtered_df = df_pivot[df_pivot["w/s Database"] != 0]
            resampled_data = filtered_df["w/s Database"].resample(peak_minutes_sample * 80)

            # Calculate the mean for each x-minute period
            mean_values = resampled_data.mean()

            # Find the time period with the highest mean
            highest_mean_period = mean_values.idxmax()

            # Define start and end times for the period with the highest mean
            start_time = highest_mean_period
            end_time = start_time + pd.Timedelta(minutes=peak_minutes)

            write_start_time = start_time

            # Create a new DataFrame with the highest mean x-minute period
            df_pivot_zoom = df_pivot.loc[start_time:end_time]

            # Chart functions
            chart_output.chart_iostat(
                df_pivot_zoom,
                site_survey_input,
                base_file_path=base_file_path,
                charts_path=charts_path,
                title_comment=f"Peak Database Writes {peak_minutes}-min window",
            )
