"""Small, self-contained visual system for the temporal investigation workspace."""

CSS = """<style>
:root {color-scheme:dark}
.stApp {background:#0b1220}
.block-container {max-width:1520px;
  padding:2.1rem 3rem 4rem}
header[data-testid="stHeader"] {background:transparent}
#MainMenu,footer,[data-testid="stToolbar"] {visibility:hidden}
html,body,.stApp {font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
h1,h2,h3 {letter-spacing:-.035em;
  font-weight:650!important}
h3 {font-size:1.15rem!important}
[data-testid="stVerticalBlockBorderWrapper"]>div {border-color:#273448!important;
  border-radius:12px}
[data-testid="stMetricValue"] {font-size:1.45rem}
[data-testid="stMetricLabel"],.muted {color:#94a3b8}
.lab-header {display:flex;
  justify-content:space-between;
  align-items:center;
  margin:0 0 1.5rem}
.lab-kicker,.section-label {font-size:10px;
  font-weight:700;
  letter-spacing:1.8px;
  color:#74b8bf}
.lab-header h1 {font-size:30px;
  margin:5px 0 0;
  line-height:1.2}
.lab-header p {font-size:13px;
  color:#94a3b8;
  margin:8px 0}
.lab-badge {font-size:10px;
  color:#79d4c3;
  border:1px solid #285048;
  border-radius:5px;
  padding:7px 10px;
  letter-spacing:1px}
.lab-meta {font-size:12px;
  color:#94a3b8;
  padding:10px 0 18px}
.lab-note {border-left:2px solid #3c6a8e;
  padding:12px 16px;
  margin:12px 0;
  background:#101c2d;
  font-size:13px;
  color:#c1cfdf}
.diagnosis-card {background:#112a30;
  border:1px solid #275154;
  border-radius:10px;
  padding:18px;
  margin:12px 0}
.diagnosis-card h3 {color:#d8f3ee;
  margin:8px 0}
.diagnosis-card p {color:#c4d4df;
  font-size:14px;
  line-height:1.65;
  margin:8px 0}
.lab-step {padding:10px 0;
  border-bottom:1px solid #233147}
.lab-step strong {font-size:13px;
  color:#d9e3ef}
.lab-step p {font-size:12px;
  color:#94a3b8;
  margin:4px 0}
.lab-empty {border:1px dashed #304159;
  border-radius:12px;
  padding:40px 30px;
  margin:15px 0}
.lab-empty h3 {font-size:21px!important;
  margin:0 0 10px}
.lab-empty p {font-size:14px;
  color:#94a3b8;
  max-width:650px;
  line-height:1.7}
.lab-footer {font-size:11px;
  color:#788ba5;
  margin-top:25px;
  border-top:1px solid #243247;
  padding-top:15px}
@media(max-width:800px) {
  .block-container {padding:1.3rem}
  .lab-header {align-items:flex-start}
  .lab-badge {display:none}
}
</style>"""
