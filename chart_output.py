import chart_templates, yaspe_utilities


def safe_file_name(filename):
    keep_characters = ("-", ".", "_")
    return "".join(c for c in filename if c.isalnum() or c in keep_characters).rstrip()


def get_date_string(df):
    return f'{df.index[0].strftime("%a, %b %d, %Y %H:%M:%S")} - {df.index[-1].strftime("%a, %b %d, %Y %H:%M:%S")}'


def chart_iostat(df, site_survey_input, **kwargs):
    if yaspe_utilities.check_keyword_exists(site_survey_input, "chart sub folder"):
        charts_path = site_survey_input["Chart"]["chart sub folder"]
    else:
        charts_path = "System review"

    base_file_path = kwargs.get("base_file_path", ".")
    title_comment = kwargs.get("title_comment", "")
    if not title_comment == "":
        title_comment = f" - {title_comment}"

    date_string = get_date_string(df)

    disk_list = site_survey_input["Disk List"]
    device_human_names = list(disk_list.keys())

    iostat_columns = site_survey_input["iostat columns"]

    for device in device_human_names:
        # Loop through all
        for counter in iostat_columns:
            if "peak" in title_comment.lower():
                percentile_field = f"{counter} {device}"

            else:
                percentile_field = "False"

            if "await" in counter:
                percentile_field = f"{counter} {device}"

            extra_horizontal = (0, "")
            if "await" in counter:
                extra_horizontal = (1, "Optimal storage latency below 1 ms")

            chart_templates.chart_multi_line(
                df,
                f"iostat {device} {counter}{title_comment}",
                [f"{counter} {device}"],
                site_survey_input,
                base_file_path=base_file_path,
                charts_path=charts_path,
                percentile_field=percentile_field,
                extra_subtitle=date_string,
                sub_folder=f"iostat/{device}",
                extra_horizontal=extra_horizontal,
                left_y_axis_label=counter,
            )

        # Special cases
        if "w/s" in iostat_columns and "r/s" in iostat_columns:
            chart_templates.chart_multi_line(
                df,
                f"iostat {device} r/s and w/s IOPS{title_comment}",
                [f"w/s {device}", f"r/s {device}"],
                site_survey_input,
                base_file_path=base_file_path,
                charts_path=charts_path,
                extra_subtitle=date_string,
                sub_folder=f"iostat/{device}",
                left_y_axis_label="IOPS",
            )

            chart_templates.chart_multi_line(
                df,
                f"iostat {device} Total IOPS{title_comment}",
                [f"reads plus writes {device}"],
                site_survey_input,
                base_file_path=base_file_path,
                charts_path=charts_path,
                extra_subtitle=date_string,
                sub_folder=f"iostat/{device}",
                left_y_axis_label="IOPS",
            )

        if "wkB/s" in iostat_columns and "rkB/s" in iostat_columns:
            chart_templates.chart_multi_line(
                df,
                f"iostat {device} Total throughput (kB per sec){title_comment}",
                [f"read plus write throughput {device}"],
                site_survey_input,
                base_file_path=base_file_path,
                charts_path=charts_path,
                extra_subtitle=date_string,
                sub_folder=f"iostat/{device}",
                left_y_axis_label="Throughput kB/s",
            )


def chart_vmstat(df, site_survey_input, **kwargs):
    if yaspe_utilities.check_keyword_exists(site_survey_input, "chart sub folder"):
        charts_path = site_survey_input["Chart"]["chart sub folder"]
    else:
        charts_path = "System review"

    base_file_path = kwargs.get("base_file_path", ".")
    number_cpus = kwargs.get("number_cpus", 0)

    title_comment = kwargs.get("title_comment", "")
    if not title_comment == "":
        title_comment = f" - {title_comment}"

    extra_subtitle = kwargs.get("extra_subtitle", "")
    if not extra_subtitle == "":
        extra_subtitle += f" "

    extra_subtitle += get_date_string(df)

    vmstat_columns = site_survey_input["vmstat columns"]
    vmstat_columns.append("Total CPU")

    for counter in vmstat_columns:
        left_y_axis_max = 0
        if "Total CPU" in counter:
            left_y_axis_max = 100

        extra_horizontal = (0, "")
        if counter == "r" and number_cpus > 0:
            extra_horizontal = (number_cpus, f"Optimal Run Queue less than vCPUs ({number_cpus})")

        if counter == "Total CPU":
            extra_horizontal = (80, f"Optimal peak CPU utilisation 80%")

        if "peak" in title_comment.lower():
            percentile_field = counter
        else:
            percentile_field = "False"

        chart_templates.chart_multi_line(
            df,
            f"vmstat {counter}{title_comment}",
            [counter],
            site_survey_input,
            base_file_path=base_file_path,
            charts_path=charts_path,
            percentile_field=percentile_field,
            extra_subtitle=extra_subtitle,
            left_y_axis_max=left_y_axis_max,
            sub_folder="vmstat",
            extra_horizontal=extra_horizontal,
            left_y_axis_label=counter,
        )


def chart_mgstat(df, site_survey_input, **kwargs):
    if yaspe_utilities.check_keyword_exists(site_survey_input, "chart sub folder"):
        charts_path = site_survey_input["Chart"]["chart sub folder"]
    else:
        charts_path = "System review"

    base_file_path = kwargs.get("base_file_path", ".")
    title_comment = kwargs.get("title_comment", "")
    if not title_comment == "":
        title_comment = f" - {title_comment}"

    date_string = get_date_string(df)

    mgstat_columns = site_survey_input["mgstat columns"]

    for counter in mgstat_columns:
        if "peak" in title_comment.lower():
            percentile_field = counter
        else:
            percentile_field = "False"

        chart_templates.chart_multi_line(
            df,
            f"mgstat {counter}{title_comment}",
            [counter],
            site_survey_input,
            base_file_path=base_file_path,
            charts_path=charts_path,
            percentile_field=percentile_field,
            extra_subtitle=date_string,
            sub_folder="mgstat",
            left_y_axis_label=counter,
        )
