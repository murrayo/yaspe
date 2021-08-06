# yaspe
Parse and chart pButtons and SystemPerformance files

# Yet Another System Performance Extractor

## Create docker container image

- download the source files
- `cd` to folder with source files
- build yaspe container image: `docker build --no-cache -t yaspe .`

## Run the command over a pButtons or SystemPerformance file

Required argument `-i /data/filename.html` to point to the pButtons or SystemPerformance file.

See the help text:

```plaintext
$ docker run -v "$(pwd)":/data --rm --name yaspe yaspe ./yaspe.py -h
usage: yaspe [-h] -i "/path/file.html" [--iostat]

Performance file review

optional arguments:
  -h, --help            show this help message and exit
  -i "/path/file.html", --input_file "/path/file.html"
                        Input html filename with full path
  --iostat              Also plot iostat data (can take a long time)

Be safe, "quote the path"
```

For example, change to the folder with the html file and run the command:

```plaintext
docker run -v "$(pwd)":/data --rm --name yaspe yaspe ./yaspe.py -i /data/mysystems_systemperformance_24hour_1sec.html
```

Or put the path to the folder with the html file in the docker volume parameter and put the html file name after `-i /data/` 

```plaintext
docker run -v "/path/to/folder/with html file":/data --rm --name yaspe yaspe ./yaspe.py -i /data/mysystems_systemperformance_24hour_1sec.html
```

## Output files

- An sqlite database file `SystemPerformance.sqlite` stores extracted metrics for further processing (TBA)
- HTML charts for all columns in mgstat and vmstat or windows perfmon a output to folders under `./metrics`
- It is optional to create charts for iostat as this can take a long time if there is a big disk list

*Example output*

![alt text][logo]

<hr>

This will replace `yape`. I will add functionality as I need it. e.g. I expect to create charts with multiple interesting metrics. If you would like to see specific combinations let me know e.g. glorefs with CPU 


[logo]: https://github.com/murrayo/yaspe/blob/main/yaspe.gif "Example"

