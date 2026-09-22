import pytest

from tools.upstream import source_version


@pytest.mark.parametrize(
    ("value", "expected"),
    [("5.048 2026-04-26", "v5.048"), ("5.049 devel", "v5.049"), ("5.050", "v5.050")],
)
def test_parse_upstream_version_without_using_comment_examples(value, expected):
    text = f"#AC_INIT([Verilator],[0.000 devel])\nAC_INIT([Verilator],[{value}],\n [url])"
    assert source_version(text) == expected


def test_commented_version_is_not_a_declaration():
    with pytest.raises(ValueError, match="Cannot read Verilator version"):
        source_version("#AC_INIT([Verilator],[5.050 devel])")
