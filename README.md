# yaspe

Parse and chart pButtons and SystemPerformance files

# Yet Another System Performance Extractor

This will replace `yape`. I will add functionality as I need it. e.g. I expect to create charts with multiple interesting metrics. If you would like to see specific combinations let me know e.g. glorefs with CPU 

:: **NOTE:** Currently only supports ::

- IRIS/Caché (mgstat)
- Linux (vmstat, iostat)
- Windows (Perfmon)

## Create docker container image

- download the source files
- `cd` to folder with source files
- build yaspe container image: `docker build --no-cache -t yaspe .`

## Run the command over a pButtons or SystemPerformance file

See the help text:

```plaintext
usage: yaspe [-h] [-v] [-i "/path/file.html"] [-x] [-a]
             [-o "output file prefix"]
             [-e "/path/filename_SystemPerformance.sqlite"] [-c] [-p] [-s]

Performance file review.

optional arguments:
  -h, --help            show this help message and exit
  -v, --version         show program's version number and exit
  -i "/path/file.html", --input_file "/path/file.html"
                        Input html filename with full path.
  -x, --iostat          Also plot iostat data (can take a long time).
  -a, --append          Do not overwrite database, append to existing
                        database.
  -o "output file prefix", --output_prefix "output file prefix"
                        Output filename prefix, defaults to html file name,
                        blank (-o '') is legal.
  -e "/path/filename_SystemPerformance.sqlite", --existing_database "/path/filename_SystemPerformance.sqlite"
                        Chart existing database, full path and filename to
                        existing database.
  -c, --csv             Create csv files of each html files metrics, append if
                        csv file exists.
  -p, --png             Create png files of metrics. Instead of html
  -s, --system          Output system overview.

Be safe, "quote the path"
```

For example, change to the folder with a SystemPerformance html file and run the command:

```plaintext
docker run -v "$(pwd)":/data --rm --name yaspe yaspe ./yaspe.py -i /data/mysystems_systemperformance_24hour_1sec.html
```

If you want simple png files rather than html: smaller and quicker to look through: Use the `-p` option.

```plaintext
docker run -v "$(pwd)":/data --rm --name yaspe yaspe ./yaspe.py -i /data/mysystems_systemperformance_24hour_1sec.html -p
```


<hr>

Or put the path to the folder with the html file in the docker volume parameter and put the html file name after `-i /data/` 

```plaintext
docker run -v "/path/to/folder/with html file":/data --rm --name yaspe yaspe ./yaspe.py -i /data/mysystems_systemperformance_24hour_1sec.html
```

<hr>

To run _yaspe_ over multiple input files, for example a few days or a week, use the following steps:

- Copy all the SystemPerformance html files to one folder
- Use the `-a` (append) option to put all the metrics in the database (also `-x` if you want iostat)
- Use the `-e` (existing database option) to chart the appended database (also `-x` if you want iostat)

__Note:__ This works by appending data to database that contains extracted SystemPerformance data.
If the SystemPerformance files have a short sample period this can result in long run times and large output files with many data points. 
It may be a bit clunky to work with in the browser.
I suggest you run over a week without iostat (`-x`), then use the method above to deep dive on a day or couple of days.

By default, output folders and files are prefixed with the html file name. 
To keep all the metric data in a single database use the `-o` argument to override the output file prefix.

Example of running over multiple days;
- change to the folder with the html files and run the commands, run:

```plaintext
for i in `ls *.html`;do docker run -v "$(pwd)":/data --rm --name yaspe yaspe ./yaspe.py -i /data/"${i}" -a -o "three_days"; done
```

The resulting database file will use the prefix, in this example; `three_days_SystemPerformance.sqlite`

To create charts for the accumulated days use the `-e` argument.

```plaintext
docker run -v "$(pwd)":/data --rm --name yaspe yaspe ./yaspe.py -e /data/three_days_SystemPerformance.sqlite
```

<hr>

## Output files

