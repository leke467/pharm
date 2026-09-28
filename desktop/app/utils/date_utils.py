from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_now() -> str:
    return datetime.now().astimezone().isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_display(value: str, fmt: str = "%Y-%m-%d %H:%M") -> str:
    try:
        dt = parse_iso(value)
        local_dt = dt.astimezone()
        return local_dt.strftime(fmt)
    except Exception:
        return value
