"""Compact views of retrieved facts. No diagnostic rules or model calls live here."""

from decimal import Decimal, InvalidOperation

from knowledge.temporal_fixture import DATASET


def resource_name(package, entity_id):
    index = package.get("index", {})
    record = index.get(entity_id, {})
    name = record.get("name")
    if name and record.get("label") != "Component" and any(
        other.get("name") == name and other.get("label") != record.get("label")
        for other in index.values()
    ):
        return name + " · " + record["label"]
    return name or str(entity_id or "Unknown resource").removeprefix(DATASET + ":")


def hypothesis_title(hypothesis, assessment, package):
    title = hypothesis.get("statement", hypothesis.get("title", ""))
    if title and len(title) <= 80:
        return title
    # Old saved packages contain paragraph-sized titles. Show their actual entity
    # rather than cutting a sentence mid-word or inventing a causal summary.
    entity_id = assessment.get("cause_entity_id") or hypothesis.get("cause_entity_id")
    if entity_id:
        return "Suspected cause · " + resource_name(package, entity_id)
    return "Hypothesis under investigation"


def assessment_refs(assessment):
    return list(
        dict.fromkeys(
            eid
            for field in (
                "supporting_evidence_ids",
                "current_evidence_ids",
                "metric_evidence_ids",
                "mechanism_evidence_ids",
            )
            for eid in assessment.get(field, [])
        )
    )


def display_value(value):
    if isinstance(value, str):
        try:
            numeric = Decimal(value)
        except InvalidOperation:
            return value
        return format(numeric, ",f") if numeric.is_finite() else value
    if type(value) in {int, float}:
        return f"{int(value):,}" if value == int(value) else f"{value:,}"
    return str(value)


def evidence_facts(package, evidence_ids, *, limit=3):
    """Present exact source values, only for evidence cited by the caller.

    A comparison may add its retrieved prior-window record for context. It never
    substitutes an assumed normal range or infers that a change caused an effect.
    """
    ids = set(evidence_ids)
    facts = []
    for change in package.get("changes", []):
        if change["id"] not in ids:
            continue
        if change.get("beforeValue") is None or change.get("afterValue") is None:
            continue
        facts.append(
            {
                "resource": resource_name(package, change.get("entityId")),
                "label": change.get("description") or change.get("kind", "Recorded change"),
                "value": f"{display_value(change['beforeValue'])} → "
                f"{display_value(change['afterValue'])}",
                "context": "Recorded change",
                "evidence_ids": [change["id"]],
            }
        )
    for measurement in package.get("measurements", []):
        refs = measurement.get("evidenceIds", {})
        if refs.get("incident") not in ids or measurement.get("incident") is None:
            continue
        before = measurement.get("baseline")
        has_prior = before is not None and refs.get("baseline") in package.get("index", {})
        value = (
            f"{display_value(before)} → {display_value(measurement['incident'])}"
            if has_prior
            else display_value(measurement["incident"])
        )
        facts.append(
            {
                "resource": resource_name(package, measurement.get("entityId")),
                "label": measurement["metric"] + " · " + measurement.get("aggregation", ""),
                "value": value + " " + measurement.get("unit", ""),
                "context": "Prior → incident" if has_prior else "Incident window",
                "evidence_ids": [refs[p] for p in ("baseline", "incident") if p in refs]
                if has_prior
                else [refs["incident"]],
            }
        )
    for observation in package.get("observations", []):
        if observation["id"] not in ids or not observation.get("errorType"):
            continue
        count = observation.get("eventCount")
        facts.append(
            {
                "resource": resource_name(package, observation.get("entityId")),
                "label": observation["errorType"].replace("_", " ").capitalize(),
                "value": f"{display_value(count)} events" if count is not None else "Observed",
                "context": "Recorded error",
                "evidence_ids": [observation["id"]],
            }
        )
    return facts[:limit]