- HTML charts for all columns in mgstat and vmstat or windows perfmon and output to folders under `./prefix_metrics`
- It is optional to create charts for iostat as this can take a long time if there is a big disk list
- If you do not want the default prefix (html file name), override with `-o your_choice` or `-o ''` for no prefix.
- If you want a csv file for further processing use the `-c` argument. If you use `-c` with `-o` csv files (for example for multiple days) will append.

*Example output*

![alt text][logo]

<hr>

# Updates

Remove the old image and create a new one with updated source code

`docker rmi yaspe`

[logo]: https://github.com/murrayo/yaspe/blob/main/yaspe.gif "Example"

## System config check

_yaspe_ includes a system overview and basic config check (`-s`)

This check is designed to save you hunting through your SystemPerformance file looking for system details. 

- a full list of items found is in `[prefix]_overview_all.csv`
- The check also includes a basic configuration review in `[prefix]_overview.txt`

An example of `overview.txt` follows:

```plaintext
System Summary for your site name

Hostname         : YOURHOST
Instance         : SHADOW
Operating system : Linux
Platform         : N/A
CPUs             : 24
Processor model  : Intel(R) Xeon(R) Gold 6248 CPU @ 2.50GHz
Memory           : 126 GB
Shared memory    : globals 71680 MB + routines 1023 MB + gmheap 1000 MB = 73,703 MB
Version          : Cache for UNIX (Red Hat Enterprise Linux for x86-64) 2018.1.4 (Build 505_1U) Thu May 28 2020 10:11:16 EDT
Date collected   : Profile run "24hours" started at 16:15:00 on Nov 22 2021.

Warnings:
- Journal freeze on error is not enabled. If journal IO errors occur database activity that occurs during this period cannot be restored.
- swappiness is 10. For databases 5 is recommended to adjust how aggressive the Linux kernel swaps memory pages to disk.
- Hugepages not set. For performance, memory efficiency and to protect the shared memory from paging out, use huge page memory space. It is not advisable to specify HugePages much higher than the shared memory amount because the unused memory are not be available to other components.
- dirty_background_ratio is 10. InterSystems recommends setting this parameter to 5. This setting is the maximum percentage of active memory that can be filled with dirty pages before pdflush begins to write them.
- dirty_ratio is 30. InterSystems recommends setting this parameter to 10. This setting is the maximum percentage of total memory that can be filled with dirty pages before processes are forced to write dirty buffers themselves during their time slice instead of being allowed to do more writes. These changes force the Linux pdflush daemon to write out dirty pages more often rather than queue large amounts of updates that can potentially flood the storage with a large burst of updates

Recommendations:
- Review and fix warnings above
- Set HugePages, see IRIS documentation: https://docs.intersystems.com/irislatest/csp/docbook/Doc.View.cls?KEY=GCI_prepare_install#GCI_memory_big_linux
- Total memory is 128,755 MB, 75% of total memory is 96,566 MB.
- Shared memory (globals+routines+gmheap) is 73,703 MB. (57% of total memory).
- Number of HugePages for 2048 KB page size for (73,703 MB + 5% buffer = 77,388 MB) is 38694

All instances on this host:
- >SHADOW            2018.1.4.505.1.a  56772  /cachesys
```

## My workflow

First I create the system check and create the SQLite file (for later processing):

`docker run -v "$(pwd)":/data --rm --name yaspe yaspe ./yaspe.py -i /data/SystemPerfomanceFileName.html -a -s -x -o yaspe`

Next I create the png files output for a quick look through key metrics:

`docker run -v "$(pwd)":/data --rm --name yaspe yaspe ./yaspe.py -e /data/yaspe_SystemPerformance.sqlite -p`

If I want to zoom in or create output for reports to customers I create the html output:

`docker run -v "$(pwd)":/data --rm --name yaspe yaspe ./yaspe.py -e /data/yaspe_SystemPerformance.sqlite -o html`

Next steps:

- for a deeper dive I use the _pretty pButtons_ scripts to combine different metrics. For example, vmstat (wa) with iostat w_await... _watch this space_