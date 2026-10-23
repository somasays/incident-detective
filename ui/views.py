"""Read-only workspace views. Neither view invokes an LLM."""

import json
from collections import Counter

import streamlit as st
import streamlit.components.v1 as components

from knowledge.ontology import ONTOLOGY
from ui.explorer import neighborhood, render_knowledge_graph, render_ontology_graph


def ontology_view():
    st.subheader("Ontology")
    st.write("The versioned contract that defines which facts the graph builder can store.")
    metrics = st.columns(4)
    metrics[0].metric("Ontology version", ONTOLOGY["version"])
    metrics[1].metric("Entity types", len(ONTOLOGY["entities"]))
    metrics[2].metric("Relationship types", len(ONTOLOGY["relationships"]))
    metrics[3].metric("Allowed type connections", sum(map(len, ONTOLOGY["relationships"].values())))
    left, right = st.columns([3, 2], gap="large")
    with left:
        with st.container(border=True):
            st.caption("SCHEMA MAP · TYPES AND PERMITTED DIRECTIONS")
            components.html(render_ontology_graph(ONTOLOGY), height=600, scrolling=False)
            st.caption(
                "This diagram represents types. Individual services and events appear "
                "in Knowledge Graph."
            )
    with right:
        label = st.selectbox("Inspect entity type", list(ONTOLOGY["entities"]))
        st.markdown(f"**{label} properties**")
        st.dataframe(
            [
                {"Property": key, "Type": kind, "Required": True}
                for key, kind in ONTOLOGY["entities"][label]["required"].items()
            ],
            hide_index=True,
            use_container_width=True,
        )
        st.markdown("**Allowed connections**")
        for kind, pairs in ONTOLOGY["relationships"].items():
            for source, target in pairs:
                if label in (source, target):
                    st.code(f"{source} —{kind}→ {target}", language=None)
        st.markdown("**Identity policy**")
        st.write(ONTOLOGY["identity"])
    st.subheader("How source records become facts")
    st.dataframe(
        [
            {"Input / authority": source, "Construction rule": rule}
            for source, rule in ONTOLOGY["construction_rules"].items()
        ],
        hide_index=True,
        use_container_width=True,
    )
    with st.expander("Shared provenance properties & ingestion control plane"):
        st.dataframe(
            [
                {"Property": key, "Type": kind}
                for key, kind in ONTOLOGY["common_properties"].items()
            ],
            hide_index=True,
            use_container_width=True,
        )
        st.write(ONTOLOGY["control_plane"])
    with st.expander("Exact ontology JSON"):
        st.json(ONTOLOGY)
    st.download_button(
        "Download ontology JSON",
        json.dumps(ONTOLOGY, indent=2),
        file_name="ontology.json",
        mime="application/json",
        key="download_ontology",
    )
    st.caption(
        "Source: knowledge/ontology.json · Mappings: ingestion/adapters.py · "
        "No database or model required."
    )


def node_name(node):
    return f"{node['label']} · {node.get('name', node.get('external_id', node['id']))}"


