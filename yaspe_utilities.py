import locale
from datetime import datetime, timedelta
import itertools
import dateutil
import dateutil.parser
from dataclasses import dataclass, field

import pandas as pd


def check_keyword_exists(data, keyword):
    if isinstance(data, dict):
        if keyword in data:
            return True
        return any(check_keyword_exists(value, keyword) for value in data.values())
    elif isinstance(data, list):
        return any(check_keyword_exists(value, keyword) for value in data)
    else:
        return False


# Set once at import. Calling setlocale per value was the dominant cost of
# extraction (23.6M calls per 24-hour file). locale.atof below relies on this.
locale.setlocale(locale.LC_ALL, "en_US.UTF-8")


def get_number_type(s):
    # Don't know if a European number or US
    if s is None:
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        pass
    try:
        return float(s)
    except (ValueError, TypeError):
        pass
    # Grouped numbers like "1,035.70" fall through to locale-aware parsing
    try:
        return locale.atof(s)
    except (ValueError, TypeError, AttributeError):
        return s


def get_aix_wacky_numbers(s):
    try:
        return int(s)
    except (ValueError, TypeError):
        pass
    try:
        if "K" in s:
            value = s.split("K")[0]
            return int(float(value) * 1000)
        elif "M" in s:
            value = s.split("M")[0]
            return int(float(value) * 1000000)
        elif "S" in s:
            value = s.split("S")[0]
            return int(float(value) * 1000)
    except (ValueError, TypeError):
        return s
    try:
        return float(s)
    except (ValueError, TypeError):
        pass
    try:
        return locale.atof(s)
    except (ValueError, TypeError):
        return s


def format_date(known_datetime, date_str):
    """
    :param known_datetime: The known datetime object to use as a reference for formatting.
                           If None (i.e. "Profile run" line was absent from the input file),
                           raises ValueError with a clear message rather than an opaque AttributeError.
    :param date_str: The date string to format.
    :return: The formatted date string.

    The `format_date` method takes a known datetime object and a date string as parameters.
    It returns a formatted date string.

    The method converts the known datetime to a date object and splits the date string into
    day, month, and year components. It generates all permutations of the components and iterates over each permutation.

    For each permutation, it checks if the year is two digits and adds 2000 to get the four digit year.
    It then validates the day, month, and year.

    If the day, month, and year are valid, it creates a date object using the permutation.
    If the generated date is within 24 hours of the known date, it returns the formatted date string
    in the format "%Y/%m/%d".

    If no valid date is found, it defaults to returning the string "2000/12/01".
    """
    if known_datetime is None:
        raise ValueError(
            f'Cannot parse date "{date_str}": no "Profile run" line was found in the input file. '
            "The file may be truncated, corrupted, or in an unsupported format."
        )
    # Convert known_datetime to date
    known_date = known_datetime.date()

    # Split the date string into components and convert to int
    dmy = list(map(int, date_str.split("/")))

    # Generate all permutations of the day/month/year
    permutations = list(itertools.permutations(dmy))

    for perm in permutations:
        day, month, year = perm

        # If year is two digits, add 2000 to get the four digit year
        if year < 100:
            year += 2000

        # Validate day, month, year
        if day > 31 or month > 12 or year < known_date.year:
            continue

        try:
            # Create date object for current permutation
            perm_date = datetime(year=year, month=month, day=day).date()
        except ValueError:
            # Skip this permutation and move on to the next if this is not a valid date
            continue

        # If perm_date is within 24 hours of known_date, return it
        if abs(perm_date - known_date).days <= 1:
            return perm_date.strftime("%Y/%m/%d")

    # Default to 1 Dec 2000 if no valid date found - at least you will get a chart
    print(f"Warning: could not resolve date '{date_str}' relative to {known_datetime.date()}; using 2000/12/01 as fallback.")
    return "2000/12/01"


def _overview_int(overview, key):
    try:
        return int(str(overview.get(key)).strip())
    except (TypeError, ValueError):
        return None


