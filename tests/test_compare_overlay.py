import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import yaspe_compare_overlay as yco


def test_extract_instance_name_from_html():
    html = """
    Instance Name     Version ID        Port   Directory
    ----------------  ----------------  -----  --------------------------------
up >MCMELIVETCC       2024.1.1.347.0.2  56772  /trak/mcme/live/tc/hs
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(html)
        path = f.name
    try:
        assert yco._extract_instance_name(path) == "MCMELIVETCC"
    finally:
        os.unlink(path)


def test_extract_instance_name_fallback():
    html = "<html><body>no instance here</body></html>"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False,
                                     prefix="MY_SERVER_") as f:
        f.write(html)
        path = f.name
    try:
        result = yco._extract_instance_name(path)
        assert result == os.path.splitext(os.path.basename(path))[0]
    finally:
        os.unlink(path)


def test_normalise_to_timeofday():
    ts = pd.Timestamp("2026-02-12 14:30:00")
    result = yco._normalise_to_timeofday(ts)
    assert result == pd.Timestamp("2000-01-01 14:30:00")


def test_normalise_preserves_seconds():
    ts = pd.Timestamp("2026-03-31 00:01:30")
    result = yco._normalise_to_timeofday(ts)
    assert result == pd.Timestamp("2000-01-01 00:01:30")


def test_load_dataframes_returns_empty_for_missing_tables():
    import tempfile, sqlite3 as sql
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    try:
        conn = sql.connect(db_path)
        conn.close()
        mgstat_df, vmstat_df = yco._load_dataframes(db_path)
        assert mgstat_df.empty
        assert vmstat_df.empty
    finally:
        os.unlink(db_path)


def test_load_dataframes_reads_tables():
    import tempfile, sqlite3 as sql
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    try:
        conn = sql.connect(db_path)
        conn.execute(
            "CREATE TABLE mgstat (id INTEGER PRIMARY KEY, DateTime TEXT, metric REAL)"
        )
        conn.execute(
            "INSERT INTO mgstat VALUES (1, '2026-02-12 10:00:00', 42.0)"
        )
        conn.commit()
        conn.close()

        mgstat_df, vmstat_df = yco._load_dataframes(db_path)
        assert len(mgstat_df) == 1
        assert vmstat_df.empty
    finally:
        os.unlink(db_path)
