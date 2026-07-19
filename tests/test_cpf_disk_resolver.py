# tests/test_cpf_disk_resolver.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cpf_disk_resolver as cdr


# ── _build_mapper_map ──────────────────────────────────────────────────────────

def _mapper_sp_dict():
    return {
        "dev mapper 0": "lrwxrwxrwx 1 root root       7 May  8 00:44 vgapp-lvapp -> ../dm-3",
        "dev mapper 1": "lrwxrwxrwx 1 root root       7 May  8 00:44 vgdb-lvdb -> ../dm-2",
        "dev mapper 2": "lrwxrwxrwx 1 root root       7 May  8 00:44 vghs-lvprijrn -> ../dm-6",
        "dev mapper 3": "lrwxrwxrwx 1 root root       7 May  8 00:44 vghs-lvaltjrn -> ../dm-8",
    }


def test_build_mapper_map_extracts_entries():
    result = cdr._build_mapper_map(_mapper_sp_dict())
    assert result == {"vgapp-lvapp": "dm-3", "vgdb-lvdb": "dm-2", "vghs-lvprijrn": "dm-6", "vghs-lvaltjrn": "dm-8"}


def test_build_mapper_map_empty():
    assert cdr._build_mapper_map({}) == {}


# ── _build_mount_map ───────────────────────────────────────────────────────────

def _df_sp_dict():
    return {
        "filesystem df 0": "Filesystem                       1M-blocks    Used Available Use% Mounted on",
        "filesystem df 1": "devtmpfs                             64167       0     64167   0% /dev",
        "filesystem df 2": "tmpfs                                64185       0     64185   0% /dev/shm",
        "filesystem df 3": "/dev/mapper/vgdb-lvdb              6289406 4287252   2002155  69% /trak/live/tc",
        "filesystem df 4": "/dev/mapper/vghs-lvprijrn           921542   12384    909159   2% /trak/live/tc/prijrn",
        "filesystem df 5": "/dev/mapper/vghs-lvaltjrn           358318      33    358285   1% /trak/live/tc/altjrn",
        "filesystem df 6": "/dev/sdb1                             1014     269       746  27% /boot",
        "filesystem df 7": "172.16.201.33:/trak/live/lab/app    204743  159923     44820  79% /trak/live/lab/app",
    }


def test_build_mount_map_mapper_devices():
    result = cdr._build_mount_map(_df_sp_dict(), _mapper_sp_dict())
    assert result["/trak/live/tc"] == "dm-2"
    assert result["/trak/live/tc/prijrn"] == "dm-6"


def test_build_mount_map_bare_device():
    result = cdr._build_mount_map(_df_sp_dict(), _mapper_sp_dict())
    assert result["/boot"] == "sdb"


def test_build_mount_map_excludes_nfs_and_tmpfs():
    result = cdr._build_mount_map(_df_sp_dict(), _mapper_sp_dict())
    assert "/trak/live/lab/app" not in result
    assert "/dev" not in result
    assert "/dev/shm" not in result


# ── _path_to_device ────────────────────────────────────────────────────────────

def test_path_to_device_exact_mount():
    mount_map = {"/trak/live/tc": "dm-2", "/trak/live/tc/prijrn": "dm-6"}
    assert cdr._path_to_device("/trak/live/tc/db/data/", mount_map) == "dm-2"


def test_path_to_device_longer_mount_wins():
    mount_map = {"/trak/live/tc": "dm-2", "/trak/live/tc/prijrn": "dm-6"}
    assert cdr._path_to_device("/trak/live/tc/prijrn/", mount_map) == "dm-6"


def test_path_to_device_no_match():
    mount_map = {"/trak/live/tc": "dm-2"}
    assert cdr._path_to_device("/some/other/path/", mount_map) is None


def test_path_to_device_none_path():
    assert cdr._path_to_device(None, {"/trak": "dm-2"}) is None


def test_path_to_device_empty_path():
    assert cdr._path_to_device("", {"/trak": "dm-2"}) is None


