# System Monitoring Comparison Tools

This repository contains Python tools for comparing system performance metrics across multiple time periods. The tools are designed to analyze before/after performance changes following system modifications, upgrades, or troubleshooting activities.

## Tools Overview

### 1. VMStat Comparison Tool (`vmstat_comparison.py`)
Analyzes Linux system performance metrics from vmstat output.

### 2. MGStat Comparison Tool (`mgstat_comparison.py`) 
Analyzes InterSystems IRIS database performance metrics from mgstat output.

### 3. Simple VMStat Tool (`vmstat_simple.py`)
Simplified version of the vmstat analyzer for quick comparisons.

## Prerequisites

### Python Dependencies
```bash
pip install pandas matplotlib seaborn python-dateutil
```

### System Requirements
- Python 3.7+
- 16GB+ RAM recommended for large datasets (24-hour collections)
- Sufficient disk space for output charts and reports

## VMStat Tool

### Data Collection
Collect vmstat data using 5-second intervals for 24 hours:
```bash
# Start vmstat collection
vmstat 5 > vmstat_before.txt 2>&1 &

# After 24 hours, stop collection and convert to CSV format
# (CSV conversion process depends on your vmstat processing pipeline)
```

### Expected CSV Format
The tool expects CSV files with these columns:
- `RunDate`, `RunTime`, `datetime` - Timestamp information
- `r`, `b` - System load (running/blocked processes)  
- `swpd`, `free`, `buff`, `cache` - Memory metrics (KB)
- `si`, `so` - Swap activity
- `bi`, `bo` - Block I/O (blocks/second)
- `in`, `cs` - Interrupts and context switches per second
- `us`, `sy`, `id`, `wa`, `st` - CPU percentages

### Key Metrics Analyzed
- **CPU Usage (id)**: 100 - idle%, total CPU utilization
- **Free Memory (free)**: Available system memory in GB
- **Running Processes (r)**: Processes in run queue
- **Block I/O (bi/bo)**: Disk read/write activity
- **I/O Wait (wa)**: Percentage of time waiting for I/O
- **Context Switches (cs)**: Process switching activity

### Usage Examples
```bash
# Basic comparison
python vmstat_comparison.py before.csv after.csv --labels "Before" "After"

# Specify output directory
python vmstat_comparison.py day1.csv day2.csv -o ./results

# Focus on specific metrics
python vmstat_comparison.py *.csv --metrics cpu_usage memory_free io_read io_write

# Compare multiple periods
python vmstat_comparison.py baseline.csv change1.csv change2.csv --labels "Baseline" "Change 1" "Change 2"
```

### Command Line Options
- `files`: VMStat CSV files to compare (required)
- `--labels`: Custom labels for datasets
- `--output-dir`, `-o`: Output directory (default: ./output)
- `--metrics`: Specific metrics to analyze

Available metrics: `cpu_usage`, `memory_free`, `load_avg_r`, `load_avg_b`, `io_read`, `io_write`, `wait_io`, `context_switches`, `interrupts`, `user_cpu`, `system_cpu`

## MGStat Tool

### Data Collection
Collect mgstat data from InterSystems IRIS:
```bash
# From IRIS terminal
USER> do ^mgstat

# Or automated collection
USER> set logfile="/path/to/mgstat_before.log"
USER> do ^mgstat(logfile,5,17280)  // 5-second intervals, 24 hours
```

### Expected CSV Format
The tool expects CSV files with these columns:
- `RunDate`, `RunTime`, `datetime` - Timestamp information
- `Glorefs`, `RemGrefs` - Global reference metrics
- `GRratio`, `Rdratio` - Cache hit ratios (%)
- `PhyRds`, `PhyWrs` - Physical disk I/O
- `Gloupds`, `RemGupds` - Global update metrics  
- `Rourefs`, `RouLaS` - Routine activity
- `WDQsz`, `WDtmpq`, `WDphase` - Write daemon metrics
- `WIJwri`, `Jrnwrts` - Journal activity
- `BytSnt`, `BytRcd` - Network activity
- `ActECP` - ECP connections
- Additional optional metrics in newer IRIS versions

### Key Metrics Analyzed
- **Global References (Glorefs)**: Database global accesses per second
- **Physical Reads (PhyRds)**: Disk reads when data not in cache  
- **Global Hit Ratio (GRratio)**: Cache efficiency percentage
- **Physical Writes (PhyWrs)**: Disk write operations per second
- **WD Queue Size (WDQsz)**: Write daemon queue depth
- **Journal Writes (Jrnwrts)**: Transaction log activity
- **Network I/O (BytSnt/BytRcd)**: Network traffic in MB/s
- **ECP Connections (ActECP)**: Distributed cache connections

