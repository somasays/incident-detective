"""Local, system-font styling for the evidence canvas and investigation panel."""
CSS = """<style>
:root {color-scheme:light;
  --paper:#f5f6f2;
  --ink:#303c33;
  --muted:#858b7f;
  --line:#e0e4db;
  --forest:#365747;
  --sage:#edf0e7}
.stApp {background:var(--paper);
  color:var(--ink)}
.block-container {max-width:1640px;
  padding:0 2rem 2rem}
header[data-testid="stHeader"] {height:0;
  background:transparent}
#MainMenu,footer,[data-testid="stToolbar"] {visibility:hidden}
html,body,.stApp {font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
[data-testid="stMainBlockContainer"]>[data-testid="stVerticalBlock"] {gap:.65rem}
h1,h2,h3 {letter-spacing:-.03em;
  font-weight:600!important;
  color:var(--ink)}
h3 {font-size:1.05rem!important}
.stCaption p,[data-testid="stCaptionContainer"] p {color:var(--muted);
  font-size:11px}
.stButton button,.stDownloadButton button,[data-testid="stFormSubmitButton"] button {
  border-radius:5px;
  font-size:12px;
  min-height:36px;
  border-color:var(--line)}
.stButton button:hover,.stDownloadButton button:hover {color:var(--forest);
  border-color:#82937c}
button[kind="primary"],button[kind="primaryFormSubmit"]
  {background:var(--forest);
  border-color:var(--forest)}
[data-baseweb="input"],[data-baseweb="textarea"]
  {background:#fff;
  border-color:var(--line);
  border-radius:5px}
[data-testid="stExpander"] {border-color:var(--line);
  border-radius:5px}
[data-testid="stExpander"] summary {font-size:11px;
  min-height:32px}
[data-testid="stTabs"] [data-baseweb="tab-list"] {gap:17px;
  border-bottom:1px solid var(--line)}
[data-testid="stTabs"] [data-baseweb="tab"] {font-size:12px;
  height:38px;
  padding:0
  1px;
  color:var(--muted)}
[data-testid="stTabs"] [aria-selected="true"] {color:var(--forest)!important}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {background:var(--forest);
  height:2px}
[data-testid="stVerticalBlockBorderWrapper"]>div
  {border-color:var(--line)!important;
  border-radius:7px}
.lab-header {display:flex;
  align-items:center;
  justify-content:space-between;
  height:67px;
  background:#fff;
  border-bottom:1px solid var(--line);
  margin:0 -2rem;
  padding:0 2rem}
.brand {display:flex;
  align-items:center;
  gap:11px}
.brand strong {font-size:22px;
  font-weight:650;
  letter-spacing:-1px;
  color:#293a30}
.brand-mark {display:grid;
  place-items:center;
  background:var(--forest);
  color:#f5f6f2;
  width:29px;
  height:29px;
  border-radius:7px;
  font-size:24px}
.brand-divider {height:21px;
  width:1px;
  background:var(--line);
  margin:0 7px}
.workspace-label,.header-status {font-size:11px;
  color:var(--muted)}
.header-status {display:flex;
  align-items:center;
  gap:7px}
.avatar {width:28px;
  height:28px;
  border-radius:50%;
  display:grid;
  place-items:center;
  margin-left:14px;
  background:var(--sage);
  font-size:10px;
  color:#59634f}
.status-dot
  {display:inline-block;
  width:5px;
  height:5px;
  border-radius:50%;
  background:#7f9679;
  margin-right:5px}
.st-key-workspace_navigation [role="radiogroup"] {gap:22px;
  margin:6px 0 0}
.st-key-workspace_navigation [role="radiogroup"] label {margin:0;
  padding:3px 0}
.st-key-workspace_navigation [role="radiogroup"] label>div:first-child {display:none}
.st-key-workspace_navigation [role="radiogroup"] label p {font-size:12px;
  color:var(--muted)}
.st-key-workspace_navigation label:has(input:checked) p {color:var(--forest);
  font-weight:600}
.st-key-investigation_controls {padding:4px 0 0}
.st-key-investigation_controls>.stVerticalBlock {gap:.35rem}
.st-key-investigation_controls .stButton button {background:transparent;
  min-height:29px;
  color:#697260;
  border-color:var(--line);
  font-size:11px}
.st-key-investigation_controls [data-testid="stWidgetLabel"] p {font-size:11px;
  color:#6d7767}
.st-key-investigation_controls [data-testid="stForm"] [data-testid="stVerticalBlock"] {gap:.4rem}
.st-key-investigation_controls [data-testid="stExpander"] {border:0}
.st-key-investigation_controls [data-testid="stExpander"] summary
  {padding:0;
  min-height:23px;
  color:var(--muted)}
.case-heading {display:flex;
  align-items:center;
  justify-content:space-between;
  margin:1px 0 -7px}
.case-heading>div>span {color:var(--muted);
  font-size:9px;
  letter-spacing:1px}
.case-heading h1 {font-size:21px;
  line-height:1.25;
  margin:4px 0 2px}
.case-mode {font-size:10px;
  padding:5px 8px;
  border-radius:4px;
  background:var(--sage);
  color:#65765c}
.st-key-evidence_canvas {background:#fff;
  overflow:hidden;
  padding:0!important;
  gap:0}
.st-key-evidence_canvas>[data-testid="stVerticalBlock"] {gap:0}
.canvas-heading {display:flex;
  align-items:center;
  gap:11px;
  min-height:38px;
  padding:0 14px;
  font-size:11px;
  border-bottom:1px solid var(--line);
  color:var(--muted)}
.canvas-heading>span:first-child {color:var(--ink);
  font-weight:600}
.canvas-tag {margin-left:auto;
  background:var(--sage);
  padding:4px
  6px;
  color:#6a7a60;
  font-size:10px;
  border-radius:3px}
.canvas-empty
  {height:515px;
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:center;
  text-align:center;
  background:radial-gradient(ellipse at center,#f3f5ed,#fdfefb 65%);
  padding:30px}
.empty-mark {font-size:36px;
  color:#86957b;
  margin-bottom:24px}
.canvas-empty h2 {font:29px Georgia,'Times New Roman',serif!important;
  letter-spacing:-.8px;
  margin:12px 0}
.canvas-empty p {max-width:390px;
  color:var(--muted);
  font-size:13px;
  line-height:1.8}
.empty-legend {display:flex;
  gap:22px;
  margin-top:35px;
  font-size:10px;
  color:#7b8871}
.empty-legend span:before {content:'';
  display:inline-block;
  background:#819276;
  width:6px;
  height:6px;
  border-radius:2px;
  margin-right:7px}
.canvas-footer {display:flex;
  align-items:center;
  gap:12px;
  padding:12px 14px;
  border-top:1px solid
  var(--line);
  background:#fcfdf9;
  color:var(--ink)}
.run-symbol {background:var(--sage);
  color:#748568;
  border-radius:50%;
  width:29px;
  height:29px;
  display:grid;
  place-items:center;
  font-size:18px}
.canvas-footer strong {display:block;
  font-size:11px;
  font-weight:600}
.canvas-footer>div>span {display:block;
  font-size:10px;
  color:var(--muted);
  margin-top:3px}
.evidence-scale {display:flex;
  flex:1;
  gap:4px;
  margin:0 6px 0 22px}
.evidence-scale i {height:3px;
  background:#e9ece4;
  flex:1;
  border-radius:4px}
.evidence-scale i.filled {background:#7c9070}
.run-count {font-size:10px;
  color:var(--muted);
  white-space:nowrap}
.findings-heading
  {display:flex;
  align-items:center;
  justify-content:space-between;
  font-size:11px;
  margin-top:5px}
.findings-heading strong {font-weight:600}
.findings-heading span {font-size:10px;
  color:var(--muted)}
.st-key-investigation_panel {background:#fff;
  padding:0 17px 15px!important;
  scrollbar-width:thin;
  scrollbar-color:#dfe4d6 transparent}
.st-key-investigation_panel [data-testid="stTabs"] [data-baseweb="tab"] {font-size:11px}
.assistant-intro {margin:15px 0 18px}
.section-label {font-size:8px;
  font-weight:600;
  letter-spacing:1.5px;
  color:#89917f}
.assistant-intro h2 {font:27px/1.2 Georgia,'Times New Roman',serif!important;
  letter-spacing:-.9px;
  margin:10px 0 12px;
  color:#30392e}
.assistant-intro p {font-size:11px;
  line-height:1.7;
  color:var(--muted);
  max-width:260px}
.question-card {border:1px solid
  #e8ebe2;
  border-radius:5px;
  padding:14px;
  background:#f6f7f1;
  margin-bottom:20px}
.question-card p {font-size:12px;
  line-height:1.65;
  color:#4b5846;
  margin:9px 0 12px}
.question-card>span:last-child {font-size:9px;
  color:#89917f}
.timeline-heading
  {display:flex;
  align-items:center;
  justify-content:space-between;
  font-size:11px;
  margin:17px 0}
.timeline-heading strong {font-weight:600}
.timeline-heading span {font-size:9px;
  color:#929989}
.activity-timeline {list-style:none;
  margin:0;
  padding:0 0 0 15px}
.activity-timeline li {border-left:1px solid #e4e8de;
  padding:0 0 24px 18px;
  position:relative}
.activity-timeline li:last-child {border-color:transparent;
  padding-bottom:10px}
.timeline-dot
  {position:absolute;
  left:-10px;
  top:0;
  width:19px;
  height:19px;
  border-radius:50%;
  background:#f0f3ea;
  color:#8c9b7c;
  font-size:11px;
  display:grid;
  place-items:center;
  border:2px solid #fff}
.activity-timeline h4 {font-size:12px;
  line-height:1.5;
  font-weight:550;
  margin:4px 0
  5px;
  color:#47533e}
.activity-timeline p {font-size:10px;
  line-height:1.7;
  color:#929989;
  margin:0;
  overflow-wrap:anywhere}
.activity-timeline .pending .timeline-dot {background:#e4ebdc}
.diagnosis-card {background:#f4f6ee;
  border:1px solid
  #d9e0cf;
  border-radius:5px;
  padding:15px;
  margin:12px 0}
.diagnosis-card h3 {font:22px/1.25 Georgia,'Times New Roman',serif!important;
  color:#40573f;
  margin:9px 0}
.diagnosis-card p {color:#68725f;
  font-size:12px;
  line-height:1.7;
  margin:10px 0}
.diagnosis-card .muted {font-size:10px;
  color:#89917f}
.evidence-facts {display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:10px;
  margin:8px 0}
.evidence-fact {padding:12px 13px;
  border:1px solid var(--line);
  border-radius:5px;
  background:#fff;
  min-width:0;
  font-size:10px;
  color:#4f5c47;
  overflow-wrap:anywhere}
.evidence-fact strong {display:block;
  font-size:20px;
  letter-spacing:-.4px;
  color:#40533c;
  margin:4px 0;
  font-variant-numeric:tabular-nums;
  font-weight:550}
.evidence-fact span,.fact-resource {color:#929989;
  font-size:9px}
.evidence-fact span {display:block;
  margin-top:4px}
.st-key-investigation_panel .evidence-facts {grid-template-columns:1fr}
.st-key-investigation_panel .evidence-fact {padding:9px 12px}
.st-key-investigation_panel .evidence-fact strong {font-size:17px}
.st-key-investigation_panel [data-testid="stMarkdownContainer"] p {font-size:12px}
.hypothesis-heading {display:flex;
  align-items:center;
  gap:8px;
  margin:0 0 10px}
.hypothesis-heading h3 {flex:1;
  margin:0!important;
  font-size:14px!important}
.hypothesis-number {font-size:10px;
  color:#6b7f5c;
  background:#eef2e8;
  padding:4px
  6px;
  border-radius:4px}
.outcome {font-size:8px;
  text-transform:uppercase;
  letter-spacing:.5px;
  padding:4px
  6px;
  border-radius:3px;
  background:#f1f3ed;
  color:#7a866f;
  white-space:nowrap;
  align-self:flex-start}
.outcome.supported {color:#496b3c;
  background:#eaf2e4}
.outcome.refuted {color:#9c6057;
  background:#f8eae6}
.outcome.unresolved,.outcome.validating {color:#9b8953;
  background:#f7f2df}
.check-row {display:flex;
  gap:8px;
  align-items:flex-start;
  border-top:1px solid
  var(--line);
  padding:12px 0 6px}
.check-row>div {flex:1;
  min-width:0}
.check-number {color:#89917f;
  font-size:10px;
  padding-top:2px;
  font-variant-numeric:tabular-nums}
.check-row strong {font-size:11px;
  font-weight:600}
.check-resources {color:#7e8972;
  font-size:10px;
  margin-top:3px;
  overflow-wrap:anywhere}
.check-result {color:#929989;
  font-size:10px;
  margin-top:3px}
.lab-footer {display:flex;
  justify-content:space-between;
  gap:10px;
  font-size:9px;
  color:#929989;
  margin-top:15px;
  border-top:1px solid var(--line);
  padding-top:12px}
@media(max-width:800px) {
  .block-container {padding:0 1rem 1rem}
  .lab-header {margin:0 -1rem;
  padding:0 1rem;
  height:57px}
  .brand strong {font-size:18px}
  .workspace-label,.brand-divider,.header-status .avatar {display:none}
  .case-heading h1 {font-size:19px}
  .evidence-facts {grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}
  .evidence-scale {margin-left:5px}
  .canvas-tag {display:none}
  .lab-footer {flex-direction:column}
}
</style>"""
