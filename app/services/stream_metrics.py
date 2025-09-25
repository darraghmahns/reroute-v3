from __future__ import annotations

from dataclasses import dataclass
from math import pow
from typing import Any, Iterable, Sequence

from app.schemas.metrics import HeartRateSummary, PowerSummary, StreamSummary


def _get_stream_data(stream: dict[str, Any] | None) -> list[float]:
    if not stream:
        return []
    data = stream.get("data")
    if isinstance(data, list):
        return [float(x) for x in data]
    return []


def _rolling_average(values: Sequence[float], window: int = 30) -> list[float]:
    if not values:
        return []
    window = max(1, window)
    rolling: list[float] = []
    cumulative = 0.0
    for i, value in enumerate(values):
        cumulative += value
        if i >= window:
            cumulative -= values[i - window]
            rolling.append(cumulative / window)
        else:
            rolling.append(cumulative / (i + 1))
    return rolling


def _normalized_power(watts: Sequence[float]) -> float | None:
    if not watts:
        return None
    rolling = _rolling_average(watts, window=30)
    if not rolling:
        return None
    fourth_power_avg = sum(pow(v, 4) for v in rolling) / len(rolling)
    return pow(fourth_power_avg, 0.25)


def _intensity_factor(np_value: float | None, ftp: float | None) -> float | None:
    if not np_value or not ftp or ftp <= 0:
        return None
    return np_value / ftp


def _tss(duration_seconds: int | None, np_value: float | None, intensity_factor_value: float | None, ftp: float | None) -> float | None:
    if not duration_seconds or not np_value or not intensity_factor_value or not ftp or ftp <= 0:
        return None
    return (duration_seconds * np_value * intensity_factor_value) / (ftp * 3600) * 100


def _time_in_zones(
    hr_values: Sequence[float],
    time_values: Sequence[float],
    zones: Sequence[int] | None,
) -> list[float]:
    if not hr_values:
        return []
    if not zones:
        zones = []
    zone_counts = [0.0 for _ in range(len(zones) + 1)]

    # Use provided time deltas or assume 1-second intervals
    for idx, hr in enumerate(hr_values):
        if idx + 1 < len(time_values):
            delta = max(0.0, float(time_values[idx + 1]) - float(time_values[idx]))
        else:
            delta = 1.0
        zone_index = 0
        for threshold in zones:
            if hr > threshold:
                zone_index += 1
            else:
                break
        zone_counts[zone_index] += delta
    return zone_counts


def summarize_streams(
    *,
    streams: dict[str, Any],
    ftp: float | None = None,
    hr_zones: Sequence[int] | None = None,
) -> StreamSummary:
    time_stream = _get_stream_data(streams.get("time"))
    distance_stream = _get_stream_data(streams.get("distance"))
    heart_rate_stream = _get_stream_data(streams.get("heartrate"))
    power_stream = _get_stream_data(streams.get("watts"))
    cadence_stream = _get_stream_data(streams.get("cadence"))
    moving_stream = _get_stream_data(streams.get("moving"))

    duration_seconds = int(time_stream[-1]) if time_stream else (len(power_stream) if power_stream else None)
    moving_seconds = None
    if moving_stream:
        moving_seconds = int(sum(moving_stream))
    elif duration_seconds is not None:
        moving_seconds = duration_seconds

    distance_km = None
    if distance_stream:
        distance_km = distance_stream[-1] / 1000.0

    average_speed_kph = None
    if distance_km is not None and duration_seconds:
        average_speed_kph = (distance_km / duration_seconds) * 3600.0

    avg_power = sum(power_stream) / len(power_stream) if power_stream else None
    np_value = _normalized_power(power_stream)
    intensity_value = _intensity_factor(np_value, ftp)
    tss_value = _tss(duration_seconds, np_value, intensity_value, ftp)

    avg_hr = sum(heart_rate_stream) / len(heart_rate_stream) if heart_rate_stream else None
    max_hr = max(heart_rate_stream) if heart_rate_stream else None
    hr_time_in_zones = _time_in_zones(heart_rate_stream, time_stream, hr_zones)

    avg_cadence = sum(cadence_stream) / len(cadence_stream) if cadence_stream else None

    power_summary = None
    if any(value is not None for value in (avg_power, np_value, intensity_value, tss_value)):
        power_summary = PowerSummary(
            average=avg_power,
            normalized=np_value,
            intensity_factor=intensity_value,
            tss=tss_value,
        )

    heart_rate_summary = None
    if any(value is not None for value in (avg_hr, max_hr)) or hr_time_in_zones:
        heart_rate_summary = HeartRateSummary(
            average=avg_hr,
            max=max_hr,
            time_in_zones=hr_time_in_zones,
        )

    return StreamSummary(
        duration_seconds=duration_seconds,
        moving_seconds=moving_seconds,
        distance_km=distance_km,
        average_speed_kph=average_speed_kph,
        power=power_summary,
        heart_rate=heart_rate_summary,
        cadence_avg=avg_cadence,
    )
