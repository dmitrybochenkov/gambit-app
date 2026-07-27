import pytest

from app.common.normalization import normalize_display_name


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  Дима   Боченков ", "дима боченков"),
        ("Дима\t\nБоченков", "дима боченков"),
        ("ACE", "ace"),
        ("Ёж", "еж"),
        ("Еж", "еж"),
        ("", None),
        ("   ", None),
        (None, None),
        ("Troy ACE", "troy ace"),
        ("Дима Troy  Ёж", "дима troy еж"),
    ],
)
def test_normalize_display_name(value: str | None, expected: str | None) -> None:
    assert normalize_display_name(value) == expected
