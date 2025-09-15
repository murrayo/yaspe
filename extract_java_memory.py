#!/usr/bin/env python3
"""
Combined script to extract Java process memory usage from all HTML files in current directory
- Processes all *.html files automatically
- Shows detailed breakdown per process and totals per ps section
- Each section represents a different time snapshot
- Classifies processes as JReport Server, Render Server, or Other
- Generates individual analysis files and consolidated summary
Usage: python3 process_all_java_memory_fixed.py
"""

import sys
import re
import os
import glob
from typing import List, Tuple, Dict, Optional
from datetime import datetime

def extract_jvm_memory_settings(command: str) -> Dict[str, str]:
    """
    Extract JVM memory settings (-Xms, -Xmx) from command line
    Returns: dict with 'xms' and 'xmx' keys, empty string if not found
    """
    import re
    
    settings = {'xms': '', 'xmx': ''}
    
    # Look for -Xms and -Xmx parameters
    xms_match = re.search(r'-Xms(\d+[kmgKMG]?)', command)
    if xms_match:
        settings['xms'] = xms_match.group(1)
    
    xmx_match = re.search(r'-Xmx(\d+[kmgKMG]?)', command)
    if xmx_match:
        settings['xmx'] = xmx_match.group(1)
    
    return settings

def classify_java_process(command: str) -> str:
    """
    Classify Java process based on command line
    Returns: "JReport Server", "Render Server", or "Other"
    """
    if 'jet.server.JREntServer' in command:
        return "JReport Server"
    elif 'com.intersystems.zenreports.RenderServer' in command:
        return "Render Server"
    else:
        return "Other"

def parse_ps_line(line: str) -> Optional[Tuple[str, str, int, str, str, str, str, Dict[str, str]]]:
    """
    Parse a ps -elfy line and extract relevant fields
    Returns: (pid, user, rss_kb_int, rss_mb, rss_gb, command, process_type, jvm_settings)
    """
    # Split by whitespace, handling multiple spaces
    fields = line.strip().split()
    
    if len(fields) < 14:
        return None
    
    try:
        # Fields: S UID PID PPID C PRI NI RSS SZ WCHAN STIME TTY TIME CMD
        pid = fields[2]
        user = fields[1] 
        rss_kb = int(fields[7])
        rss_mb = rss_kb / 1024
        rss_gb = rss_kb / 1024 / 1024
        
        # Command starts at field 13 (0-indexed), but we want the full command line
        cmd_start_idx = 0
        field_count = 0
        for i, char in enumerate(line):
            if char != ' ':
                if field_count == 13:  # 14th field (0-indexed)
                    cmd_start_idx = i
                    break
            elif char == ' ' and i > 0 and line[i-1] != ' ':
                field_count += 1
        
        command = line[cmd_start_idx:].strip() if cmd_start_idx > 0 else ' '.join(fields[13:])
        
        # Extract JVM memory settings
        jvm_settings = extract_jvm_memory_settings(command)
        
        # Classify the process
        process_type = classify_java_process(command)
        
        # Truncate long commands
        if len(command) > 120:
            command = command[:120] + "..."
            
        return (pid, user, rss_kb, f"{rss_mb:.1f}", f"{rss_gb:.2f}", command, process_type, jvm_settings)
        
    except (ValueError, IndexError):
        return None

