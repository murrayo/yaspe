import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sp_check


def _html(tmp_path, cpf_lines):
    path = tmp_path / "sample.html"
    path.write_text("\n".join(["<html>", "[ConfigFile]", *cpf_lines, "<!-- beg_mgstat -->", "</html>"]) + "\n",
                    encoding="ISO-8859-1")
    return str(path)


def test_strip_cpf_comment_trailing():
    assert sp_check._strip_cpf_comment("gmheap=0 ;3145728\n") == "gmheap=0\n"


def test_strip_cpf_comment_whole_line():
    assert sp_check._strip_cpf_comment(";memlock=4\n").strip() == ""


def test_strip_cpf_comment_keeps_semicolon_inside_value():
    device = 'C-VT100=80^#,$C(27,91,72)^24^$C(8)^W $C(27,91)_(DY+1)_";"_(DX+1)_"H"\n'
    trx = "IdTrxFrom=~ `!@#$%^&*()_+-=[]\\{}|;':\",./<>?\n"
    assert sp_check._strip_cpf_comment(device) == device
    assert sp_check._strip_cpf_comment(trx) == trx


def test_system_check_ignores_cpf_comments(tmp_path):
    sp_dict = sp_check.system_check(_html(tmp_path, [
        "[config]",
        "gmheap=0 ;3145728",
        ";memlock=99",
        "memlock=4",
        "globals=0,0,8192,0,0,0  ; 8GB for 8k buffers",
    ]))
    assert sp_dict["gmheap"] == "0"
    assert sp_dict["memlock"] == "4"
    assert sp_dict["globals"] == "0,0,8192,0,0,0"
