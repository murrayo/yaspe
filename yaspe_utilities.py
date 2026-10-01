import locale
from datetime import datetime, timedelta
import itertools
import dateutil
import dateutil.parser


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
