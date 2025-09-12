#!/usr/bin/env python3
"""
VMStat Multi-Day Comparison Tool

This script compares vmstat metrics across multiple days to analyze performance
changes before and after system modifications.

Usage:
    python vmstat_comparison.py file1.csv file2.csv [file3.csv ...]

Dependencies:
    pandas, matplotlib, seaborn, python-dateutil
"""

import pandas as pd
import matplotlib

matplotlib.use("Agg")  # Set non-interactive backend before importing pyplot
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
import argparse
import sys
from pathlib import Path
import numpy as np

# Ensure matplotlib doesn't try to display plots
plt.ioff()


class VmstatAnalyzer:
    def __init__(self):
        # Define key metrics to analyze - WITH VMSTAT COLUMN NAMES IN TITLES
        self.key_metrics = {
            "cpu_usage": {
                "column": "id",
                "transform": lambda x: 100 - x,
                "unit": "%",
                "title": "CPU Usage (id)",
                "formula": "100 - idle%",
            },
            "memory_free": {
                "column": "free",
                "transform": lambda x: x / 1024 / 1024,
                "unit": "GB",
                "title": "Free Memory (free)",
                "formula": "free KB / 1024²",
            },
            "load_avg_r": {
                "column": "r",
                "transform": None,
                "unit": "processes",
                "title": "Running Processes (r)",
                "formula": "r",
            },
            "load_avg_b": {
                "column": "b",
                "transform": None,
                "unit": "processes",
                "title": "Blocked Processes (b)",
                "formula": "b",
            },
            "io_read": {
                "column": "bi",
                "transform": None,
                "unit": "blocks/s",
                "title": "Block Read I/O (bi)",
                "formula": "bi",
            },
            "io_write": {
                "column": "bo",
                "transform": None,
                "unit": "blocks/s",
                "title": "Block Write I/O (bo)",
                "formula": "bo",
            },
            "wait_io": {
                "column": "wa",
                "transform": None,
                "unit": "%",
                "title": "I/O Wait Time (wa)",
                "formula": "wa%",
            },
            "context_switches": {
                "column": "cs",
                "transform": None,
                "unit": "switches/s",
                "title": "Context Switches (cs)",
                "formula": "cs",
            },
            "interrupts": {
                "column": "in",
                "transform": None,
                "unit": "interrupts/s",
                "title": "Interrupts (in)",
                "formula": "in",
            },
            "user_cpu": {"column": "us", "transform": None, "unit": "%", "title": "User CPU (us)", "formula": "us%"},
            "system_cpu": {
                "column": "sy",
                "transform": None,
                "unit": "%",
                "title": "System CPU (sy)",
                "formula": "sy%",
            },
        }

        self.datasets = {}

    def load_vmstat_file(self, filepath, label=None):
        """Load a vmstat CSV file and prepare it for analysis."""
        try:
            df = pd.read_csv(filepath)

            # Auto-generate label if not provided
            if label is None:
                label = Path(filepath).stem

            # Parse datetime
            df["timestamp"] = pd.to_datetime(df["datetime"], format="%Y/%m/%d %H:%M:%S")

            # Handle day rollover - detect if timestamps go backwards (crossing midnight)
            df = self._handle_day_rollover(df)

            # Determine collection frequency
            time_diffs = df["timestamp"].diff().dropna()
            # Filter out large gaps (likely day rollover artifacts)
            normal_diffs = time_diffs[time_diffs < pd.Timedelta(minutes=5)]
            freq_seconds = normal_diffs.median().total_seconds()

            # Store dataset info
            self.datasets[label] = {
                "data": df,
                "frequency": freq_seconds,
                "start_time": df["timestamp"].min(),
                "end_time": df["timestamp"].max(),
                "total_samples": len(df),
                "collection_duration": (df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 3600,
            }

            print(
                f"Loaded {label}: {len(df)} samples, {freq_seconds}s frequency, "
                f"{self.datasets[label]['collection_duration']:.1f}h duration"
            )
            return True

        except Exception as e:
            print(f"Error loading {filepath}: {e}")
            return False

    def _handle_day_rollover(self, df):
        """Handle vmstat files that cross midnight."""
        df_sorted = df.sort_values("timestamp").copy()

        # Check for time going backwards (day rollover)
        time_diffs = df_sorted["timestamp"].diff()
        large_negative_diffs = time_diffs < pd.Timedelta(hours=-12)

        if large_negative_diffs.any():
            print("  Detected day rollover in vmstat data")

            # Find rollover points
            rollover_indices = df_sorted[large_negative_diffs].index

            # Add 1 day to timestamps after each rollover
            for rollover_idx in rollover_indices:
                mask = df_sorted.index >= rollover_idx
                df_sorted.loc[mask, "timestamp"] += pd.Timedelta(days=1)

        return df_sorted

    def process_datasets(self):
        """Process all loaded datasets without complex alignment."""
        if not self.datasets:
            return

        print("Processing datasets...")

        # Simple processing: just copy data and calculate metrics
        for label, dataset in self.datasets.items():
            df = dataset["data"].copy()
            print(f"  Processing {label}: {len(df)} samples")

            # Calculate derived metrics
            for metric_name, metric_config in self.key_metrics.items():
                column = metric_config["column"]
                transform = metric_config["transform"]

                if column in df.columns:
                    if transform:
                        df[metric_name] = transform(df[column])
                    else:
                        df[metric_name] = df[column]

            # Add hour for grouping
            df["hour"] = df["timestamp"].dt.hour

            # Store processed data
            self.datasets[label]["processed_data"] = df
            print(f"    Processed {len(df)} samples with all metrics")

    def generate_summary_stats(self):
        """Generate summary statistics for each dataset."""
        summary_data = []

        for label, dataset in self.datasets.items():
            if "processed_data" not in dataset:
                continue

            df = dataset["processed_data"]

            for metric_name, metric_config in self.key_metrics.items():
                if metric_name in df.columns:
                    stats = {
                        "Dataset": label,
                        "Metric": metric_config["title"],
                        "Unit": metric_config["unit"],
                        "Mean": df[metric_name].mean(),
                        "Median": df[metric_name].median(),
                        "Min": df[metric_name].min(),
                        "Max": df[metric_name].max(),
                        "Std Dev": df[metric_name].std(),
                        "P95": df[metric_name].quantile(0.95),
                        "P99": df[metric_name].quantile(0.99),
                    }
                    summary_data.append(stats)

        return pd.DataFrame(summary_data)

    def plot_time_series_comparison(self, metrics_to_plot=None, save_path=None):
        """Create time series plots comparing metrics across datasets."""
        if metrics_to_plot is None:
            # Default to most important metrics
            metrics_to_plot = ["cpu_usage", "memory_free", "load_avg_r", "io_read", "io_write", "wait_io"]

        print(f"Creating time series plots for metrics: {metrics_to_plot}")

        # Debug: Print the actual metric configuration
        print("DEBUG: Current metric configurations:")
        for name, config in self.key_metrics.items():
            print(f"  {name}: title='{config['title']}'")

        # Set up the plot - side by side layout for each dataset
        n_metrics = len(metrics_to_plot)
        n_datasets = len(self.datasets)
        fig, axes = plt.subplots(n_metrics, n_datasets, figsize=(8 * n_datasets, 4 * n_metrics))

        # Handle single metric or single dataset cases
        if n_metrics == 1 and n_datasets == 1:
            axes = [[axes]]
        elif n_metrics == 1:
            axes = [axes]
        elif n_datasets == 1:
            axes = [[ax] for ax in axes]

        # Color palette for different datasets
        colors = plt.cm.Set1(np.linspace(0, 1, len(self.datasets)))

        dataset_labels = list(self.datasets.keys())

        for i, metric_name in enumerate(metrics_to_plot):
            metric_config = self.key_metrics[metric_name]

            # First pass: find the max value across all datasets for this metric to align Y-axis
            metric_max = 0
            for label, dataset in self.datasets.items():
                if "processed_data" in dataset and metric_name in dataset["processed_data"].columns:
                    df = dataset["processed_data"]
                    if not df[metric_name].empty:
                        metric_max = max(metric_max, df[metric_name].max())

            for j, (label, dataset) in enumerate(self.datasets.items()):
                ax = axes[i][j]

                if "processed_data" not in dataset or metric_name not in dataset["processed_data"].columns:
                    ax.text(0.5, 0.5, f"{metric_name}\nnot available", ha="center", va="center", transform=ax.transAxes)
                    ax.set_title(f"{label}")
                    continue

                df = dataset["processed_data"]
                print(f"  Plotting {metric_name} for {label}: {len(df)} data points")

                # Plot time series for this dataset
                ax.plot(df["timestamp"], df[metric_name], color=colors[j], alpha=0.7, linewidth=1)

                # Set title and labels
                if i == 0:  # Only set dataset label on top row
                    # Extract date from first timestamp for legend
                    dataset_date = df["timestamp"].iloc[0].strftime("%Y-%m-%d")
                    ax.set_title(f"{label}\n{dataset_date}")

                if j == 0:  # Only set metric label on left column
                    ax.set_ylabel(f"{metric_config['title']}\n({metric_config['unit']})")

                ax.grid(True, alpha=0.3)

                # Format Y-axis to prevent scientific notation
                if metric_max < 10 and metric_max != 0:
                    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"{x:,.2f}" if x != 0 else "0"))
                else:
                    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"{int(x):,}" if x != 0 else "0"))

                # Set Y-axis limits for percentage metrics
                if metric_config["unit"] == "%":
                    ax.set_ylim(0, 100)
                else:
                    # Align Y-axis across all datasets for this metric
                    ax.set_ylim(0, metric_max * 1.05)  # Add 5% padding

                # Format x-axis - only show labels on bottom row
                if i == n_metrics - 1:
                    ax.set_xlabel("Time")
                    # Rotate x-axis labels for better readability
                    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
                else:
                    ax.set_xticklabels([])

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
            print(f"Time series plot saved to {save_path}")

        plt.close(fig)

    def plot_distribution_comparison(self, metrics_to_plot=None, save_path=None):
        """Create distribution plots comparing metrics across datasets."""
        if metrics_to_plot is None:
            metrics_to_plot = ["cpu_usage", "memory_free", "load_avg_r", "wait_io"]

        n_metrics = len(metrics_to_plot)
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        axes = axes.flatten()

        for i, metric_name in enumerate(metrics_to_plot[:4]):  # Limit to 4 for 2x2 grid
            ax = axes[i]
            metric_config = self.key_metrics[metric_name]

            data_for_plot = []
            labels_for_plot = []

            for label, dataset in self.datasets.items():
                if "processed_data" not in dataset or metric_name not in dataset["processed_data"].columns:
                    continue

                df = dataset["processed_data"]
                data_for_plot.append(df[metric_name])
                labels_for_plot.append(label)

            if data_for_plot:
                # Create violin plot
                ax.violinplot(data_for_plot, positions=range(len(data_for_plot)), showmeans=True)
                ax.set_xticks(range(len(labels_for_plot)))
                ax.set_xticklabels(labels_for_plot, rotation=45)
                ax.set_title(f"{metric_config['title']} Distribution")
                ax.set_ylabel(metric_config["unit"])
                ax.grid(True, alpha=0.3)

                # Format Y-axis to prevent scientific notation
                max_val = max(max(data) if len(data) > 0 else 0 for data in data_for_plot)
                if max_val < 10 and max_val != 0:
                    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"{x:,.2f}" if x != 0 else "0"))
                else:
                    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"{int(x):,}" if x != 0 else "0"))

        # Remove empty subplots
        for i in range(len(metrics_to_plot), 4):
            fig.delaxes(axes[i])

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
            print(f"Distribution plot saved to {save_path}")

        plt.close(fig)

    def plot_hourly_patterns(self, metrics_to_plot=None, save_path=None):
        """Create hourly pattern comparison plots."""
        if metrics_to_plot is None:
            metrics_to_plot = ["cpu_usage", "memory_free", "load_avg_r", "wait_io"]

        n_metrics = len(metrics_to_plot)
        fig, axes = plt.subplots(n_metrics, 1, figsize=(15, 4 * n_metrics))
        if n_metrics == 1:
            axes = [axes]

        for i, metric_name in enumerate(metrics_to_plot):
            ax = axes[i]
            metric_config = self.key_metrics[metric_name]

            for label, dataset in self.datasets.items():
                if "processed_data" not in dataset or metric_name not in dataset["processed_data"].columns:
                    continue

                df = dataset["processed_data"]

                # Group by hour and calculate mean
                hourly_avg = df.groupby("hour")[metric_name].mean()

                # Extract date for legend
                dataset_date = df["timestamp"].iloc[0].strftime("%Y-%m-%d")
                legend_label = f"{label} ({dataset_date})"

                ax.plot(hourly_avg.index, hourly_avg.values, marker="o", label=legend_label, linewidth=2, markersize=4)

            hourly_title = f"Hourly Pattern: {metric_config['title']}"
            ax.set_title(hourly_title)
            ax.set_ylabel(metric_config["unit"])
            ax.set_xlabel("Hour of Day")
            ax.set_xticks(range(0, 24, 2))
            ax.legend()
            ax.grid(True, alpha=0.3)

            # Format Y-axis to prevent scientific notation
            y_max = 0
            for label, dataset in self.datasets.items():
                if "processed_data" in dataset and metric_name in dataset["processed_data"].columns:
                    hourly_avg = dataset["processed_data"].groupby("hour")[metric_name].mean()
                    if not hourly_avg.empty:
                        y_max = max(y_max, hourly_avg.max())

            if y_max < 10 and y_max != 0:
                ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"{x:,.2f}" if x != 0 else "0"))
            else:
                ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"{int(x):,}" if x != 0 else "0"))

            # Debug output to verify title
            print(f"  Hourly chart title set to: {hourly_title}")

            # Set Y-axis limits for percentage metrics
            if metric_config["unit"] == "%":
                ax.set_ylim(0, 100)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
            print(f"Hourly pattern plot saved to {save_path}")

        plt.close(fig)

    def generate_comparison_report(self, output_file=None):
        """Generate a comprehensive comparison report."""
        # Calculate summary statistics
        summary_df = self.generate_summary_stats()

        # Create report
        report = []
        report.append("VMStat Multi-Day Comparison Report")
        report.append("=" * 50)
        report.append("")

        # Dataset overview
        report.append("Dataset Overview:")
        report.append("-" * 20)
        for label, dataset in self.datasets.items():
            report.append(f"{label}:")
            report.append(f"  Samples: {dataset['total_samples']}")
            report.append(f"  Frequency: {dataset['frequency']}s")
            report.append(f"  Duration: {dataset['collection_duration']:.1f} hours")
            report.append(f"  Time Range: {dataset['start_time']} to {dataset['end_time']}")

            # Check for day rollover
            start_date = dataset["start_time"].date()
            end_date = dataset["end_time"].date()
            if start_date != end_date:
                report.append(f"  Note: Collection crosses midnight ({start_date} to {end_date})")
            report.append("")

        # Summary statistics
        report.append("Summary Statistics by Metric:")
        report.append("-" * 35)

        for metric in self.key_metrics.keys():
            metric_data = summary_df[summary_df["Metric"] == self.key_metrics[metric]["title"]]
            if not metric_data.empty:
                report.append(f"\n{self.key_metrics[metric]['title']} ({self.key_metrics[metric]['unit']}):")
                for _, row in metric_data.iterrows():
                    report.append(
                        f"  {row['Dataset']}: Mean={row['Mean']:.2f}, " f"P95={row['P95']:.2f}, Max={row['Max']:.2f}"
                    )

        report_text = "\n".join(report)

        if output_file:
            with open(output_file, "w") as f:
                f.write(report_text)
            print(f"Report saved to {output_file}")

        print(report_text)
        return summary_df


