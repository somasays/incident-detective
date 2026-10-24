"""Shared, safe display formatting for the temporal workspace."""

import html
from datetime import datetime
from zoneinfo import ZoneInfo

from knowledge.temporal_fixture import DATASET


def esc(value):
    return html.escape(str(value))


def short(value):
    return str(value).removeprefix(DATASET + ":")


def clock(value):
    if not value:
        return "—"
    try:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            .astimezone(ZoneInfo("Europe/Berlin"))
            .strftime("%d %b · %H:%M:%S")
        )
    except ValueError:
        return str(value)