def _count(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _threads(n):
    return _count(n, "thread")


def cpu_topology_text(overview):
    """Return (title_label, footnote) describing CPU capacity from overview fields."""
    sockets = _overview_int(overview, "lscpu sockets")
    cores_per_socket = _overview_int(overview, "lscpu cores per socket")
    threads_per_core = _overview_int(overview, "lscpu threads per core")
    logical = _overview_int(overview, "lscpu cpus") or _overview_int(overview, "number cpus")
    host_type = overview.get("cpu host type")

    if None in (sockets, cores_per_socket, threads_per_core) or host_type not in ("bare metal", "virtual"):
        if logical is None:
            return "", (
                "CPU topology not available in this file. "
                "Review the true processor architecture before making capacity assumptions."
            )
        return f"{logical} logical CPUs", (
            f"CPU topology not available in this file. {logical} is the logical CPU count reported by IRIS, "
            "which may be threads or vCPUs. "
            "Review the true processor architecture before making capacity assumptions."
        )

    if logical is None:
        logical = sockets * cores_per_socket * threads_per_core
    cores = sockets * cores_per_socket
    source = overview.get("cpu topology source") or "lscpu"
    model = overview.get("processor model") or ""
    if model == "Unknown Processor":
        model = ""

    if host_type == "bare metal":
        model_text = f" ({model})" if model else ""
        topology = (
            f"{_count(sockets, 'socket')} × {_count(cores_per_socket, 'physical core')} × {_threads(threads_per_core)} "
            f"= {logical} logical CPUs{model_text}."
        )
        if threads_per_core > 1:
            label = f"{logical} threads ({_count(sockets, 'socket')} x {_count(cores_per_socket, 'core')} x {threads_per_core} HT)"
            busy = (
                f"100% = all {logical} threads busy. "
                "A Hyper-Threading thread shares a physical core and is not equivalent to a full core."
            )
        else:
            label = f"{cores} physical cores ({_count(sockets, 'socket')} x {_count(cores_per_socket, 'core')}, no HT)"
            busy = f"100% = all {cores} cores busy."
        return label, (
            f"CPU topology ({source}): bare metal, no hypervisor detected. {topology} {busy} "
            "Review the processor architecture before making capacity assumptions."
        )

    vendor = overview.get("hypervisor vendor") or ""
    label = f"{logical} vCPUs ({vendor or 'VM'})"

    if vendor == "KVM":
        return label, (
            f"CPU topology ({source}): KVM VM. {logical} vCPUs presented as "
            f"{_count(cores, 'core')} × {_threads(threads_per_core)}. "
            "On cloud instances each vCPU is typically one hyperthread, not a full core. "
            "Host contention appears as vmstat st (steal). "
            "Review the instance type and host architecture before making capacity assumptions."
        )

    who = f"{vendor} VM" if vendor else "virtual machine, hypervisor not identified"
    model_text = f"Host CPU model: {model}. " if model else ""
    vcenter = " and vCenter CPU Ready (%RDY)" if vendor == "VMware" else ""
    return label, (
        f"CPU topology ({source}): {who}. {logical} vCPUs presented as {_count(sockets, 'socket')} × "
        f"{_count(cores_per_socket, 'core')} × {_threads(threads_per_core)} — this is VM configuration, not host hardware. "
        f"{model_text}"
        "Host physical cores, Hyper-Threading and overcommit are not visible from inside the guest. "
        f"Review the host architecture{vcenter} before making capacity assumptions."
    )


@dataclass
class RefLine:
    value: int
    kind: str      # "cores" | "threads" | "presented_cores" | "vcpus" | "logical"
    noun: str      # used in sentences: "128 physical cores"
    label: str     # legend base: "Physical cores 128"
    meaning: str   # what r above this line means


_WAITING = "tasks waiting for any CPU"


def run_queue_lines(overview):
    """Return run queue reference lines (lowest first) for the CPU topology in overview."""
    overview = overview or {}
    sockets = _overview_int(overview, "lscpu sockets")
    cores_per_socket = _overview_int(overview, "lscpu cores per socket")
    threads_per_core = _overview_int(overview, "lscpu threads per core")
    logical = _overview_int(overview, "lscpu cpus") or _overview_int(overview, "number cpus")
    if logical is not None and logical <= 0:
        logical = None
    host_type = overview.get("cpu host type")

    if None in (sockets, cores_per_socket, threads_per_core) or host_type not in ("bare metal", "virtual"):
        if logical is None:
            return []
        return [RefLine(logical, "logical", "logical CPUs", f"Logical CPUs {logical}", _WAITING)]

    cores = sockets * cores_per_socket
    if logical is None:
        logical = cores * threads_per_core

    if host_type == "bare metal":
        if threads_per_core > 1:
            return [
                RefLine(cores, "cores", "physical cores", f"Physical cores {cores}", "cores running two tasks via HT"),
                RefLine(logical, "threads", "threads", f"Threads {logical}", _WAITING),
            ]
        return [RefLine(cores, "cores", "physical cores", f"Physical cores {cores}", "tasks waiting for a core")]

    if overview.get("hypervisor vendor") == "KVM" and threads_per_core > 1:
        return [
            RefLine(cores, "presented_cores", "presented cores", f"Presented cores {cores}", "vCPUs sharing a core via HT"),
            RefLine(logical, "vcpus", "vCPUs", f"vCPUs {logical}", _WAITING),
        ]
    return [RefLine(logical, "vcpus", "vCPUs", f"vCPUs {logical}", _WAITING)]


@dataclass
class RunQueueInsight:
    lines: list = field(default_factory=list)
    pct_above: list = field(default_factory=list)
    legend_labels: list = field(default_factory=list)
    drawn: list = field(default_factory=list)
    thresholds: list = field(default_factory=list)  # (value or None when off scale, legend label)
    y_max: float = None
    peak: float = None
    peak_time: str = None
    verdict: str = ""
    per_core_divisor: int = None
    per_core_label: str = ""
    per_core_thresholds: list = field(default_factory=list)
    per_core_y_max: float = None


def _fmt_pct(pct):
    if 0 < pct < 0.05:
        return "<0.1%"
    return f"{pct:.1f}%"


def _run_queue_verdict(data, r, lines, pct_above, overview):
    first = lines[0]
    first_text = f"{first.value} {first.noun}"
    if pct_above[0] < 1.0:
        return (f"Run queue: tasks wanting to run rarely exceeded {first_text} (under 1% of samples), "
                "so there was no CPU queuing.")

    queued = (r > first.value).to_numpy()
    if "Total CPU" in data.columns:
        cpu = pd.to_numeric(data["Total CPU"], errors="coerce")
    elif "us" in data.columns and "sy" in data.columns:
        cpu = pd.to_numeric(data["us"], errors="coerce") + pd.to_numeric(data["sy"], errors="coerce")
    else:
        cpu = None
    cpu_median = cpu[queued].median() if cpu is not None else None

    parts = []
    cpu_bound = False
    wanted = f"more than {first.value} tasks wanted to run (there are {first_text})"
    if cpu_median is None or pd.isna(cpu_median):
        parts.append(f"{wanted} in {_fmt_pct(pct_above[0])} of samples.")
    elif cpu_median >= 80:
        cpu_bound = True
        parts.append(f"at times {wanted} and the CPU was {cpu_median:.0f}% busy — the server is short of CPU.")
    else:
        parts.append(
            f"at times {wanted}, but the CPU was only {cpu_median:.0f}% busy — not a CPU shortage. "
            "Likely short bursts of work, or tasks waiting on each other (locks)."
        )

    if first.kind == "cores" and len(lines) > 1:
        band = pct_above[0] - pct_above[1]
        if band > 0:
            parts.append(
                f"For {_fmt_pct(band)} of the time some physical cores were running two tasks at once (HT), "
                "so each task ran slower."
            )

    vendor = overview.get("hypervisor vendor") if first.kind in ("presented_cores", "vcpus") else ""
    if vendor == "KVM" and "st" in data.columns:
        st_median = pd.to_numeric(data["st"], errors="coerce")[queued].median()
        if not pd.isna(st_median):
            if st_median >= 5:
                parts.append(
                    f"Steal was {st_median:.0f}% at those times — the host is short of CPU, "
                    "so adding vCPUs alone won't help."
                )
            elif cpu_bound:
                parts.append("Steal was low — this VM needs more vCPUs.")
    elif vendor == "VMware":
        parts.append("VMware hides steal from inside the VM; check CPU Ready (%RDY) in vCenter for these times.")

    return "Run queue: " + " ".join(parts)


def run_queue_insight(df, overview, time_col="datetime_parsed"):
    """Reference lines, time above each line, verdict and per-core scaling for the vmstat r chart."""
    lines = run_queue_lines(overview)
    if df is None or "r" not in df.columns or not lines:
        return RunQueueInsight()
    r = pd.to_numeric(df["r"], errors="coerce")
    keep = r.notna()
    if not keep.any():
        return RunQueueInsight()
    data = df.loc[keep.to_numpy()]
    r = r[keep.to_numpy()]
    n = len(r)

    peak = float(r.max())
    peak_time = None
    if time_col in data.columns:
        peak_pos = int(r.to_numpy().argmax())
        peak_time = pd.Timestamp(data[time_col].iloc[peak_pos]).strftime("%d-%b %H:%M")

    pct_above = [100.0 * float((r > line.value).sum()) / n for line in lines]
    first = lines[0]
    y_max = max(peak, first.value) * 1.05 if peak >= 0.5 * first.value else peak
    drawn = [line.value <= y_max for line in lines]

    highest = max((i for i, pct in enumerate(pct_above) if pct > 0), default=None)
    legend_labels = []
    for i, line in enumerate(lines):
        if not drawn[i]:
            legend_labels.append(f"{line.label} (off scale, peak {peak:,.0f} = {100 * peak / line.value:.0f}%)")
            continue
        text = f"{line.label} (above = {line.meaning}): {_fmt_pct(pct_above[i])} of samples above"
        if i == highest and peak_time:
            text += f", peak {peak:,.0f} at {peak_time}"
        legend_labels.append(text)
    thresholds = [(line.value if drawn[i] else None, legend_labels[i]) for i, line in enumerate(lines)]

    per_core_y_max = max(peak / first.value, 1.0) * 1.05
    per_core_thresholds = [(1.0, f"1.0 = r equals {first.value} {first.noun} (saturated)")]
    if len(lines) > 1:
        ratio = lines[-1].value / first.value
        label = f"{ratio:g} = all {lines[-1].value} {lines[-1].noun} busy"
        if ratio <= per_core_y_max:
            per_core_thresholds.append((ratio, label))
        else:
            per_core_thresholds.append((None, f"{label} (off scale)"))

    return RunQueueInsight(
        lines=lines,
        pct_above=pct_above,
        legend_labels=legend_labels,
        drawn=drawn,
        thresholds=thresholds,
        y_max=y_max,
        peak=peak,
        peak_time=peak_time,
        verdict=_run_queue_verdict(data, r, lines, pct_above, overview or {}),
        per_core_divisor=first.value,
        per_core_label=f"r ÷ {first.value} {first.noun}",
        per_core_thresholds=per_core_thresholds,
        per_core_y_max=per_core_y_max,
    )
