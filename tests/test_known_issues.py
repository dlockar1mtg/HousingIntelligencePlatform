"""Issues found in the migration review (docs/MODEL_LIMITATIONS.md). They are kept as V10 behaves on purpose,
so the baseline reproduces; each test is marked xfail(strict) and must be flipped when V11 fixes it."""
import pytest

from data_sources.local_files import market_from_text


@pytest.mark.xfail(strict=True, reason="V10 alias matching pulls unrelated metros into the composites (fix in V11)")
def test_alias_matching_maps_only_the_real_metros():
    for name in ("Huntsville, AL", "Fort Collins, CO", "Johnson City, TN", "Parkersburg, WV", "Wichita Falls, TX"):
        assert market_from_text(name) is None, name


def test_the_real_metros_are_matched():
    assert market_from_text("Dallas-Fort Worth-Arlington, TX") == "DFW Composite"
    assert market_from_text("Wichita, KS") == "Wichita Composite"
