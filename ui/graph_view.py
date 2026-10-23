"""PyVis data model rendered with bundled inline vis-network assets. No CDN requests."""

import html
import json
from importlib.resources import files

from pyvis.network import Network

PALETTE = {
    "Component": "#2563EB",
    "Deployment": "#B83C49",
    "Incident": "#D97706",
    "Symptom": "#E59A38",
    "Finding": "#8B78CE",
}


def visualization_id(node):
    return f"{node['label'].lower()}:{node['id']}"


def build_network(evidence: dict, analysis: dict | None = None) -> Network:
    network = Network(
        height="590px",
        width="100%",
        directed=True,
        bgcolor="#0B1423",
        font_color="#E5E7EB",
        cdn_resources="in_line",
    )
    graph = evidence.get("graph", {"nodes": [], "edges": []})
    nodes = {n["id"]: n for n in graph["nodes"]}
    current = evidence.get("incident", {}).get("id")
    highlighted = set()
    if analysis and analysis.get("analysis_available") and analysis.get("hypotheses"):
        highlighted.add(analysis["hypotheses"][0].get("cause_entity_id"))
    depth = {}
    for path in evidence.get("dependency_paths", []):
        for index, id in enumerate(path):
            depth[id] = min(depth.get(id, 99), index + 1)
    for id, n in nodes.items():
        label = n["label"]
        is_current = label == "Incident" and id == current
        color = PALETTE[label]
        if label == "Component" and n.get("type") in {"pipeline", "connector", "worker"}:
            color = "#0D9488"
        elif label == "Component" and n.get("type") in {"storage", "cache"}:
            color = "#526D96"
        elif label == "Incident" and not is_current:
            color = "#7861AA"
        level = depth.get(id, 6)
        if is_current:
            level = 0
        elif label == "Deployment":
            targets = [
                e["target"] for e in graph["edges"] if e["source"] == id and e["type"] == "CHANGED"
            ]
            level = max([depth.get(t, 5) + 1 for t in targets], default=6)
        elif label == "Symptom":
            targets = [
                e["target"]
                for e in graph["edges"]
                if e["source"] == id and e["type"] == "OBSERVED_ON"
            ]
            level = max([depth.get(t, 4) for t in targets], default=4)
        title = "<br>".join(
            html.escape(str(x))
            for x in [
                n.get("name", id),
                label + (" · " + n["type"] if n.get("type") else ""),
                n.get("timestamp", n.get("created_at", "")),
                n.get("description", n.get("message", n.get("conclusion", n.get("summary", "")))),
                n.get("source_ref", ""),
            ]
            if x
        )
        display_id = n.get("external_id", id)
        name = n.get("name", n.get("type", display_id) if label == "Symptom" else display_id)
        if label == "Deployment":
            name = display_id + "\n" + n.get("version", "")
        network.add_node(
            visualization_id(n),
            label=name.replace(" ", "\n", 1) if len(name) > 15 else name,
            title=title,
            level=level,
            shape="box" if label in {"Component", "Deployment"} else "dot",
            size=15 if label == "Symptom" else 19,
            color={
                "background": "#702938" if id in highlighted else color,
                "border": "#FF6B76" if id in highlighted else color,
                "highlight": {"background": "#2563EB", "border": "#93C5FD"},
            },
            borderWidth=3 if id in highlighted else 1,
            font={"face": "system-ui", "size": 13, "color": "#F1F5F9", "multi": False},
            margin=13,
        )
    for e in graph["edges"]:
        if e["source"] not in nodes or e["target"] not in nodes:
            raise ValueError("Graph relationship endpoint was not retrieved.")
        important = e["type"] == "DEPENDS_ON" or bool({e["source"], e["target"]} & highlighted)
        network.add_edge(
            visualization_id(nodes[e["source"]]),
            visualization_id(nodes[e["target"]]),
            label=e["type"].replace("_", " "),
            title=html.escape(
                e["type"]
                + " · "
                + e.get("properties", {}).get("method", "seeded")
                + " · "
                + e.get("properties", {}).get("source_ref", "manual fixture")
            ),
            arrows="to",
            dashes=e.get("properties", {}).get("method") == "observed_trace",
            color="#5686B8" if important else "#394860",
            width=2 if important else 1,
            font={"size": 9, "color": "#9DACBF", "strokeWidth": 0, "align": "middle"},
        )
    network.set_options(
        json.dumps(
            {
                "layout": {
                    "hierarchical": {
                        "enabled": True,
                        "direction": "UD",
                        "sortMethod": "directed",
                        "levelSeparation": 110,
                        "nodeSpacing": 170,
                        "treeSpacing": 190,
                        "blockShifting": False,
                        "edgeMinimization": True,
                        "parentCentralization": True,
                    }
                },
                "physics": {"enabled": False},
                "interaction": {
                    "hover": True,
                    "navigationButtons": False,
                    "keyboard": True,
                    "tooltipDelay": 100,
                    "zoomView": True,
                },
                "edges": {
                    "smooth": {
                        "enabled": True,
                        "type": "cubicBezier",
                        "forceDirection": "vertical",
                        "roundness": 0.35,
                    },
                    "arrows": {"to": {"scaleFactor": 0.65}},
                },
            }
        )
    )
    return network


def _inline_asset(name):
    return files("pyvis").joinpath("templates", "lib", "vis-9.1.2", name).read_text()


def render_evidence_graph(evidence: dict, analysis: dict | None = None) -> str:
    network = build_network(evidence, analysis)

    # Escape JSON's script terminator, including potentially hostile event/confirmation text.
    def js(value):
        return (
            json.dumps(value, ensure_ascii=True)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
        )

    options = network.options if isinstance(network.options, dict) else network.options.to_json()
    if isinstance(options, str):
        options = json.loads(options)
    return (
        """<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline';
style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'">
<style>"""
        + _inline_asset("vis-network.css")
        + """
html,body{margin:0;background:#0B1423;color:#94A3B8;font-family:system-ui}
#graph{width:100%;height:590px;border-radius:12px}
#hint{position:absolute;bottom:14px;left:18px;font-size:11px;pointer-events:none}
</style></head><body><div id="graph"></div>
<div id="hint">SCROLL TO ZOOM · DRAG TO PAN · HOVER TO INSPECT</div>
<script>"""
        + _inline_asset("vis-network.min.js")
        + """</script><script>
const nodes=new vis.DataSet("""
        + js(network.nodes)
        + """);
const edges=new vis.DataSet("""
        + js(network.edges)
        + """);
const network=new vis.Network(document.getElementById('graph'),{nodes,edges},"""
        + js(options)
        + """);
network.once('afterDrawing',()=>network.fit({animation:false}));
</script></body></html>"""
    )
