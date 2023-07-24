import os

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import ticker

import re


def chart_common(site_survey_input, base_file_path, charts_path, sub_folder):
    base_title = site_survey_input["Site Name"]
    # Style, 'seaborn-whitegrid', 'fivethirtyeight',
    # plt.style.available
    chart_style = site_survey_input["Chart"]["chart style"]
    # print (300) or screen (100)
    chart_dpi = site_survey_input["Chart"]["dpi"]
    figure_size = (site_survey_input["Chart"]["width"], site_survey_input["Chart"]["height"])
    output_format = site_survey_input["Chart"]["format"]
    line_style = site_survey_input["Chart"]["line style"]
    marker = site_survey_input["Chart"]["marker"]

    if not charts_path == "":
        output_file_path = f"{base_file_path}/{charts_path}"
    else:
        output_file_path = base_file_path

    # Create sub folder based on chart type
    if not sub_folder == "":
        output_file_path += f"/{sub_folder}"

        # add csv and text folders
        if not os.path.exists(output_file_path):
            os.makedirs(output_file_path)

    output_file = f"{output_file_path}/{base_title}"

    return (
        base_title,
        chart_style,
        chart_dpi,
        figure_size,
        output_format,
        line_style,
        marker,
        output_file_path,
        output_file,
    )


def chart_multi_line(df, extra_title, field_names, site_survey_input, **kwargs):

    base_file_path = kwargs.get("base_file_path", ".")
    charts_path = kwargs.get("charts_path", "")

    percentile_field = kwargs.get("percentile_field", "")
    extra_subtitle = kwargs.get("extra_subtitle", "")
    left_y_axis_max = kwargs.get("left_y_axis_max", 0)
    left_y_axis_label = kwargs.get("left_y_axis_label", "")
    sub_folder = kwargs.get("sub_folder", "")
    extra_horizontal = kwargs.get("extra_horizontal", (0, ""))
    line_style_in = kwargs.get("line_style", "")

    if percentile_field == "False":
        percentile_field = ""

    if not percentile_field == "":
        # Filter wij or db writes cycle only (ie non-zero)
        if percentile_field in ["w/s", "PhyWrs", "WIJwri"]:
            filtered_df = df[df[percentile_field] != 0]
            percentile_98 = filtered_df[percentile_field].quantile(0.98)
            percentile_98_plus20 = filtered_df[percentile_field].quantile(0.98) * 1.2
        else:
            percentile_98 = df[percentile_field].quantile(0.98)
            percentile_98_plus20 = df[percentile_field].quantile(0.98) * 1.2

    (
        base_title,
        chart_style,
        chart_dpi,
        figure_size,
        output_format,
        line_style_default,
        marker,
        output_file_path,
        output_file,
    ) = chart_common(site_survey_input, base_file_path, charts_path, sub_folder)

    if not line_style_in == "":
        line_style_default = line_style_in

    # Create a summary chart with single y-axis
    output_name = f"{extra_title}"
    safe_output_name = output_name.replace("/", "_")
    chart_title = f"{base_title} - {extra_title}"

    # create figure and axis objects with subplots()
    plt.style.use(chart_style)
    fig, ax1 = plt.subplots(figsize=(figure_size))
    if not extra_subtitle == "":
        fig.suptitle(extra_subtitle)

    # make a plot
    plt.title(chart_title)

    max_max_y = left_y_axis_max
    for field_name in field_names:

        max_y = df[field_name].max()
        if max_y > max_max_y:
            max_max_y = max_y

        line_style = line_style_default
        for writes in ["w/s", "PhyWrs", "WIJwri"]:
            if writes in field_name:
                line_style = "solid"

        # Plot it
        ax1.plot(
            df.index,
            df[field_name],
            linestyle=line_style,
            marker=marker,
            alpha=0.7,
            label=f"{field_name} max {df[field_name].max():,.0f}",
        )

    if not percentile_field == "":

        percentile_color = "m"
        # if percentile_98_plus20 < max_y:
        #     percentile_color = "m"

        if max_max_y > 15:

            ax1.axhline(y=percentile_98, color="b", linestyle="--", label=f"98th percentile: {percentile_98:,.0f}")
            ax1.axhline(
                y=percentile_98_plus20,
                color=percentile_color,
                linestyle="--",
                label=f"98th plus 20%: {percentile_98_plus20:,.0f}",
            )
        else:
            ax1.axhline(y=percentile_98, color="b", linestyle="--", label=f"98th percentile: {percentile_98:,.2f}")
            ax1.axhline(
                y=percentile_98_plus20,
                color=percentile_color,
                linestyle="--",
                label=f"98th plus 20%: {percentile_98_plus20:,.2f}",
            )

        if percentile_98_plus20 > max_max_y:
            left_y_axis_max = percentile_98_plus20

    extra_color = "m"
    if extra_horizontal[0] > 0:

        if extra_horizontal[0] < max_y:
            extra_color = "r"

        ax1.axhline(y=extra_horizontal[0], color=extra_color, linestyle="--", label=f"{extra_horizontal[1]}")

    # Select the appropriate x-axis major formatter based on the time range
    locator = mdates.AutoDateLocator()
    formatter = mdates.ConciseDateFormatter(locator)
    ax1.xaxis.set_major_locator(locator)
    ax1.xaxis.set_major_formatter(formatter)

    # Rotate the x-axis labels for readability
    plt.xticks(rotation=45)

    # set y-axis label
    # Label override
    if left_y_axis_label == "":
        ax1.set_ylabel(extra_title.split("(")[0])
    else:
        ax1.set_ylabel(left_y_axis_label)

    if max_max_y > 15:
        ax1.yaxis.set_major_formatter(ticker.StrMethodFormatter("{x:,.0f}"))
    else:
        ax1.yaxis.set_major_formatter(ticker.StrMethodFormatter("{x:,.2f}"))

    ax1.set_ylim(bottom=0)

    if left_y_axis_max > 0:
        ax1.set_ylim(top=left_y_axis_max)

    ax1.legend()

    if not extra_subtitle == "":
        plt.suptitle(extra_subtitle, fontsize=10, y=0.95)

    # save the plot as a file
    fig.savefig(
        f"{output_file} {safe_output_name}.{output_format}", format=output_format, dpi=chart_dpi, bbox_inches="tight"
    )

    plt.close(fig)