def main():
    parser = argparse.ArgumentParser(description="Compare vmstat metrics across multiple days")
    parser.add_argument("files", nargs="+", help="VMStat CSV files to compare")
    parser.add_argument("--output-dir", "-o", default="./output", help="Output directory for plots and reports")
    parser.add_argument("--labels", nargs="+", help="Custom labels for datasets")
    parser.add_argument(
        "--metrics",
        nargs="+",
        choices=[
            "cpu_usage",
            "memory_free",
            "load_avg_r",
            "load_avg_b",
            "io_read",
            "io_write",
            "wait_io",
            "context_switches",
            "interrupts",
            "user_cpu",
            "system_cpu",
        ],
        help="Specific metrics to analyze",
    )

    args = parser.parse_args()

    # Create analyzer
    analyzer = VmstatAnalyzer()

    # Load files
    for i, filepath in enumerate(args.files):
        label = args.labels[i] if args.labels and i < len(args.labels) else None
        if not analyzer.load_vmstat_file(filepath, label):
            sys.exit(1)

    if not analyzer.datasets:
        print("No datasets loaded successfully.")
        sys.exit(1)

    # Process data
    print("\nProcessing datasets...")
    analyzer.process_datasets()

    # Generate outputs
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)

    print("\nGenerating comparison report...")
    summary_df = analyzer.generate_comparison_report(output_file=output_dir / "vmstat_comparison_report.txt")

    # Save summary statistics
    summary_df.to_csv(output_dir / "vmstat_summary_stats.csv", index=False)

    print("\nGenerating visualizations...")

    # Time series plots
    analyzer.plot_time_series_comparison(metrics_to_plot=args.metrics, save_path=output_dir / "vmstat_timeseries.png")

    # Distribution plots
    analyzer.plot_distribution_comparison(
        metrics_to_plot=args.metrics, save_path=output_dir / "vmstat_distributions.png"
    )

    # Hourly pattern plots
    analyzer.plot_hourly_patterns(metrics_to_plot=args.metrics, save_path=output_dir / "vmstat_hourly_patterns.png")

    print(f"\nAnalysis complete! Check {output_dir} for all outputs.")


if __name__ == "__main__":
    main()
