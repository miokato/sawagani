"""schedule.md による Sawagani 自己予約テーブル。"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, cast

from . import settings, tasks

ENTRY_RE = re.compile(
    r"^- \[(?P<done>[ xX])\] (?P<kind>at|cron):(?P<body>.+?) \| (?P<task>.+)$"
)
LAST_RE = re.compile(r"\s+last:(?P<last>\S+)$")
MONTH_NAMES = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
DOW_NAMES = {
    "SUN": 0,
    "MON": 1,
    "TUE": 2,
    "WED": 3,
    "THU": 4,
    "FRI": 5,
    "SAT": 6,
}


@dataclass
class Entry:
    """schedule.md の1予約行。"""

    kind: Literal["at", "cron"]
    spec: str
    task: str
    done: bool
    last: datetime | None
    raw_index: int


def local_timezone():
    """ローカル timezone を返す。"""
    return datetime.now().astimezone().tzinfo


def normalize_datetime(dt: datetime) -> datetime:
    """timezone なし datetime をローカル timezone とみなして aware にする。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=local_timezone())
    return dt.astimezone()


def parse_datetime(text: str) -> datetime:
    """ISO8601 文字列を aware datetime として読む。"""
    return normalize_datetime(datetime.fromisoformat(text))


def parse_entry(line: str, index: int) -> Entry | None:
    """schedule.md の1行を Entry に変換する。壊れた行は None。"""
    match = ENTRY_RE.match(line.strip())
    if match is None:
        return None

    kind = cast(Literal["at", "cron"], match.group("kind"))
    body = match.group("body").strip()
    task = match.group("task").strip()
    last = None
    if kind == "cron":
        last_match = LAST_RE.search(body)
        if last_match is not None:
            try:
                last = parse_datetime(last_match.group("last"))
            except ValueError:
                return None
            body = body[: last_match.start()].strip()

    if not body or not task:
        return None

    if kind == "at":
        try:
            parse_datetime(body)
        except ValueError:
            return None

    return Entry(
        kind=kind,
        spec=body,
        task=task,
        done=match.group("done").lower() == "x",
        last=last,
        raw_index=index,
    )


def parse_entries(text: str) -> list[Entry]:
    """schedule.md の有効な予約行だけを返す。"""
    entries: list[Entry] = []
    for index, line in enumerate(text.splitlines()):
        entry = parse_entry(line, index)
        if entry is not None:
            entries.append(entry)
    return entries


def is_due(entry: Entry, now: datetime) -> bool:
    """予約が期限到来しているか判定する。"""
    now = normalize_datetime(now)
    if entry.done:
        return False
    if entry.kind == "at":
        return now >= parse_datetime(entry.spec)
    if entry.last is None:
        return False

    next_time = next_cron_time(entry.spec, entry.last)
    return now >= next_time


def parse_cron_field(field: str, minimum: int, maximum: int, names: dict[str, int] | None = None) -> set[int]:
    """cron の1フィールドを値集合にする。v1 は `*`、数値、カンマ、名前を扱う。"""
    if field == "*":
        return set(range(minimum, maximum + 1))

    values: set[int] = set()
    for part in field.split(","):
        token = part.strip().upper()
        if names and token in names:
            value = names[token]
        else:
            value = int(token)
        if value == 7 and minimum == 0 and maximum == 6:
            value = 0
        if value < minimum or value > maximum:
            raise ValueError(f"cron field value out of range: {field}")
        values.add(value)
    return values


def cron_matches(spec: str, when: datetime) -> bool:
    """5フィールドcron式が指定時刻に一致するか判定する。"""
    fields = spec.split()
    if len(fields) != 5:
        raise ValueError(f"unsupported cron expression: {spec}")

    minutes = parse_cron_field(fields[0], 0, 59)
    hours = parse_cron_field(fields[1], 0, 23)
    days = parse_cron_field(fields[2], 1, 31)
    months = parse_cron_field(fields[3], 1, 12, MONTH_NAMES)
    weekdays = parse_cron_field(fields[4], 0, 6, DOW_NAMES)
    cron_weekday = (when.weekday() + 1) % 7

    return (
        when.minute in minutes
        and when.hour in hours
        and when.day in days
        and when.month in months
        and cron_weekday in weekdays
    )


def next_cron_time(spec: str, last: datetime) -> datetime:
    """last より後の最初のcron一致時刻を返す。"""
    cursor = normalize_datetime(last).replace(second=0, microsecond=0) + timedelta(minutes=1)
    deadline = cursor + timedelta(days=366)
    while cursor <= deadline:
        if cron_matches(spec, cursor):
            return cursor
        cursor += timedelta(minutes=1)
    raise ValueError(f"could not find next cron time within 366 days: {spec}")


def serialize_entry(entry: Entry) -> str:
    """Entry を schedule.md の1行へ戻す。"""
    mark = "x" if entry.done else " "
    spec = entry.spec
    if entry.kind == "cron" and entry.last is not None:
        spec = f"{spec} last:{entry.last.isoformat(timespec='seconds')}"
    return f"- [{mark}] {entry.kind}:{spec} | {entry.task}"


def serialize(entries: list[Entry]) -> str:
    """Entry のリストを schedule.md テキストへ変換する。"""
    if not entries:
        return ""
    return "\n".join(serialize_entry(entry) for entry in entries) + "\n"


def fire_due(now: datetime | None = None) -> list[str]:
    """期限到来した予約を tasks.md へ追記し、schedule.md を更新する。"""
    path = settings.schedule_path()
    if not path.exists():
        return []

    now = normalize_datetime(now or datetime.now().astimezone())
    lines = path.read_text(encoding="utf-8").splitlines()
    entries = parse_entries("\n".join(lines))
    fired: list[str] = []
    changed = False

    for entry in entries:
        if entry.kind == "cron" and entry.last is None and not entry.done:
            entry.last = now
            lines[entry.raw_index] = serialize_entry(entry)
            changed = True
            continue

        if not is_due(entry, now):
            continue

        tasks.append_task(entry.task, source="schedule")
        fired.append(entry.task)
        changed = True
        if entry.kind == "at":
            entry.done = True
        else:
            entry.last = now
        lines[entry.raw_index] = serialize_entry(entry)

    if changed:
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    return fired
