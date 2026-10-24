"""Deterministic measurement comparisons shared by both investigation workflows."""

from datetime import timedelta

from knowledge.temporal_fixture import instant


def measurement_rows(observations, request):
    at = instant(request["effectiveAt"])
    groups = {}
    for observation in observations:
        if observation.get("kind") != "metric_window":
            continue
        phase = (
            "baseline"
            if instant(observation["windowEnd"]) <= at - timedelta(minutes=25)
            else "recovery"
            if instant(observation["windowStart"]) >= at + timedelta(minutes=15)
            else "incident"
        )
        key = (
            observation["entityId"],
            observation["metricName"],
            observation["unit"],
            observation["aggregation"],
            tuple(sorted(observation.get("dimensions", []))),
        )
        current = groups.setdefault(key, {}).get(phase)
        if current is None or (observation["windowEnd"], observation["id"]) > (
            current["windowEnd"],
            current["id"],
        ):
            groups[key][phase] = observation
    rows = []
    for key, phases in sorted(groups.items()):
        row = {
            "entityId": key[0],
            "metric": key[1],
            "unit": key[2],
            "aggregation": key[3],
            "dimensions": list(key[4]),
            **{p: o["value"] for p, o in phases.items()},
            "evidenceIds": {p: o["id"] for p, o in phases.items()},
            "windows": {p: [o["windowStart"], o["windowEnd"]] for p, o in phases.items()},
            "sampleCounts": {p: o.get("sampleCount") for p, o in phases.items()},
        }
        if "baseline" in phases and "incident" in phases:
            before, during = row["baseline"], row["incident"]
            row.update(
                difference=round(during - before, 4),
                ratio=round(during / before, 4) if before else None,
                calculation="incident - baseline; incident / baseline (if baseline != 0)",
            )
        rows.append(row)
    return rows
