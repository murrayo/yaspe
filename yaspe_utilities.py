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
            return "", "CPU details are not in this file."
        return f"{logical} logical CPUs", (
            f"CPU details are not in this file. IRIS reports {logical} CPUs; these may be threads or vCPUs."
        )

    # The chart title already carries sockets x cores x threads and the processor model,
    # so the footnote only explains what 100% means and what the topology implies.
    if logical is None:
        logical = sockets * cores_per_socket * threads_per_core
    cores = sockets * cores_per_socket

    if host_type == "bare metal":
        if threads_per_core > 1:
            label = f"{logical} threads ({_count(sockets, 'socket')} x {_count(cores_per_socket, 'core')} x {threads_per_core} HT)"
            return label, (
                f"Physical server (not a VM) with {cores} cores, {logical} threads with Hyper-Threading. "
                f"100% = all {logical} threads busy. {_ht_note(threads_per_core)}"
            )
        label = f"{cores} physical cores ({_count(sockets, 'socket')} x {_count(cores_per_socket, 'core')}, no HT)"
        return label, f"Physical server (not a VM) with {cores} cores, no Hyper-Threading. 100% = all {cores} cores busy."

    vendor = overview.get("hypervisor vendor") or ""
    label = f"{logical} vCPUs ({vendor or 'VM'})"
    who = f"{vendor} VM" if vendor else "VM (hypervisor unknown)"
    full = f"100% = all {logical} vCPUs busy."
    steal = " If the host is short of CPU it shows as steal (st) in vmstat." if vendor == "KVM" else ""
    ready = (" Check CPU Ready (%RDY) in vCenter; above about 5% means the VM is waiting for the host."
             if vendor == "VMware" else "")

    if threads_per_core > 1:
        # Cloud VMs (AWS, GCP, Azure) present the host's HT pairs, so the HT reading applies inside the guest
        return label, (
            f"{who} with {logical} vCPUs ({_count(cores, 'core')} × {_threads(threads_per_core)}). {full} "
            f"A vCPU is one thread, not a full core: {_ht_note(threads_per_core)}{steal}{ready}"
        )

    if vendor == "KVM":
        return label, f"KVM VM with {logical} vCPUs. {full} On cloud servers a vCPU is usually one thread, not a full core.{steal}"

    return label, (
        f"{who} with {logical} vCPUs. {full} "
        "A vCPU is a thread on the host, not a guaranteed core: how much CPU it really gets depends on "
        f"how busy the host is, and that can't be seen from inside the VM.{ready}"
    )


def _ht_note(threads_per_core):
    """How to read CPU % on a Hyper-Threaded box: run above the HT point, but the % overstates headroom."""
    ht_point = 100 // threads_per_core
    return (
        "Hyper-Threading adds roughly 20-30% capacity, not double. "
        f"Running above {ht_point}% is normal and uses the hardware well, but past {ht_point}% every core "
        "is already in use, so the headroom left is smaller than the % suggests. Treat 80% as the practical ceiling."
    )


@dataclass
class RefLine:
    value: int
    kind: str      # "cores" | "threads" | "presented_cores" | "vcpus" | "logical"
    noun: str      # plural, used in sentences: "128 physical cores"
    unit: str      # singular, used per task: "one task per core"
    meaning: str   # what r above this line means: "r above 128 means <meaning>"


_QUEUING = "tasks are queuing for CPU"
_HT_SHARING = "every core is busy and Hyper-Threading is sharing cores between tasks"


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
        return [RefLine(logical, "logical", "logical CPUs", "CPU", _QUEUING)]

    cores = sockets * cores_per_socket
    if logical is None:
        logical = cores * threads_per_core

    if host_type == "bare metal":
        if threads_per_core > 1:
            return [
                RefLine(cores, "cores", "physical cores", "core", _HT_SHARING),
                RefLine(logical, "threads", "threads", "thread", _QUEUING),
            ]
        return [RefLine(cores, "cores", "physical cores", "core", _QUEUING)]

    if threads_per_core > 1:
        return [
            RefLine(cores, "presented_cores", "presented cores", "core", _HT_SHARING),
            RefLine(logical, "vcpus", "vCPUs", "vCPU", _QUEUING),
        ]
    return [RefLine(logical, "vcpus", "vCPUs", "vCPU", _QUEUING)]


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
    explain: str = ""   # what r is and what the reference lines mean
    verdict: str = ""   # what happened in this data
    footnote: str = ""  # explain + verdict, for the r charts
    per_core_divisor: int = None
    per_core_label: str = ""
    per_core_thresholds: list = field(default_factory=list)
    per_core_y_max: float = None


def _fmt_pct(pct):
    if 0 < pct < 0.05:
        return "<0.1%"
    return f"{pct:.1f}%"