def process_html_file(html_file: str) -> Dict:
    """Process a single HTML file and return results dictionary with separate sections"""
    
    result = {
        'html_file': html_file,
        'base_name': os.path.splitext(os.path.basename(html_file))[0],
        'output_file': f"{os.path.splitext(os.path.basename(html_file))[0]}_java_memory.txt",
        'sections_found': 0,
        'sections': [],  # List of sections with their own data
        'error': None
    }
    
    try:
        with open(html_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        result['error'] = f"Error reading file: {e}"
        return result
    
    # Pattern to find ps -elfy sections
    section_pattern = r'<a id="ps -elfy_\d+">'
    end_pattern = r'<div id=vmstat>'
    
    sections = []
    lines = content.split('\n')
    
    in_section = False
    current_section = []
    
    for line in lines:
        # Check for start of section
        if re.search(section_pattern, line):
            if current_section:  # Save previous section if exists
                sections.append(current_section)
            current_section = []
            in_section = True
            continue
            
        # Check for end of section
        if re.search(end_pattern, line) and in_section:
            if current_section:
                sections.append(current_section)
                current_section = []
            in_section = False
            continue
            
        # Collect lines in section
        if in_section:
            current_section.append(line)
    
    # Don't forget the last section if file doesn't end with vmstat
    if current_section:
        sections.append(current_section)
    
    result['sections_found'] = len(sections)
    
    if not sections:
        return result
    
    # Process each section separately
    for section_num, section in enumerate(sections, 1):
        section_data = {
            'section_number': section_num,
            'processes': [],
            'total_processes': 0,
            'total_memory_kb': 0
        }
        
        for line in section:
            # Look for lines containing java processes
            if ('java' in line and 
                (line.startswith('S ') or line.startswith('R ')) and
                ('/java' in line or 'bin/java' in line)):
                
                parsed = parse_ps_line(line)
                if parsed:
                    pid, user, rss_kb, rss_mb, rss_gb, command, process_type, jvm_settings = parsed
                    process_info = {
                        'pid': pid,
                        'user': user,
                        'memory_kb': rss_kb,
                        'memory_mb': rss_mb,
                        'memory_gb': rss_gb,
                        'command': command,
                        'type': process_type,
                        'jvm_settings': jvm_settings
                    }
                    section_data['processes'].append(process_info)
                    section_data['total_processes'] += 1
                    section_data['total_memory_kb'] += rss_kb
        
        # Only add section if it has Java processes
        result['sections'].append(section_data)
    
    return result

def write_individual_report(result: Dict) -> bool:
    """Write individual analysis report to file with detailed process breakdown"""
    
    if result['error']:
        try:
            with open(result['output_file'], 'w') as f:
                f.write(f"Error processing {result['html_file']}: {result['error']}\n")
            return True
        except:
            return False
    
    try:
        output_lines = []
        output_lines.append(f"JAVA PROCESS MEMORY ANALYSIS - DETAILED BREAKDOWN")
        output_lines.append(f"Source File: {result['html_file']}")
        output_lines.append(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        output_lines.append("=" * 80)
        
        if result['sections_found'] == 0:
            output_lines.append("No ps -elfy sections found in the file")
        else:
            sections_with_java = [s for s in result['sections'] if s['total_processes'] > 0]
            
            if not sections_with_java:
                output_lines.append(f"Found {result['sections_found']} ps -elfy section(s) but no Java processes in any section")
            else:
                output_lines.append(f"\nAnalyzing {len(sections_with_java)} section(s) with Java processes:")
                output_lines.append("(Each section represents a different point in time)")
                output_lines.append("=" * 80)
                
                # Detailed breakdown per section
                for section_data in sections_with_java:
                    output_lines.append(f"\nSECTION {section_data['section_number']} - TIME SNAPSHOT")
                    output_lines.append("=" * 40)
                    
                    # Individual process details
                    output_lines.append("PROCESS BREAKDOWN:")
                    output_lines.append("-" * 40)
                    
                    for i, proc in enumerate(section_data['processes'], 1):
                        # Add visual indicator based on process type
                        type_indicator = "[JReport]" if proc['type'] == "JReport Server" else "[Render]" if proc['type'] == "Render Server" else "[Other]"
                        
                        output_lines.append(f"Process #{i} - {proc['type']} {type_indicator}:")
                        output_lines.append(f"  PID:     {proc['pid']:>8}")
                        output_lines.append(f"  User:    {proc['user']}")
                        output_lines.append(f"  Memory:  {proc['memory_kb']:>8,} KB  |  {proc['memory_mb']:>6} MB  |  {proc['memory_gb']:>5} GB")
                        
                        # Display JVM memory settings if available
                        jvm_settings = proc['jvm_settings']
                        if jvm_settings['xms'] or jvm_settings['xmx']:
                            jvm_info = []
                            if jvm_settings['xms']:
                                jvm_info.append(f"-Xms{jvm_settings['xms']}")
                            if jvm_settings['xmx']:
                                jvm_info.append(f"-Xmx{jvm_settings['xmx']}")
                            output_lines.append(f"  JVM:     {' '.join(jvm_info)}")
                        
                        output_lines.append(f"  Command: {proc['command']}")
                        output_lines.append("")
                    
                    # Section total with breakdown by type
                    type_counts = {}
                    type_memory = {}
                    for proc in section_data['processes']:
                        ptype = proc['type']
                        type_counts[ptype] = type_counts.get(ptype, 0) + 1
                        type_memory[ptype] = type_memory.get(ptype, 0) + proc['memory_kb']
                    
                    output_lines.append("-" * 80)
                    output_lines.append(f"SECTION {section_data['section_number']} TOTAL:")
                    output_lines.append(f"   Total Processes: {section_data['total_processes']:>3}")
                    output_lines.append(f"   Total Memory:    {section_data['total_memory_kb']:>10,} KB  |  {section_data['total_memory_kb']/1024:>7.1f} MB  |  {section_data['total_memory_kb']/1024/1024:>5.2f} GB")
                    
                    # Breakdown by process type
                    output_lines.append("")
                    output_lines.append("   Process Type Breakdown:")
                    for ptype in sorted(type_counts.keys()):
                        indicator = "[JReport]" if ptype == "JReport Server" else "[Render]" if ptype == "Render Server" else "[Other]"
                        output_lines.append(f"   {indicator} {ptype}: {type_counts[ptype]} process{'es' if type_counts[ptype] > 1 else ''}, {type_memory[ptype]:,} KB ({type_memory[ptype]/1024/1024:.2f} GB)")
                    
                    output_lines.append("-" * 80)
                    output_lines.append("")
                
                # Overall file summary
                output_lines.append(f"\nFILE SUMMARY:")
                output_lines.append("=" * 30)
                output_lines.append(f"Total ps sections analyzed: {result['sections_found']}")
                output_lines.append(f"Sections with Java processes: {len(sections_with_java)}")
                output_lines.append("")
                
                output_lines.append("Memory usage by section (each represents different time):")
                for section_data in sections_with_java:
                    if section_data['total_processes'] > 0:
                        output_lines.append(f"  Section {section_data['section_number']:>2}: {section_data['total_memory_kb']/1024/1024:>6.2f} GB  ({section_data['total_processes']} process{'es' if section_data['total_processes'] > 1 else ''})")
                
                # Find peak usage
                if sections_with_java:
                    peak_section = max(sections_with_java, key=lambda x: x['total_memory_kb'])
                    output_lines.append(f"\nPeak memory usage: {peak_section['total_memory_kb']/1024/1024:.2f} GB (Section {peak_section['section_number']})")
        
        with open(result['output_file'], 'w', encoding='utf-8') as f:
            f.write('\n'.join(output_lines))
        
        return True
        
    except Exception as e:
        print(f"  -> Error writing {result['output_file']}: {e}")
        return False

def write_consolidated_summary(results: List[Dict]) -> None:
    """Write consolidated summary of all processed files"""
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    summary_file = f"consolidated_java_memory_summary_{timestamp}.txt"
    
    # Calculate totals
    total_files = len(results)
    successful_files = len([r for r in results if not r['error']])
    
    output_lines = []
    output_lines.append("CONSOLIDATED JAVA MEMORY ANALYSIS SUMMARY")
    output_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output_lines.append(f"Files Processed: {total_files} ({successful_files} successful)")
    output_lines.append("=" * 70)
    
    # Individual file results with process breakdown
    output_lines.append("\nINDIVIDUAL FILE RESULTS:")
    output_lines.append("(Memory shown per section - each section is a different time snapshot)")
    output_lines.append("-" * 70)
    
    for result in results:
        if result['error']:
            output_lines.append(f"\nERROR: {result['base_name']}.html - {result['error']}")
        else:
            sections_with_java = [s for s in result['sections'] if s['total_processes'] > 0]
            if not sections_with_java:
                output_lines.append(f"\nNO JAVA: {result['base_name']}.html - No Java processes found ({result['sections_found']} sections)")
            else:
                output_lines.append(f"\nSUCCESS: {result['base_name']}.html - {len(sections_with_java)} section(s) with Java processes:")
                for section_data in sections_with_java:
                    output_lines.append(f"   Section {section_data['section_number']:>2} Total: {section_data['total_memory_kb']/1024/1024:>5.2f} GB ({section_data['total_processes']} process{'es' if section_data['total_processes'] > 1 else ''})")
                    # Show individual processes in this section with type
                    for proc in section_data['processes']:
                        type_short = "[JReport]" if proc['type'] == "JReport Server" else "[Render]" if proc['type'] == "Render Server" else "[Other]"
                        
                        # Add JVM settings if available
                        jvm_info = ""
                        jvm_settings = proc['jvm_settings']
                        if jvm_settings['xms'] or jvm_settings['xmx']:
                            jvm_parts = []
                            if jvm_settings['xms']:
                                jvm_parts.append(f"Xms{jvm_settings['xms']}")
                            if jvm_settings['xmx']:
                                jvm_parts.append(f"Xmx{jvm_settings['xmx']}")
                            jvm_info = f" ({'/'.join(jvm_parts)})"
                        
                        output_lines.append(f"     +-- PID {proc['pid']}: {int(proc['memory_kb'])/1024/1024:>5.2f} GB ({proc['user']}) - {type_short}{jvm_info}")
    
    # Peak memory analysis
    files_with_peak_memory = []
    for result in results:
        if not result['error'] and result['sections']:
            sections_with_java = [s for s in result['sections'] if s['total_processes'] > 0]
            if sections_with_java:
                peak_section = max(sections_with_java, key=lambda x: x['total_memory_kb'])
                files_with_peak_memory.append({
                    'filename': result['base_name'],
                    'peak_memory_kb': peak_section['total_memory_kb'],
                    'peak_section': peak_section['section_number'],
                    'peak_processes': peak_section['total_processes']
                })
    
    if files_with_peak_memory:
        output_lines.append(f"\nPEAK MEMORY USAGE BY FILE:")
        output_lines.append("(Highest memory usage from any single section per file)")
        output_lines.append("-" * 50)
        sorted_peaks = sorted(files_with_peak_memory, key=lambda x: x['peak_memory_kb'], reverse=True)
        for i, peak in enumerate(sorted_peaks[:15], 1):  # Top 15
            output_lines.append(f"{i:>2}. {peak['filename']}.html: {peak['peak_memory_kb']/1024/1024:>5.2f} GB (Section {peak['peak_section']}, {peak['peak_processes']} process{'es' if peak['peak_processes'] > 1 else ''})")
    
    # Overall statistics
    total_sections_analyzed = sum(r['sections_found'] for r in results if not r['error'])
    total_sections_with_java = sum(len([s for s in r['sections'] if s['total_processes'] > 0]) for r in results if not r['error'])
    
    output_lines.append(f"\nOVERALL STATISTICS:")
    output_lines.append("-" * 25)
    output_lines.append(f"Files analyzed: {successful_files}")
    output_lines.append(f"Total ps sections found: {total_sections_analyzed}")
    output_lines.append(f"Sections with Java processes: {total_sections_with_java}")
    if files_with_peak_memory:
        highest_peak = max(files_with_peak_memory, key=lambda x: x['peak_memory_kb'])
        output_lines.append(f"Highest memory usage seen: {highest_peak['peak_memory_kb']/1024/1024:.2f} GB ({highest_peak['filename']}.html, Section {highest_peak['peak_section']})")
        
        # Find and display the detailed process information for the highest peak
        for result in results:
            if result['base_name'] == highest_peak['filename'] and not result['error']:
                sections_with_java = [s for s in result['sections'] if s['total_processes'] > 0]
                peak_section_data = None
                for section_data in sections_with_java:
                    if section_data['section_number'] == highest_peak['peak_section']:
                        peak_section_data = section_data
                        break
                
                if peak_section_data:
                    output_lines.append("Peak memory details:")
                    for proc in peak_section_data['processes']:
                        type_short = "[JReport]" if proc['type'] == "JReport Server" else "[Render]" if proc['type'] == "Render Server" else "[Other]"
                        
                        # Add JVM settings if available
                        jvm_info = ""
                        jvm_settings = proc['jvm_settings']
                        if jvm_settings['xms'] or jvm_settings['xmx']:
                            jvm_parts = []
                            if jvm_settings['xms']:
                                jvm_parts.append(f"Xms{jvm_settings['xms']}")
                            if jvm_settings['xmx']:
                                jvm_parts.append(f"Xmx{jvm_settings['xmx']}")
                            jvm_info = f" ({'/'.join(jvm_parts)})"
                        
                        output_lines.append(f"  +-- PID {proc['pid']}: {int(proc['memory_kb'])/1024/1024:>5.2f} GB ({proc['user']}) - {type_short}{jvm_info}")
                break
    
    # Write summary
    summary_content = '\n'.join(output_lines)
    
    try:
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(summary_content)
        print(f"\n" + "="*70)
        print(summary_content)
        print(f"\nDetailed summary written to: {summary_file}")
    except Exception as e:
        print(f"Error writing summary file: {e}")
        print(summary_content)

def main():
    # Find all HTML files in current directory
    html_files = glob.glob("*.html")
    
    if not html_files:
        print("No HTML files found in current directory")
        sys.exit(1)
    
    print(f"Found {len(html_files)} HTML file(s) to process")
    print("="*70)
    
    results = []
    
    # Process each HTML file
    for html_file in sorted(html_files):
        print(f"Processing: {html_file}")
        
        result = process_html_file(html_file)
        results.append(result)
        
        # Write individual report
        if write_individual_report(result):
            if result['error']:
                print(f"  -> Error logged to {result['output_file']}")
            else:
                sections_with_java = [s for s in result['sections'] if s['total_processes'] > 0]
                if sections_with_java:
                    print(f"  -> Analysis written to {result['output_file']}")
                    print(f"  -> Found {len(sections_with_java)} section(s) with Java processes:")
                    
                    for section_data in sections_with_java:
                        print(f"     Section {section_data['section_number']}: {section_data['total_memory_kb']/1024/1024:.2f} GB total ({section_data['total_processes']} processes)")
                        for proc in section_data['processes']:
                            type_short = proc['type'][:6] if proc['type'] != "JReport Server" else "JReport"
                            
                            # Add JVM settings if available
                            jvm_info = ""
                            jvm_settings = proc['jvm_settings']
                            if jvm_settings['xms'] or jvm_settings['xmx']:
                                jvm_parts = []
                                if jvm_settings['xms']:
                                    jvm_parts.append(f"Xms{jvm_settings['xms']}")
                                if jvm_settings['xmx']:
                                    jvm_parts.append(f"Xmx{jvm_settings['xmx']}")
                                jvm_info = f" ({'/'.join(jvm_parts)})"
                            
                            print(f"       +-- PID {proc['pid']}: {int(proc['memory_kb'])/1024/1024:.2f} GB ({proc['user']}) - {type_short}{jvm_info}")
                else:
                    print(f"  -> Analysis written to {result['output_file']}")
                    print(f"  -> No Java processes found in any section")
        else:
            print(f"  -> Failed to write output file")
    
    # Write consolidated summary
    write_consolidated_summary(results)

if __name__ == "__main__":
    main()