### Usage Examples
```bash
# Basic database performance comparison
python mgstat_comparison.py before.csv after.csv --labels "Before" "After"

# Focus on I/O and caching metrics
python mgstat_comparison.py *.csv --metrics global_refs physical_reads global_hit_ratio

# Include network and ECP analysis
python mgstat_comparison.py db1.csv db2.csv --metrics global_refs network_sent network_received active_ecp
```

### Command Line Options
Same as vmstat tool, with mgstat-specific metrics:

Available metrics: `global_refs`, `remote_global_refs`, `global_hit_ratio`, `physical_reads`, `read_ratio`, `global_updates`, `routine_refs`, `routine_loads`, `physical_writes`, `wd_queue_size`, `wij_writes`, `journal_writes`, `network_sent`, `network_received`, `active_ecp`, `process_buffer_local`

## Output Files

Both tools generate the same output structure:

### Generated Files
- **`*_timeseries.png`**: Side-by-side time series plots for each metric
- **`*_distributions.png`**: Statistical distribution comparisons (violin plots)
- **`*_hourly_patterns.png`**: Average metrics by hour of day
- **`*_comparison_report.txt`**: Detailed text analysis report
- **`*_summary_stats.csv`**: Statistical summary data in CSV format

### Chart Layouts
- **Time Series**: Side-by-side subplots eliminate time gaps between different collection periods
- **Distributions**: Shows statistical spread and outliers for each dataset
- **Hourly Patterns**: Reveals daily usage patterns and peak periods

## Data Requirements

### File Compatibility
- **Different column counts**: Tools handle files with different numbers of columns
- **Missing metrics**: Only metrics present in ALL files are compared
- **Day rollover**: Automatically handles midnight boundary crossings
- **Frequency detection**: Automatically detects collection intervals (5s, 10s, 30s, etc.)

### Time Alignment
- No time-based filtering applied
- Each dataset analyzed independently
- Side-by-side visualization prevents timeline confusion
- Handles different collection start times gracefully

## Troubleshooting

### Common Issues

**"No common metrics found"**
- Check column names in CSV files match expected format
- Verify CSV files have proper headers
- Ensure at least one metric exists in all input files

**Empty charts or missing data**
- Verify datetime format matches: `YYYY/MM/DD HH:MM:SS`
- Check for missing or corrupted CSV data
- Ensure sufficient data points (minimum 10-20 samples)

**Memory issues with large files**
- Use 8GB+ RAM for 24-hour collections
- Consider reducing collection frequency for longer periods
- Split very large datasets into smaller time windows

### Debug Output
Both tools provide verbose logging:
- Dataset loading information
- Metric processing details  
- Chart generation progress
- Warning messages for missing data

## Performance Interpretation

### VMStat Analysis
- **High CPU usage**: Look for correlation with high context switches or I/O wait
- **Memory pressure**: Monitor free memory trends and swap activity
- **I/O bottlenecks**: Correlate physical I/O with I/O wait percentages
- **System load**: Running processes vs. blocked processes ratios

### MGStat Analysis  
- **Cache efficiency**: Global hit ratio should be >90% for good performance
- **I/O patterns**: Physical reads indicate cache misses requiring disk access
- **Write activity**: Monitor write daemon queue for potential bottlenecks
- **Network load**: ECP and network metrics show distributed system activity

### Comparison Strategy
1. **Baseline establishment**: Collect data during normal operation
2. **Change impact**: Collect data after modifications  
3. **Pattern analysis**: Compare hourly patterns for workload changes
4. **Statistical analysis**: Use distribution plots to identify performance shifts
5. **Correlation analysis**: Look for relationships between related metrics

## Best Practices

### Data Collection
- Use consistent collection intervals (5 seconds recommended)
- Collect for full 24-hour periods to capture daily patterns
- Document system changes between collection periods
- Ensure system stability during collection (avoid reboots, major changes)

### Analysis Workflow
1. Compare overall statistical summaries first
2. Examine time series for trend changes  
3. Analyze hourly patterns for workload shifts
4. Investigate distribution changes for performance impact
5. Cross-reference metrics for root cause analysis

### Reporting
- Include system configuration details in reports
- Document any known issues during collection periods
- Note correlation between metrics changes
- Provide actionable recommendations based on findings

## License and Support

These tools are provided as-is for system performance analysis. Modify and extend as needed for your specific monitoring requirements.

For issues or enhancements, ensure CSV format compatibility and verify metric definitions match your system output format.