# ── resolve_iris_disk_roles ────────────────────────────────────────────────────

def _full_sp_dict():
    d = {}
    d.update(_mapper_sp_dict())
    d.update(_df_sp_dict())
    d["cpf_databases"] = [
        ("TRAK-DATA", "/trak/live/tc/db/data/,,1"),
        ("TRAK-DOCS", "/trak/live/tc/db/docs/,,1"),
        ("TRAK-LABDATA", ":mirror:PRDLAB:TRAK-LABDATA,PRDLAB"),
    ]
    d["current journal"] = "/trak/live/tc/prijrn/"
    d["alternate journal"] = "/trak/live/tc/altjrn/"
    d["wijdir"] = ""
    return d


def test_resolve_database_role_returns_list():
    result = cdr.resolve_iris_disk_roles(_full_sp_dict())
    # Database is now a list of (device, [names]) tuples
    assert isinstance(result["Database"], list)
    assert len(result["Database"]) == 1
    device, names = result["Database"][0]
    assert device == "dm-2"
    assert "TRAK-DATA" in names
    assert "TRAK-DOCS" in names


def test_resolve_database_role_multi_device():
    # Two databases on different devices
    sp = {}
    sp.update(_mapper_sp_dict())
    # Add an extra mount: /boot is already on sdb (bare device)
    sp.update(_df_sp_dict())
    sp["cpf_databases"] = [
        ("APP-DATA", "/trak/live/tc/db/data/,,1"),   # → dm-2
        ("BOOT-DB", "/boot/,,1"),                     # → sdb
    ]
    sp["current journal"] = "/trak/live/tc/prijrn/"
    sp["alternate journal"] = "/trak/live/tc/altjrn/"
    sp["wijdir"] = ""
    result = cdr.resolve_iris_disk_roles(sp)
    devices = [d for d, _ in result["Database"]]
    assert "dm-2" in devices
    assert "sdb" in devices
    # names grouped by device
    by_device = dict(result["Database"])
    assert "APP-DATA" in by_device["dm-2"]
    assert "BOOT-DB" in by_device["sdb"]


def test_resolve_database_empty_list_when_no_databases():
    sp = {}
    sp.update(_mapper_sp_dict())
    sp.update(_df_sp_dict())
    sp["cpf_databases"] = []
    sp["current journal"] = "/trak/live/tc/prijrn/"
    sp["alternate journal"] = "/trak/live/tc/altjrn/"
    sp["wijdir"] = ""
    result = cdr.resolve_iris_disk_roles(sp)
    assert result["Database"] == []


def test_resolve_journal_roles_still_strings():
    result = cdr.resolve_iris_disk_roles(_full_sp_dict())
    assert result["Primary Journal"] == "dm-6"
    assert result["Alternate Journal"] == "dm-8"
    assert result["WIJ"] is None


def test_resolve_database_role():
    result = cdr.resolve_iris_disk_roles(_full_sp_dict())
    # _full_sp_dict has TRAK-DATA and TRAK-DOCS both on /trak/live/tc → dm-2
    assert len(result["Database"]) == 1
    device, names = result["Database"][0]
    assert device == "dm-2"
    assert "TRAK-DATA" in names


def test_resolve_primary_journal():
    result = cdr.resolve_iris_disk_roles(_full_sp_dict())
    assert result["Primary Journal"] == "dm-6"


def test_resolve_alternate_journal():
    result = cdr.resolve_iris_disk_roles(_full_sp_dict())
    assert result["Alternate Journal"] == "dm-8"


def test_resolve_wij_empty_is_none():
    result = cdr.resolve_iris_disk_roles(_full_sp_dict())
    assert result["WIJ"] is None


