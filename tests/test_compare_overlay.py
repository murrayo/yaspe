import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
