"""Ontology types and stored graph instances, rendered separately from investigation results."""

from collections import deque

from pyvis.network import Network

from ui.graph_view import PALETTE, build_network, render_network


def ontology_network(ontology):
    network = Network(height="590px", width="100%", directed=True, bgcolor="#FFFFFF")
    positions = {
        "Component": (0, 0),
        "Deployment": (-320, -180),
        "Incident": (320, -180),
        "Symptom": (320, 180),
        "Finding": (-320, 180),
    }
    for label, definition in ontology["entities"].items():
        x, y = positions.get(label, (0, 360))
        network.add_node(
            "ontology:" + label,
            label=label,
            x=x,
            y=y,
            shape="box",
            margin=20,
            color=PALETTE.get(label, "#526D96"),
            title=f"{label}: {len(definition['required'])} required properties",
            font={"face": "system-ui", "size": 19, "color": "#F1F5F9"},
        )
    for kind, endpoints in ontology["relationships"].items():
        for source, target in endpoints:
            network.add_edge(
                "ontology:" + source,
                "ontology:" + target,
                label=kind.replace("_", " "),
                title=f"Allowed: {source} → {kind} → {target}",
                arrows="to",
                color="#7589A9",
                width=1.6,
                selfReferenceSize=45,
                font={
                    "size": 12,
                    "color": "#475569",
                    "strokeWidth": 5,
                    "strokeColor": "#FFFFFF",
                    "align": "middle",
                },
                smooth={"enabled": True, "type": "curvedCW", "roundness": 0.18},
            )
    network.set_options(
        '{"physics":{"enabled":false},"interaction":{"hover":true},"layout":{"randomSeed":7}}'
    )
    return network


def render_ontology_graph(ontology):
    return render_network(
        ontology_network(ontology), "ONTOLOGY · ALLOWED ENTITY TYPES AND RELATIONSHIPS"
    )


def neighborhood(graph, focus_id=None, hops=2):
    """Filter only retrieved records; never invent connecting edges."""
    if not focus_id:
        return graph
    adjacency = {n["id"]: set() for n in graph["nodes"]}
    if focus_id not in adjacency:
        return {"nodes": [], "edges": []}
    for edge in graph["edges"]:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
    visited, frontier = {focus_id}, {focus_id}
    for _ in range(hops):
        frontier = {n for current in frontier for n in adjacency[current]} - visited
        visited |= frontier
    return {
        "nodes": [n for n in graph["nodes"] if n["id"] in visited],
        "edges": [e for e in graph["edges"] if e["source"] in visited and e["target"] in visited],
    }


def dependency_paths(graph):
    # Dependency paths are used only to lay out actual retrieved nodes in this explorer.
    components = {n["id"] for n in graph["nodes"] if n["label"] == "Component"}
    adjacency = {id: set() for id in components}
    dependencies = set()
    for edge in graph["edges"]:
        if edge["type"] == "DEPENDS_ON":
            adjacency[edge["source"]].add(edge["target"])
            dependencies.add(edge["target"])
    roots = sorted(components - dependencies) + sorted(dependencies)
    paths = {}
    for root in roots:
        if root in paths:
            continue
        paths[root] = [root]
        queue = deque([root])
        while queue:
            current = queue.popleft()
            for child in sorted(adjacency[current]):
                if child not in paths:
                    paths[child] = paths[current] + [child]
                    queue.append(child)
    return list(paths.values())


def render_knowledge_graph(graph):
    network = build_network(
        {"graph": graph, "dependency_paths": dependency_paths(graph)}, overview=True
    )
    return render_network(network, "STORED GRAPH · ZOOM / PAN / INSPECT · NO MODEL INFERENCE")
