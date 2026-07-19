import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yaspe_utilities import get_number_type, get_aix_wacky_numbers


def test_int_passthrough():
    assert get_number_type("134") == 134
    assert isinstance(get_number_type("134"), int)


def test_plain_float():
    assert get_number_type("0.56") == 0.56
    assert isinstance(get_number_type("0.56"), float)


def test_locale_grouped_float():
    # float() rejects this; locale.atof (en_US) must still handle it
    assert get_number_type("1,035.70") == 1035.70


def test_non_numeric_string_unchanged():
    assert get_number_type("sda") == "sda"
    assert get_number_type("") == ""


def test_none_passthrough():
    assert get_number_type(None) is None


def test_negative_and_exponent():
    assert get_number_type("-3.5") == -3.5
    assert get_number_type("1e3") == 1000.0


def test_no_per_call_setlocale():
    # setlocale must not be called inside get_number_type (that was the
    # 55-second bug: 23.6M setlocale calls per file).
    import inspect
    import yaspe_utilities
    src = inspect.getsource(yaspe_utilities.get_number_type)
    assert "setlocale" not in src


def test_aix_wacky_numbers():
    assert get_aix_wacky_numbers("13") == 13
    assert get_aix_wacky_numbers("65.5K") == 65500
    assert get_aix_wacky_numbers("4.2M") == 4200000
    assert get_aix_wacky_numbers("1.5S") == 1500
    assert get_aix_wacky_numbers("0.6") == 0.6
    assert get_aix_wacky_numbers("hdisk0") == "hdisk0"