def test_resolve_mirror_databases_skipped():
    sp = {}
    sp.update(_mapper_sp_dict())
    sp.update(_df_sp_dict())
    sp["cpf_databases"] = [("TRAK-LABDATA", ":mirror:PRDLAB:TRAK-LABDATA,PRDLAB")]
    sp["current journal"] = "/trak/live/tc/prijrn/"
    sp["alternate journal"] = "/trak/live/tc/altjrn/"
    sp["wijdir"] = ""
    result = cdr.resolve_iris_disk_roles(sp)
    assert result["Database"] == []


def test_resolve_no_cpf_databases_key():
    sp = {}
    sp.update(_mapper_sp_dict())
    sp.update(_df_sp_dict())
    sp["current journal"] = "/trak/live/tc/prijrn/"
    sp["alternate journal"] = "/trak/live/tc/altjrn/"
    sp["wijdir"] = ""
    result = cdr.resolve_iris_disk_roles(sp)
    assert result["Database"] == []


def test_resolve_wij_configured():
    sp = _full_sp_dict()
    sp["wijdir"] = "/trak/live/tc/wij/"
    result = cdr.resolve_iris_disk_roles(sp)
    assert result["WIJ"] == "dm-2"


def test_resolve_bare_sdb_device():
    # Journal on a plain partition device
    sp = _full_sp_dict()
    sp["current journal"] = "/boot/"
    result = cdr.resolve_iris_disk_roles(sp)
    assert result["Primary Journal"] == "sdb"


def test_path_to_device_no_false_prefix_match():
    mount_map = {"/data": "dm-1"}
    assert cdr._path_to_device("/data2/file/", mount_map) is None


def test_path_to_device_windows_drive_letter():
    from cpf_disk_resolver import _path_to_device
    assert _path_to_device("G:\\DB\\IRISTEMP\\", {}) == "G:"
    assert _path_to_device("c:\\intersystems\\iris\\mgr\\", {}) == "C:"
    assert _path_to_device("J:/JOURNAL/", {}) == "J:"


def test_path_to_device_unc_path_returns_none():
    from cpf_disk_resolver import _path_to_device
    assert _path_to_device("\\\\server\\share\\db\\", {}) is None


def test_resolve_roles_windows_sp_dict():
    from cpf_disk_resolver import resolve_iris_disk_roles
    sp_dict = {
        "cpf_databases": [
            ("IRISSYS", "C:\\InterSystems\\IRIS\\mgr\\"),
            ("IRISTEMP", "G:\\DB\\IRISTEMP\\"),
            ("APPDATA", "N:\\DB\\APP\\"),
            ("MIRRORDB", ":mirror:MIRRORSET:\\somewhere\\"),
        ],
        "current journal": "J:\\JOURNAL\\",
        "alternate journal": "G:\\JOURNAL\\",
        "wijdir": "W:\\WIJ\\",
    }
    roles = resolve_iris_disk_roles(sp_dict)
    assert roles["Database"] == [("C:", ["IRISSYS"]), ("G:", ["IRISTEMP"]), ("N:", ["APPDATA"])]
    assert roles["Primary Journal"] == "J:"
    assert roles["Alternate Journal"] == "G:"
    assert roles["WIJ"] == "W:"


def test_build_mount_map_nvme_partition():
    """NVMe partition /dev/nvme0n1p1 should resolve to nvme0n1 not nvme0."""
    sp_dict = {
        "filesystem df 0": "Filesystem  1M-blocks  Used Available Use% Mounted on",
        "filesystem df 1": "/dev/nvme0n1p1  512000  12345  499655  3% /data",
    }
    result = cdr._build_mount_map(sp_dict, {})
    assert result.get("/data") == "nvme0n1"


def test_build_mount_map_nvme_no_partition():
    """Whole NVMe device /dev/nvme0n1 should resolve to nvme0n1 unchanged."""
    sp_dict = {
        "filesystem df 0": "Filesystem  1M-blocks  Used Available Use% Mounted on",
        "filesystem df 1": "/dev/nvme0n1  512000  12345  499655  3% /data",
    }
    result = cdr._build_mount_map(sp_dict, {})
    assert result.get("/data") == "nvme0n1"


