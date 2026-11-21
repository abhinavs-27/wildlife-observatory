from datetime import date, datetime, timezone

from observatory_edge.astro import moon_illumination, night_of, sun_times

TRENTON = (40.22, -74.76)
NY = "America/New_York"


def minutes(dt):
    return dt.hour * 60 + dt.minute


def test_sun_times_summer_solstice_trenton():
    rise, set_ = sun_times(date(2024, 6, 21), *TRENTON, NY)
    assert abs(minutes(rise) - (5 * 60 + 29)) <= 3
    assert abs(minutes(set_) - (20 * 60 + 32)) <= 3
    assert rise.utcoffset().total_seconds() == -4 * 3600  # EDT


def test_sun_times_winter_solstice_trenton():
    rise, set_ = sun_times(date(2024, 12, 21), *TRENTON, NY)
    assert abs(minutes(rise) - (7 * 60 + 17)) <= 3
    assert abs(minutes(set_) - (16 * 60 + 37)) <= 3


def test_moon_illumination_known_phases():
    assert moon_illumination(datetime(2024, 1, 11, 11, 57, tzinfo=timezone.utc)) < 0.02
    assert moon_illumination(datetime(2024, 1, 25, 17, 54, tzinfo=timezone.utc)) > 0.98


def test_night_of_early_morning_belongs_to_previous_evening():
    assert night_of(datetime(2024, 6, 2, 6, 0, tzinfo=timezone.utc), NY) == date(2024, 6, 1)
    assert night_of(datetime(2024, 6, 2, 23, 0, tzinfo=timezone.utc), NY) == date(2024, 6, 2)
