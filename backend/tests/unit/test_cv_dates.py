import pytest

from app.cv.dates import find_date_range

pytestmark = pytest.mark.feature("cv-parsing")

YM = tuple[int, int | None] | None


def _ym(value: object) -> YM:
    if value is None:
        return None
    return (value.year, value.month)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("text", "start", "end", "current"),
    [
        ("Jan 2022 – Present", (2022, 1), None, True),
        ("January 2021 - March 2023", (2021, 1), (2023, 3), False),
        ("Sep 2019 to Dec 2021", (2019, 9), (2021, 12), False),
        ("Sept. 2019 — Dec. 2021", (2019, 9), (2021, 12), False),
        ("01/2020 – 12/2021", (2020, 1), (2021, 12), False),
        ("2020-03 - 2021-07", (2020, 3), (2021, 7), False),
        ("2017 – 2019", (2017, None), (2019, None), False),
        ("2020 - now", (2020, None), None, True),
        ("Since June 2023", (2023, 6), None, True),
        ("janv. 2021 – aujourd'hui", (2021, 1), None, True),
        ("mars 2019 – déc. 2020", (2019, 3), (2020, 12), False),
        ("septembre 2018 à juin 2020", (2018, 9), (2020, 6), False),
        ("Depuis février 2022", (2022, 2), None, True),
        ("De 2015 à 2018", (2015, None), (2018, None), False),
        ("2016 – Présent", (2016, None), None, True),
    ],
)
def test_date_ranges_are_recognised(text: str, start: YM, end: YM, current: bool) -> None:
    match = find_date_range(text)

    assert match is not None
    assert _ym(match.range.start) == start
    assert _ym(match.range.end) == end
    assert match.range.is_current is current


def test_the_matched_span_can_be_removed_from_the_line() -> None:
    line = "Acme Analytics, Paris | Feb. 2021 – Present"

    match = find_date_range(line)

    assert match is not None
    assert line[match.start : match.end] == match.range.text
    assert line[: match.start].rstrip(" |") == "Acme Analytics, Paris"


def test_single_year_is_a_point_in_time() -> None:
    match = find_date_range("Azure AI Engineer Associate (2023)")

    assert match is not None
    assert _ym(match.range.start) == (2023, None)
    assert _ym(match.range.end) == (2023, None)
    assert match.range.is_current is False


@pytest.mark.parametrize(
    "text",
    [
        "Senior AI Engineer — Acme Analytics",
        "I may join in the spring",
        "Reduced inference latency by 35%.",
        "Serving 2,000 users",
        "13/2020 – 14/2021",
        "Room 1234",
    ],
)
def test_text_without_dates_is_ignored(text: str) -> None:
    assert find_date_range(text) is None
