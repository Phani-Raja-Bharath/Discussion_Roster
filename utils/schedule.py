import json
from datetime import date
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SCHEDULE_PATH = BASE_DIR / "inputs" / "discussion_schedule.json"


def load_schedule_metadata():
    if not SCHEDULE_PATH.exists():
        return {}

    with SCHEDULE_PATH.open(encoding="utf-8") as handle:
        schedule = json.load(handle)

    metadata = {}
    for item in schedule:
        week = item.get("week")
        if week is None:
            continue
        metadata[int(week)] = {
            "date": item.get("date", ""),
            "week_label": item.get("week_label", f"Week {week}"),
            "topic": item.get("topic", ""),
        }
    return metadata


def week_details(week):
    metadata = load_schedule_metadata()
    return metadata.get(int(week), {"date": "", "week_label": f"Week {week}", "topic": ""})


def display_date(value):
    if not value:
        return ""
    parsed = date.fromisoformat(str(value))
    return f"{parsed.month}/{parsed.day}/{parsed.year}"
