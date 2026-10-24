"""PyVis data model rendered with bundled inline vis-network assets. No CDN requests."""

import html
import json
from importlib.resources import files

from pyvis.network import Network

PALETTE = {
    "Component": "#426754",
    "Deployment": "#AA7569",
    "Incident": "#B9985A",
    "Symptom": "#BE925C",
    "Finding": "#899878",
}


def visualization_id(node):
    return f"{node['label'].lower()}:{node['id']}"


def build_network(evidence: dict, analysis: dict | None = None, *, overview=False) -> Network:
    network = Network(
        height="590px",
        width="100%",
        directed=True,
        bgcolor="#FFFFFF",
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
        color = PALETTE.get(
            label,
            {
                "StorageVolume": "#7A8C68",
                "Change": "#AA7569",
                "StateSnapshot": "#708269",
                "K8sCluster": "#949B7B",
                "K8sWorkload": "#426754",
            }.get(label, "#708269"),
        )
        kind = n.get("type", n.get("kind"))
        if label == "Component" and kind in {"pipeline", "connector", "worker"}:
            color = "#7A8C68"
        elif label == "Component" and kind in {"storage", "database", "cache"}:
            color = "#708269"
        elif (
            label == "Incident" and not is_current and not (overview and n.get("status") == "open")
        ):
            color = "#949B7B"
        level = depth.get(id, 6)
        if is_current or (overview and label == "Incident"):
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
                "background": "#77594F" if id in highlighted else color,
                "border": "#C58E79" if id in highlighted else color,
                "highlight": {"background": "#426754", "border": "#AABB9E"},
            },
            borderWidth=3 if id in highlighted else 1,
            font={
                "face": "system-ui",
                "size": 13,
                "color": "#FFFFFF" if label in {"Component", "Deployment"} else "#334155",
                "multi": False,
            },
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
            color="#7D9480" if important else "#B6BEB0",
            width=2 if important else 1,
            font={"size": 9, "color": "#475569", "strokeWidth": 0, "align": "middle"},
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
    return render_network(build_network(evidence, analysis))


def render_network(
    network: Network, hint="SCROLL TO ZOOM · DRAG TO PAN · HOVER TO INSPECT", *, height=590
) -> str:

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
html,body{margin:0;background:#FDFEFB;color:#89917F;font-family:system-ui}
#graph{width:100%;height:GRAPH_HEIGHTpx;border-radius:5px}
#hint{position:absolute;bottom:14px;left:18px;font-size:11px;pointer-events:none}
</style></head><body><div id="graph"></div>
<div id="hint">"""
        + html.escape(hint)
        + """</div><script>"""
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
    ).replace("height:GRAPH_HEIGHTpx", f"height:{int(height)}px")
