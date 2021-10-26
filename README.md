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
$ docker run -v "$(pwd)":/data --rm --name yaspe yaspe ./yaspe.py -h
usage: yaspe [-h] [-v] [-i "/path/file.html"] [-x] [-a] [-o "output file prefix"] [-e "/path/filename_SystemPerformance.sqlite"] [-c] [-p] [-s]

Performance file review.

optional arguments:
  -h, --help            show this help message and exit
  -v, --version         show program's version number and exit
  -i "/path/file.html", --input_file "/path/file.html"
                        Input html filename with full path.
  -x, --iostat          Also plot iostat data (can take a long time).
  -a, --append          Do not overwrite database, append to existing database.
  -o "output file prefix", --output_prefix "output file prefix"
                        Output filename prefix, defaults to html file name, blank (-o '') is legal.
  -e "/path/filename_SystemPerformance.sqlite", --existing_database "/path/filename_SystemPerformance.sqlite"
                        Chart existing database, full path and filename to existing database.
  -c, --csv             Create csv files of each html files metrics, append if csv file exists.
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

