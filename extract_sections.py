import dateutil.parser
import pandas as pd
from yaspe_utilities import get_number_type, make_mdy_date, check_date


def extract_sections(operating_system, profile_run, input_file, include_iostat, include_nfsiostat, html_filename):

    once = True

    vmstat_processing = False
    vmstat_header = ""
    vmstat_rows_list = []
    vmstat_date = ""
    vmstat_date_convert = False

    iostat_processing = False
    iostat_header = ""
    iostat_rows_list = []
    iostat_device_block_processing = False
    iostat_am_pm = False
    iostat_date_included = False
    iostat_date = ""
    iostat_date_convert = False

    mgstat_processing = False
    mgstat_header = ""
    mgstat_rows_list = []
    mgstat_date = ""
    mgstat_date_convert = False

    perfmon_processing = False
    perfmon_header = ""
    perfmon_rows_list = []

    nfsiostat_processing = False
    nfsiostat_header = ""
    nfsiostat_rows_list = []
    nfsiostat_read = False
    nfsiostat_write = False

    run_start = profile_run.split("on ")[1]
    run_start = run_start[:-1]
    run_start_date = dateutil.parser.parse(run_start)

    with open(input_file, "r", encoding="ISO-8859-1") as file:

        for line in file:
            if "<!-- beg_mgstat -->" in line:
                mgstat_processing = True
            if "<!-- end_mgstat -->" in line:
                mgstat_processing = False
            if mgstat_processing and mgstat_header != "":
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

                    # Check date format
                    if not mgstat_date_convert and mgstat_row_dict['Date'] != mgstat_date:
                        mgstat_date = mgstat_row_dict['Date']
                        mgstat_date_convert = check_date("mgstat", run_start_date, mgstat_row_dict['Date'])

                    if mgstat_date_convert:
                        new_date = make_mdy_date(mgstat_row_dict["Date"])
                        new_date_dict = {"Date": new_date}
                        mgstat_row_dict.update(new_date_dict)

                    # Added for pretty processing
                    mgstat_row_dict["datetime"] = f'{mgstat_row_dict["Date"]} {mgstat_row_dict["Time"]}'
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
                    if line.strip() != "":
                        vmstat_row_dict = {}
                        values = line.split()
                        values = [i.strip() for i in values]  # strip off carriage return etc
                        values_converted = [get_number_type(v) for v in values]
                        vmstat_row_dict = dict(zip(vmstat_columns, values_converted))
                        vmstat_row_dict["html name"] = html_filename

                        # Check date format
                        if not vmstat_date_convert and vmstat_row_dict['Date'] != vmstat_date:
                            vmstat_date = vmstat_row_dict['Date']
                            vmstat_date_convert = check_date("vmstat", run_start_date, vmstat_row_dict['Date'])

                        if vmstat_date_convert:
                            new_date = make_mdy_date(vmstat_row_dict["Date"])
                            new_date_dict = {"Date": new_date}
                            vmstat_row_dict.update(new_date_dict)

                        # Added for pretty processing
                        vmstat_row_dict["datetime"] = f'{vmstat_row_dict["Date"]} {vmstat_row_dict["Time"]}'
                        vmstat_rows_list.append(vmstat_row_dict)
                if vmstat_processing and "us sy id wa" in line:
                    # vmstat !sometimes! has column names on same line as html
                    if "<pre>" in line:
                        vmstat_header = line.split("<pre>")[1].strip()
                    else:
                        vmstat_header = line
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
                    if line.strip() != "":
                        perfmon_row_dict = {}
                        values = line.split(",")
                        values = [i.strip() for i in values]  # strip off carriage return etc
                        values = list(map(lambda x: x[1:-1].replace('"', ""), values))
                        values = list(map(lambda x: 0.0 if x == " " else x, values))
                        values_converted = [get_number_type(v) for v in values]
                        perfmon_row_dict = dict(zip(perfmon_columns, values_converted))
                        perfmon_row_dict["html name"] = html_filename

                        # The first column is a date time with timezone
                        # todo: move datetime column creation to here, include dd/mm/yy check

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
                        if line.strip() != "":
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

                            # Check date format
                            if not iostat_date_convert and iostat_row_dict['Date'] != iostat_date:
                                iostat_date = iostat_row_dict['Date']
                                iostat_date_convert = check_date("iostat", run_start_date, iostat_row_dict['Date'])

                            if iostat_date_convert:
                                new_date = make_mdy_date(iostat_row_dict["Date"])
                                new_date_dict = {"Date": new_date}
                                iostat_row_dict.update(new_date_dict)

                            # Added for pretty processing
                            iostat_row_dict["datetime"] = f'{iostat_row_dict["Date"]} {iostat_row_dict["Time"]}'
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

            # nfsiostat
            if (operating_system == "Linux" or operating_system == "Ubuntu") and include_nfsiostat:

                if nfsiostat_processing and "pre>" in line:  # nfsiostat does not flag end
                    nfsiostat_processing = False
                else:
                    # Found nfsiostat
                    if "id=nfsiostat" in line:
                        nfsiostat_processing = True
                    # There is no date and time
                    if "mounted on" in line:
                        nfsiostat_host = line.split(":")[0]
                        nfsiostat_device = line.split()[0].split(":")[1].replace("/", "_")
                        nfsiostat_mount_point = line.split()[3].replace(":", "").replace("/", "_")
                        nfs_output_line = f"{nfsiostat_host},{nfsiostat_device},{nfsiostat_mount_point}"
                    if nfsiostat_read:
                        # Get rid of extra spaces
                        line = " ".join(line.split())
                        # make percentage (0.0%) a number
                        line = line.replace("(", "")
                        line = line.replace(")", "")
                        line = line.replace("%", "")
                        line = line.replace(" ", ",")
                        nfs_output_line += f",{line}"
                        nfsiostat_read = False
                    if nfsiostat_write:
                        # Get rid of extra spaces
                        line = " ".join(line.split())
                        # make percentage (0.0%) a number
                        line = line.replace("(", "")
                        line = line.replace(")", "")
                        line = line.replace("%", "")
                        line = line.replace(" ", ",")
                        nfs_output_line += f",{line}"
                        nfsiostat_write = False
                    if "read:" in line:
                        nfsiostat_read = True
                        nfsiostat_write = False
                        # First time in create column names
                        if nfsiostat_header == "":
                            # Hardcoded while debugging
                            nfsiostat_header = "Host,Device,Mounted on"
                            nfsiostat_header += f",read ops/s,read kB/s,read kB/op,read retrans,read retrans %," \
                                                f"read avg RTT (ms),read avg exe (ms),read avg queue (ms)," \
                                                f"read errors,read errors % "
                            nfsiostat_header += f",write ops/s,write kB/s,write kB/op,write retrans,write retrans %," \
                                                f"write avg RTT (ms),write avg exe (ms),write avg queue (ms)," \
                                                f"write errors,write errors %"
                            nfsiostat_header += f",html name"
                            nfsiostat_columns = nfsiostat_header.split(",")
                            mgstat_columns = [i.strip() for i in nfsiostat_columns]  # strip off carriage return etc
                    if "write:" in line:
                        nfsiostat_read = False
                        nfsiostat_write = True
                    if nfsiostat_processing and nfsiostat_header != "":
                        if nfs_output_line.strip() != "":
                            nfsiostat_row_dict = {}
                            values = nfs_output_line.split(",")
                            values = [i.strip() for i in values]  # strip off carriage return etc
                            values_converted = [get_number_type(v) for v in values]
                            nfsiostat_row_dict = dict(zip(nfsiostat_columns, values_converted))
                            nfsiostat_row_dict["html name"] = html_filename
                            nfsiostat_rows_list.append(nfsiostat_row_dict)

    if mgstat_header != "":
        # Create dataframe of rows. Shortcut here to creating table columns or later charts etc
        mgstat_df = pd.DataFrame(mgstat_rows_list)

        # "date" and "time" are reserved words in SQL. Rename the columns to avoid clashes later.
        mgstat_df.rename(columns={"Date": "RunDate", "Time": "RunTime"}, inplace=True)

        # Remove any rows with NaN
        mgstat_df.dropna(inplace=True)

    else:
        mgstat_df = pd.DataFrame({'empty': []})

    if vmstat_header != "":
        vmstat_df = pd.DataFrame(vmstat_rows_list)
        # "date" and "time" are reserved words in SQL. Rename the columns to avoid clashes later.
        vmstat_df.rename(columns={"Date": "RunDate", "Time": "RunTime"}, inplace=True)
        vmstat_df.dropna(inplace=True)
    else:
        vmstat_df = pd.DataFrame({'empty': []})

    if perfmon_header != "":

        perfmon_df = pd.DataFrame(perfmon_rows_list)
        perfmon_df.dropna(inplace=True)

        # add datetime column
        # The first column is a date time with timezone
        perfmon_df.columns = perfmon_df.columns[:0].tolist() + ["datetime"] + perfmon_df.columns[1:].tolist()

        # In some cases time is a separate column
        if perfmon_df.columns[1] == "Time":
            perfmon_df["datetime"] = perfmon_df["datetime"] + " " + perfmon_df["Time"]

        # preprocess time to remove decimal precision
        perfmon_df["datetime"] = perfmon_df["datetime"].apply(lambda x: x.split(".")[0])

    else:
        perfmon_df = pd.DataFrame({'empty': []})

    if iostat_header != "":
        iostat_df = pd.DataFrame(iostat_rows_list)
        # "date" and "time" are reserved words in SQL. Rename the columns to avoid clashes later.
        iostat_df.rename(columns={"Date": "RunDate", "Time": "RunTime"}, inplace=True)
        iostat_df.dropna(inplace=True)
    else:
        iostat_df = pd.DataFrame({'empty': []})

    if nfsiostat_header != "":
        nfsiostat_df = pd.DataFrame(nfsiostat_rows_list)
        nfsiostat_df.dropna(inplace=True)
    else:
        nfsiostat_df = pd.DataFrame({'empty': []})

    return mgstat_df, vmstat_df, iostat_df, nfsiostat_df, perfmon_df