def iostat_metrics(df, site_survey_input, disk_list, title, **kwargs):

    base_file_path = kwargs.get("base_file_path", ".")
    charts_path = kwargs.get("charts_path", "")

    base_title = site_survey_input["Site Name"]

    output_file_path_txt = f"{base_file_path}/{charts_path}/txt"
    episodes_per_year = site_survey_input["Episodes"]["episodes per year"]
    average_episodes_per_day = site_survey_input["Episodes"]["average episodes per day"]

    if episodes_per_year == 0 or average_episodes_per_day == 0:
        print("Application metrics missing from input, please update yml file.")
    else:

        for device, value in disk_list.items():
            max_reads = df[f"r/s {device}"].describe().loc["max"]
            reads_98th = df[f"r/s {device}"].quantile(0.98)

            # database writes are every 80 seconds, just count peaks
            max_writes = df[f"w/s {device}"].describe().loc["max"]

            max_iops = df[f"reads plus writes {device}"].describe().loc["max"]
            max_throughput = df[f"read plus write throughput {device}"].describe().loc["max"]

            full_path = f"{output_file_path_txt}/{title} {device} System metrics.txt"

            output_log = f"{full_path}\n\n"
            output_log += f"Episodes per year: {episodes_per_year:,}\n"
            output_log += f"Average episodes per day: {average_episodes_per_day:,}\n"
            output_log += "\n\n"
            output_log += f"{title} Metrics {device}\n"
            output_log += "==============================\n"
            output_log += f"Peak reads: {max_reads:,.0f}\n"
            output_log += f"98th percentile reads: {reads_98th:,.0f}\n"
            if max_reads > 0:
                output_log += f"Episodes per year per max read: {episodes_per_year / max_reads:,.0f}\n"
                output_log += f"Episodes per day per max read: {average_episodes_per_day / max_reads:,.2f}\n"
            output_log += "\n"
            output_log += f"Peak writes: {max_writes:,.0f}\n"
            output_log += "\n"
            output_log += f"Peak iops (reads + writes): {max_iops:,.0f}\n"
            output_log += f"Peak throughput (reads + writes): {max_throughput:,.0f} kB/s\n"
            output_log += "\n"
            if max_iops > 0:
                output_log += f"Episodes per year per IOP: {episodes_per_year / max_iops:,.0f}\n"
                output_log += f"Episodes per day per IOP: {average_episodes_per_day / max_iops:,.4f}\n"
                output_log += "\n"
                output_log += f"IOPS per episode per year: {max_iops / episodes_per_year:,.4f}\n"
                output_log += f"IOPS per episode per day: {max_iops / average_episodes_per_day:,.0f}\n"

            text_file = open(rf"{full_path}", "w")
            text_file.write(output_log)
            text_file.close()


def detect_date_format(date_str):
    mm_dd_yyyy = r"(0[1-9]|1[012])[- /.](0[1-9]|[12][0-9]|3[01])[- /.](19|20)\d\d"
    dd_mm_yyyy = r"(0[1-9]|[12][0-9]|3[01])[- /.](0[1-9]|1[012])[- /.](19|20)\d\d"

    if re.match(mm_dd_yyyy, date_str):
        return "mm/dd/yyyy"
    elif re.match(dd_mm_yyyy, date_str):
        return "dd/mm/yyyy"
    else:
        return "Unknown format"


# this one better for mixed bag of dates
def infer_date_format(date_series):
    mm_dd_count = 0
    dd_mm_count = 0

    for date_str in date_series:
        try:
            day, month, year = map(int, date_str.split("/"))

            if 1 <= month <= 12 and 1 <= day <= 31:
                mm_dd_count += 1
            if 1 <= day <= 12 and 1 <= month <= 31:
                dd_mm_count += 1
        except ValueError:
            continue

    if mm_dd_count > dd_mm_count:
        return "mm/dd/yyyy"
    elif dd_mm_count > mm_dd_count:
        return "dd/mm/yyyy"
    else:
        return "ambiguous"
