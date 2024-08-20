#!/usr/bin/env python3

import sys
import subprocess
from PyQt5.QtCore import pyqtSignal, QObject, Qt, QThread
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QCheckBox,
    QMessageBox,
)


class Worker(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        input_files,
        existing_database,
        var_iostat,
        var_nfsiostat,
        var_append,
        output_prefix,
        var_csv,
        var_png,
        var_system,
        var_ddmmyyyy,
        disk_list,
        large_file_split_on_string,
        var_version,
    ):
        super().__init__()
        self.input_files = input_files
        self.existing_database = existing_database
        self.var_iostat = var_iostat
        self.var_nfsiostat = var_nfsiostat
        self.var_append = var_append
        self.output_prefix = output_prefix
        self.var_csv = var_csv
        self.var_png = var_png
        self.var_system = var_system
        self.var_ddmmyyyy = var_ddmmyyyy
        self.disk_list = disk_list
        self.large_file_split_on_string = large_file_split_on_string
        self.var_version = var_version

    def run(self):
        targets = [self.existing_database] if self.existing_database else self.input_files

        for target in targets:
            args = (
                ["yaspe.py", "-i", target]
                if self.input_files and not self.existing_database
                else ["yaspe.py", "-e", target]
            )
            if self.var_iostat:
                args.append("-x")
            if self.var_nfsiostat:
                args.append("-n")
            if self.var_append:
                args.append("-a")
                if not self.output_prefix:
                    self.output_prefix = "yaspe"
            if self.output_prefix:
                args.extend(["-o", self.output_prefix])
            if self.var_csv:
                args.append("-c")
            if self.var_png:
                args.append("-p")
            if self.var_system:
                args.append("-s")
            if self.var_ddmmyyyy:
                args.append("-D")
            if self.disk_list:
                disks = self.disk_list.split()
                args.extend(["-d"] + disks)
            if self.large_file_split_on_string:
                args.extend(["-l", self.large_file_split_on_string])
            if self.var_version:
                args.append("-v")

            try:
                subprocess.run(args, check=True)
            except subprocess.CalledProcessError as e:
                self.error.emit(f"Error executing YASPE for target {target}: {e}")
                return

        self.finished.emit()


