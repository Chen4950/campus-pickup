from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from math import ceil
from statistics import median, quantiles

SHANGHAI = timezone(timedelta(hours=8))
SLOT_MINUTES = 30
MIN_SAMPLES = 6
WALK_METERS_PER_MINUTE = 65
SEARCH_MINUTES_PER_PARCEL = 0.6


def ceil_slot(value):
    start = value.replace(minute=value.minute // SLOT_MINUTES * SLOT_MINUTES, second=0, microsecond=0)
    return start if start == value else start + timedelta(minutes=SLOT_MINUTES)


def minutes_between(start, end):
    return (end - start).total_seconds() / 60


class StationForecast:
    def __init__(self, station, rows):
        self.station = station
        self.rows = []
        self.buckets = defaultdict(list)
        for joined, started, finished in rows:
            joined, started, finished = (datetime.fromisoformat(value) for value in (joined, started, finished))
            wait = minutes_between(joined, started)
            service = minutes_between(started, finished)
            if wait >= 0 and service > 0:
                local = joined.astimezone(SHANGHAI)
                self.rows.append((local, wait, service))
                self.buckets[self.section(local)].append((wait, service))
        self.latest = max((row[0] for row in self.rows), default=None)

    @staticmethod
    def section(moment):
        return moment.weekday() >= 5, moment.hour * 60 + moment.minute // SLOT_MINUTES * SLOT_MINUTES

    def estimate(self, moment):
        weekend, slot = self.section(moment)
        matched = self.buckets.get((weekend, slot), [])
        basis = "同类日期 · 同一时段"
        if len(matched) < MIN_SAMPLES:
            matched = [
                record
                for (is_weekend, start), records in self.buckets.items()
                if weekend == is_weekend and abs(start - slot) <= SLOT_MINUTES
                for record in records
            ]
            basis = "同类日期 · 相邻时段"
        if len(matched) < MIN_SAMPLES:
            return None
        waits, services = zip(*matched)
        lower, _, upper = quantiles(waits, method="inclusive")
        return {
            "wait_minutes": round(median(waits), 1),
            "usual_low_minutes": round(lower, 1),
            "usual_high_minutes": round(upper, 1),
            "service_minutes": round(median(services), 1),
            "samples": len(matched),
            "basis": basis,
        }

    def recommendations(self, day, earliest, latest, trip=None, now=None):
        if earliest >= latest:
            raise ValueError("请将结束时间设在开始时间之后。")
        now = now or datetime.now(SHANGHAI)
        opening, closing = self.station["operating_hours"]["weekend" if day.weekday() >= 5 else "weekday"]
        opens_at, closes_at = (datetime.combine(day, time.fromisoformat(value), SHANGHAI) for value in (opening, closing))
        first = max(datetime.combine(day, earliest, SHANGHAI), opens_at, now)
        last = min(datetime.combine(day, latest, SHANGHAI), closes_at)

        def estimate_at(arrival):
            if arrival >= closes_at:
                return None
            walk = trip["distance_m"] / WALK_METERS_PER_MINUTE if trip else 0
            search = trip["parcel_count"] * SEARCH_MINUTES_PER_PARCEL if trip else 0
            walk_to_queue = trip["to_verification_m"] / WALK_METERS_PER_MINUTE if trip else 0
            queue_at = arrival + timedelta(minutes=walk_to_queue + search)
            if queue_at >= closes_at:
                return None
            estimate = self.estimate(queue_at)
            if estimate is None:
                return None
            total = walk + search + estimate["wait_minutes"] + estimate["service_minutes"] if trip else None
            return {
                "time": arrival.strftime("%H:%M"),
                "queue_time": queue_at.strftime("%H:%M"),
                "walk_minutes": round(walk, 1) if trip else None,
                "search_minutes": round(search, 1) if trip else None,
                "total_minutes": round(total, 1) if trip else None,
                "may_finish_after_close": bool(total is not None and arrival + timedelta(minutes=total) > closes_at),
                **estimate,
            }

        candidates = []
        slot = ceil_slot(first)
        while slot <= last and slot < closes_at:
            estimate = estimate_at(slot)
            if estimate:
                candidates.append(estimate)
            slot += timedelta(minutes=SLOT_MINUTES)
        candidates.sort(key=lambda option: (option["wait_minutes"], option["time"]))
        now_estimate = estimate_at(now) if now.date() == day and opens_at <= now < closes_at else None
        message = None
        if not candidates:
            message = "所选范围内没有可推荐的到站时段，请调整时间范围。" if first >= last else "暂无可用估算，请扩大到站时间范围。"
        return {
            "candidates": candidates,
            "now": now_estimate,
            "opening_hours": [opening, closing],
            "latest_sample": self.latest.date().isoformat() if self.latest else None,
            "message": message,
            "assumptions": {"walk_m_per_minute": WALK_METERS_PER_MINUTE, "find_min_per_parcel": SEARCH_MINUTES_PER_PARCEL},
        }

    def backtest(self, split_day):
        train = StationForecast(self.station, [
            (moment.isoformat(), (moment + timedelta(minutes=wait)).isoformat(),
             (moment + timedelta(minutes=wait + service)).isoformat())
            for moment, wait, service in self.rows if moment.date() < split_day
        ])
        errors = []
        peak_errors = []
        for moment, wait, _ in self.rows:
            if moment.date() < split_day:
                continue
            estimate = train.estimate(moment)
            if estimate:
                error = abs(wait - estimate["wait_minutes"])
                errors.append(error)
                if moment.weekday() < 5 and (moment.hour == 12 or 17 <= moment.hour < 19):
                    peak_errors.append(error)
        return {
            "train_count": len(train.rows),
            "test_count": len(errors),
            "mae_minutes": round(sum(errors) / len(errors), 2) if errors else None,
            "peak_count": len(peak_errors),
            "peak_mae_minutes": round(sum(peak_errors) / len(peak_errors), 2) if peak_errors else None,
        }
