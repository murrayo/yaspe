"""Plain-language chart footnotes: what each metric is, and what to look for.

mgstat column meanings follow "Monitoring Performance Using ^mgstat" in the IRIS Monitoring Guide.
"""


def _expand(notes):
    out = {}
    for names, note in notes.items():
        for name in names if isinstance(names, tuple) else (names,):
            out[name] = note
    return out


_WORKLOAD = "Rises and falls with the workload. Look for sudden changes from the baseline."

VMSTAT_COLUMN_NOTES = _expand({
    "b": ("Processes blocked, usually waiting for disk I/O.",
          "Normally 0 or close to it. A steady non-zero value suggests storage is slow."),
    "swpd": ("Swap space in use (KB).",
             "A flat value is often harmless. Watch for steady growth."),
    "free": ("Unused physical memory (KB).",
             "Low free memory is normal on Linux because cache uses it. Look at si/so instead."),
    "buff": ("Memory used for filesystem metadata buffers (KB).",
             "Usually small and stable. Rarely a concern."),
    "cache": ("Memory used for the filesystem page cache (KB).",
              "High is normal, Linux gives it back when needed. A sudden drop can mean memory pressure."),
    "si": ("Memory read back in from swap (KB/s).",
           "Should be 0 or near 0. Sustained values mean the system is short of memory."),
    "so": ("Memory written out to swap (KB/s).",
           "Should be 0. Any sustained swap-out is a red flag for memory."),
    "bi": ("Blocks read from disk per second (1 block = 1 KB).",
           "Compare to your normal workload. Spikes often line up with reports, backups or integrity checks."),
    "bo": ("Blocks written to disk per second (1 block = 1 KB).",
           "Regular spikes are normal (IRIS write daemon cycles). Look for sustained highs."),
    "in": ("Hardware interrupts per second.",
           "Rises and falls with disk and network activity. Look for sudden changes from the baseline."),
    "cs": ("Context switches per second.",
           "Rises and falls with the workload. A big jump without more work can mean lock or scheduling contention."),
    "id": ("CPU idle %.",
           "Low idle for long periods means the CPU is close to capacity."),
    "wa": ("CPU % spent idle while waiting for disk I/O.",
           "Usually under 10%. It is averaged over all CPUs, so on a big server slow storage can show as only 1-2%. "
           "Low wa does not clear storage; judge that from iostat await."),
    "st": ("CPU % the hypervisor gave to other VMs while this VM wanted to run (VMs only).",
           "Should be near 0. Sustained values mean the host is overcommitted. "
           "Linux on VMware does not report steal; use CPU Ready in vCenter instead."),
    # AIX vmstat
    "sy_calls": ("System calls per second (AIX).", _WORKLOAD),
    "avm": ("Active virtual memory in 4 KB pages (AIX).",
            "Rises and falls with the workload. If it exceeds real memory the LPAR is paging."),
    "fre": ("Free real memory in 4 KB pages (AIX).",
            "AIX keeps this small on purpose. Low fre alone is not a problem; check pi and po."),
    "pi": ("Pages read in from paging space per second (AIX).",
           "Should be 0 or near 0. Sustained values mean the LPAR is short of memory."),
    "po": ("Pages written out to paging space per second (AIX).",
           "Should be 0. Any sustained paging out is a red flag for memory."),
    "fr": ("Pages freed by the page replacement daemon per second (AIX).",
           "Rises with memory pressure. Read it with sr."),
    "sr": ("Pages scanned by the page replacement daemon per second (AIX).",
           "Many pages scanned for each page freed means the system is working hard to find memory."),
    "pc": ("Physical processors consumed by this LPAR (AIX shared processor pool).",
           "Compare with the entitlement and the virtual processor count. "
           "Running above entitlement relies on spare capacity in the pool."),
    "ec": ("% of entitled processor capacity consumed (AIX).",
           "Can exceed 100% in an uncapped LPAR. Sustained values above 100% mean the LPAR depends on "
           "spare pool capacity that other LPARs may take back."),
})

_ECP_ONLY = "0 unless this server is an ECP application server."

# Seize columns (^mgstat docs). Only present when CollectResourceStats is enabled.
_SEIZE = {
    "Gbl": ("global", ""),
    "Rou": ("routine", ""),
    "Obj": ("object", ""),
    "BDB": ("BDB", " (undocumented)"),
}


def _seize_notes():
    notes = {}
    for key, (resource, tag) in _SEIZE.items():
        notes[f"{key}Sz"] = (
            f"Seizes per second on the {resource} resource{tag}: a process needed exclusive access to update it.",
            f"Rises with update load. Read it with p{key}Nsz.")
        notes[f"p{key}Nsz"] = (
            f"% of {resource} seizes where the process had to sleep and be woken (NSeize).",
            "Low is good. A high % means update contention that shows up as system CPU.")
        notes[f"p{key}Asz"] = (
            f"% of {resource} seizes satisfied after a short spin (ASeize).",
            "Normal on multi-CPU servers. Costs a little user CPU, no action needed.")
    return notes


