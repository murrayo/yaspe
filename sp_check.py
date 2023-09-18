"""
Check IRIS SystemPerformance or Caché pButtons

Extract useful details to create a performance report.
Validate common OS and IRIS/Caché configuration settings and show pass, fail
and suggested fixes.

"""


def shared_memory_estimate(
    global_buffers_mb,
    routine_buffers_mb,
    gmheap_in_mb,
    number_of_logical_cpus,
    jrnbufs_in_mb,
    MaxServerConn,
    MaxServers,
):
    # Shared memory size in MB =
    # [global buffers in MB] * 1.08 + [routine buffers in MB] * 1.02
    # + [gmheap in KB]/1024 + 2 * [number of logical CPUs] + [jrnbufs in MB] +
    # 2 * ( [MaxServerConn] + [MaxServers]) + 300 [overall fixed padding]

    overall_fixed_padding = 300

    total_shared_memory = (
        (global_buffers_mb * 1.08)
        + (routine_buffers_mb * 1.02)
        + gmheap_in_mb
        + (2 * number_of_logical_cpus)
        + jrnbufs_in_mb
        + (2 * (MaxServerConn + MaxServers))
        + overall_fixed_padding
    )

    return int(total_shared_memory)


def system_check(input_file):
    sp_dict = {}
    operating_system = ""
    cpf_section = False

    linux_info_available = False
    dev_mapper_section = True
    dev_mapper_counter = 0

    filesystem_info_available = False
    filesystem_section = True
    filesystem_counter = 0

    shared_memory_available = False
    shared_memory_section = True
    shared_memory_counter = 0
    shared_memory_total = 0

    with open(input_file, "r", encoding="ISO-8859-1") as file:
        model_name = True
        windows_info_available = False

        memory_next = False
        perfmon_next = False

        up_counter = 0

        for line in file:
            if "[ConfigFile]" in line:
                cpf_section = True
            elif "!-- beg_mgstat --" in line:
                cpf_section = False

            # Summary

            if "VMware" in line:
                sp_dict["platform"] = "VMware"

            if "Customer: " in line:
                customer = (line.split(":")[1]).strip()
                sp_dict["customer"] = customer

            if "overview=" in line:
                sp_dict["overview"] = (line.split("=")[1]).strip()

            # Product Version String:
            if "Version String: " in line or "Product Version String: " in line:
                sp_dict["version string"] = (line.split(":", 1)[1]).strip()

                if "Windows" in line:
                    sp_dict["operating system"] = "Windows"
                    operating_system = "Windows"
                elif "Linux" in line:
                    sp_dict["operating system"] = "Linux"
                    operating_system = "Linux"
                elif "AIX" in line:
                    sp_dict["operating system"] = "AIX"
                    operating_system = "AIX"
                elif "Ubuntu" in line:
                    sp_dict["operating system"] = "Ubuntu"
                    operating_system = "Ubuntu"
                # Placeholder for when I care.
                elif "Oracle Solaris" in line:
                    sp_dict["operating system"] = "Unknown"
                    operating_system = "Unknown"
                else:
                    sp_dict["operating system"] = "Unknown"
                    operating_system = "Unknown"

            if "Profile run " in line:
                sp_dict["profile run"] = line.strip()

            if "Run over " in line:
                sp_dict["run over"] = line.strip()

            if "on machine" in line:
                sp_dict[f"instance"] = (line.split(" on machine ", 1)[0]).strip()
                sp_dict[f"linux hostname"] = (line.split(" on machine ", 1)[1]).strip()

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

            if cpf_section:
                if "AlternateDirectory=" in line:
                    sp_dict["alternate journal"] = (line.split("=")[1]).strip()
                if "CurrentDirectory=" in line and not line[0] == ";":
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
                if "FreezeOnError" in line:
                    sp_dict["freeze"] = (line.split("=")[1]).strip()
                if "Asyncwij=" in line:
                    sp_dict["asyncwij"] = (line.split("=")[1]).strip()
                if "wduseasyncio=" in line:
                    sp_dict["wduseasyncio"] = (line.split("=")[1]).strip()
                if "jrnbufs=" in line:
                    sp_dict["jrnbufs"] = (line.split("=")[1]).strip()

            # Chad's metrics
            if "CACHESYS=" in line:
                sp_dict["CACHESYS"] = (line.split("=")[1]).strip()
            if "IRISSYS=" in line:
                sp_dict["IRISSYS"] = (line.split("=")[1]).strip()
            if "memlock=" in line:
                sp_dict["memlock"] = (line.split("=")[1]).strip()
            if "WebServer=" in line:
                sp_dict["WebServer"] = (line.split("=")[1]).strip()
            if "MaxServers=" in line:
                sp_dict["MaxServers"] = (line.split("=")[1]).strip()
            if "MaxServerConn=" in line:
                sp_dict["MaxServerConn"] = (line.split("=")[1]).strip()
            if "DaysBeforePurge=" in line:
                sp_dict["DaysBeforePurge"] = (line.split("=")[1]).strip()

            # Linux filesystem info

            if "<div id=Linuxinfo>" in line:
                linux_info_available = True

            if linux_info_available:
                if "/dev/mapper:" in line:
                    dev_mapper_section = True

                if dev_mapper_section:
                    if "->" in line:
                        sp_dict[f"dev mapper {dev_mapper_counter}"] = line.strip()
                        dev_mapper_counter += 1

                    if dev_mapper_counter > 0 and "rw" not in line:
                        dev_mapper_section = False

            if "<div id=df-m>" in line:
                filesystem_info_available = True

            if filesystem_info_available:
                if "Filesystem " in line:
                    filesystem_section = True

                if filesystem_section and "</pre>" in line:
                    filesystem_section = False

                if filesystem_section:
                    sp_dict[f"filesystem df {filesystem_counter}"] = line.strip()
                    filesystem_counter += 1

            if "Shared Memory Segments" in line:
                shared_memory_available = True

            if shared_memory_available:
                if "key" in line:
                    shared_memory_section = True

                if shared_memory_section and line.strip() == "":
                    shared_memory_section = False
                    shared_memory_available = False
                    sp_dict[
                        f"Shared memory ipcs {shared_memory_counter}"
                    ] = f"Total shared memory used: {int(shared_memory_total/1024/1024):,} MB"
                    sp_dict["Shared memory segment total"] = shared_memory_total

                if shared_memory_section:
                    if "key" not in line and "----" not in line:
                        shared_memory_columns = line.split()
                        shared_memory_bytes = int(shared_memory_columns[4])
                        shared_memory_total += shared_memory_bytes

                    sp_dict[f"Shared memory ipcs {shared_memory_counter}"] = line.strip()
                    shared_memory_counter += 1

            # Linux kernel

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

            if "max locked memory" in line:
                sp_dict["max locked memory"] = (line.split(")")[1]).strip()

            # dirty_* parameters are not relevant if using async IO – which any IRIS-based install should be.
            # # dirty background ratio = 5
            # if "vm.dirty_background_ratio" in line:
            #     sp_dict["vm.dirty_background_ratio"] = (line.split("=")[1]).strip()
            #
            # # dirty ratio = 10
            # if "vm.dirty_ratio" in line:
            #     sp_dict["vm.dirty_ratio"] = (line.split("=")[1]).strip()

            # Linux free

            if memory_next:
                if "Memtotal" in line:
                    pass
                else:
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
                if "hypervisor" in line:
                    sp_dict["windows hypervisor"] = line.strip()

            # Windows perform

            if perfmon_next:
                sp_dict["perfmon_header"] = line.strip()
                perfmon_next = False
            if "beg_win_perfmon" in line:
                perfmon_next = True

            # AIX
            if operating_system == "AIX":
                if "Processor Type:" in line:
                    sp_dict["processor model"] = (line.split(":")[1]).strip()
                if "smt_enabled true" in line:
                    sp_dict["AIX SMT enabled"] = True
                if "smt_threads" in line:
                    sp_dict["AIX SMT"] = f'{(line.split(" ")[1]).strip()}'
                if "Number Of Processors:" in line:
                    sp_dict["Number Of Processors"] = f'{(line.split(":")[1]).strip()}'
                if "Memory Size:" in line:
                    sp_dict["memory MB"] = (line.split(":")[1]).split()[0].strip()
                # Number Of Processors: 10
                # Memory Size: 24576 MB
                # smt_threads 8

    # # Debug
    # for key in sp_dict:
    #     print(f"{key} : {sp_dict[key]}")

    # Tidy up not found keys

    if "asyncwij" not in sp_dict:
        sp_dict["asyncwij"] = 0
    if "wduseasyncio" not in sp_dict:
        sp_dict["wduseasyncio"] = 0

    if "processor model" not in sp_dict:
        if "windows processor" not in sp_dict:
            sp_dict["processor model"] = "Unknown Processor"
        else:
            sp_dict["processor model"] = sp_dict["windows processor"]

    if "memory MB" not in sp_dict:
        if "windows total memory" in sp_dict:
            # Extract numbers only. Eg there may be point, commas, letters, and others from around the world.
            sp_dict["memory MB"] = int("".join(i for i in sp_dict["windows total memory"] if i.isdigit()))
        else:
            sp_dict["memory MB"] = 0

    return sp_dict


