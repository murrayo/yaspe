import os
from pathlib import Path


def split_large_file(input_file, **kwargs):

    split_found = False

    split_string = kwargs.get("split_string", "")
    if split_string == "":
        split_string = "div id=iostat"

    # If string not found I do not want a full copy of the file
    # Means possibly two full reads, but even 100s of MB is quick.

    with open(input_file, "r", encoding="ISO-8859-1") as file:
        # Open the output files in write mode
        for line in file:
            # Check if the split string is in the line
            if split_string in line:
                split_found = True
                break  # Exit the loop after the first occurrence

    if split_found:

        path = Path(input_file)

        input_file_name = path.name
        sub_directory = f"{path.parent}/split_html"

        if not os.path.isdir(sub_directory):
            os.mkdir(sub_directory)

        split_file = f"{sub_directory}/part1_{input_file_name}"

        # Open the input file in read mode
        with open(input_file, "r", encoding="ISO-8859-1") as file:
            # Open the output files in write mode
            with open(split_file, "w") as file_before:
                # Read the file line by line
                for line in file:
                    # Check if the split string is in the line
                    if split_string in line:
                        break  # Exit the loop after the first occurrence
                    else:
                        # Write the line to the output file before the split string is found
                        file_before.write(line)

        # Close all the files
        file_before.close()
        print(f"Part 1 of html file in {split_file}")

    else:
        print(f'File split string "{split_string}" not found, file not split')
