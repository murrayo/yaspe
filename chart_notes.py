"""Plain-language chart footnotes: what each metric is, and what to look for."""


def _expand(notes):
    out = {}
    for names, note in notes.items():
        for name in names if isinstance(names, tuple) else (names,):
            out[name] = note
    return out


VMSTAT_COLUMN_NOTES = _expand({
    "b": ("Processes blocked, usually waiting for disk I/O.",
          "Normally 0 or close to it. A steady non-zero value suggests storage is slow."),
    "swpd": ("Memory paged out to swap (KB).",
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
    "bi": ("Blocks read from disk per second.",
           "Compare to your normal workload. Spikes often line up with reports, backups or integrity checks."),
    "bo": ("Blocks written to disk per second.",
           "Regular spikes are normal (IRIS write daemon cycles). Look for sustained highs."),
    "in": ("Hardware interrupts per second.",
           "Tracks with disk and network activity. Look for sudden changes from the baseline."),
    "cs": ("Context switches per second.",
           "Tracks with workload. A big jump without more work can mean lock or scheduling contention."),
    "id": ("CPU idle %.",
           "Low idle for long periods means the CPU is close to capacity."),
    "wa": ("CPU % spent idle while waiting for disk I/O.",
           "Usually under 10%. Higher values suggest storage is the bottleneck."),
    "st": ("CPU % taken by the hypervisor (VMs only).",
           "Should be near 0. Sustained values mean the host is overcommitted."),
    "sy_calls": ("System calls per second (AIX).",
                 "Tracks with workload. Look for sudden changes from the baseline."),
})

_ECP_ONLY = "0 unless this is an ECP application server."

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
                "Tracks with application activity."),
    "RemRrefs": ("Routine references to remote servers per second.",
                 "0 unless routines are served over ECP."),
    "PPGrefs": ("Process-private global references per second.",
                "Temporary per-process data. High values are normal for some apps."),
    "PPGupds": ("Process-private global updates per second.",
                "Temporary per-process data. High values are normal for some apps."),
    "PhyRds": ("Database blocks read from disk per second.",
               "Should be small next to Glorefs. If it rises, the cache may be too small or a large scan is running."),
    "Rdratio": ("Global references per physical read.",
                "Higher is better. A falling ratio means more reads are going to disk."),
    "PhyWrs": ("Database blocks written to disk per second.",
               "Bursts at each write daemon cycle (about every 80s) are normal."),
    "RouLaS": ("Routine loads and saves per second.",
               "Should be low. Sustained highs suggest the routine buffer is too small."),
    "RemRLaS": ("Remote routine loads and saves per second.",
                "0 unless routines are served over ECP."),
    "RouCMs": ("Routine cache misses per second.",
               "Should be low. Highs suggest the routine buffer is too small."),
    "GblSz": ("Size of the global buffer pool (database cache).",
              "A flat line is normal. It only changes when the configuration changes."),
    "ObjSz": ("Size of the routine buffer pool.",
              "A flat line is normal. It only changes when the configuration changes."),
    "BDBSz": ("Size of the big-data buffer pool.",
              "A flat line is normal. It only changes when the configuration changes."),
    ("pGblNsz", "pObjNsz", "pBDBNsz"): ("% of the buffer pool in the newer part of the cache.",
                                         "Informational. Read it alongside Rdratio and PhyRds."),
    ("pGblAsz", "pObjAsz", "pBDBAsz"): ("% of the buffer pool in the aged part of the cache.",
                                         "Informational. Read it alongside Rdratio and PhyRds."),
    "WDQsz": ("Blocks queued for the write daemon.",
              "Should drain every cycle. A queue that keeps growing means storage can't keep up."),
    "WDtmpq": ("Blocks updated while a write cycle is in progress.",
               "Usually small. Large values mean heavy updates during flushes."),
    "WDphase": ("Current write daemon phase (0 = idle).",
                "Mostly 0. Staying non-zero for long means write cycles are slow."),
    "WDpass": ("Write daemon cycles completed.",
               "A steady rate is normal."),
    "WIJwri": ("Write image journal (WIJ) writes per second.",
               "Bursts at each write cycle are normal."),
    "Jrnwrts": ("Journal writes per second.",
                "Tracks with Gloupds. Sustained highs need fast journal storage."),
    "IJUcnt": ("Jobs waiting on the write daemon to accept updates.",
               "Normally 0. Non-zero values mean updates are being held up."),
    "IJULock": ("Whether updates are paused for the write daemon.",
                "Normally 0. Frequent non-zero values mean write cycles are blocking users."),
    "ActECP": ("Active ECP connections.",
               "0 if ECP isn't used. Drops can mean disconnects."),
    "Addblk": ("Blocks added to the ECP client cache per second.",
               "ECP clients only."),
    "PrgBufL": ("ECP cache purges made locally, per second.",
                "ECP clients only. Spikes mean cached data is being invalidated."),
    "PrgSrvR": ("ECP cache purges requested by the server, per second.",
                "ECP clients only. Spikes mean cached data is being invalidated."),
    "BytSnt": ("ECP bytes sent per second.",
               "ECP only. Tracks with remote workload."),
    "BytRcd": ("ECP bytes received per second.",
               "ECP only. Tracks with remote workload."),
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