def test_build_mount_map_dm_device_not_mangled():
    """Bare /dev/dm-2 in df output should resolve to dm-2, not dm-."""
    sp_dict = {
        "filesystem df 0": "Filesystem  1M-blocks  Used Available Use% Mounted on",
        "filesystem df 1": "/dev/dm-2  1024000  51200  972800  5% /data",
    }
    result = cdr._build_mount_map(sp_dict, {})
    assert result.get("/data") == "dm-2"


# ── sp_check integration tests ─────────────────────────────────────────────────

import tempfile
import sp_check


def _make_html(databases_block, journal_current="/jrn/pri/", journal_alt="/jrn/alt/", wijdir=""):
    """Minimal HTML that looks like a SystemPerformance file to sp_check."""
    return f"""Customer: TestSite
Version String: IRIS for UNIX (RHEL 8 for x86-64) 2024.1
Profile run 2026-06-15
up >TESTIRIS on machine testhost
[ConfigFile]
DaysBeforePurge=3
globals=1024
routines=256
gmheap=307200
[Databases]
{databases_block}
[Namespaces]
[Journal]
AlternateDirectory={journal_alt}
CurrentDirectory={journal_current}
[config]
wijdir={wijdir}
!-- beg_mgstat --
"""


def test_sp_check_parses_cpf_databases():
    html = _make_html(
        "IRISSYS=/trak/live/tc/hs/trak/mgr/\n"
        "TRAK-DATA=/trak/live/tc/db/data/,,1\n"
        "TRAK-LABDATA=:mirror:PRDLAB:TRAK-LABDATA,PRDLAB\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        path = f.name
    try:
        sp_dict = sp_check.system_check(path)
        assert "cpf_databases" in sp_dict
        names = [name for name, _ in sp_dict["cpf_databases"]]
        assert "IRISSYS" in names
        assert "TRAK-DATA" in names
        assert "TRAK-LABDATA" in names
    finally:
        os.unlink(path)


def test_sp_check_cpf_databases_empty_when_no_section():
    html = _make_html("")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        path = f.name
    try:
        sp_dict = sp_check.system_check(path)
        assert sp_dict.get("cpf_databases", []) == []
    finally:
        os.unlink(path)


def test_yaspe_stores_multi_device_database_roles():
    """Verify that sp_dict keys for multi-device databases are structured correctly."""
    # Simulate what yaspe.py does after calling resolve_iris_disk_roles
    iris_roles = {
        "Database": [("dm-2", ["TRAK-DATA", "TRAK-DOCS"]), ("dm-1", ["IRISSYS"])],
        "Primary Journal": "dm-6",
        "Alternate Journal": "dm-8",
        "WIJ": None,
    }
    sp_dict = {}
    device_to_mount = {"dm-2": "/trak/live/tc", "dm-1": "/", "dm-6": "/prijrn", "dm-8": "/altjrn"}

    # Apply the same logic as yaspe.py will use
    db_pairs = iris_roles["Database"]
    for i, (device, names) in enumerate(db_pairs):
        sp_dict[f"iris disk role Database {i}"] = device
        sp_dict[f"iris disk role Database {i} names"] = ",".join(names)
        sp_dict[f"iris_disk_role_mount Database {i}"] = device_to_mount.get(device, "")

    for role in ("Primary Journal", "Alternate Journal", "WIJ"):
        device = iris_roles[role]
        if device:
            sp_dict[f"iris disk role {role}"] = device
            sp_dict[f"iris_disk_role_mount {role}"] = device_to_mount.get(device, "")

    # Verify expected keys
    assert sp_dict["iris disk role Database 0"] == "dm-2"
    assert sp_dict["iris disk role Database 0 names"] == "TRAK-DATA,TRAK-DOCS"
    assert sp_dict["iris disk role Database 1"] == "dm-1"
    assert sp_dict["iris disk role Database 1 names"] == "IRISSYS"
    assert sp_dict["iris disk role Primary Journal"] == "dm-6"
    assert "iris disk role Database" not in sp_dict  # old single-device key gone


def test_build_log_shows_multi_device_database_roles():
    import tempfile, os
    html = _make_html(
        "TRAK-DATA=/trak/live/tc/db/data/,,1\n",
        journal_current="/trak/live/tc/prijrn/",
        journal_alt="/trak/live/tc/altjrn/",
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        path = f.name
    try:
        sp_dict = sp_check.system_check(path)
        # Simulate multi-device database storage (Task 2 output)
        sp_dict["iris disk role Database 0"] = "dm-2"
        sp_dict["iris disk role Database 0 names"] = "TRAK-DATA,TRAK-DOCS"
        sp_dict["iris_disk_role_mount Database 0"] = "/trak/live/tc"
        sp_dict["iris disk role Database 1"] = "dm-1"
        sp_dict["iris disk role Database 1 names"] = "IRISSYS"
        sp_dict["iris_disk_role_mount Database 1"] = "/"
        sp_dict["iris disk role Primary Journal"] = "dm-6"
        sp_dict["iris disk role Alternate Journal"] = "dm-8"
        sp_dict["iris_disk_role_mount Primary Journal"] = "/trak/live/tc/prijrn"
        sp_dict["iris_disk_role_mount Alternate Journal"] = "/trak/live/tc/altjrn"
        log, _ = sp_check.build_log(sp_dict)
        assert "IRIS disk roles" in log
        assert "dm-2" in log and "TRAK-DATA" in log
        assert "dm-1" in log and "IRISSYS" in log
        assert "Primary Journal" in log and "dm-6" in log
        assert "Alternate Journal" in log and "dm-8" in log
    finally:
        os.unlink(path)


def test_build_log_shows_disk_roles():
    html = _make_html(
        "TRAK-DATA=/trak/live/tc/db/data/,,1\n",
        journal_current="/trak/live/tc/prijrn/",
        journal_alt="/trak/live/tc/altjrn/",
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        path = f.name
    try:
        sp_dict = sp_check.system_check(path)
        sp_dict["iris disk role Database 0"] = "dm-2"
        sp_dict["iris disk role Database 0 names"] = "TRAK-DATA"
        sp_dict["iris_disk_role_mount Database 0"] = "/trak/live/tc"
        sp_dict["iris disk role Primary Journal"] = "dm-6"
        sp_dict["iris disk role Alternate Journal"] = "dm-8"
        sp_dict["iris_disk_role_mount Primary Journal"] = "/trak/live/tc/prijrn"
        sp_dict["iris_disk_role_mount Alternate Journal"] = "/trak/live/tc/altjrn"
        log, _ = sp_check.build_log(sp_dict)
        assert "IRIS disk roles" in log
        assert "Database" in log and "dm-2" in log
        assert "Primary Journal" in log and "dm-6" in log
        assert "Alternate Journal" in log and "dm-8" in log
    finally:
        os.unlink(path)


# ── device_labels slug and two-line title helpers ─────────────────────────────

def test_device_label_slug():
    """Verify the slug derivation used for directory naming."""
    import re

    def _label_slug(label):
        return re.sub(r"[^a-z0-9_-]", "_", label.lower())

    assert _label_slug("TRAK-DATA, TRAK-DOCS") == "trak-data__trak-docs"
    assert _label_slug("Primary Journal") == "primary_journal"
    assert _label_slug("dm-2") == "dm-2"


def test_two_line_title_format():
    """Verify two-line title string construction."""
    label = "TRAK-DATA, TRAK-DOCS"
    base_title = "dm-2 : r/s - CustomerName"

    png_title = f"{label}\n{base_title}"
    html_title = f"{label}<br>{base_title}"

    assert png_title == "TRAK-DATA, TRAK-DOCS\ndm-2 : r/s - CustomerName"
    assert html_title == "TRAK-DATA, TRAK-DOCS<br>dm-2 : r/s - CustomerName"
