# App screenshots

[Back to README](../../README.md)

Captured from the warm off-white and sage Streamlit workspace at `http://localhost:8502` on **24 October 2026**.
All records are synthetic. The investigation used the explicitly requested **GPT-5 mini** provider
and real local Neo4j/MCP retrieval. It finished **incomplete** at its bounded investigation budget,
retaining a provisional hypothesis rather than presenting a confirmed cause.

## Ontology

The approved Component definition, its permitted relationship directions and property types.

![Component ontology and property inspector](ontology.jpg)

## Stored knowledge graph

The Component view shows ten stored records and six dependency relationships, alongside identity,
timestamps and source provenance. The separate All types view was also exercised through page two.

![Stored component dependencies and record provenance](knowledge-graph.jpg)

## Investigation evidence graph

The real Profile run is shown with the evidence map, chronological check timeline and cited finding
cards. Its incomplete status is visible. Every shown edge comes from retrieved records.

![Profile graph and investigation activity](investigation.jpg)

## Report

The adjacent Report tab preserves the graph while showing the provisional hypothesis, next verification
and downloads. Longer explanations and source records remain available in detail expanders.

![Provisional report beside the retrieved graph](report.jpg)

## Measurements

Retrieved prior/incident measurements and expandable source windows. The prior window is a reference
comparison, not a learned normal range. The displayed latency values are 58 ms and 950 ms.

![Profile measurements and exact evidence windows](measurements.jpg)

JSON and standalone HTML were downloaded through the dashboard. The JSON references were checked
against retrieved IDs; the HTML report has inline assets and no external asset URLs. The broader
model-backed verifier did not pass every case; see the [review results](../cleanup-review.md).
