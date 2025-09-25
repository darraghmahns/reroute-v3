from app.services.stream_metrics import summarize_streams


def test_summarize_streams_basic():
    streams = {
        "time": {"data": [0, 1, 2, 3, 4, 5]},
        "distance": {"data": [0, 10, 20, 40, 60, 80]},  # meters
        "moving": {"data": [1, 1, 1, 1, 1, 1]},
        "watts": {"data": [150, 160, 170, 180, 190, 200]},
        "heartrate": {"data": [120, 125, 130, 135, 140, 145]},
        "cadence": {"data": [80, 82, 83, 84, 85, 86]},
    }

    summary = summarize_streams(streams=streams, ftp=250, hr_zones=[120, 135, 150])

    assert summary.duration_seconds == 5
    assert summary.distance_km == 0.08
    assert summary.power is not None
    assert summary.power.average is not None
    assert summary.power.intensity_factor is not None
    assert summary.heart_rate is not None
    assert len(summary.heart_rate.time_in_zones) == 4
    assert summary.cadence_avg > 80


def test_summarize_streams_no_data():
    summary = summarize_streams(streams={})
    assert summary.duration_seconds is None
    assert summary.power is None
    assert summary.heart_rate is None


def test_summarize_streams_partial_streams():
    streams = {
        "time": {"data": [0, 60, 120]},
        "watts": {"data": [200, 210, 220]},
    }

    summary = summarize_streams(streams=streams, ftp=200)
    assert summary.duration_seconds == 120
    assert summary.power is not None
    assert summary.power.normalized is not None