class YaspeApp(QWidget):
    def __init__(self):
        super().__init__()

        self.initUI()

    def initUI(self):
        self.setWindowTitle("YASPE Argument Prompter")

        main_layout = QVBoxLayout()

        # Input Files
        input_files_layout = QHBoxLayout()
        input_files_label = QLabel("Input HTML Files:")
        self.input_files = QLineEdit()
        input_files_browse = QPushButton("Browse")
        input_files_browse.clicked.connect(self.browse_input_files)
        input_files_layout.addWidget(input_files_label)
        input_files_layout.addWidget(self.input_files)
        input_files_layout.addWidget(input_files_browse)
        main_layout.addLayout(input_files_layout)

        # Iostat Checkbox
        self.var_iostat = QCheckBox("Plot Iostat Data")
        main_layout.addWidget(self.var_iostat)

        # Nfsiostat Checkbox
        self.var_nfsiostat = QCheckBox("Plot Nfsiostat Data")
        main_layout.addWidget(self.var_nfsiostat)

        # Append Checkbox
        self.var_append = QCheckBox("Append to Existing Database")
        main_layout.addWidget(self.var_append)

        # Output Prefix
        output_prefix_layout = QHBoxLayout()
        output_prefix_label = QLabel("Output File Prefix:")
        self.output_prefix = QLineEdit()
        output_prefix_layout.addWidget(output_prefix_label)
        output_prefix_layout.addWidget(self.output_prefix)
        main_layout.addLayout(output_prefix_layout)

        # Existing Database
        existing_database_layout = QHBoxLayout()
        existing_database_label = QLabel("Existing Database File:")
        self.existing_database = QLineEdit()
        existing_database_browse = QPushButton("Browse")
        existing_database_browse.clicked.connect(self.browse_existing_database)
        existing_database_layout.addWidget(existing_database_label)
        existing_database_layout.addWidget(self.existing_database)
        existing_database_layout.addWidget(existing_database_browse)
        main_layout.addLayout(existing_database_layout)

        # CSV Checkbox
        self.var_csv = QCheckBox("Create CSV Files")
        main_layout.addWidget(self.var_csv)

        # PNG Checkbox
        self.var_png = QCheckBox("Create PNG Files")
        main_layout.addWidget(self.var_png)

        # System Overview Checkbox
        self.var_system = QCheckBox("Output System Overview")
        main_layout.addWidget(self.var_system)

        # Date Format Checkbox
        self.var_ddmmyyyy = QCheckBox("Date Format DDMMYYYY")
        main_layout.addWidget(self.var_ddmmyyyy)

        # Disk List
        disk_list_layout = QHBoxLayout()
        disk_list_label = QLabel("Disk List:")
        self.disk_list = QLineEdit()
        disk_list_layout.addWidget(disk_list_label)
        disk_list_layout.addWidget(self.disk_list)
        main_layout.addLayout(disk_list_layout)

        # Large File Split String
        large_file_split_on_string_layout = QHBoxLayout()
        large_file_split_on_string_label = QLabel("String to Split On:")
        self.large_file_split_on_string = QLineEdit()
        large_file_split_on_string_layout.addWidget(large_file_split_on_string_label)
        large_file_split_on_string_layout.addWidget(self.large_file_split_on_string)
        main_layout.addLayout(large_file_split_on_string_layout)

        # Version Checkbox
        self.var_version = QCheckBox("Show Version")
        main_layout.addWidget(self.var_version)

        # Submit and Exit Buttons
        buttons_layout = QHBoxLayout()
        submit_button = QPushButton("Submit")
        submit_button.clicked.connect(self.submit)
        exit_button = QPushButton("Exit")
        exit_button.clicked.connect(self.close)
        buttons_layout.addWidget(submit_button)
        buttons_layout.addWidget(exit_button)
        main_layout.addLayout(buttons_layout)

        self.setLayout(main_layout)

    def browse_input_files(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select HTML Files", "", "HTML files (*.html);;All files (*.*)"
        )
        if file_paths:
            self.input_files.setText(", ".join(file_paths))

    def browse_existing_database(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select SQLite File", "", "SQLite files (*.sqlite);;All files (*.*)"
        )
        if file_path:
            self.existing_database.setText(file_path)

    def submit(self):
        input_files = self.input_files.text().split(", ") if self.input_files.text() else []
        existing_database = self.existing_database.text()

        if not input_files and not existing_database:
            QMessageBox.critical(self, "Error", "Please provide at least one input file or an existing database.")
            return

        self.label_processing = QLabel("Processing, please wait...")
        self.layout().insertWidget(0, self.label_processing)

        self.thread = QThread()
        self.worker = Worker(
            input_files,
            existing_database,
            self.var_iostat.isChecked(),
            self.var_nfsiostat.isChecked(),
            self.var_append.isChecked(),
            self.output_prefix.text(),
            self.var_csv.isChecked(),
            self.var_png.isChecked(),
            self.var_system.isChecked(),
            self.var_ddmmyyyy.isChecked(),
            self.disk_list.text(),
            self.large_file_split_on_string.text(),
            self.var_version.isChecked(),
        )

        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.error.connect(self.show_error)
        self.worker.finished.connect(self.show_success)

        self.thread.start()

    def show_error(self, message):
        self.label_processing.deleteLater()
        QMessageBox.critical(self, "Error", message)

    def show_success(self):
        self.label_processing.deleteLater()
        QMessageBox.information(self, "Success", "YASPE executed successfully for all targets.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = YaspeApp()
    ex.show()
    sys.exit(app.exec_())
