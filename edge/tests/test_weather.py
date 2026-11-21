from datetime import date

import httpx

from observatory_edge.weather import fetch_weather


def test_disabled_makes_no_request(conn, settings):
    def boom(req):
        raise AssertionError("should not be called")
    client = httpx.Client(transport=httpx.MockTransport(boom))
    assert fetch_weather(conn, settings, date(2024, 6, 1), date(2024, 6, 3), client) == 0


def test_fetch_stores_rows_with_rounded_coordinates(conn, settings):
    seen = {}

    def handler(req):
        seen.update(dict(req.url.params))
        return httpx.Response(200, json={"daily": {
            "time": ["2024-06-01", "2024-06-02"], "precipitation_sum": [0.0, 7.5],
            "temperature_2m_min": [14.1, 15.0], "temperature_2m_max": [25.3, 22.0]}})
    s = settings.with_(weather_enabled=True, camera_lat=40.123456, camera_lon=-74.987654)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_weather(conn, s, date(2024, 6, 1), date(2024, 6, 2), client) == 2
    assert seen["latitude"] == "40.12" and seen["longitude"] == "-74.99"
    assert conn.execute("SELECT precip_mm FROM weather_daily WHERE date='2024-06-02'").fetchone()[0] == 7.5


def test_rain_insight_needs_ten_days_each(conn, settings, tmp_path):
    from datetime import datetime, timedelta

    import test_flow
    from test_flow import RACCOON, add_image, animal, classify, detect

    from observatory_edge.insights import compute_insights
    saved = test_flow.BASE
    try:
        for i in range(12):  # visits only on dry days
            test_flow.BASE = datetime(2024, 6, 1, 22, 0) + timedelta(days=2 * i)
            m = add_image(conn, settings, tmp_path, live=False)
            detect(conn, settings, m, [animal()])
            classify(conn, settings, m, RACCOON)
    finally:
        test_flow.BASE = saved
    rows = [((date(2024, 6, 1) + timedelta(days=d)).isoformat(), 0.0 if d % 2 == 0 else 5.0)
            for d in range(18)]  # 9 wet days only
    conn.executemany("INSERT INTO weather_daily(date, precip_mm) VALUES (?,?)", rows)
    assert not [i for i in compute_insights(conn, settings) if i.kind == "rain"]
    conn.executemany("INSERT INTO weather_daily(date, precip_mm) VALUES (?,?)",
                     [((date(2024, 6, 1) + timedelta(days=d)).isoformat(), 0.0 if d % 2 == 0 else 5.0)
                      for d in range(18, 24)])  # now 12 wet, 12 dry
    rain = [i for i in compute_insights(conn, settings) if i.kind == "rain"]
    assert rain and rain[0].text.startswith("Fewer visits on rainy days")