def knowledge_graph_view(repository):
    st.subheader("Knowledge Graph")
    st.write(
        "Explore the stored entities, connections and provenance before running an investigation."
    )
    scope = repository.namespace
    with st.container(border=True):
        filters = st.columns([2, 2, 2, 1])
        labels = filters[0].multiselect(
            "Entity types",
            list(ONTOLOGY["entities"]),
            list(ONTOLOGY["entities"]),
            key=f"graph_labels_{scope}",
        )
        relations = filters[1].multiselect(
            "Relationship types",
            list(ONTOLOGY["relationships"]),
            list(ONTOLOGY["relationships"]),
            key=f"graph_relations_{scope}",
        )
        incidents = repository.list_incidents()
        snapshots = {i["id"]: i for i in incidents}
        incident_id = filters[2].selectbox(
            "Dependency time",
            [None, *snapshots],
            format_func=lambda id: (
                "All recorded history"
                if id is None
                else f"{snapshots[id].get('external_id', id)} · "
                f"{snapshots[id]['timestamp'][11:16]} UTC"
            ),
            key=f"graph_time_{scope}",
        )
        limit = filters[3].selectbox(
            "Nodes per page", [50, 100, 200], index=1, key="graph_page_size"
        )
    signature = json.dumps([scope, sorted(labels), sorted(relations), incident_id, limit])
    if st.session_state.get("graph_filter_signature") != signature:
        st.session_state.graph_filter_signature = signature
        st.session_state.graph_cursors = [""]
    toolbar = st.columns([1, 1, 1, 4])
    cursors = st.session_state.graph_cursors
    if toolbar[0].button("Refresh graph", key="refresh_stored_graph"):
        cursors[:] = [""]
    if toolbar[1].button("Previous page", disabled=len(cursors) == 1):
        cursors.pop()
    at = snapshots[incident_id]["timestamp"] if incident_id else None
    page = repository.graph_page(
        labels, relations, after_id=cursors[-1], node_limit=limit, incident_time=at
    )
    if toolbar[2].button("Next page", disabled=not page["has_more_nodes"]):
        cursors.append(page["nodes"][-1]["id"])
        st.rerun()
    toolbar[3].caption(
        f"Page {len(cursors)} · {len(page['nodes'])} nodes · {len(page['edges'])} relationships"
    )
    st.caption(
        "Each page shows connections between its displayed nodes. "
        "Dependency time filters DEPENDS_ON edges; stored events and latest component "
        "metadata remain visible."
    )
    if page["has_more_nodes"] or page["has_more_edges"]:
        st.warning(
            "This view reached its display budget. Page forward or narrow the filters; "
            "connections may be omitted."
        )
    if not page["nodes"]:
        st.info(
            "No entities match these filters. "
            "Refresh after the source ingester commits new records."
        )
        return
    nodes = {n["id"]: n for n in page["nodes"]}
    counts = Counter(n["label"] for n in page["nodes"])
    for column, label in zip(st.columns(5), ONTOLOGY["entities"], strict=True):
        column.metric(label, counts[label])
    graph_column, inspector = st.columns([3, 1.3], gap="large")
    with inspector:
        focus = st.selectbox(
            "Focus within this page",
            [None, *nodes],
            format_func=lambda id: "All displayed nodes" if id is None else node_name(nodes[id]),
            key=f"graph_focus_{scope}",
        )
        hops = st.select_slider("Neighborhood hops", [0, 1, 2, 3], value=2, disabled=focus is None)
        visible = neighborhood(page, focus, hops)
        st.caption("Focus follows stored connections in either direction within this page.")
        selected = st.selectbox(
            "Inspect stored node",
            list(nodes),
            format_func=lambda id: node_name(nodes[id]),
            key=f"inspect_stored_node_{scope}",
        )
        with st.expander("Node properties", expanded=True):
            st.json(nodes[selected])
        if visible["edges"]:
            edge_index = st.selectbox(
                "Inspect stored relationship",
                range(len(visible["edges"])),
                format_func=lambda index: (
                    f"{node_name(nodes[visible['edges'][index]['source']])} "
                    f"—{visible['edges'][index]['type']}→ "
                    f"{node_name(nodes[visible['edges'][index]['target']])}"
                ),
                key=f"inspect_stored_edge_{scope}",
            )
            with st.expander("Relationship properties", expanded=True):
                st.json(visible["edges"][edge_index])
    with graph_column:
        with st.container(border=True):
            st.caption(
                "STORED KNOWLEDGE · BLUE COMPONENTS / TEAL PIPELINES / RED RELEASES / AMBER SIGNALS"
            )
            components.html(render_knowledge_graph(visible), height=600, scrolling=False)
            st.caption(
                "Dashed dependencies were observed in traces. "
                "Hover for source references. Layout is fixed."
            )
        st.download_button(
            "Download displayed graph JSON",
            json.dumps(visible, indent=2),
            file_name="knowledge-graph.json",
            mime="application/json",
            key="download_stored_graph",
        )
