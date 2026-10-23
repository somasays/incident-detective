"""Dashboard CSS using system fonts and local resources only."""

CSS = """
<style>
:root {
  color-scheme:dark
}

.stApp {
  background:radial-gradient(ellipse at 80% 0%,#14233b 0,transparent 50%),#0B1220
}

.block-container {
  max-width:1550px;
  padding:2.2rem 3.2rem 3rem
}

header[data-testid="stHeader"] {
  background:transparent
}

#MainMenu,footer,[data-testid="stToolbar"] {
  visibility:hidden
}

html,body,[class*="css"],.stApp {
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif
}

h1,h2,h3 {
  letter-spacing:-.035em;
  font-weight:650!important
}

h3 {
  font-size:1.08rem!important
}

[data-testid="stVerticalBlockBorderWrapper"]>div {
  border-color:#293548!important;
  border-radius:14px!important
}

[data-testid="stMetric"] {
  padding:10px 0
}

[data-testid="stMetricLabel"] {
  color:#94A3B8;
  font-size:12px
}

[data-testid="stMetricValue"] {
  font-size:1.5rem;
  letter-spacing:-.03em
}

.masthead {
  display:flex;
  align-items:center;
  justify-content:space-between;
  padding-bottom:26px;
  border-bottom:1px solid #293548;
  margin-bottom:24px
}

.brand {
  display:flex;
  align-items:center;
  gap:14px
}

.brand-icon {
  display:grid;
  place-items:center;
  background:#172C4C;
  border:1px solid #2C4770;
  border-radius:14px;
  width:52px;
  height:52px
}

.brand h1 {
  font-size:29px;
  margin:0;
  line-height:1.2;
  letter-spacing:-1px
}

.brand p {
  color:#94A3B8;
  font-size:13px;
  margin:6px 0 0
}

.local-badge {
  font-size:10px;
  letter-spacing:1.6px;
  color:#72D7C8;
  border:1px solid #24483E;
  background:#102A29;
  border-radius:6px;
  padding:8px 11px;
  font-weight:700
}

.local-dot {
  display:inline-block;
  width:6px;
  height:6px;
  background:#2DD4BF;
  border-radius:100%;
  margin-right:7px
}

.eyebrow {
  color:#94A3B8;
  font-size:10px;
  font-weight:700;
  letter-spacing:1.7px;
  margin:0 0 8px
}

.panel-heading {
  display:flex;
  align-items:center;
  justify-content:space-between;
  margin:5px 0 14px;
  font-size:11px;
  letter-spacing:1.6px;
  font-weight:700;
  color:#C6D1E1
}

.tag {
  font-size:10px;
  color:#94A3B8;
  letter-spacing:.4px;
  padding:4px 7px;
  border:1px solid #293548;
  border-radius:5px
}

.legend {
  display:flex;
  flex-wrap:wrap;
  gap:14px;
  font-size:10px;
  color:#94A3B8;
  margin:5px 0 12px
}

.legend i {
  display:inline-block;
  width:6px;
  height:6px;
  border-radius:2px;
  margin-right:5px
}

.hypothesis {
  background:linear-gradient(120deg,#182B40,#121D30);
  border:1px solid #315271;
  border-left:3px solid #2DD4BF;
  border-radius:10px;
  padding:20px;
  margin:10px 0 16px
}

.hypothesis h2 {
  font-size:21px!important;
  line-height:1.3;
  margin:7px 0 12px;
  letter-spacing:-.5px
}

.hypothesis p {
  color:#BECBDD;
  font-size:13px;
  line-height:1.65;
  margin:0
}

.hypothesis .eyebrow {
  color:#56C6B5
}

.verification {
  background:#102E32;
  border:1px solid #1D5152;
  border-radius:9px;
  padding:15px 17px;
  margin:12px 0
}

.verification .eyebrow {
  color:#5ECABB
}

.verification p {
  font-size:13px;
  color:#D1EEEA;
  margin:0;
  line-height:1.6
}

.signal-row {
  display:flex;
  gap:12px;
  align-items:flex-start;
  padding:10px 0;
  border-bottom:1px solid #223047
}

.signal-time {
  color:#72AEDF;
  font-size:12px;
  font-variant-numeric:tabular-nums;
  min-width:48px;
  padding-top:2px
}

.signal-title {
  font-size:12px;
  color:#D5DFEB;
  line-height:1.45
}

.signal-detail {
  font-size:11px;
  color:#8396B0;
  margin-top:3px;
  line-height:1.5
}

.memory-card {
  border:1px solid #35405A;
  background:#141E32;
  border-radius:10px;
  padding:18px;
  margin:8px 0
}

.memory-id {
  color:#B6A3E5;
  font-size:12px;
  font-weight:700;
  letter-spacing:.3px
}

.memory-card p {
  font-size:13px;
  line-height:1.6;
  color:#BFCCDE;
  margin:10px 0
}

.memory-meta {
  font-size:11px;
  color:#899AB3;
  line-height:1.6
}

.empty-graph {
  display:flex;
  flex-direction:column;
  justify-content:center;
  align-items:center;
  min-height:470px;
  border:1px dashed #2A3D58;
  border-radius:12px;
  background:radial-gradient(ellipse at center,#142740 0,transparent 65%);
  text-align:center;
  padding:36px
}

.empty-graph h2 {
  font-size:24px!important;
  margin:16px 0 8px
}

.empty-graph p {
  color:#94A3B8;
  font-size:13px;
  line-height:1.7;
  max-width:360px
}

.workflow {
  display:flex;
  gap:5px;
  flex-wrap:wrap;
  color:#7893B4;
  font-size:10px;
  letter-spacing:.5px;
  margin:14px 0
}

.workflow span {
  padding:5px 8px;
  border:1px solid #22354C;
  border-radius:5px
}

.footer-note {
  color:#667C98;
  font-size:11px;
  margin-top:24px;
  padding-top:18px;
  border-top:1px solid #243047
}

div.stButton>button[kind="primary"],div.stFormSubmitButton>button[kind="primary"] {
  background:#2563EB;
  border:1px solid #4780F4;
  border-radius:8px;
  font-weight:650;
  min-height:44px
}

[data-testid="stSelectbox"]>label {
  font-size:10px;
  letter-spacing:1px;
  color:#94A3B8
}

[data-testid="stCaptionContainer"] {
  color:#8192AA;
  font-size:11px
}

[data-testid="stExpander"] {
  border-color:#293548;
  border-radius:9px
}

@media(max-width:900px){
  .block-container{
  padding:1rem
}
.masthead{
  align-items:flex-start
}
.brand h1{
  font-size:23px
}
.brand-icon{
  display:none
}
.local-badge{
  font-size:8px;
  padding:7px
}
.brand p{
  font-size:11px
}

}

</style>
"""

LOGO = """<svg width="31" height="31" viewBox="0 0 32 32" fill="none" aria-hidden="true">
<path d="M8 8L24 8L16 24Z" stroke="#64A4FA" stroke-width="1.5"/>
<circle cx="8" cy="8" r="4" fill="#2563EB" stroke="#A5CCFF"/>
<circle cx="24" cy="8" r="4" fill="#0D9488" stroke="#7CE6D6"/>
<circle cx="16" cy="24" r="4" fill="#2563EB" stroke="#A5CCFF"/></svg>"""


def header():
    return (
        "<div class='masthead'><div class='brand'><div class='brand-icon'>"
        + LOGO
        + "</div><div><h1>Incident Detective</h1><p>Graph-powered root cause investigation</p>"
        "</div></div><span class='local-badge'><i class='local-dot'></i>LOCAL DEMO</span></div>"
    )