_IRIS_LATENCY = "IRIS wants about 1 ms or less for the database. Sustained highs during busy periods point to storage."

IOSTAT_COLUMN_NOTES = _expand({
    ("r/s", "read rps"): ("Reads per second.",
                          "Compare with this disk's role, for example database vs journal. "
                          "Spikes often line up with batch jobs or backups."),
    ("w/s", "write wps"): ("Writes per second.",
                           "Compare with this disk's role, for example database vs journal. "
                           "Spikes often line up with batch jobs or backups."),
    "Total IOPS": ("Reads plus writes per second.",
                   "Overall load on this device. Compare with what the storage is rated for."),
    ("rkB/s", "rMB/s", "rsec/s"): ("Data read per second.",
                                   "Large, steady transfers suggest scans, backups or copies."),
    ("wkB/s", "wMB/s", "wsec/s"): ("Data written per second.",
                                   "Large, steady transfers suggest scans, backups or copies."),
    ("rrqm/s", "wrqm/s"): ("Requests merged per second before being sent to the device.",
                           "Informational. Merging is normal for sequential I/O."),
    ("%rrqm", "%wrqm"): ("% of requests that were merged.", "Informational."),
    "r_await": ("Average read latency, including time spent queued (ms).", _IRIS_LATENCY),
    "w_await": ("Average write latency, including time spent queued (ms).", _IRIS_LATENCY),
    "await": ("Average I/O latency (ms), from older iostat versions.", _IRIS_LATENCY),
    ("aqu-sz", "avgqu-sz"): ("Average number of requests waiting at the device.",
                             "Low is normal. A growing queue together with rising await means the device is saturated."),
    ("rareq-sz", "wareq-sz", "avgrq-sz"): ("Average request size.",
                                           "Small (8 KB) is typical for database blocks. "
                                           "Large sizes mean sequential work such as backups."),
    "svctm": ("Average service time (ms). Deprecated and unreliable.",
              "Ignore it in favour of await."),
    "%util": ("% of time the device was busy.",
              "Useful for single disks. On SAN, NVMe or striped volumes, 100% doesn't mean full, "
              "so check await instead."),
    ("d/s", "dkB/s", "drqm/s", "%drqm", "d_await", "dareq-sz"): (
        "Discard (TRIM) requests.", "Usually near 0."),
    ("f/s", "f_await"): ("Flush requests.",
                         "Usually near 0. Flush latency can matter for journal disks."),
    "read avg serv": ("Average read service time (ms).", _IRIS_LATENCY),
    "write avg serv": ("Average write service time (ms).", _IRIS_LATENCY),
    ("read max serv", "write max serv"): ("Worst service time in the interval (ms).",
                                          "Occasional spikes are normal. Frequent high peaks are not."),
    "queue avg time": ("Average time requests spend waiting in the queue (ms).",
                       "Should be near 0. Rising values mean the queue depth is too small or the device is saturated."),
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
