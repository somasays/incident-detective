"""Self-contained local evidence report; measured tables are built outside the LLM."""

import html
import json
from pathlib import Path

from ui.graph_view import render_evidence_graph


def report_html(package):
    def esc(value):
        return html.escape(str(value))

    def table(rows):
        if not rows:
            return "<p>No records in retrieved coverage.</p>"
        keys = list(dict.fromkeys(k for row in rows for k in row))
        return (
            "<div class='scroll'><table><tr>"
            + "".join("<th>" + esc(k) + "</th>" for k in keys)
            + "</tr>"
            + "".join(
                "<tr>"
                + "".join(
                    "<td>"
                    + esc(
                        json.dumps(row.get(k), ensure_ascii=False)
                        if isinstance(row.get(k), dict | list)
                        else row.get(k, "—")
                    )
                    + "</td>"
                    for k in keys
                )
                + "</tr>"
                for row in rows
            )
            + "</table></div>"
        )

    analysis = package.get("analysis", {})
    sections = [
        "<h1>Incident Detective · Diagnostic evidence package</h1>",
        "<p>Prepared synthetic operational data · graph-grounded investigation</p>",
        "<h2>Question and time scope</h2><pre>"
        + esc(json.dumps(package.get("request", {}), indent=2))
        + "</pre>",
        "<h2>Diagnosis</h2><p>"
        + esc(
            analysis.get(
                "summary",
                package.get("error", "Evidence retrieved; model analysis was not requested."),
            )
        )
        + "</p>",
    ]
    for hypothesis in analysis.get("hypotheses", []):
        sections += [
            "<h3>" + esc(hypothesis["title"]) + "</h3>",
            "<p>" + esc(hypothesis["explanation"]) + "</p>",
            "<p>Citations: " + esc(", ".join(hypothesis["supporting_evidence_ids"])) + "</p>",
            "<p>Missing / contradictory: "
            + esc("; ".join(hypothesis["contradicting_or_missing_evidence"]))
            + "</p>",
            "<p>Next verification: " + esc(hypothesis["next_check"]) + "</p>",
        ]
    sections += [
        "<h2>Measured values · deterministic comparisons</h2>",
        table(package.get("measurements", [])),
        "<h2>Exact observations · windows, errors, alerts and trace timings</h2>",
        table(package.get("observations", [])),
        "<h2>Historical state versions</h2>",
        table(package.get("states", [])),
        "<h2>Change timeline</h2>",
        table(package.get("changes", [])),
        "<h2>Running releases at the selected time</h2>",
        table(package.get("runningReleases", [])),
        "<h2>Code and commit provenance</h2>",
        table(
            [
                n
                for n in package.get("graph", {}).get("nodes", [])
                if n["label"] in {"CodeArtifact", "Commit", "Person"}
            ]
        ),
        "<h2>Confirmed historical findings · availability timestamps retained</h2>",
        table(package.get("historicalFindings", [])),
        "<h2>Evidence graph</h2>",
    ]
    if package.get("graph"):
        graph = render_evidence_graph(
            {"graph": package["graph"], "dependency_paths": package["topology"]["paths"]},
            {
                "analysis_available": package.get("analysisAvailable"),
                "hypotheses": analysis.get("hypotheses", []),
            },
        )
        sections.append(
            '<iframe title="Retrieved temporal evidence graph" srcdoc="'
            + html.escape(graph, quote=True)
            + '" style="width:100%;height:610px;border:0"></iframe>'
        )
    sections += [
        "<h2>Coverage and limitations</h2><pre>"
        + esc(
            json.dumps(
                [*package.get("limitations", []), *analysis.get("limitations", [])], indent=2
            )
        )
        + "</pre>",
        "<h2>Executed stages</h2>",
        table(package.get("stages", [])),
        "<h2>Query templates and parameters</h2>",
        table(package.get("queryTrace", [])),
    ]
    return (
        """<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; frame-src 'self' about:;
script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:">
<title>Incident Detective evidence package</title><style>
body{background:#0b1220;color:#e5e7eb;font:15px system-ui;margin:32px auto;
max-width:1450px;padding:20px}
h1,h2{color:#8ec7ff}p{line-height:1.7}pre{white-space:pre-wrap;overflow-wrap:anywhere}
.scroll{overflow:auto;border:1px solid #293548;border-radius:8px;margin:18px 0}
table{border-collapse:collapse;font-size:12px}
td,th{text-align:left;padding:10px;border:1px solid #293548;
min-width:100px;max-width:500px;overflow-wrap:anywhere;vertical-align:top}th{background:#172b45}
</style></head><body>"""
        + "".join(sections)
        + "</body></html>"
    )


def save_package(package, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "investigation.json").write_text(json.dumps(package, indent=2) + "\n")
    (output / "report.html").write_text(report_html(package))
    return output / "report.html"
