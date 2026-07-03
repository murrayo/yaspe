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


def test_resolve_database_role():
    result = cdr.resolve_iris_disk_roles(_full_sp_dict())
    assert result["Database"] == "dm-2"


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
    # Only mirror databases → Database role is None
    sp = {}
    sp.update(_mapper_sp_dict())
    sp.update(_df_sp_dict())
    sp["cpf_databases"] = [("TRAK-LABDATA", ":mirror:PRDLAB:TRAK-LABDATA,PRDLAB")]
    sp["current journal"] = "/trak/live/tc/prijrn/"
    sp["alternate journal"] = "/trak/live/tc/altjrn/"
    sp["wijdir"] = ""
    result = cdr.resolve_iris_disk_roles(sp)
    assert result["Database"] is None


def test_resolve_no_cpf_databases_key():
    sp = {}
    sp.update(_mapper_sp_dict())
    sp.update(_df_sp_dict())
    sp["current journal"] = "/trak/live/tc/prijrn/"
    sp["alternate journal"] = "/trak/live/tc/altjrn/"
    sp["wijdir"] = ""
    result = cdr.resolve_iris_disk_roles(sp)
    assert result["Database"] is None


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