def build_log(sp_dict):
    # Build log for cut and paste

    ct_dict = {}
    pass_count = warn_count = recommend_count = 0
    ct_dict["swappiness"] = 5

    # split up mgstat header

    mgstat_header = sp_dict["mgstat header"].split(",")
    for item in mgstat_header:
        if "numberofcpus" in item:
            sp_dict["number cpus"] = item.split("=")[1].split(":")[0]

    # CPF

    if "WebServer" in sp_dict:
        if sp_dict["WebServer"] == "1":
            warn_count += 1
            sp_dict[f"warning {warn_count}"] = f"** Insecure Private Webserver Enabled! **"

    if "freeze" in sp_dict:
        if sp_dict["freeze"] == "0":
            warn_count += 1
            sp_dict[f"warning {warn_count}"] = (
                f"Journal freeze on error is not enabled. If journal IO errors occur "
                f"database activity that occurs during this period cannot be restored. "
            )
        else:
            pass_count += 1
            sp_dict[f"pass {pass_count}"] = f"freeze on error is enabled."

    if sp_dict["current journal"] == sp_dict["alternate journal"]:
        warn_count += 1
        sp_dict[f"warning {warn_count}"] = f"Primary Journal is the same as Alternate Journal"

    if "globals" in sp_dict:
        globals = sp_dict["globals"].split(",")
        globals_total = 0
        for item in globals:
            globals_total += int(item)
        sp_dict["globals total MB"] = globals_total

    if "routines" in sp_dict:
        routines = sp_dict["routines"].split(",")
        routines_total = 0
        for item in routines:
            routines_total += int(item)
        sp_dict["routines total MB"] = routines_total

    # Chad's metrics

    if "gmheap" in sp_dict:
        if int(sp_dict["gmheap"]) == 37568:
            warn_count += 1
            sp_dict[f"warning {warn_count}"] = f"gmheap is default"

        if int(sp_dict["gmheap"]) / 1024 < 200:
            warn_count += 1
            sp_dict[f"warning {warn_count}"] = f"gmheap {sp_dict['gmheap']} size does not support parallel dejournaling"

    if "locksiz" in sp_dict:
        if int(sp_dict["locksiz"]) == 16777216:
            warn_count += 1
            sp_dict[f"warning {warn_count}"] = f"locksiz is default"
        if int(sp_dict["locksiz"]) < 16777216:
            warn_count += 1
            sp_dict[f"warning {warn_count}"] = f"locksiz {sp_dict['locksiz']} is less than IRIS default (16777216)"

    if "wijdir" in sp_dict:
        if sp_dict["wijdir"] == "":
            warn_count += 1
            sp_dict[f"warning {warn_count}"] = f"WIJ in Installation Directory"

    # Linux kernel

    if "swappiness" in sp_dict:
        if int(sp_dict["swappiness"]) > ct_dict["swappiness"]:
            warn_count += 1
            sp_dict[f"warning {warn_count}"] = (
                f"swappiness is {sp_dict['swappiness']}. "
                f"For databases {ct_dict['swappiness']} "
                f"is recommended to adjust how aggressive the Linux kernel swaps memory "
                f"pages to disk. "
            )
        else:
            pass_count += 1
            sp_dict[f"pass {pass_count}"] = f"swappiness is {sp_dict['swappiness']}"

    # memory comes from Linux free or from Windows info

    if "memlock" in sp_dict:
        if int(sp_dict["memlock"]) == 0:
            warn_count += 1
            sp_dict[f"warning {warn_count}"] = f"memlock={sp_dict['memlock']} does not enforce Huge/Large pages"

    if "memory MB" in sp_dict:
        huge_page_size_kb = 2048

        sp_dict["memory GB"] = f"{round(int(sp_dict['memory MB']) / 1024)}"

        # Basic shared memory calculation
        sp_dict["shared memory MB"] = (
            sp_dict["globals total MB"] + sp_dict["routines total MB"] + round(int(sp_dict["gmheap"]) / 1024)
        )
        sp_dict[
            "shared memory calc"
        ] = f"globals {sp_dict['globals total MB']} MB + routines {sp_dict['routines total MB']} MB + gmheap {round(int(sp_dict['gmheap']) / 1024)} MB"

        # Estimate total shared memory (e.g. for huge pages) based on 2022.1 calculations
        all_present = False
        if "routines total MB" in sp_dict:
            routine_buffers_mb = int(sp_dict["routines total MB"])
            if "gmheap" in sp_dict:
                gmheap_in_mb = int(int(sp_dict["gmheap"]) / 1024)
                if "number cpus" in sp_dict:
                    number_of_logical_cpus = int(sp_dict["number cpus"])
                if "jrnbufs" in sp_dict:
                    jrnbufs_in_mb = int(sp_dict["jrnbufs"])
                    if "MaxServerConn" in sp_dict:
                        MaxServerConn = int(sp_dict["MaxServerConn"])
                        if "MaxServers" in sp_dict:
                            MaxServers = int(sp_dict["MaxServers"])
                            if "globals total MB" in sp_dict:
                                global_buffers_mb = int(sp_dict["globals total MB"])
                                all_present = True

        if all_present:
            total_shared_memory = shared_memory_estimate(
                global_buffers_mb,
                routine_buffers_mb,
                gmheap_in_mb,
                number_of_logical_cpus,
                jrnbufs_in_mb,
                MaxServerConn,
                MaxServers,
            )

            sp_dict["Estimated total IRIS shared memory"] = total_shared_memory
            sp_dict["Estimated total IRIS shared memory text"] = (
                f"Estimated total shared memory (MB):\n"
                f"[global buffers in MB] * 1.08 + [routine buffers in MB] * 1.02 + [gmheap in MB] + \n"
                f"  2 * [number of logical CPUs] + [jrnbufs in MB] + 2 * ( [MaxServerConn] + [MaxServers]) + "
                f"300 [overall fixed padding]\n\n"
                f"[{global_buffers_mb}] * 1.08 + [{routine_buffers_mb}] * 1.02 + [{gmheap_in_mb}] + \n"
                f"  2 * [{number_of_logical_cpus}] + [{jrnbufs_in_mb}] + 2 * ( [{MaxServerConn}] + [{MaxServers}]) + "
                f"300 [overall fixed padding]\n\n"
                f"See https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls"
                f"?KEY=ARES#ARES_memory_plan_estimate\n"
            )

        sp_dict["75pct memory MB"] = round(int(sp_dict["memory MB"]) * 0.75)
        sp_dict["75pct memory number huge pages"] = round((sp_dict["75pct memory MB"] * 1024) / huge_page_size_kb)

        if "vm.nr_hugepages" in sp_dict:
            if int(sp_dict["vm.nr_hugepages"]) == 0:
                warn_count += 1
                sp_dict[f"warning {warn_count}"] = (
                    f"HugePages are not set. Consider huge page memory space for production instances to improve "
                    f"performance and efficiency and to protect the shared memory from paging out. "
                    f"Specifying HugePages much higher than the shared memory amount is not advisable because the "
                    f"unused memory is not available to other components."
                )

                recommend_count += 1
                sp_dict[f"recommend {recommend_count}"] = (
                    f"Set HugePages, see IRIS documentation: "
                    f"https://docs.intersystems.com/irislatest/csp/docbook/Doc.View"
                    f".cls?KEY=GCI_prepare_install#GCI_memory_big_linux "
                )

                recommend_count += 1
                msg = f"Total memory is {int(sp_dict['memory MB']):,} MB, 75% of total memory is {int(sp_dict['75pct memory MB']):,} MB."
                sp_dict[f"recommend {recommend_count}"] = msg

                recommend_count += 1
                msg = (
                    f"Shared memory (globals+routines+gmheap+other) is {sp_dict['shared memory MB']:,} MB. "
                    f"({round((sp_dict['shared memory MB'] / int(sp_dict['memory MB'])) * 100):,}% of total memory)."
                )
                sp_dict[f"recommend {recommend_count}"] = msg

                recommend_count += 1
                # If all the info for full estimate use that, else ballpark
                if "Estimated total IRIS shared memory" in sp_dict:
                    msg = (
                        f"Number of HugePages for {huge_page_size_kb} KB page size for {sp_dict['Estimated total IRIS shared memory']:,} MB "
                        f"is {round((sp_dict['Estimated total IRIS shared memory'] * 1024) / huge_page_size_kb)}"
                    )
                else:
                    shared_memory_plus_8pct = round(sp_dict["shared memory MB"] * 1.08)
                    msg = (
                        f"Number of HugePages for {huge_page_size_kb} KB page size for ({sp_dict['shared memory MB']:,} MB + 8% buffer = {shared_memory_plus_8pct:,} MB) "
                        f"is {round((shared_memory_plus_8pct * 1024) / huge_page_size_kb)}"
                    )

                sp_dict[f"recommend {recommend_count}"] = msg

                if "max locked memory" in sp_dict:
                    if sp_dict["max locked memory"].isdigit():
                        if int(sp_dict["max locked memory"]) < 100:
                            warn_count += 1
                            sp_dict[f"warning {warn_count}"] = (
                                f"max locked memory {sp_dict['max locked memory']} kb too "
                                f"small to lock shared memory segment in memory without huge "
                                f"pages (see ulimit -a) "
                            )

            # Huge pages is specified, validate
            else:
                sp_dict["hugepages MB"] = round(int(sp_dict["vm.nr_hugepages"]) * huge_page_size_kb / 1024)

                if sp_dict["hugepages MB"] < sp_dict["shared memory MB"]:
                    warn_count += 1
                    sp_dict[
                        f"warning {warn_count}"
                    ] = f"shared memory is {sp_dict['shared memory MB']:,} MB hugepages is {sp_dict['hugepages MB']:,} MB"
                else:
                    pass_count += 1
                    sp_dict[f"pass {pass_count}"] = f"HugePages is set:"
                    pass_count += 1
                    msg = f"Total memory is {int(sp_dict['memory MB']):,} MB. "
                    sp_dict[f"pass {pass_count}"] = msg

                    pass_count += 1
                    msg = (
                        f"75% of total memory is {int(sp_dict['75pct memory MB']):,} MB. "
                        f"Shared memory is {sp_dict['shared memory MB']:,}, {round(sp_dict['shared memory MB'] / int(sp_dict['memory MB']) * 100):,}% of total memory."
                    )
                    sp_dict[f"pass {pass_count}"] = msg

                    pass_count += 1
                    msg = (
                        f"Shared memory (globals+routines+gmheap+other) is {sp_dict['shared memory MB']:,} MB, hugepages is {sp_dict['hugepages MB']:,} MB, "
                        f"gap is {sp_dict['hugepages MB'] - sp_dict['shared memory MB']:,} MB. "
                        f"Shared memory is {round((sp_dict['shared memory MB']) / int(sp_dict['hugepages MB']) * 100):,}% of huge pages."
                    )
                    sp_dict[f"pass {pass_count}"] = msg

            if "kernel.shmmax" in sp_dict:
                if int(sp_dict["kernel.shmmax"]) == 18446744073692774399:
                    pass_count += 1
                    sp_dict[f"pass {pass_count}"] = f"Kernel shared memory limit is at default"
                else:
                    if "hugepages MB" in sp_dict:
                        if int(sp_dict["kernel.shmmax"]) < sp_dict["hugepages MB"] * 1024 * 1024:
                            warn_count += 1
                            sp_dict[
                                f"warning {warn_count}"
                            ] = f"Kernel shared memory limit must be higher than hugepages."
                        else:
                            pass_count += 1
                            sp_dict[f"pass {pass_count}"] = f"Kernel shared memory limit is higher than hugepages"

        # dirty_* parameters are not relevant if using async IO – which any IRIS-based install should be.
        # A better question is async io set?
        # if "vm.dirty_background_ratio" in sp_dict:
        #     if int(sp_dict["vm.dirty_background_ratio"]) > 5:
        #         warn_count += 1
        #         sp_dict[
        #             f"warning {warn_count}"] = f"dirty_background_ratio is {sp_dict['vm.dirty_background_ratio']}. InterSystems recommends setting this parameter to 5. This setting is the maximum percentage of active memory that can be filled with dirty pages before pdflush begins to write them."
        #     else:
        #         pass_count += 1
        #         sp_dict[f"pass {pass_count}"] = f"dirty_background_ratio is {sp_dict['vm.dirty_background_ratio']}"
        #
        # if "vm.dirty_ratio" in sp_dict:
        #     if int(sp_dict["vm.dirty_ratio"]) > 10:
        #         warn_count += 1
        #         sp_dict[
        #             f"warning {warn_count}"] = f"dirty_ratio is {sp_dict['vm.dirty_ratio']}. InterSystems recommends setting this parameter to 10. This setting is the maximum percentage of total memory that can be filled with dirty pages before processes are forced to write dirty buffers themselves during their time slice instead of being allowed to do more writes. These changes force the Linux pdflush daemon to write out dirty pages more often rather than queue large amounts of updates that can potentially flood the storage with a large burst of updates"
        #     else:
        #         pass_count += 1
        #         sp_dict[f"pass {pass_count}"] = f"dirty_ratio is {sp_dict['vm.dirty_ratio']}"

    # Debug

    # for key in sp_dict:
    #     print(f"{key} : {sp_dict[key]}")

    # Some tidy up if empty

    if "platform" not in sp_dict:
        sp_dict["platform"] = "N/A"
    if "shared memory calc" not in sp_dict:
        sp_dict["shared memory calc"] = ""
    if "shared memory MB" not in sp_dict:
        sp_dict["shared memory MB"] = 0
    hostname = "N/A"
    if "linux hostname" in sp_dict:
        hostname = sp_dict["linux hostname"]
    if "windows host name" in sp_dict:
        hostname = sp_dict["windows host name"]

    # Build log

    log = f"System Summary for {sp_dict['customer']}\n\n"
    log += f"Hostname         : {hostname}\n"
    log += f"Instance         : {sp_dict['instance']}\n"

    log += f"Operating system : {sp_dict['operating system']}\n"
    log += f"Platform         : {sp_dict['platform']}\n"
    if sp_dict["operating system"] == "AIX":
        if "Number Of Processors" in sp_dict:
            log += f"No. Processors   : {sp_dict['Number Of Processors']}\n"
        if sp_dict["AIX SMT enabled"]:
            log += f"SMT enabled      : True\n"

            warn_count += 1
            sp_dict[f"recommend {recommend_count}"] = f"SMT in use check entitlement capacity (ec in vmstat)"

        if "AIX SMT" in sp_dict:
            log += f"SMT              : {sp_dict['AIX SMT']}\n"
        log += f"Logical CPUs     : {sp_dict['number cpus']}\n"
    else:
        log += f"CPUs             : {sp_dict['number cpus']}\n"
    log += f"Processor model  : {sp_dict['processor model']}\n"
    log += f"Memory           : {sp_dict['memory GB']} GB\n"
    log += f"Shared memory    : {sp_dict['shared memory calc']} = {int(sp_dict['shared memory MB']):,} MB\n"
    log += f"Version          : {sp_dict['version string']}\n"
    log += f"Date collected   : {sp_dict['profile run']}\n"

    first_pass = True
    for key in sp_dict:
        if "pass" in key:
            if first_pass:
                log += "\nPasses:\n"
                first_pass = False
            log += f"- {sp_dict[key]}\n"

    first_warning = True
    for key in sp_dict:
        if "warn" in key:
            if first_warning:
                log += "\nWarnings:\n"
                first_warning = False
            log += f"- {sp_dict[key]}\n"

    recommendations_count = False
    log += "\nRecommendations:\n"

    if not first_warning:
        log += f"- Review and fix warnings above\n"

    for key in sp_dict:
        if "recommend" in key:
            recommendations_count = True
            log += f"- {sp_dict[key]}\n"

    if not recommendations_count and first_warning:
        log += f"- No recommendations\n"

    first_instance = True
    for key in sp_dict:
        if "up instance" in key:
            if first_instance:
                log += "\nAll instances on this host:\n"
                first_instance = False
            log += f"- {sp_dict[key]}\n"

    log += "\nStorage:\n"

    log += f"Current journal        : {sp_dict['current journal']}\n"
    log += f"Alternate journal      : {sp_dict['alternate journal']}\n"
    log += f"Days before purge      : {sp_dict['DaysBeforePurge']}\n"
    if "wijdir" in sp_dict:
        log += f"WIJ directory          : {sp_dict['wijdir']}\n"

    log += "\nAdditional:\n"
    if "IRISSYS" in sp_dict:
        log += f"IRISSYS                : {sp_dict['IRISSYS']}\n"
    if "CACHESYS" in sp_dict:
        log += f"CACHESYS               : {sp_dict['CACHESYS']}\n"

    first_dev_mapper = True
    for key in sp_dict:
        if "dev mapper" in key:
            if first_dev_mapper:
                log += "\n/dev/mapper:\n"
                first_dev_mapper = False
            log += f"{sp_dict[key]}\n"

    first_filesystem = True
    for key in sp_dict:
        if "filesystem df" in key:
            if first_filesystem:
                log += "\nFilesystem (df):\n"
                first_filesystem = False
            log += f"{sp_dict[key]}\n"

    if "Estimated total IRIS shared memory" in sp_dict:
        log += f"\n--------------------------------------------------------------------------------------------------\n"
        log += f"Estimated total shared memory for IRIS 2022.1 and later: "
        log += f"{int(sp_dict['Estimated total IRIS shared memory']):,} (MB)\n\n"
        log += f'{sp_dict["Estimated total IRIS shared memory text"]}\n'

        if "hugepages MB" in sp_dict and "memory MB" in sp_dict:
            if sp_dict["hugepages MB"] < sp_dict["Estimated total IRIS shared memory"]:
                log += f"Warning:\n"
                log += f"Estimated shared memory is {sp_dict['Estimated total IRIS shared memory']:,} MB, "
                log += f"hugepages is {sp_dict['hugepages MB']:,} MB\n\n"

            log += f"Total memory is {int(sp_dict['memory MB']):,} MB.\n"
            log += (
                f"75% of total memory is {int(sp_dict['75pct memory MB']):,} MB. "
                f"Estimated shared memory is {sp_dict['Estimated total IRIS shared memory']:,}, "
                f"{round(sp_dict['Estimated total IRIS shared memory'] / int(sp_dict['memory MB']) * 100):,}% "
                f"of total memory.\n"
            )
            log += (
                f"Estimated shared memory (globals+routines+gmheap+other) is {sp_dict['Estimated total IRIS shared memory']:,} MB"
                f", hugepages is {sp_dict['hugepages MB']:,} MB, "
                f"gap is {sp_dict['hugepages MB'] - sp_dict['Estimated total IRIS shared memory']:,} MB. "
                f"Shared memory is "
                f"{round((sp_dict['Estimated total IRIS shared memory']) / int(sp_dict['hugepages MB']) * 100):,}"
                f"% of huge pages.\n"
            )
            log += (
                f"Current shared memory (from ipcs -m) is "
                f"{int(sp_dict['Shared memory segment total']/1024/1024):,} MB"
                f", hugepages is {sp_dict['hugepages MB']:,} MB, "
                f"gap is {sp_dict['hugepages MB'] - int(sp_dict['Shared memory segment total']/1024/1024):,} MB. "
                f"Shared memory is "
                f"{round((int(sp_dict['Shared memory segment total']/1024/1024))/int(sp_dict['hugepages MB']) * 100):,}"
                f"% of huge pages.\n\n"
            )

            log += f"Note:\n"
            log += f"Estimated shared memory only accounts for IRIS. "
            log += f"Other components such as JVM for reports are not included.\n"

            log += f"Confirm Huge Pages setting on the first IRIS startup. Especially for instances with low RAM."
            log += f" Adjust global buffers down if needed.\n"
            log += f"Start IRIS with all your CPF parameters set to desired values without HugePages allocated, record "
            log += f"the total shared memory segment size from the messages.log,\nand then use that as the figure for "
            log += f"calculating/allocating HugePages and then restart IRIS.\n"

    first_shared_memory = True
    for key in sp_dict:
        if "Shared memory ipcs" in key:
            if first_shared_memory:
                log += "\nShared memory from ipcs -m:\n"
                first_shared_memory = False
            log += f"{sp_dict[key]}\n"

    log += "\nEnd of report."

    yaspe_yaml = "yaspe:\n"
    yaspe_yaml += f"  Site: {sp_dict['customer'].replace(':','-')}\n"
    yaspe_yaml += f"  Hostname: {hostname}\n"
    yaspe_yaml += f"  Instance: {sp_dict['instance']}\n"

    yaspe_yaml += f"  Operating system: {sp_dict['operating system']}\n"
    yaspe_yaml += f"  Platform: {sp_dict['platform']}\n"
    yaspe_yaml += f"  CPUs: {sp_dict['number cpus']}\n"

    yaspe_yaml += f"  Processor model: {sp_dict['processor model'].replace(':','-')}\n"
    yaspe_yaml += f"  Memory: {sp_dict['memory GB']} GB\n"
    yaspe_yaml += f"  Shared memory: {sp_dict['shared memory calc']} = {int(sp_dict['shared memory MB']):,} MB\n"
    yaspe_yaml += f"  Version: {sp_dict['version string'].replace(':','-')}\n"
    yaspe_yaml += f"  Date collected: {sp_dict['profile run'].replace(':','-')}\n"

    return log, yaspe_yaml
