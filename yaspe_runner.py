#!/usr/bin/env python3
import os

import tkinter as tk
from tkinter import filedialog, messagebox, Toplevel, Label
import subprocess
import threading


class YaspeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YASPE")

        padx = 10  # Padding for the left and right side
        pady = 10  # Padding for the top and bottom

        # Input Files
        tk.Label(root, text="Input HTML Files. You can select more than one:").grid(
            row=0, column=0, sticky="e", padx=(padx, 0), pady=pady
        )
        self.input_files = tk.Entry(root, width=50)
        self.input_files.grid(row=0, column=1, pady=pady, padx=(0, padx))
        tk.Button(root, text="Browse", command=self.browse_input_files).grid(row=0, column=2, pady=pady, padx=(0, padx))

        # System Overview Checkbox
        self.var_system = tk.BooleanVar(value=True)
        tk.Checkbutton(root, text="Output System Overview. Very useful.", variable=self.var_system).grid(
            row=1, column=1, sticky="w", pady=pady, padx=(padx, 0)
        )

        # Append Checkbox (defaulted to unchecked)
        self.var_append = tk.BooleanVar(value=False)
        tk.Checkbutton(
            root,
            text="Append to Existing Database. Select multiple HTML files and use an 'output file prefix' (below).",
            variable=self.var_append,
        ).grid(row=3, column=1, sticky="w", pady=pady, padx=(padx, 0))

        # Output Prefix
        tk.Label(root, text="Output File Prefix. HTML file name used by default:").grid(
            row=4, column=0, sticky="e", pady=pady, padx=(padx, 0)
        )
        self.output_prefix = tk.Entry(root, width=50)
        self.output_prefix.grid(row=4, column=1, pady=pady, padx=(0, padx))

        # Existing Database
        tk.Label(
            root, text="Existing SQLite Database File. If 'Append' used on previous run. Uncheck 'Append' now:"
        ).grid(row=5, column=0, sticky="e", pady=pady, padx=(padx, 0))
        self.existing_database = tk.Entry(root, width=50)
        self.existing_database.grid(row=5, column=1, pady=pady, padx=(0, padx))
        tk.Button(root, text="Browse", command=self.browse_existing_database).grid(
            row=5, column=2, pady=pady, padx=(0, padx)
        )

        # CSV Checkbox
        self.var_csv = tk.BooleanVar(value=True)
        tk.Checkbutton(root, text="Create CSV Files. So you can make your own plots.", variable=self.var_csv).grid(
            row=7, column=1, sticky="w", pady=pady, padx=(padx, 0)
        )

        # PNG Checkbox
        self.var_png = tk.BooleanVar(value=True)
        tk.Checkbutton(
            root,
            text="Create PNG Files. Instead of HTML plots (will take a little longer). Good for reports.",
            variable=self.var_png,
        ).grid(row=8, column=1, sticky="w", pady=pady, padx=(padx, 0))

        # Iostat Checkbox
        self.var_iostat = tk.BooleanVar()
        tk.Checkbutton(root, text="Plot iostat data. This can take a long time.", variable=self.var_iostat).grid(
            row=10, column=1, sticky="w", pady=pady, padx=(padx, 0)
        )

        # Disk List
        tk.Label(root, text="Disk List. For example limit to only dm-0 dm-3 sdf:").grid(
            row=12, column=0, sticky="e", pady=pady, padx=(padx, 0)
        )
        self.disk_list = tk.Entry(root, width=50)
        self.disk_list.grid(row=12, column=1, pady=pady, padx=(0, padx))

        # Nfsiostat Checkbox
        self.var_nfsiostat = tk.BooleanVar()
        tk.Checkbutton(
            root,
            text="Plot nfsiostat data. Not included by default in ^SystemPerformance.",
            variable=self.var_nfsiostat,
        ).grid(row=13, column=1, sticky="w", pady=pady, padx=(padx, 0))

        # Large File Split String
        tk.Label(root, text="String to split on. If '' will split at iostat:").grid(
            row=14, column=0, sticky="e", pady=pady, padx=(padx, 0)
        )
        self.large_file_split_on_string = tk.Entry(root, width=50)
        self.large_file_split_on_string.grid(row=14, column=1, pady=pady, padx=(0, padx))

        # Date Format Checkbox
        self.var_ddmmyyyy = tk.BooleanVar()
        tk.Checkbutton(root, text="Date Format DDMMYYYY for csv files.", variable=self.var_ddmmyyyy).grid(
            row=15, column=1, sticky="w", pady=pady, padx=(padx, 0)
        )

        # Version Checkbox
        self.var_version = tk.BooleanVar()
        tk.Checkbutton(root, text="Show Version", variable=self.var_version).grid(
            row=17, column=1, sticky="w", pady=pady, padx=(padx, 0)
        )

        # Submit Button
        tk.Button(root, text="Submit", command=self.submit).grid(
            row=19, column=1, pady=pady, padx=(0, padx), sticky="e"
        )

        # Exit Button
        tk.Button(root, text="Exit", command=root.quit).grid(row=19, column=2, pady=pady, padx=(0, padx), sticky="w")

        # Ensure the window gains focus
        self.root.focus_force()

    def browse_input_files(self):
        file_paths = filedialog.askopenfilenames(filetypes=[("HTML files", "*.html"), ("All files", "*.*")])
        if file_paths:
            self.input_files.delete(0, tk.END)
            self.input_files.insert(0, ", ".join(file_paths))

    def browse_existing_database(self):
        file_path = filedialog.askopenfilename(filetypes=[("SQLite files", "*.sqlite"), ("All files", "*.*")])
        if file_path:
            self.existing_database.delete(0, tk.END)
            self.existing_database.insert(0, file_path)

    def submit(self):
        input_files = self.input_files.get().split(", ") if self.input_files.get() else []
        existing_database = self.existing_database.get()

        if not input_files and not existing_database:
            messagebox.showerror("Error", "Please provide at least one input HTML file or an existing SQLite database.")
            return

        wait_window = Toplevel(self.root)
        wait_window.title("Please Wait")
        Label(wait_window, text="Processing, please wait...").pack(padx=20, pady=20)
        wait_window.transient(self.root)
        wait_window.grab_set()

        threading.Thread(target=self.run_yaspe, args=(input_files, existing_database, wait_window)).start()

    def is_running_in_container(self):
        # Check for common environment variables (including YASPE)
        container_env_vars = ["container", "YASPE_IN_CONTAINER", "KUBERNETES_SERVICE_HOST"]
        if any(var in os.environ for var in container_env_vars):
            return True

        # Fallback to checking /proc/1/cgroup
        try:
            with open("/proc/1/cgroup", "rt") as f:
                contents = f.read().strip()
                return contents == "0::/"
        except Exception:
            return False

    def run_yaspe(self, input_files, existing_database, wait_window):
        targets = [existing_database] if existing_database else input_files

        for target in targets:
            command = "/app/./yaspe.py" if self.is_running_in_container() else "yaspe.py"
            args = [command, "-i", target] if input_files and not existing_database else [command, "-e", target]

            if self.var_iostat.get():
                args.append("-x")
            if self.var_nfsiostat.get():
                args.append("-n")
            if self.var_append.get():
                args.append("-a")
                if not self.output_prefix.get():
                    self.output_prefix.insert(0, "yaspe")
            if self.output_prefix.get():
                args.extend(["-o", self.output_prefix.get()])
            if self.var_csv.get():
                args.append("-c")
            if self.var_png.get():
                args.append("-p")
            if self.var_system.get():
                args.append("-s")
            if self.var_ddmmyyyy.get():
                args.append("-D")
            if self.disk_list.get():
                disks = self.disk_list.get().split()
                args.extend(["-d"] + disks)
            if self.large_file_split_on_string.get():
                args.extend(["-l", self.large_file_split_on_string.get()])
            if self.var_version.get():
                args.append("-v")

            try:
                subprocess.run(args, check=True)
            except subprocess.CalledProcessError as e:
                self.root.after(0, messagebox.showerror, "Error", f"Error executing YASPE for HTML {target}: {e}")

        self.root.after(0, wait_window.destroy)
        self.root.after(0, messagebox.showinfo, "Success", "YASPE executed successfully for all files.")


if __name__ == "__main__":
    root = tk.Tk()
    app = YaspeApp(root)
    root.mainloop()
