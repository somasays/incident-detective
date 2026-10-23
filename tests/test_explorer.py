"""Schema diagrams derive from the ontology; instance views preserve retrieved relationships."""

import re

from knowledge.ontology import ONTOLOGY
from ui.explorer import (
    neighborhood,
    ontology_network,
    render_knowledge_graph,
    render_ontology_graph,
)


def test_ontology_diagram_exactly_matches_the_contract():
    graph = ontology_network(ONTOLOGY)
    assert {n["id"] for n in graph.nodes} == {"ontology:" + label for label in ONTOLOGY["entities"]}
    expected = {
        ("ontology:" + source, kind, "ontology:" + target)
        for kind, pairs in ONTOLOGY["relationships"].items()
        for source, target in pairs
    }
    actual = {(e["from"], e["label"].replace(" ", "_"), e["to"]) for e in graph.edges}
    assert actual == expected


def test_ontology_and_instance_graphs_use_inline_assets(evidence):
    for document in (render_ontology_graph(ONTOLOGY), render_knowledge_graph(evidence["graph"])):
        assert "new vis.Network" in document
        assert "connect-src 'none'" in document
        assert not re.search(r"<(script|link|img)[^>]+(?:src|href)=[\"']https?://", document)
    assert "INC-104" not in render_ontology_graph(ONTOLOGY)


def test_neighborhood_includes_only_retrieved_adjacent_records(evidence):
    graph = evidence["graph"]
    focused = neighborhood(graph, "event-connector", hops=1)
    assert {"event-connector", "ingestion-pipeline", "deploy-014"} <= {
        n["id"] for n in focused["nodes"]
    }
    assert "analytics-api" not in {n["id"] for n in focused["nodes"]}
    assert all(e in graph["edges"] for e in focused["edges"])
    assert neighborhood(graph, "missing") == {"nodes": [], "edges": []}
    assert not neighborhood(graph, "event-connector", hops=0)["edges"]


def test_cycles_and_isolated_components_render_without_invented_edges():
    graph = {
        "nodes": [
            {"id": id, "label": "Component", "name": id, "type": "service"}
            for id in ["a", "b", "isolated"]
        ],
        "edges": [
            {"source": "a", "target": "b", "type": "DEPENDS_ON"},
            {"source": "b", "target": "a", "type": "DEPENDS_ON"},
        ],
    }
    document = render_knowledge_graph(graph)
    assert "component:isolated" in document
    assert "component:a" in document and "component:b" in document
