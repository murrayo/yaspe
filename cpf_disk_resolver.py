# cpf_disk_resolver.py
import re


def _build_mapper_map(sp_dict):
    """Parse 'dev mapper N' entries → {mapper_name: dm_device}."""
    mapper_map = {}
    for key, value in sp_dict.items():
        if not key.startswith("dev mapper "):
            continue
        # e.g. "lrwxrwxrwx 1 root root  7 May  8 vgdb-lvdb -> ../dm-2"
        m = re.search(r"(\S+)\s+->\s+\.\./(\S+)", value)
        if m:
            mapper_map[m.group(1)] = m.group(2)
    return mapper_map


def _build_mount_map(sp_dict, mapper_sp_dict):
    """
    Parse 'filesystem df N' entries → {mount_point: iostat_device_name}.

    sp_dict contains the 'filesystem df N' entries.
    mapper_sp_dict contains the 'dev mapper N' entries (raw sp_dict format);
    _build_mapper_map is called internally to resolve mapper names to dm devices.

    Includes /dev/mapper/* (resolved via mapper_sp_dict → dm-N) and bare
    /dev/<name>[digit] (stripped to base device name e.g. sdb).
    Excludes NFS, tmpfs, devtmpfs, and other non-/dev/ entries.
    Skips the header row (filesystem df 0).
    """
    mapper_map = _build_mapper_map(mapper_sp_dict)
    mount_map = {}
    for key, value in sp_dict.items():
        if not key.startswith("filesystem df "):
            continue
        if key == "filesystem df 0":
            continue
        parts = value.split()
        if len(parts) < 2:
            continue
        device_field = parts[0]
        mount_point = parts[-1]
        if not device_field.startswith("/dev/"):
            continue
        if device_field.startswith("/dev/mapper/"):
            mapper_name = device_field[len("/dev/mapper/"):]
            dm_device = mapper_map.get(mapper_name)
            if dm_device:
                mount_map[mount_point] = dm_device
        else:
            # e.g. /dev/sdb1 → sdb, /dev/nvme0n1p1 → nvme0n1
            bare = device_field[len("/dev/"):]
            if bare.startswith("nvme"):
                # NVMe partition suffix is pN; strip it but keep nN namespace
                bare = re.sub(r"p\d+$", "", bare)
            else:
                if not bare.startswith("dm-"):
                    bare = re.sub(r"\d+$", "", bare)
            if bare:
                mount_map[mount_point] = bare
    return mount_map


def _path_to_device(path, mount_map):
    """
    Return the iostat device name for the given directory path by
    finding the longest matching mount point. Returns None if no match.
    """
    if not path:
        return None
    best_mount = None
    best_len = -1
    for mount_point in mount_map:
        if (path == mount_point or path.startswith(mount_point.rstrip("/") + "/")) and len(mount_point) > best_len:
            best_mount = mount_point
            best_len = len(mount_point)
    if best_mount is None:
        return None
    return mount_map[best_mount]


def resolve_iris_disk_roles(sp_dict):
    """
    Resolve IRIS storage roles to iostat device names.

    Returns dict with keys "Database", "Primary Journal",
    "Alternate Journal", "WIJ".
    - "Database" is list[tuple[str, list[str]]] — list of (device, db_names) pairs, empty if none.
    - Other roles are iostat device name strings (e.g. "dm-2", "sdb") or None if unresolved.
    """
    mount_map = _build_mount_map(sp_dict, sp_dict)

    roles = {
        "Database": [],          # list[tuple[str, list[str]]]
        "Primary Journal": None,
        "Alternate Journal": None,
        "WIJ": None,
    }

    # Database: group local (non-mirror) paths by device, preserving insertion order
    cpf_databases = sp_dict.get("cpf_databases", [])
    # ordered dict: device → [db_names]
    device_names_map = {}
    for name, path in cpf_databases:
        clean_path = path.split(",,")[0]
        if clean_path.startswith(":mirror:"):
            continue
        device = _path_to_device(clean_path, mount_map)
        if device:
            if device not in device_names_map:
                device_names_map[device] = []
            device_names_map[device].append(name)

    if len(device_names_map) > 1:
        print(f"  Note: databases span multiple devices: {list(device_names_map.keys())}")

    roles["Database"] = list(device_names_map.items())  # [(device, [names]), ...]

    # Journal roles
    roles["Primary Journal"] = _path_to_device(
        sp_dict.get("current journal"), mount_map
    )
    roles["Alternate Journal"] = _path_to_device(
        sp_dict.get("alternate journal"), mount_map
    )

    # WIJ: empty string means installation directory — skip
    wijdir = sp_dict.get("wijdir", "")
    if wijdir:
        roles["WIJ"] = _path_to_device(wijdir, mount_map)

    return roles