MGSTAT_COLUMN_NOTES = _expand({
    "Glorefs": ("Global references per second. This is the main measure of IRIS database work.",
                "Compare against a normal day. The peak sets the busy period."),
    "RemGrefs": ("Global references sent to remote ECP servers per second.", _ECP_ONLY),
    "Total Glorefs": ("Local plus remote global references per second.",
                      "Total database work, wherever it is served from."),
    "GRratio": ("Ratio of local to remote global references.",
                "Only meaningful on ECP systems."),
    "Gloupds": ("Global updates (sets and kills) per second.",
                "Write workload. It drives journal and write daemon activity."),
    "RemGupds": ("Global updates sent to remote ECP servers per second.", _ECP_ONLY),
    "Rourefs": ("Routine (code) references per second.",
                "Rises and falls with application activity."),
    "RemRrefs": ("Routine references to remote ECP servers per second.", _ECP_ONLY),
    "PPGrefs": ("Process-private global references per second.",
                "Temporary per-process data. High values are normal for some apps."),
    "PPGupds": ("Process-private global updates per second.",
                "Temporary per-process data. High values are normal for some apps."),
    "PhyRds": ("Database blocks read from disk per second.",
               "Should be small next to Glorefs. If it rises, the cache may be too small or a large scan is running."),
    "Rdratio": ("Global references per physical read.",
                "Higher is better. A falling ratio means more reads are going to disk."),
    "PhyWrs": ("Database blocks written to disk per second.",
               "Bursts at each write daemon cycle (every 80 s, or sooner when busy) are normal."),
    "RouLaS": ("Routine loads and saves per second.",
               "Should be low. Sustained highs suggest the routine buffer is too small."),
    "RemRLaS": ("Remote routine loads and saves per second.", _ECP_ONLY),
    "RouCMs": ("Routine cache misses per second.",
               "Should be low. Highs suggest the routine buffer is too small."),
    **_seize_notes(),
    "WDQsz": ("Blocks queued for the write daemon.",
              "Should drain every cycle. A queue that keeps growing means storage can't keep up."),
    "WDtmpq": ("Updated blocks in IRISTEMP waiting to be written.",
               "Usually small. Large values mean heavy temporary-global activity."),
    "WDphase": ("Write daemon phase: 0 idle, 5 writing the WIJ, 7 committing WIJ and journal, 8 writing databases.",
                "Mostly 0. Staying in 5, 7 or 8 for long means write cycles are slow."),
    "WDpass": ("Write daemon cycles since startup (a running count).",
               "Climbs steadily. Flat stretches mean the write daemon stopped cycling."),
    "WIJwri": ("Write image journal (WIJ) writes per second, in 256 KB blocks.",
               "Bursts at each write cycle are normal."),
    "Jrnwrts": ("Journal blocks written per second (4 KB to 4 MB each).",
                "Rises and falls with Gloupds. Sustained highs need fast journal storage."),
    "IJUcnt": ("Jobs the write daemon is waiting for before it can continue the cycle.",
               "Normally 0. Non-zero means a job is holding up the write cycle."),
    "IJULock": ("Whether updates are locked out while the write daemon finalises the cycle.",
                "Normally 0. Frequent non-zero values mean write cycles are blocking users."),
    "ActECP": ("Active ECP connections.",
               "0 if ECP isn't used. Drops can mean disconnects."),
    "Addblk": ("Blocks added to this ECP client's cache per second.",
               "ECP clients only."),
    "PrgBufL": ("Blocks purged from this ECP client's cache because it ran short of global buffers.",
                "ECP clients only. A high rate means the client needs more global buffers."),
    "PrgSrvR": ("Blocks purged from this ECP client's cache at the ECP server's request.",
                "ECP clients only. Spikes mean cached data was changed on the server."),
    "BytSnt": ("ECP bytes sent per second.",
               "ECP only. Rises and falls with the remote workload."),
    "BytRcd": ("ECP bytes received per second.",
               "ECP only. Rises and falls with the remote workload."),
})

FREE_MEMORY_COLUMN_NOTES = _expand({
    "Memtotal": ("Total physical memory.",
                 "Should be flat. A change means the server was resized."),
    "used": ("Memory in use by processes and the kernel.",
             "IRIS global buffers, often in huge pages, count here, so high is normal. "
             "Watch for growth over time."),
    "free": ("Memory not used for anything.",
             "Low is normal on Linux because cache uses the spare memory. Check available instead."),
    "shared": ("Shared memory, such as tmpfs and shared segments.",
               "Usually stable. Huge-page shared memory may not show here."),
    "buf/cache": ("Memory used for filesystem cache.",
                  "High is normal, Linux gives it back when needed."),
    "available": ("Memory that can be given to new work without swapping.",
                  "This is the real headroom. A low or steadily falling value is a warning."),
    "swaptotal": ("Total swap space configured.",
                  "Should be flat."),
    "swapused": ("Swap in use.",
                 "A small flat value is often harmless. Steady growth means memory pressure."),
    "swapfree": ("Unused swap space.",
                 "Should stay close to swaptotal."),
})

