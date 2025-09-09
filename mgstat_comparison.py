#!/usr/bin/env python3
"""
MGStat Multi-Day Comparison Tool

This script compares InterSystems IRIS mgstat metrics across multiple days to analyze
database performance changes before and after system modifications.

Usage:
    python mgstat_comparison.py file1.csv file2.csv [file3.csv ...]

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


class MgstatAnalyzer:
    def __init__(self):
        # Define key mgstat metrics to analyze - WITH MGSTAT COLUMN NAMES IN TITLES
        self.key_metrics = {
            "global_refs": {
                "column": "Glorefs",
                "transform": None,
                "unit": "refs/s",
                "title": "Global References (Glorefs)",
                "description": "Global references per second",
            },
            "remote_global_refs": {
                "column": "RemGrefs",
                "transform": None,
                "unit": "refs/s",
                "title": "Remote Global Refs (RemGrefs)",
                "description": "Remote global references per second",
            },
            "global_hit_ratio": {
                "column": "GRratio",
                "transform": None,
                "unit": "%",
                "title": "Global Hit Ratio (GRratio)",
                "description": "Global buffer hit ratio percentage",
            },
            "physical_reads": {
                "column": "PhyRds",
                "transform": None,
                "unit": "reads/s",
                "title": "Physical Reads (PhyRds)",
                "description": "Physical disk reads per second",
            },
            "read_ratio": {
                "column": "Rdratio",
                "transform": None,
                "unit": "%",
                "title": "Read Ratio (Rdratio)",
                "description": "Read hit ratio percentage",
            },
            "global_updates": {
                "column": "Gloupds",
                "transform": None,
                "unit": "upds/s",
                "title": "Global Updates (Gloupds)",
                "description": "Global updates per second",
            },
            "routine_refs": {
                "column": "Rourefs",
                "transform": None,
                "unit": "refs/s",
                "title": "Routine References (Rourefs)",
                "description": "Routine references per second",
            },
            "routine_loads": {
                "column": "RouLaS",
                "transform": None,
                "unit": "loads/s",
                "title": "Routine Loads (RouLaS)",
                "description": "Routine loads per second",
            },
            "physical_writes": {
                "column": "PhyWrs",
                "transform": None,
                "unit": "writes/s",
                "title": "Physical Writes (PhyWrs)",
                "description": "Physical disk writes per second",
            },
            "wd_queue_size": {
                "column": "WDQsz",
                "transform": None,
                "unit": "entries",
                "title": "WD Queue Size (WDQsz)",
                "description": "Write daemon queue size",
            },
            "wij_writes": {
                "column": "WIJwri",
                "transform": None,
                "unit": "writes/s",
                "title": "WIJ Writes (WIJwri)",
                "description": "Write image journal writes per second",
            },
            "journal_writes": {
                "column": "Jrnwrts",
                "transform": None,
                "unit": "writes/s",
                "title": "Journal Writes (Jrnwrts)",
                "description": "Journal writes per second",
            },
            "network_sent": {
                "column": "BytSnt",
                "transform": lambda x: x / 1024 / 1024,
                "unit": "MB/s",
                "title": "Network Sent (BytSnt)",
                "description": "Network bytes sent per second (MB/s)",
            },
            "network_received": {
                "column": "BytRcd",
                "transform": lambda x: x / 1024 / 1024,
                "unit": "MB/s",
                "title": "Network Received (BytRcd)",
                "description": "Network bytes received per second (MB/s)",
            },
            "active_ecp": {
                "column": "ActECP",
                "transform": None,
                "unit": "connections",
                "title": "Active ECP (ActECP)",
                "description": "Active ECP connections",
            },
            "process_buffer_local": {
                "column": "PrgBufL",
                "transform": None,
                "unit": "buffers",
                "title": "Process Buffer Local (PrgBufL)",
                "description": "Process private global buffers local",
            },
        }

        # Add conditional metrics that might not be present in all files
        self.optional_metrics = {
            "global_buffer_size": {
                "column": "GblSz",
                "transform": lambda x: x / 1024 if x is not None else None,
                "unit": "GB",
                "title": "Global Buffer Size (GblSz)",
                "description": "Global buffer pool size in GB",
            },
            "object_buffer_size": {
                "column": "ObjSz",
                "transform": lambda x: x / 1024 if x is not None else None,
                "unit": "GB",
                "title": "Object Buffer Size (ObjSz)",
                "description": "Object buffer pool size in GB",
            },
            "bdb_buffer_size": {
                "column": "BDBSz",
                "transform": lambda x: x / 1024 if x is not None else None,
                "unit": "GB",
                "title": "BDB Buffer Size (BDBSz)",
                "description": "Big data buffer pool size in GB",
            },
        }

        self.datasets = {}

    def load_mgstat_file(self, filepath, label=None):
        """Load a mgstat CSV file and prepare it for analysis."""
        try:
            df = pd.read_csv(filepath)

            # Auto-generate label if not provided
            if label is None:
                label = Path(filepath).stem

            # Debug: Show actual columns in the file
            print(f"DEBUG: Columns in {label}: {list(df.columns)}")

            # Parse datetime
            df["timestamp"] = pd.to_datetime(df["datetime"], format="%Y/%m/%d %H:%M:%S")

            # Handle day rollover - detect if timestamps go backwards (crossing midnight)
            df = self._handle_day_rollover(df)

            # Determine collection frequency
            time_diffs = df["timestamp"].diff().dropna()
            # Filter out large gaps (likely day rollover artifacts)
            normal_diffs = time_diffs[time_diffs < pd.Timedelta(minutes=5)]
            freq_seconds = normal_diffs.median().total_seconds()

            # Check which optional metrics are available
            available_optional = {}
            for metric_name, metric_config in self.optional_metrics.items():
                if metric_config["column"] in df.columns:
                    available_optional[metric_name] = metric_config

            # Store dataset info
            self.datasets[label] = {
                "data": df,
                "frequency": freq_seconds,
                "start_time": df["timestamp"].min(),
                "end_time": df["timestamp"].max(),
                "total_samples": len(df),
                "collection_duration": (df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 3600,
                "available_optional": available_optional,
                "columns": list(df.columns),
            }

            print(
                f"Loaded {label}: {len(df)} samples, {freq_seconds}s frequency, "
                f"{self.datasets[label]['collection_duration']:.1f}h duration"
            )
            print(f"  Columns: {len(df.columns)} total, {len(available_optional)} optional metrics available")
            return True

        except Exception as e:
            print(f"Error loading {filepath}: {e}")
            return False

    def _handle_day_rollover(self, df):
        """Handle mgstat files that cross midnight."""
        df_sorted = df.sort_values("timestamp").copy()

        # Check for time going backwards (day rollover)
        time_diffs = df_sorted["timestamp"].diff()
        large_negative_diffs = time_diffs < pd.Timedelta(hours=-12)

        if large_negative_diffs.any():
            print("  Detected day rollover in mgstat data")

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

        # Combine core metrics with available optional metrics for each dataset
        for label, dataset in self.datasets.items():
            df = dataset["data"].copy()
            print(f"  Processing {label}: {len(df)} samples")

            # Process core metrics
            all_metrics = self.key_metrics.copy()
            all_metrics.update(dataset["available_optional"])

            # Calculate derived metrics
            processed_metrics = 0
            for metric_name, metric_config in all_metrics.items():
                column = metric_config["column"]
                transform = metric_config["transform"]

                if column in df.columns:
                    if transform:
                        try:
                            df[metric_name] = transform(df[column])
                        except:
                            df[metric_name] = df[column]  # Fallback if transform fails
                    else:
                        df[metric_name] = df[column]
                    processed_metrics += 1
                    print(f"    Added metric: {metric_name} from column {column}")

            # Add hour for grouping
            df["hour"] = df["timestamp"].dt.hour

            # Store processed data
            self.datasets[label]["processed_data"] = df
            self.datasets[label]["all_metrics"] = all_metrics
            print(f"    Processed {len(df)} samples with {processed_metrics} metrics")

    def get_common_metrics(self):
        """Get metrics that are available in all datasets."""
        if not self.datasets:
            print("DEBUG: No datasets available")
            return {}

        print("DEBUG: Finding common metrics across all datasets...")

        # Start with empty set, then find metrics available in ALL datasets
        common_metrics = None

        for label, dataset in self.datasets.items():
            if "processed_data" not in dataset:
                print(f"DEBUG: No processed_data for {label}")
                continue

            df = dataset["processed_data"]

            # Get all metrics available in this dataset (core + optional)
            available_metrics = set()

            # Check core metrics
            for metric_name, metric_config in self.key_metrics.items():
                if metric_config["column"] in df.columns:
                    available_metrics.add(metric_name)

            # Check optional metrics
            for metric_name, metric_config in self.optional_metrics.items():
                if metric_config["column"] in df.columns:
                    available_metrics.add(metric_name)

            print(f"DEBUG: {label} has {len(available_metrics)} available metrics")

            # Find intersection with previous datasets
            if common_metrics is None:
                common_metrics = available_metrics
                print(f"DEBUG: Starting with {len(common_metrics)} metrics from {label}")
            else:
                before_count = len(common_metrics)
                common_metrics = common_metrics.intersection(available_metrics)
                print(f"DEBUG: After intersection with {label}: {before_count} -> {len(common_metrics)} metrics")

        # Build final metrics dict
        final_metrics = {}
        if common_metrics:
            for metric_name in common_metrics:
                if metric_name in self.key_metrics:
                    final_metrics[metric_name] = self.key_metrics[metric_name]
                elif metric_name in self.optional_metrics:
                    final_metrics[metric_name] = self.optional_metrics[metric_name]

        print(f"DEBUG: Found {len(final_metrics)} common metrics: {list(final_metrics.keys())}")
        return final_metrics

    def generate_summary_stats(self):
        """Generate summary statistics for each dataset."""
        summary_data = []
        common_metrics = self.get_common_metrics()

        for label, dataset in self.datasets.items():
            if "processed_data" not in dataset:
                continue

            df = dataset["processed_data"]

            for metric_name, metric_config in common_metrics.items():
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
        common_metrics = self.get_common_metrics()

        if not common_metrics:
            print("WARNING: No common metrics found between datasets. Skipping time series plots.")
            return

        if metrics_to_plot is None:
            # Default to most important mgstat metrics that are available
            default_metrics = [
                "global_refs",
                "physical_reads",
                "global_hit_ratio",
                "physical_writes",
                "wd_queue_size",
                "journal_writes",
            ]
            metrics_to_plot = [m for m in default_metrics if m in common_metrics]
        else:
            # Filter user-specified metrics to only those available
            metrics_to_plot = [m for m in (metrics_to_plot or []) if m in common_metrics]

        if not metrics_to_plot:
            print("WARNING: No specified metrics available in common datasets. Skipping time series plots.")
            print(f"Available common metrics: {list(common_metrics.keys())}")
            return

        print(f"Creating time series plots for metrics: {metrics_to_plot}")

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

        for i, metric_name in enumerate(metrics_to_plot):
            metric_config = common_metrics[metric_name]

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
                    ax.set_title(f"{label}")

                if j == 0:  # Only set metric label on left column
                    ax.set_ylabel(f"{metric_config['title']}\n({metric_config['unit']})")

                ax.grid(True, alpha=0.3)

                # Set Y-axis limits for percentage metrics
                if metric_config["unit"] == "%":
                    ax.set_ylim(0, 100)

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
        common_metrics = self.get_common_metrics()

        if not common_metrics:
            print("WARNING: No common metrics found between datasets. Skipping distribution plots.")
            return

        if metrics_to_plot is None:
            default_metrics = ["global_refs", "physical_reads", "global_hit_ratio", "wd_queue_size"]
            metrics_to_plot = [m for m in default_metrics if m in common_metrics][:4]
        else:
            metrics_to_plot = [m for m in (metrics_to_plot or []) if m in common_metrics][:4]

        if not metrics_to_plot:
            print("WARNING: No specified metrics available for distribution plots.")
            return

        n_metrics = len(metrics_to_plot)
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        axes = axes.flatten()

        for i, metric_name in enumerate(metrics_to_plot):
            ax = axes[i]
            metric_config = common_metrics[metric_name]

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
        common_metrics = self.get_common_metrics()

        if not common_metrics:
            print("WARNING: No common metrics found between datasets. Skipping hourly pattern plots.")
            return

        if metrics_to_plot is None:
            default_metrics = ["global_refs", "physical_reads", "global_hit_ratio", "wd_queue_size"]
            metrics_to_plot = [m for m in default_metrics if m in common_metrics]
        else:
            metrics_to_plot = [m for m in (metrics_to_plot or []) if m in common_metrics]

        if not metrics_to_plot:
            print("WARNING: No specified metrics available for hourly patterns.")
            return

        n_metrics = len(metrics_to_plot)
        fig, axes = plt.subplots(n_metrics, 1, figsize=(15, 4 * n_metrics))
        if n_metrics == 1:
            axes = [axes]

        for i, metric_name in enumerate(metrics_to_plot):
            ax = axes[i]
            metric_config = common_metrics[metric_name]

            for label, dataset in self.datasets.items():
                if "processed_data" not in dataset or metric_name not in dataset["processed_data"].columns:
                    continue

                df = dataset["processed_data"]

                # Group by hour and calculate mean
                hourly_avg = df.groupby("hour")[metric_name].mean()

                ax.plot(hourly_avg.index, hourly_avg.values, marker="o", label=label, linewidth=2, markersize=4)

            hourly_title = f"Hourly Pattern: {metric_config['title']}"
            ax.set_title(hourly_title)
            ax.set_ylabel(metric_config["unit"])
            ax.set_xlabel("Hour of Day")
            ax.set_xticks(range(0, 24, 2))
            ax.legend()
            ax.grid(True, alpha=0.3)

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
        common_metrics = self.get_common_metrics()

        # Create report
        report = []
        report.append("MGStat Multi-Day Comparison Report")
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
            report.append(f"  Available Metrics: {len(dataset.get('all_metrics', {}))}")

            # Check for day rollover
            start_date = dataset["start_time"].date()
            end_date = dataset["end_time"].date()
            if start_date != end_date:
                report.append(f"  Note: Collection crosses midnight ({start_date} to {end_date})")
            report.append("")

        # Common metrics info
        report.append(f"Common Metrics Analyzed: {len(common_metrics)}")
        report.append("-" * 30)
        for metric_name, metric_config in common_metrics.items():
            report.append(f"  {metric_config['title']}: {metric_config['description']}")
        report.append("")

        # Summary statistics
        report.append("Summary Statistics by Metric:")
        report.append("-" * 35)

        for metric_name, metric_config in common_metrics.items():
            metric_data = summary_df[summary_df["Metric"] == metric_config["title"]]
            if not metric_data.empty:
                report.append(f"\n{metric_config['title']} ({metric_config['unit']}):")
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
    parser = argparse.ArgumentParser(description="Compare mgstat metrics across multiple days")
    parser.add_argument("files", nargs="+", help="MGStat CSV files to compare")
    parser.add_argument("--output-dir", "-o", default="./output", help="Output directory for plots and reports")
    parser.add_argument("--labels", nargs="+", help="Custom labels for datasets")
    parser.add_argument(
        "--metrics",
        nargs="+",
        choices=[
            "global_refs",
            "remote_global_refs",
            "global_hit_ratio",
            "physical_reads",
            "read_ratio",
            "global_updates",
            "routine_refs",
            "routine_loads",
            "physical_writes",
            "wd_queue_size",
            "wij_writes",
            "journal_writes",
            "network_sent",
            "network_received",
            "active_ecp",
            "process_buffer_local",
        ],
        help="Specific metrics to analyze",
    )

    args = parser.parse_args()

    # Create analyzer
    analyzer = MgstatAnalyzer()

    # Load files
    for i, filepath in enumerate(args.files):
        label = args.labels[i] if args.labels and i < len(args.labels) else None
        if not analyzer.load_mgstat_file(filepath, label):
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
    summary_df = analyzer.generate_comparison_report(output_file=output_dir / "mgstat_comparison_report.txt")

    # Save summary statistics
    summary_df.to_csv(output_dir / "mgstat_summary_stats.csv", index=False)

    print("\nGenerating visualizations...")

    # Time series plots
    analyzer.plot_time_series_comparison(metrics_to_plot=args.metrics, save_path=output_dir / "mgstat_timeseries.png")

    # Distribution plots
    analyzer.plot_distribution_comparison(
        metrics_to_plot=args.metrics, save_path=output_dir / "mgstat_distributions.png"
    )

    # Hourly pattern plots
    analyzer.plot_hourly_patterns(metrics_to_plot=args.metrics, save_path=output_dir / "mgstat_hourly_patterns.png")

    print(f"\nAnalysis complete! Check {output_dir} for all outputs.")


if __name__ == "__main__":
    main()