def _run_queue_explain(lines, overview):
    """What r is, how many CPUs there are, and what r above each reference line means."""
    first, last = lines[0], lines[-1]
    if first.kind == "logical":
        have = f"IRIS reports {first.value} {first.noun}."
    else:
        host = "server" if overview.get("cpu host type") == "bare metal" else "VM"
        have = f"This {host} has {first.value} {first.noun}"
        have += f" ({last.value} {last.noun} with Hyper-Threading)." if len(lines) > 1 else "."
    above = f"r above {first.value} means {first.meaning}"
    if len(lines) > 1:
        above += f"; above {last.value} means {last.meaning}"
    return f"r counts tasks running or waiting for a CPU. {have} {above}."


def _run_queue_verdict(data, r, lines, pct_above, overview, peak, peak_time):
    first = lines[0]
    peak_text = f"peak {peak:,.0f} at {peak_time}" if peak_time else f"peak {peak:,.0f}"
    if pct_above[0] == 0:
        return f"Here r never went above {first.value} ({peak_text}), so there was no CPU queuing."
    was_above = f"Here r was above {first.value} for {_fmt_pct(pct_above[0])} of the time"
    if pct_above[0] < 1.0:
        return f"{was_above} ({peak_text}), so CPU queuing was not a problem."
    if len(lines) > 1 and pct_above[-1] > 0:
        was_above += f" and above {lines[-1].value} for {_fmt_pct(pct_above[-1])}"
    was_above += f" ({peak_text})."

    queued = (r > first.value).to_numpy()
    if "Total CPU" in data.columns:
        cpu = pd.to_numeric(data["Total CPU"], errors="coerce")
    elif "us" in data.columns and "sy" in data.columns:
        cpu = pd.to_numeric(data["us"], errors="coerce") + pd.to_numeric(data["sy"], errors="coerce")
    else:
        cpu = None
    cpu_median = cpu[queued].median() if cpu is not None else None

    # With HT, the first line is cores and the last is threads; CPU % at the ratio means every core is in use
    ht_point = 100.0 * first.value / lines[-1].value if len(lines) > 1 else None

    parts = [was_above]
    cpu_bound = False
    if cpu_median is None or pd.isna(cpu_median):
        pass
    elif cpu_median >= 80:
        cpu_bound = True
        parts.append(f"The CPU was about {cpu_median:.0f}% busy at those times: the server was short of CPU.")
    elif ht_point is not None and cpu_median >= ht_point:
        parts.append(f"The CPU was about {cpu_median:.0f}% busy then: every core was in use and Hyper-Threading "
                     "was absorbing the extra load. That is normal use of the hardware, but headroom was limited.")
    else:
        parts.append(f"The CPU was only about {cpu_median:.0f}% busy then, so this points to short bursts "
                     "or tasks waiting on each other (locks), not a CPU shortage.")

    vendor = overview.get("hypervisor vendor") if first.kind in ("presented_cores", "vcpus") else ""
    if vendor == "KVM" and "st" in data.columns:
        st_median = pd.to_numeric(data["st"], errors="coerce")[queued].median()
        if not pd.isna(st_median):
            if st_median >= 5:
                parts.append(f"Steal was about {st_median:.0f}% at those times: the host is short of CPU, "
                             "so adding vCPUs alone won't help.")
            elif cpu_bound:
                parts.append("Steal was low, so this VM needs more vCPUs.")
    elif vendor == "VMware":
        parts.append("VMware hides steal from inside the VM; check CPU Ready (%RDY) in vCenter for these times.")

    return " ".join(parts)


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

    # Legend entries stay short; the meaning of each line and the peak time go in the footnote
    legend_labels = []
    for i, line in enumerate(lines):
        if pct_above[i] == 0:
            legend_labels.append(f"{line.value} {line.noun}: never exceeded (peak {peak:,.0f})")
        else:
            legend_labels.append(f"{line.value} {line.noun}: above {_fmt_pct(pct_above[i])} of the time")
    thresholds = [(line.value if drawn[i] else None, legend_labels[i]) for i, line in enumerate(lines)]

    per_core_y_max = max(peak / first.value, 1.0) * 1.05
    per_core_thresholds = [(1.0, f"1.0 = one task per {first.unit} ({first.value} {first.noun})")]
    if len(lines) > 1:
        last = lines[-1]
        ratio = last.value / first.value
        if ratio <= per_core_y_max:
            per_core_thresholds.append((ratio, f"{ratio:.1f} = one task per {last.unit} ({last.value} {last.noun})"))
        else:
            per_core_thresholds.append((None, f"{ratio:.1f} = one task per {last.unit} ({last.value} {last.noun}, not reached)"))

    explain = _run_queue_explain(lines, overview or {})
    verdict = _run_queue_verdict(data, r, lines, pct_above, overview or {}, peak, peak_time)

    return RunQueueInsight(
        lines=lines,
        pct_above=pct_above,
        legend_labels=legend_labels,
        drawn=drawn,
        thresholds=thresholds,
        y_max=y_max,
        peak=peak,
        peak_time=peak_time,
        explain=explain,
        verdict=verdict,
        footnote=f"{explain} {verdict}",
        per_core_divisor=first.value,
        per_core_label=f"runnable tasks per {first.unit}",
        per_core_thresholds=per_core_thresholds,
        per_core_y_max=per_core_y_max,
    )