_READ_LATENCY = ("IRIS wants about 1 ms or less for database reads. "
                 "Sustained highs during busy periods point to storage.")
_WRITE_LATENCY = ("Matters most on the journal and WIJ disks, where every transaction waits for the write. "
                  "IRIS wants about 1 ms or less there.")
_ANY_LATENCY = "IRIS wants about 1 ms or less for the database. Sustained highs during busy periods point to storage."
_MERGING = "Merging is normal for sequential I/O and needs no action."
_TRANSFER = "Large, steady transfers suggest scans, backups or copies."
_DEVICE_LOAD = "Overall load on this device. Compare with what the storage is rated for."
_BUSY = ("Useful for single disks. On SAN, NVMe or striped volumes, 100% doesn't mean full, "
         "so check latency instead.")

IOSTAT_COLUMN_NOTES = _expand({
    ("r/s", "read rps"): ("Reads per second.",
                          "Compare with this disk's role, for example database vs journal. "
                          "Spikes often line up with batch jobs or backups."),
    ("w/s", "write wps"): ("Writes per second.",
                           "Compare with this disk's role, for example database vs journal. "
                           "Spikes often line up with batch jobs or backups."),
    "Total IOPS": ("Reads plus writes per second.", _DEVICE_LOAD),
    ("rkB/s", "rMB/s", "rsec/s"): ("Data read per second.", _TRANSFER),
    ("wkB/s", "wMB/s", "wsec/s"): ("Data written per second.", _TRANSFER),
    ("rrqm/s", "wrqm/s"): ("Requests merged per second before being sent to the device.", _MERGING),
    ("%rrqm", "%wrqm"): ("% of requests that were merged.", _MERGING),
    "r_await": ("Average read latency, including time spent queued (ms).", _READ_LATENCY),
    "w_await": ("Average write latency, including time spent queued (ms).", _WRITE_LATENCY),
    "await": ("Average I/O latency (ms), from older iostat versions.", _ANY_LATENCY),
    ("aqu-sz", "avgqu-sz"): ("Average number of requests waiting at the device.",
                             "Low is normal. A growing queue together with rising await means the device is saturated."),
    ("rareq-sz", "wareq-sz"): ("Average request size (KB).",
                               "Small (8 KB) is typical for database blocks. "
                               "Large sizes mean sequential work such as backups."),
    "avgrq-sz": ("Average request size in 512-byte sectors (older iostat).",
                 "16 sectors = 8 KB, typical for database blocks. Large sizes mean sequential work such as backups."),
    "svctm": ("Average service time (ms). Deprecated and unreliable.",
              "Ignore it in favour of await."),
    "%util": ("% of time the device was busy.", _BUSY),
    ("d/s", "dkB/s", "drqm/s", "%drqm", "d_await", "dareq-sz"): (
        "Discard (TRIM) requests.", "Usually near 0."),
    ("f/s", "f_await"): ("Flush requests.",
                         "Usually near 0. Flush latency can matter for journal disks."),
    # AIX iostat -D
    "xfer tm act": ("% of time the disk was active (AIX).", _BUSY),
    "xfer bps": ("Bytes transferred per second (AIX).", _TRANSFER),
    "xfer tps": ("Transfers (I/O requests) per second (AIX).", _DEVICE_LOAD),
    "xfer bread": ("Bytes read per second (AIX).", _TRANSFER),
    "xfer bwrtn": ("Bytes written per second (AIX).", _TRANSFER),
    "read avg serv": ("Average read service time (ms).", _READ_LATENCY),
    "write avg serv": ("Average write service time (ms).", _WRITE_LATENCY),
    ("read min serv", "write min serv"): ("Best service time in the interval (ms).",
                                          "Shows what the device can do when lightly loaded. No action needed."),
    ("read max serv", "write max serv"): ("Worst service time in the interval (ms).",
                                          "Occasional spikes are normal. Frequent high peaks are not."),
    "queue avg time": ("Average time requests spend waiting in the queue (ms).",
                       "Should be near 0. Rising values mean the queue depth is too small or the device is saturated."),
    ("queue min time", "queue max time"): ("Shortest / longest queue wait in the interval (ms).",
                                           "An occasional high maximum is normal. Frequent high peaks mean the queue is backing up."),
    ("queue avg wqsz", "queue avg sqsz"): ("Average wait / service queue size.", "Low is normal."),
    "queue serv qfull": ("Times the service queue was full, per second.",
                         "Should be 0. Non-zero means the queue_depth setting is too low."),
    ("read time outs", "write time outs", "read fail", "write fail"): (
        "I/O timeouts and failures.", "Should be 0. Any value needs investigating."),
})


def column_note(notes, column):
    """Return a two-line footnote for column, or "" if there is no note."""
    note = notes.get(column)
    return f"{note[0]}\n{note[1]}" if note else ""
