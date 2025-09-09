#!/usr/bin/env python3
"""
Simplified VMStat Comparison - No Complex Time Alignment

This version skips the complex time alignment and just compares the datasets as-is.
"""

import pandas as pd
import matplotlib

matplotlib.use("Agg")  # Set non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from pathlib import Path
import argparse

# Ensure matplotlib doesn't try to display plots
plt.ioff()


class SimpleVmstatAnalyzer:
    def __init__(self):
        self.datasets = {}

    def load_vmstat_file(self, filepath, label=None):
        """Load a vmstat CSV file."""
        try:
            df = pd.read_csv(filepath)

            if label is None:
                label = Path(filepath).stem

            # Parse datetime
            df["timestamp"] = pd.to_datetime(df["datetime"], format="%Y/%m/%d %H:%M:%S")

            # Handle day rollover
            df = self._handle_day_rollover(df)

            # Calculate key metrics
            df["cpu_usage"] = 100 - df["id"]  # CPU usage from idle
            df["memory_free_gb"] = df["free"] / 1024 / 1024  # Convert KB to GB
            df["total_load"] = df["r"] + df["b"]  # Total system load

            # Add hour for grouping
            df["hour"] = df["timestamp"].dt.hour

            self.datasets[label] = df

            print(f"Loaded {label}:")
            print(f"  Samples: {len(df)}")
            print(f"  Time range: {df['timestamp'].min()} to {df['timestamp'].max()}")
            print(f"  CPU usage range: {df['cpu_usage'].min():.1f}% to {df['cpu_usage'].max():.1f}%")
            print(f"  Memory range: {df['memory_free_gb'].min():.1f}GB to {df['memory_free_gb'].max():.1f}GB")
            print()

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
            print("  Detected day rollover - adjusting timestamps")

            # Find rollover points
            rollover_indices = df_sorted[large_negative_diffs].index

            # Add 1 day to timestamps after each rollover
            for rollover_idx in rollover_indices:
                mask = df_sorted.index >= rollover_idx
                df_sorted.loc[mask, "timestamp"] += pd.Timedelta(days=1)

        return df_sorted

    def create_comparison_plots(self, output_dir):
        """Create all comparison plots."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # 1. Time series plots
        self.plot_time_series(output_dir)

        # 2. Distribution plots
        self.plot_distributions(output_dir)

        # 3. Hourly patterns
        self.plot_hourly_patterns(output_dir)

        # 4. Summary statistics
        self.print_summary_stats()

    def plot_time_series(self, output_dir):
        """Create time series comparison plots."""
        metrics = [
            ("cpu_usage", "CPU Usage (%)", "%"),
            ("memory_free_gb", "Free Memory (GB)", "GB"),
            ("r", "Running Processes", "processes"),
            ("bi", "Block Read I/O", "blocks/s"),
            ("bo", "Block Write I/O", "blocks/s"),
            ("wa", "I/O Wait Time", "%"),
        ]

        fig, axes = plt.subplots(len(metrics), 1, figsize=(15, 4 * len(metrics)))
        if len(metrics) == 1:
            axes = [axes]

        colors = plt.cm.Set1(np.linspace(0, 1, len(self.datasets)))

        for i, (metric, title, unit) in enumerate(metrics):
            ax = axes[i]

            for j, (label, df) in enumerate(self.datasets.items()):
                if metric in df.columns:
                    ax.plot(df["timestamp"], df[metric], label=label, color=colors[j], alpha=0.7, linewidth=1)
                    print(f"Plotted {metric} for {label}: {len(df)} points")
                else:
                    print(f"Warning: {metric} not found in {label}")

            ax.set_title(f"{title}")
            ax.set_ylabel(unit)
            ax.legend()
            ax.grid(True, alpha=0.3)

            if i == len(metrics) - 1:
                ax.set_xlabel("Time")

        plt.tight_layout()
        output_path = Path(output_dir) / "vmstat_timeseries.png"
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        print(f"Time series plot saved to {output_path}")
        plt.close(fig)

    def plot_distributions(self, output_dir):
        """Create distribution comparison plots."""
        metrics = [
            ("cpu_usage", "CPU Usage (%)", "%"),
            ("memory_free_gb", "Free Memory (GB)", "GB"),
            ("r", "Running Processes", "processes"),
            ("wa", "I/O Wait Time", "%"),
        ]

        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        axes = axes.flatten()

        for i, (metric, title, unit) in enumerate(metrics):
            ax = axes[i]

            data_for_plot = []
            labels_for_plot = []

            for label, df in self.datasets.items():
                if metric in df.columns:
                    data_for_plot.append(df[metric])
                    labels_for_plot.append(label)

            if data_for_plot:
                # Create box plot
                box_plot = ax.boxplot(data_for_plot, labels=labels_for_plot, patch_artist=True)
                colors = plt.cm.Set2(np.linspace(0, 1, len(data_for_plot)))
                for patch, color in zip(box_plot["boxes"], colors):
                    patch.set_facecolor(color)
                    patch.set_alpha(0.7)

                ax.set_title(title)
                ax.set_ylabel(unit)
                ax.grid(True, alpha=0.3)

        plt.tight_layout()
        output_path = Path(output_dir) / "vmstat_distributions.png"
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        print(f"Distribution plot saved to {output_path}")
        plt.close(fig)

    def plot_hourly_patterns(self, output_dir):
        """Create hourly pattern plots."""
        metrics = [
            ("cpu_usage", "CPU Usage (%)", "%"),
            ("memory_free_gb", "Free Memory (GB)", "GB"),
            ("r", "Running Processes", "processes"),
            ("wa", "I/O Wait Time", "%"),
        ]

        fig, axes = plt.subplots(len(metrics), 1, figsize=(15, 4 * len(metrics)))
        if len(metrics) == 1:
            axes = [axes]

        for i, (metric, title, unit) in enumerate(metrics):
            ax = axes[i]

            for label, df in self.datasets.items():
                if metric in df.columns:
                    # Group by hour and calculate mean
                    hourly_avg = df.groupby("hour")[metric].mean()

                    ax.plot(hourly_avg.index, hourly_avg.values, marker="o", label=label, linewidth=2, markersize=6)
                    print(f"Hourly pattern for {label} {metric}: {len(hourly_avg)} hours")

            ax.set_title(f"Hourly Pattern: {title}")
            ax.set_ylabel(unit)
            ax.set_xlabel("Hour of Day")
            ax.set_xticks(range(0, 24, 2))
            ax.legend()
            ax.grid(True, alpha=0.3)

        plt.tight_layout()
        output_path = Path(output_dir) / "vmstat_hourly_patterns.png"
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        print(f"Hourly pattern plot saved to {output_path}")
        plt.close(fig)

    def print_summary_stats(self):
        """Print summary statistics."""
        print("\n" + "=" * 60)
        print("SUMMARY STATISTICS")
        print("=" * 60)

        metrics = {
            "CPU Usage (%)": "cpu_usage",
            "Free Memory (GB)": "memory_free_gb",
            "Running Processes": "r",
            "Blocked Processes": "b",
            "I/O Wait (%)": "wa",
            "Context Switches/s": "cs",
        }

        for metric_name, column in metrics.items():
            print(f"\n{metric_name}:")
            print("-" * len(metric_name))

            for label, df in self.datasets.items():
                if column in df.columns:
                    mean_val = df[column].mean()
                    median_val = df[column].median()
                    p95_val = df[column].quantile(0.95)
                    max_val = df[column].max()
                    min_val = df[column].min()
                    std_val = df[column].std()

                    print(
                        f"  {label:12}: Mean={mean_val:8.2f}, "
                        f"Median={median_val:8.2f}, Std={std_val:8.2f}, "
                        f"Min={min_val:8.2f}, Max={max_val:8.2f}"
                    )


def main():
    parser = argparse.ArgumentParser(description="Simple VMStat comparison without complex alignment")
    parser.add_argument("files", nargs="+", help="VMStat CSV files to compare")
    parser.add_argument("--output-dir", "-o", default="./output", help="Output directory")
    parser.add_argument("--labels", nargs="+", help="Custom labels for datasets")

    args = parser.parse_args()

    analyzer = SimpleVmstatAnalyzer()

    # Load files
    for i, filepath in enumerate(args.files):
        label = args.labels[i] if args.labels and i < len(args.labels) else None
        if not analyzer.load_vmstat_file(filepath, label):
            return

    if not analyzer.datasets:
        print("No datasets loaded successfully.")
        return

    print("Creating comparison plots...")
    analyzer.create_comparison_plots(args.output_dir)
    print(f"\nAnalysis complete! Check {args.output_dir} for outputs.")


if __name__ == "__main__":
    main()
