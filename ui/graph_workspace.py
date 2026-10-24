"""Ontology and evidence graph views with a paginated stored-record explorer."""

import json

import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

from knowledge.explorer import GraphExplorer
from knowledge.temporal_seed import spec
from ui.explorer import dependency_paths
from ui.formatting import esc, short
from ui.graph_view import build_network, render_network, visualization_id


def graph_html(graph, paths=None, analysis=None, *, height=590):
    network = build_network(
        {"graph": graph, "dependency_paths": paths or []},
        {
            "analysis_available": bool(analysis),
            "hypotheses": (analysis or {}).get("hypotheses", []),
        },
    )
    records = {visualization_id(n): n for n in graph["nodes"]}
    records_by_id = {n["id"]: n for n in graph["nodes"]}
    display_nodes = {node["id"]: node for node in network.nodes}
    for node in network.nodes:
        record = records[node["id"]]
        label = record.get("name") or record.get("errorType") or record.get("metricName")
        node["label"] = label or short(record["id"])
        if len(node["label"]) > 38:
            node["label"] = node["label"][:35] + "…"
        node["title"] = "<br>".join(
            esc(f"{k}: {v}")
            for k, v in record.items()
            if k in {"id", "label", "timestamp", "description", "message", "sourceRef", "kind"}
        )
        if record["label"] == "Observation":
            node["color"]["background"] = "#BE925C"
            node["color"]["border"] = "#D3B17D"
            targets = [e["target"] for e in graph["edges"] if e["source"] == record["id"]]
            for target in targets:
                target_record = records_by_id.get(target)
                other = (
                    display_nodes.get(visualization_id(target_record)) if target_record else None
                )
                if other:
                    node["level"] = other["level"]
                    break
    return render_network(network, height=height)


def display_graph(package, *, full=False):
    graph = package.get("graph") or package.get("topology")
    if not graph or not graph.get("nodes"):
        return
    if not full:
        excluded = {"StateSnapshot", "CodeArtifact", "Commit", "Person"}
        ids = {
            n["id"]
            for n in graph["nodes"]
            if n["label"] not in excluded
            and not (n["label"] == "Observation" and n.get("kind") == "metric_window")
        }
        graph = {
            "nodes": [n for n in graph["nodes"] if n["id"] in ids],
            "edges": [e for e in graph["edges"] if e["source"] in ids and e["target"] in ids],
        }
    components.html(
        graph_html(
            graph, package.get("topology", {}).get("paths"), package.get("analysis"), height=500
        ),
        height=515,
    )


def ontology_view():
    ontology = spec()
    st.subheader("The model behind the investigation")
    st.caption("Stable identities connect to dated observations, state versions and changes.")
    left, right = st.columns([3, 2], gap="large")
    with right:
        choices = {n["label"]: key for key, n in ontology["nodes"].items()}
        label = st.selectbox("Inspect an entity type", sorted(choices), key="ontology_type")
        key = choices[label]
        definition = ontology["nodes"][key]
        st.text(definition.get("description", ""))
        st.dataframe(
            [
                {"Property": name, "Type": p["type"], "Required": bool(p.get("must_exist"))}
                for name, p in definition["properties"].items()
            ],
            hide_index=True,
            use_container_width=True,
        )
        with st.expander("Full definition"):
            st.json(definition)
    with left:
        network = Network(height="590px", width="100%", directed=True, bgcolor="#FFFFFF")
        relationships = [
            r
            for r in ontology["relationships"].values()
            if key in {r["from"]["node"], r["to"]["node"]}
        ]
        node_keys = {key} | {r[end]["node"] for r in relationships for end in ("from", "to")}
        for node_key in sorted(node_keys):
            n = ontology["nodes"][node_key]
            network.add_node(
                node_key,
                label=n["label"],
                shape="box",
                margin=12,
                color="#7A8C68" if node_key == key else "#426754",
                font={"color": "#ffffff", "face": "system-ui"},
            )
        seen = set()
        for r in relationships:
            edge = (r["from"]["node"], r["to"]["node"], r["type"])
            if edge not in seen:
                network.add_edge(
                    edge[0],
                    edge[1],
                    label=edge[2],
                    arrows="to",
                    color="#537397",
                    font={"size": 10, "color": "#475569", "strokeWidth": 0},
                )
                seen.add(edge)
        network.set_options(
            json.dumps(
                {
                    "layout": {"randomSeed": 7},
                    "physics": {"enabled": True, "stabilization": {"iterations": 150}},
                    "interaction": {"hover": True},
                }
            )
        )
        components.html(render_network(network), height=605)
        st.caption(
            f"Ontology {ontology['version']} · {len(ontology['nodes'])} entity types · "
            "Showing relationships for the selected type."
        )
    st.info(
        "Two clocks: validFrom/validTo describe when a fact held; recordedAt/supersededAt "
        "describe when that version was known. Historical queries use both."
    )
    st.download_button(
        "Download ontology", json.dumps(ontology, indent=2), "ontology.json", "application/json"
    )


def stored_graph_view(database):
    explorer = GraphExplorer(database)
    st.subheader("Explore the stored knowledge graph")
    search_col, filter_col = st.columns([3, 2])
    with search_col:
        search = st.text_input("Search records", placeholder="payments, IOPS, timeout, schema…")[
            :200
        ]
    with filter_col:
        labels = ["All types", *explorer.labels]
        label = st.selectbox("Entity type", labels, index=labels.index("Component"))
    key = (label, search)
    state = st.session_state.setdefault("graph_pages", {"filter": key, "cursors": [""]})
    if state["filter"] != key:
        state = {"filter": key, "cursors": [""]}
        st.session_state.graph_pages = state
    edge_cursor = state.get("edge_cursor", "")
    page = explorer.page(
        label=label, search=search, after=state["cursors"][-1], edge_after=edge_cursor
    )
    graph = page["graph"]
    st.caption(
        f"Page {len(state['cursors'])} · {len(graph['nodes'])} records · "
        f"{len(graph['edges'])} stored relationships · All retained history. "
        "Edges connect matching records on this page only."
    )
    previous, following, more_edges = st.columns(3)
    if previous.button("Previous records", disabled=len(state["cursors"]) == 1):
        state["cursors"].pop()
        state.pop("edge_cursor", None)
        st.rerun()
    if following.button("Next records", disabled=not page["next_cursor"]):
        state["cursors"].append(page["next_cursor"])
        state.pop("edge_cursor", None)
        st.rerun()
    if more_edges.button("Next relationships", disabled=not page["next_edge_cursor"]):
        state["edge_cursor"] = page["next_edge_cursor"]
        st.rerun()
    if edge_cursor:
        if st.button("First relationships"):
            state.pop("edge_cursor", None)
            st.rerun()
    if not graph["nodes"]:
        st.info("No matching records. Try another entity type or search term.")
        return
    left, right = st.columns([3, 2], gap="large")
    with left:
        components.html(graph_html(graph, dependency_paths(graph)), height=605)
    with right:
        records = {n["id"]: n for n in graph["nodes"]}
        selected = st.selectbox("Inspect a record", list(records), format_func=short)
        st.json(records[selected], expanded=True)
