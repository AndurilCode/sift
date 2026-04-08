"""
Generate a self-contained HTML dashboard from NormalizedSession data.
All metrics computed client-side from per-session data, enabling interactive filters.
Design: Cursor editor aesthetic + engineering metrics UX best practices.
"""

from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime

from sift.sources.base import NormalizedSession
from sift.metrics import estimate_cost, session_cost

OUTPUT_DIR = Path.home() / ".sift"


def _build_data(sessions: list[NormalizedSession], source_names: dict) -> dict:
    """Build per-session data for client-side filtering + aggregation."""
    rows = []
    for s in sessions:
        cost = session_cost(s)
        child_cost = sum(estimate_cost(c.usage, c.model) for c in s.children)
        compaction_children = sum(1 for c in s.children if "acompact" in c.extras.get("subagent_file", ""))
        tc = s.tool_calls

        # Include children's tokens so JS totals match Python's flatten_with_children
        child_input = sum(c.usage.input_tokens for c in s.children)
        child_output = sum(c.usage.output_tokens for c in s.children)
        child_cache_read = sum(c.usage.cache_read_tokens for c in s.children)
        child_cache_write = sum(c.usage.cache_write_tokens for c in s.children)
        child_tokens = sum(c.total_tokens for c in s.children)

        rows.append({
            "id": s.session_id[:12],
            "source": s.source,
            "source_name": source_names.get(s.source, s.source),
            "project": s.project,
            "date": s.date,
            "model": s.model or "unknown",
            "cost": round(cost, 4),
            "tokens": s.total_tokens + child_tokens,
            "input": s.usage.input_tokens + child_input,
            "output": s.usage.output_tokens + child_output,
            "parent_output": s.usage.output_tokens,
            "cache_read": s.usage.cache_read_tokens + child_cache_read,
            "cache_write": s.usage.cache_write_tokens + child_cache_write,
            "tool_calls": s.total_tool_calls,
            "edits": tc.get("Edit", 0) + tc.get("edit", 0) + tc.get("replace_string_in_file", 0) + tc.get("multi_replace_string_in_file", 0) + tc.get("replace", 0) + tc.get("apply_patch", 0),
            "writes": tc.get("Write", 0) + tc.get("create", 0) + tc.get("create_file", 0) + tc.get("write_file", 0),
            "reads": tc.get("Read", 0) + tc.get("view", 0) + tc.get("read_file", 0) + tc.get("read_many_files", 0),
            "msgs": s.assistant_messages,
            "turns": s.turns,
            "dur": s.duration_seconds or 0,
            "children": len(s.children),
            "child_cost": round(child_cost, 4),
            "compactions": compaction_children,
            "tbfw": s.extras.get("turns_before_first_write"),
            "premium": s.extras.get("premium_requests", 0),
            "tool_overhead": s.extras.get("context_info", {}).get("tool_definitions_tokens", 0),
            "ctx_tokens": s.extras.get("context_info", {}).get("current_tokens", 0),
            "stop_reasons": s.extras.get("stop_reasons", {}),
            "tools": dict(s.tool_calls),
            "lines_read": s.extras.get("lines_read", 0),
            "lines_gen": s.extras.get("lines_generated", 0) or s.extras.get("lines_added", 0),
            "prompt_lengths": [len(p.get("text", "")) for p in s.prompts if isinstance(p.get("text", ""), str) and p.get("text", "").strip()],
        })

    return {
        "generated": datetime.now().isoformat(),
        "source_names": source_names,
        "sessions": rows,
    }


_HTML = (
    r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sift — AI Usage Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
:root{
  --bg:#181818;--surface:#232323;--elevated:#2a2a2a;--hover:#333;
  --text:#e4e4e4;--text2:#888;--text3:#666;
  --border:#333;--border2:#2a2a2a;
  --accent:#7c5aed;--accent-dim:rgba(124,90,237,.12);
  --blue:#60a5fa;--green:#22c55e;--yellow:#f59e0b;--red:#ef4444;--orange:#f97316;--pink:#ec4899;--teal:#14b8a6;
  --sidebar-w:200px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font:13px/1.5 system-ui,-apple-system,sans-serif}
::selection{background:var(--accent-dim)}

/* ── Sidebar ── */
.sidebar{position:fixed;top:0;left:0;width:var(--sidebar-w);height:100vh;background:var(--surface);border-right:1px solid var(--border2);display:flex;flex-direction:column;z-index:20;transition:transform .25s ease}
.sidebar-brand{padding:16px 16px 12px;border-bottom:1px solid var(--border2)}
.sidebar-brand h1{font-size:13px;font-weight:700;color:var(--text);line-height:1.3}
.sidebar-brand p{font-size:10px;color:var(--text3);margin-top:2px}
.sidebar-nav{padding:8px 0;border-bottom:1px solid var(--border2)}
.sidebar-nav a{display:flex;align-items:center;gap:8px;padding:7px 16px;font-size:12px;color:var(--text2);text-decoration:none;border-left:2px solid transparent;transition:all .15s}
.sidebar-nav a:hover{color:var(--text);background:var(--hover)}
.sidebar-nav a.active{color:var(--accent);border-left-color:var(--accent);background:var(--accent-dim)}
.sidebar-nav .nav-icon{width:16px;text-align:center;font-size:13px;flex-shrink:0}
.sidebar-toggle{display:none;position:fixed;top:12px;left:12px;z-index:25;background:var(--surface);border:1px solid var(--border);border-radius:6px;color:var(--text2);width:32px;height:32px;font-size:16px;cursor:pointer;align-items:center;justify-content:center}

/* ── Sidebar filters ── */
.sidebar-filters{flex:1;overflow-y:auto;padding:12px 16px}
.sf-section{margin-bottom:14px}
.sf-label{font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:.5px;font-weight:600;margin-bottom:6px}
.sf-select-all{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text3);cursor:pointer;margin-bottom:4px;padding:2px 0}
.sf-select-all input[type=checkbox]{accent-color:var(--accent);width:13px;height:13px}
.sf-checks{max-height:120px;overflow-y:auto;display:flex;flex-direction:column;gap:2px}
.sf-checks label{display:flex;align-items:center;gap:8px;padding:4px 0;font-size:11px;color:var(--text2);cursor:pointer;line-height:1.3}
.sf-checks label:hover{color:var(--text)}
.sf-checks input[type=checkbox]{accent-color:var(--accent);width:13px;height:13px;flex-shrink:0}
.sf-date{display:flex;flex-direction:column;gap:4px}
.sf-date input[type=date]{background:var(--elevated);color:var(--text);border:1px solid var(--border);border-radius:5px;padding:4px 8px;font-size:11px;width:100%;outline:none}
.sf-date input:focus{border-color:var(--accent)}
.sf-range{display:flex;gap:4px;margin-top:6px}
.sf-btns{display:flex;gap:4px;margin-top:10px}
.btn{border:none;border-radius:6px;padding:5px 12px;font-size:11px;font-weight:500;cursor:pointer;transition:opacity .15s}
.btn-primary{background:var(--accent);color:#fff}.btn-primary:hover{opacity:.85}
.btn-ghost{background:var(--elevated);color:var(--text2);border:1px solid var(--border)}.btn-ghost:hover{background:var(--hover)}
.btn-sm{padding:4px 8px;font-size:10px}
.sidebar-status{padding:8px 16px;border-top:1px solid var(--border2);font-size:10px;color:var(--text3)}

/* ── Main content ── */
.main{margin-left:var(--sidebar-w);padding:24px 32px;min-height:100vh}

/* Header */
.header{margin-bottom:20px}
.header p{font-size:12px;color:var(--text2)}

/* Active filter pills in main area */
.pills-bar{margin-bottom:20px;display:flex;gap:6px;align-items:center;flex-wrap:wrap;min-height:24px}
.pill{font-size:11px;background:var(--accent-dim);color:var(--accent);padding:2px 8px;border-radius:9999px;display:flex;align-items:center;gap:4px}
.pill button{background:none;border:none;color:var(--accent);cursor:pointer;font-size:11px;padding:0}

/* Grid */
.grid{display:grid;gap:12px;margin-bottom:20px}
.g-kpi{grid-template-columns:repeat(auto-fill,minmax(165px,1fr))}

/* KPI clusters */
.kpi-cluster{margin-bottom:16px}
.kpi-cluster-label{font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:.6px;font-weight:600;margin-bottom:8px;padding-left:2px}
.kpi-cluster .grid{margin-bottom:0}
.g4{grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}
.g3{grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
.g2{grid-template-columns:repeat(auto-fill,minmax(340px,1fr))}

/* Cards */
.card{background:var(--surface);border-radius:8px;padding:16px 20px}
.card-sm{padding:12px 14px}
.card h3{font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:.5px;font-weight:600;margin-bottom:6px}
.stat{font-size:20px;font-weight:700;font-family:system-ui,sans-serif;letter-spacing:-.02em}
.stat-sm{font-size:11px;color:var(--text2);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stat-green{color:var(--green)}.stat-yellow{color:var(--yellow)}.stat-red{color:var(--red)}.stat-accent{color:var(--accent)}
.card-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px}
.card-hdr h3{margin-bottom:0}
.info-btn{width:16px;height:16px;border-radius:9999px;border:1px solid var(--border);background:none;color:var(--text3);font-size:10px;font-weight:600;cursor:pointer;display:flex;align-items:center;justify-content:center;position:relative;flex-shrink:0;font-style:italic;font-family:Georgia,serif;line-height:1}
.info-btn:hover{border-color:var(--accent);color:var(--accent)}
.tooltip{display:none;position:fixed;width:280px;background:var(--elevated);border:1px solid var(--border);border-radius:8px;padding:12px;font:normal 12px/1.6 system-ui,-apple-system,sans-serif;color:var(--text2);z-index:50;box-shadow:0 8px 24px rgba(0,0,0,.5);text-align:left;letter-spacing:0;text-transform:none;pointer-events:none}
.info-btn:hover .tooltip{display:block}
.tooltip .tt-title{font-weight:600;font-size:12px;margin-bottom:4px;color:var(--text);font-style:normal}
.tooltip .tt-good{color:var(--green);font-size:10px;margin-top:4px}.tooltip .tt-bad{color:var(--red);font-size:10px;margin-top:2px}

/* Sections */
.section{margin-bottom:28px;scroll-margin-top:24px}
.section-hdr{display:flex;align-items:center;justify-content:space-between;cursor:pointer;padding:8px 0;border-bottom:1px solid var(--border2);margin-bottom:16px;user-select:none}
.section-hdr h2{font-size:13px;font-weight:600;color:var(--text)}
.section-hdr .chevron{font-size:11px;color:var(--text3);transition:transform .2s}
.section-hdr.collapsed .chevron{transform:rotate(-90deg)}
.section-body{transition:max-height .3s ease}
.section-body.hidden{max-height:0!important;overflow:hidden}

/* Gauge */
.gauge{position:relative;width:100%;max-width:140px;margin:0 auto}
.gauge-label{text-align:center;font-size:11px;color:var(--text3);margin-top:4px}

/* Charts */
.cc{position:relative;height:260px}.cl{position:relative;height:320px}
.cc-tall{position:relative;height:320px}

/* Tables */
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:var(--text3);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.3px;padding:6px 10px;border-bottom:1px solid var(--border)}
td{padding:6px 10px;border-bottom:1px solid var(--border2);color:var(--text)}
tr:hover td{background:var(--elevated)}
.table-scroll{max-height:400px;overflow-y:auto}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-block;padding:1px 8px;border-radius:9999px;font-size:11px;font-weight:500;background:var(--accent-dim);color:var(--accent)}

/* ── Responsive ── */
@media(max-width:900px){
  .sidebar{transform:translateX(-100%)}
  .sidebar.open{transform:translateX(0)}
  .sidebar-toggle{display:flex}
  .main{margin-left:0;padding:24px 16px;padding-top:52px}
  .g2,.g3,.g4,.g5{grid-template-columns:1fr}
}
</style></head><body>

<!-- Sidebar -->
<button class="sidebar-toggle" id="sidebar-toggle" onclick="document.getElementById('sidebar').classList.toggle('open')">&#9776;</button>
<nav class="sidebar" id="sidebar">
  <div class="sidebar-brand">
    <h1>Sift</h1>
    <p id="nav-sub">Dashboard</p>
  </div>
  <div class="sidebar-nav" id="sidebar-nav">
    <a href="#s-kpis" data-section="s-kpis"><span class="nav-icon">&#9632;</span>Overview</a>
    <a href="#s-burn" data-section="s-burn"><span class="nav-icon">&#9650;</span>Spend</a>
    <a href="#s-eff" data-section="s-eff"><span class="nav-icon">&#9673;</span>Efficiency</a>
    <a href="#s-break" data-section="s-break"><span class="nav-icon">&#9638;</span>Breakdowns</a>
    <a href="#s-ctx" data-section="s-ctx"><span class="nav-icon">&#9881;</span>Context</a>
    <a href="#s-tables" data-section="s-tables"><span class="nav-icon">&#9776;</span>Details</a>
  </div>
  <div class="sidebar-filters">
    <div class="sf-section">
      <div class="sf-label">Platforms</div>
      <label class="sf-select-all"><input type="checkbox" checked onchange="toggleAll('f-plats',this.checked)">Select all</label>
      <div class="sf-checks" id="f-plats"></div>
    </div>
    <div class="sf-section">
      <div class="sf-label">Projects</div>
      <label class="sf-select-all"><input type="checkbox" checked onchange="toggleAll('f-projs',this.checked)">Select all</label>
      <div class="sf-checks" id="f-projs" style="max-height:160px"></div>
    </div>
    <div class="sf-section">
      <div class="sf-label">Date Range</div>
      <div class="sf-date">
        <input type="date" id="f-from" onchange="goDebounced()">
        <input type="date" id="f-to" onchange="goDebounced()">
      </div>
      <div class="sf-range">
        <button class="btn btn-ghost btn-sm" onclick="setRange(7)">7d</button>
        <button class="btn btn-ghost btn-sm" onclick="setRange(30)">30d</button>
        <button class="btn btn-ghost btn-sm" onclick="setRange(90)">90d</button>
        <button class="btn btn-ghost btn-sm" onclick="setRange(0)">All</button>
      </div>
    </div>
    <div class="sf-btns">
      <button class="btn btn-ghost" onclick="rst()" style="flex:1">Reset filters</button>
    </div>
  </div>
  <div class="sidebar-status" id="sidebar-status"></div>
</nav>

<!-- Main content -->
<div class="main" id="main-content">

<div class="header">
  <p id="sub"></p>
</div>

<div class="pills-bar" id="pills"></div>

<!-- KPIs -->
<div class="section" id="s-kpis">
  <div class="section-hdr" onclick="toggle('s-kpis')"><h2>Overview</h2><span class="chevron">&#9660;</span></div>
  <div class="section-body" id="kpis">
    <div class="kpi-cluster"><div class="kpi-cluster-label">Cost & Usage</div><div class="grid g-kpi" id="kpi-cost"></div></div>
    <div class="kpi-cluster"><div class="kpi-cluster-label">Cache & Context</div><div class="grid g-kpi" id="kpi-cache"></div></div>
    <div class="kpi-cluster"><div class="kpi-cluster-label">Health & Productivity</div><div class="grid g-kpi" id="kpi-health"></div></div>
  </div>
</div>

<!-- Primary: Daily Burn -->
<div class="section" id="s-burn">
  <div class="section-hdr" onclick="toggle('s-burn')"><h2>Spend Over Time</h2><span class="chevron">&#9660;</span></div>
  <div class="section-body"><div class="card" data-info="burn"><h3>Daily Spend</h3><div class="cl"><canvas id="c-burn"></canvas></div></div></div>
</div>

<!-- Gauges -->
<div class="section" id="s-eff">
  <div class="section-hdr" onclick="toggle('s-eff')"><h2>Efficiency Gauges</h2><span class="chevron">&#9660;</span></div>
  <div class="section-body"><div class="grid g3" id="gauges"></div></div>
</div>

<!-- Breakdowns -->
<div class="section" id="s-break">
  <div class="section-hdr" onclick="toggle('s-break')"><h2>Breakdowns</h2><span class="chevron">&#9660;</span></div>
  <div class="section-body">
    <div class="grid g2">
      <div class="card" data-info="plat"><h3>Cost by Platform</h3><div class="cc"><canvas id="c-plat"></canvas></div></div>
      <div class="card" data-info="model"><h3>Cost by Model</h3><div class="cc"><canvas id="c-model"></canvas></div></div>
      <div class="card" data-info="tools"><h3>Top Tools</h3><div class="cc-tall"><canvas id="c-tools"></canvas></div></div>
      <div class="card" data-info="projects"><h3>Top Projects</h3><div class="cc-tall"><canvas id="c-proj"></canvas></div></div>
    </div>
  </div>
</div>

<!-- Context -->
<div class="section" id="s-ctx">
  <div class="section-hdr" onclick="toggle('s-ctx')"><h2>Context Efficiency</h2><span class="chevron">&#9660;</span></div>
  <div class="section-body">
    <div class="grid g2">
      <div class="card" data-info="stop"><h3>Stop Reasons</h3><div class="cc"><canvas id="c-stop"></canvas></div></div>
      <div class="card" data-info="erw"><h3>Productivity: Edit / Read / Write</h3><div class="cc"><canvas id="c-erw"></canvas></div></div>
      <div class="card" data-info="health"><h3>Session Size Distribution</h3><div class="cc"><canvas id="c-health"></canvas></div></div>
      <div class="card" id="tbfw-card" data-info="tbfw"><h3>Turns Before First Write</h3><div class="cc"><canvas id="c-tbfw"></canvas></div></div>
      <div class="card" id="pl-card" data-info="promptLen"><h3>Prompt Length Distribution</h3><div class="cc"><canvas id="c-pl"></canvas></div></div>
      <div class="card" id="dur-card" data-info="durTrend"><h3>Session Duration Trend</h3><div class="cc"><canvas id="c-dur"></canvas></div></div>
    </div>
  </div>
</div>

<!-- Tables -->
<div class="section" id="s-tables">
  <div class="section-hdr" onclick="toggle('s-tables')"><h2>Details</h2><span class="chevron">&#9660;</span></div>
  <div class="section-body">
    <div class="card" data-info="platTable" style="margin-bottom:12px"><h3>Platform Comparison</h3><div><table id="t1"></table></div></div>
    <div class="card" data-info="sessTable"><h3>Most Costly Sessions</h3><div class="table-scroll"><table id="t2"></table></div></div>
  </div>
</div>

</div><!-- /main -->

<script>
const RAW=%%DATA_JSON%%;
const ALL=RAW.sessions,SN=RAW.source_names;
let F=ALL;const CH={};
const P=['#7c5aed','#60a5fa','#22c55e','#f59e0b','#f97316','#ef4444','#ec4899','#14b8a6','#84cc16','#06b6d4'];
const fmt={
  usd:n=>'$'+n.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}),
  tok:n=>Math.round(n).toLocaleString(),
  pct:n=>(n*100).toFixed(1)+'%',
  pct0:n=>Math.round(n*100)+'%'
};
let _goTimer=0;
function goDebounced(){clearTimeout(_goTimer);_goTimer=setTimeout(go,150)}
function sum(a,f){return a.reduce((s,x)=>s+(typeof f==='function'?f(x):x[f]||0),0)}
function med(a){const s=[...a].sort((a,b)=>a-b);return s.length?s[s.length>>1]:0}
function grp(a,k){const m={};a.forEach(x=>{const v=typeof k==='function'?k(x):x[k];(m[v]=m[v]||[]).push(x)});return m}

// ── Filters (checkbox-based) ──
const allDates=ALL.map(s=>s.date).filter(Boolean).sort();
const minD=allDates[0]||'',maxD=allDates[allDates.length-1]||'';

function initF(){
  // Platforms
  const pf=document.getElementById('f-plats');pf.innerHTML='';
  [...new Set(ALL.map(s=>s.source))].sort().forEach(src=>{
    const id='fp-'+src.replace(/\W/g,'');
    pf.innerHTML+=`<label title="${SN[src]||src}"><input type="checkbox" id="${id}" value="${src}" checked onchange="goDebounced()">${SN[src]||src}</label>`;
  });
  // Projects
  const pr=document.getElementById('f-projs');pr.innerHTML='';
  [...new Set(ALL.map(s=>s.project))].sort().forEach(p=>{
    const id='fj-'+p.replace(/\W/g,'').slice(0,20);
    const short=p.length>28?p.slice(0,28)+'...':p;
    pr.innerHTML+=`<label title="${p}"><input type="checkbox" class="proj-cb" value="${p}" checked onchange="goDebounced()">${short}</label>`;
  });
  // Dates
  if(minD){document.getElementById('f-from').value=minD;document.getElementById('f-to').value=maxD}
}
function getChecked(containerId){
  return [...document.querySelectorAll('#'+containerId+' input[type=checkbox]')]
    .filter(cb=>cb.checked).map(cb=>cb.value);
}
function getUnchecked(containerId){
  return [...document.querySelectorAll('#'+containerId+' input[type=checkbox]')]
    .filter(cb=>!cb.checked).map(cb=>cb.value);
}
function go(){
  const plats=new Set(getChecked('f-plats')),projs=new Set(getChecked('f-projs')),
        fr=document.getElementById('f-from').value,to=document.getElementById('f-to').value;
  F=ALL.filter(s=>{
    if(!plats.has(s.source))return false;
    if(!projs.has(s.project))return false;
    if(fr&&(!s.date||s.date<fr))return false;
    if(to&&(!s.date||s.date>to))return false;
    return true;
  });
  showPills();render();
  document.getElementById('sidebar-status').textContent=F.length+' of '+ALL.length+' sessions';
}
function rst(){
  document.querySelectorAll('#f-plats input,#f-projs input').forEach(cb=>cb.checked=true);
  if(minD){document.getElementById('f-from').value=minD;document.getElementById('f-to').value=maxD}
  F=ALL;showPills();render();
  document.getElementById('sidebar-status').textContent=F.length+' of '+ALL.length+' sessions';
}
function setRange(days){
  if(days===0){
    document.getElementById('f-from').value=minD;
    document.getElementById('f-to').value=maxD;
  } else {
    const t=new Date(),f=new Date();f.setDate(f.getDate()-days);
    document.getElementById('f-from').value=f.toISOString().slice(0,10);
    document.getElementById('f-to').value=t.toISOString().slice(0,10);
  }
  go();
}
function showPills(){
  const el=document.getElementById('pills');el.innerHTML='';
  const offPlats=getUnchecked('f-plats'),offProjs=getUnchecked('f-projs'),
        fr=document.getElementById('f-from').value,to=document.getElementById('f-to').value;
  // Show pills for unchecked platforms (inverted: show what's filtered OUT)
  offPlats.forEach(src=>{
    el.innerHTML+=`<span class="pill">-${SN[src]||src}<button onclick="document.querySelector('#f-plats input[value=&quot;${src}&quot;]').checked=true;go()">&#10005;</button></span>`;
  });
  offProjs.forEach(p=>{
    const short=p.length>20?p.slice(0,20)+'...':p;
    el.innerHTML+=`<span class="pill">-${short}<button onclick="document.querySelector('#f-projs input[value=&quot;${CSS.escape(p)}&quot;]').checked=true;go()">&#10005;</button></span>`;
  });
  if(fr&&fr!==minD)el.innerHTML+=`<span class="pill">From: ${fr}<button onclick="document.getElementById('f-from').value='${minD}';go()">&#10005;</button></span>`;
  if(to&&to!==maxD)el.innerHTML+=`<span class="pill">To: ${to}<button onclick="document.getElementById('f-to').value='${maxD}';go()">&#10005;</button></span>`;
  if(!el.innerHTML)el.innerHTML=`<span style="font-size:11px;color:var(--text3)">Showing all ${F.length} sessions</span>`;
}

function toggleAll(containerId,checked){
  document.querySelectorAll('#'+containerId+' input[type=checkbox]').forEach(cb=>cb.checked=checked);
  clearTimeout(_goTimer);go();
}

// ── Collapsible sections ──
function toggle(id){
  const s=document.getElementById(id),h=s.querySelector('.section-hdr'),b=s.querySelector('.section-body');
  h.classList.toggle('collapsed');b.classList.toggle('hidden');
}

// ── Chart helpers ──
function mc(id,cfg){if(CH[id])CH[id].destroy();CH[id]=new Chart(document.getElementById(id),cfg)}
function dg(parent,id,value,max,color,label,sublabel,info){
  const el=document.createElement('div');el.className='card card-sm';
  const tip=info?`<button class="info-btn" onmouseenter="positionTip(this)">i<div class="tooltip"><div class="tt-title">${info.title||sublabel}</div>${info.desc||''}<div class="tt-good">\u2713 Good: ${info.good||''}</div><div class="tt-bad">\u2717 Bad: ${info.bad||''}</div></div></button>`:'';
  el.innerHTML=`<div class="card-hdr"><h3>${sublabel}</h3>${tip}</div><div class="gauge"><canvas id="${id}"></canvas></div>`;
  parent.appendChild(el);
  const p=Math.min(value/max,1);
  mc(id,{type:'doughnut',data:{datasets:[{data:[p*100,100-p*100],backgroundColor:[color,'rgba(255,255,255,.04)'],borderWidth:0,circumference:270,rotation:225}]},
  options:{cutout:'75%',responsive:true,plugins:{legend:{display:false},tooltip:{enabled:false}}},
  plugins:[{id:'t',afterDraw(c){const{ctx:x,width:w,height:h}=c;x.save();x.textAlign='center';x.fillStyle='#e4e4e4';x.font='bold 18px system-ui,sans-serif';x.fillText(label,w/2,h/2+6);x.restore()}}]});
}

// ── KPI card with threshold coloring + info tooltip ──
function kpi(parent,label,value,sub,color,info){
  const d=document.createElement('div');d.className='card card-sm';
  const cls=color?` stat-${color}`:'';
  const tip=info?`<button class="info-btn" onmouseenter="positionTip(this)">i<div class="tooltip"><div class="tt-title">${info.title||label}</div>${info.desc||''}<div class="tt-good">\u2713 Good: ${info.good||''}</div><div class="tt-bad">\u2717 Bad: ${info.bad||''}</div></div></button>`:'';
  d.innerHTML=`<div class="card-hdr"><h3>${label}</h3>${tip}</div><div class="stat${cls}">${value}</div><div class="stat-sm">${sub}</div>`;
  parent.appendChild(d);
}
function positionTip(btn){
  const tip=btn.querySelector('.tooltip');if(!tip)return;
  const r=btn.getBoundingClientRect();
  // Position fixed relative to viewport
  const spaceBelow=window.innerHeight-r.bottom;
  const spaceRight=window.innerWidth-r.right;
  // Vertical: prefer below, flip up if not enough space
  if(spaceBelow<200){tip.style.top='';tip.style.bottom=(window.innerHeight-r.top+4)+'px'}
  else{tip.style.bottom='';tip.style.top=(r.bottom+4)+'px'}
  // Horizontal: prefer right-aligned to button, shift left if clipped
  if(spaceRight<290){tip.style.left='';tip.style.right='12px'}
  else{tip.style.right='';tip.style.left=Math.max(8,r.left-130)+'px'}
}

// ── Render ──
function render(){
  if(F.length===0){
    // Clear everything when no sessions match
    Object.keys(CH).forEach(k=>{CH[k].destroy();delete CH[k]});
    ['kpi-cost','kpi-cache','kpi-health','gauges'].forEach(id=>{const e=document.getElementById(id);if(e)e.innerHTML=''});
    document.getElementById('sub').textContent='0 sessions match current filters';
    document.getElementById('t1').innerHTML='';document.getElementById('t2').innerHTML='';
    return;
  }
  const n=F.length,tc=sum(F,'cost'),to=sum(F,'output'),tpo=sum(F,'parent_output'),ti=sum(F,'input'),cr=sum(F,'cache_read'),cw=sum(F,'cache_write'),
    tt=sum(F,'tokens'),ttc=sum(F,'tool_calls'),te=sum(F,'edits'),tw=sum(F,'writes'),tr=sum(F,'reads'),
    tm=sum(F,'msgs'),tcc=sum(F,'child_cost'),tcmp=sum(F,'compactions'),
    prod=te+tw,ai=ti+cr+cw,chr=cr/Math.max(ai,1),
    freshInput=ti+to+cw,or_net=to/Math.max(freshInput,1),or_gross=to/Math.max(tt,1),
    fr=ti/Math.max(ti+cr,1),ca=cr/Math.max(cw,1),
    tos=F.filter(s=>s.tool_overhead>0),tov=sum(tos,'tool_overhead')/Math.max(sum(tos,'ctx_tokens'),1),
    ds=F.filter(s=>s.dur>0),
    tbfw=F.map(s=>s.tbfw).filter(v=>v!=null),nw=F.filter(s=>s.tbfw==null&&s.tool_calls>0).length,
    tka=F.map(s=>s.tokens).filter(t=>t>0),mk=med(tka),
    sr={};F.forEach(s=>{for(const[k,v]of Object.entries(s.stop_reasons||{}))sr[k]=(sr[k]||0)+v});
    const srt=Object.values(sr).reduce((a,b)=>a+b,0),
    tls={};F.forEach(s=>{for(const[k,v]of Object.entries(s.tools||{}))tls[k]=(tls[k]||0)+v});

  document.getElementById('sub').textContent=`${n.toLocaleString()} of ${ALL.length.toLocaleString()} sessions \u00b7 ${Object.keys(SN).length} sources \u00b7 Generated ${new Date(RAW.generated).toLocaleString()}`;

  // ── KPIs (clustered) ──
  const kCost=document.getElementById('kpi-cost');kCost.innerHTML='';
  const kCache=document.getElementById('kpi-cache');kCache.innerHTML='';
  const kHealth=document.getElementById('kpi-health');kHealth.innerHTML='';
  const cps=tc/Math.max(n,1);

  // Cluster 1: Cost & Usage
  kpi(kCost,'Total Cost',fmt.usd(tc),`${fmt.usd(cps)}/session`,null,
    {desc:'Total estimated spend across all AI coding tools based on per-model token pricing.',good:'Trending down or stable',bad:'Unexpected spikes or sustained growth'});
  kpi(kCost,'Sessions',n.toLocaleString(),`${Object.keys(grp(F,'project')).length} projects`,null,
    {desc:'Number of AI assistant sessions. More sessions = more adoption, but watch cost per session.',good:'Growing adoption with stable cost/session',bad:'High session count with no productivity gain'});
  kpi(kCost,'Cost/Action',fmt.usd(tc/Math.max(prod,1)),`${prod.toLocaleString()} Edit+Write`,null,
    {desc:'Cost per code-modifying action (Edit + Write). The real price of each code change the AI makes.',good:'Decreasing over time',bad:'Rising means more context overhead per productive action'});
  const costMin=ds.length?sum(ds,'cost')/Math.max(sum(ds,'dur')/60,.01):0;
  kpi(kCost,'Cost/Minute',fmt.usd(costMin),`${ds.length} sessions w/ duration`,null,
    {desc:'Time-normalized spend. Reveals if long sessions are cost-efficient or wasteful.',good:'Stable or decreasing',bad:'High and rising \u2014 sessions accumulating expensive context'});

  // Session outcome (heuristic)
  const prodSess=F.filter(s=>s.edits+s.writes>0).length;
  const failSess=F.filter(s=>{
    const sr=s.stop_reasons||{},st=Object.values(sr).reduce((a,b)=>a+b,0);
    const maxTok=sr.max_tokens||0;
    if(st>0&&maxTok/st>0.3)return true;
    if(s.tool_calls>=10&&s.edits+s.writes===0)return true;
    return false;
  }).length;
  const successRate=prodSess/Math.max(n,1),failRate=failSess/Math.max(n,1);
  kpi(kCost,'Success Rate',fmt.pct(successRate),`${prodSess} productive \u00b7 ${failSess} failed`,successRate>.6?'green':successRate>.3?'yellow':'red',
    {desc:'Heuristic success rate. Success = session has Edit/Write actions. Failure = max_tokens dominated, or many tool calls with zero production.',good:'Above 60%',bad:'Below 30% \u2014 too many sessions produce nothing'});

  // Retry/waste ratio
  const retryHeavy=F.filter(s=>{
    if(s.tool_calls<5)return false;
    const tc=s.tools||{},vals=Object.values(tc),tot=vals.reduce((a,b)=>a+b,0);
    if(tot<5)return false;
    const topV=Math.max(...vals),dom=topV/tot;
    const bash=(tc.Bash||0)+(tc.bash||0)+(tc.BashOutput||0),br=bash/tot;
    return dom>0.6||br>0.5;
  });
  const retryCost=sum(retryHeavy,'cost'),retryPct=retryHeavy.length/Math.max(F.filter(s=>s.tool_calls>=5).length,1);
  kpi(kCost,'Retry Ratio',fmt.pct(retryPct),`${retryHeavy.length} sessions \u00b7 ${fmt.usd(retryCost)}`,retryPct<.2?'green':retryPct<.4?'yellow':'red',
    {desc:'Sessions dominated by a single tool or bash-heavy patterns, indicating retry/debug loops.',good:'Below 20%',bad:'Above 40% \u2014 significant token waste from retries'});

  // Cluster 2: Cache & Context
  kpi(kCache,'Output Ratio',fmt.pct(or_net),`${fmt.tok(tpo)} output tokens \u00b7 Gross: ${fmt.pct(or_gross)}`,or_net<0.01?'red':or_net<0.03?'yellow':'green',
    {desc:'Output tokens vs fresh input (excluding cache reads). Net ratio shows how much new output is generated per unit of new input. Gross includes cache replays.',good:'Net above 2% for coding tasks',bad:'Net below 1% means heavy context overhead even after caching'});
  kpi(kCache,'Cache Hit Rate',fmt.pct(chr),`Saving ${fmt.usd(cr/1e6*2.7)}`,chr>.7?'green':chr>.4?'yellow':'red',
    {desc:'Fraction of input tokens served from cache (10x cheaper than uncached). Measures how well prompts reuse prior context.',good:'Above 70% \u2014 stable prompt prefixes',bad:'Below 40% \u2014 prompts changing too much between turns'});
  kpi(kCache,'Input Freshness',fmt.pct(fr),fr<.1?'Stable prompts':'High \u2014 poor reuse',fr<.1?'green':fr<.3?'yellow':'red',
    {desc:'Fraction of input that is uncached (new). Lower means prompts are stable and cache is effective.',good:'Below 10% by turn 20',bad:'Above 30% means prompt structure keeps changing'});
  kpi(kCache,'Cache Amortization',ca.toFixed(1)+'x',ca>1?'Net positive':'Net negative',ca>5?'green':ca>1?'yellow':'red',
    {desc:'How many times each cache write is reused. Cache writes cost 25% more than regular input, so you need at least 1 read per write to break even.',good:'Above 5x \u2014 excellent ROI on caching',bad:'Below 1x \u2014 paying more for cache writes than you save'});
  kpi(kCache,'Context Growth',fmt.tok(tt/Math.max(tm,1))+'/msg',`Median: ${fmt.tok(med(F.filter(s=>s.msgs>0).map(s=>s.tokens/s.msgs)))}/msg`,null,
    {desc:'Average tokens consumed per assistant turn. Each turn replays the full conversation, so this grows as sessions get longer.',good:'Below 100K tokens/msg',bad:'Above 500K \u2014 sessions are accumulating too much context per turn'});
  if(tos.length)kpi(kCache,'Tool Def Overhead',fmt.pct(tov),`${tos.length} sessions`,tov>.3?'red':tov>.15?'yellow':'green',
    {desc:'Fraction of the context window consumed by tool/function schemas alone, before any messages. Measured from Copilot CLI shutdown data.',good:'Below 15%',bad:'Above 30% \u2014 too many tools registered, eating context'});

  // Cluster 3: Health & Productivity
  kpi(kHealth,'Bloat Index',(Math.max(...tka,0)/Math.max(mk,1)).toFixed(0)+'x',`${tka.filter(t=>t>5e7).length} over 50M`,Math.max(...tka,0)/Math.max(mk,1)>100?'red':'yellow',
    {desc:'Ratio of the most expensive session to the median. High values mean a few sessions dominate cost.',good:'Below 50x \u2014 consistent session sizes',bad:'Above 200x \u2014 runaway sessions distort spend'});
  kpi(kHealth,'Subagent Overhead',fmt.pct(tcc/Math.max(tc,.01)),`${fmt.pct(tcmp/Math.max(F.filter(s=>s.source==='claude-code').length,1))} compaction`,null,
    {desc:'Percentage of total cost from spawned subagents. Each subagent duplicates base context. Compaction agents fire when sessions blow the context window.',good:'Below 10% with low compaction',bad:'Above 20% \u2014 consider CLAUDE_CODE_SUBAGENT_MODEL=haiku'});
  if(tbfw.length)kpi(kHealth,'Turns Before Write',(sum(tbfw,v=>v)/tbfw.length).toFixed(1),`Median: ${med(tbfw)} \u00b7 Never: ${nw}`,'accent',
    {desc:'How many exploration tool calls (Read, Bash, Grep) happen before the first production action (Edit, Write). Measures ramp-up time.',good:'Below 10 for focused tasks',bad:'Above 25 \u2014 prompts may be too vague, causing excessive exploration'});
  // Duration trend: compare first half vs second half
  if(ds.length>4){
    const sortedDur=[...ds].sort((a,b)=>(a.date||'').localeCompare(b.date||'')).map(s=>s.dur/60);
    const mid=sortedDur.length>>1;
    const medFirst=sortedDur.slice(0,mid).sort((a,b)=>a-b)[sortedDur.slice(0,mid).length>>1]||0;
    const medSecond=sortedDur.slice(mid).sort((a,b)=>a-b)[sortedDur.slice(mid).length>>1]||0;
    const trend=medFirst>0?(medSecond-medFirst)/medFirst:0;
    const dir=trend>0?'longer':'shorter';
    kpi(kHealth,'Duration Trend',(trend*100).toFixed(0)+'%',`${medFirst.toFixed(1)} \u2192 ${medSecond.toFixed(1)} min (${dir})`,Math.abs(trend)>.2?'yellow':'green',
      {desc:'Change in median session duration comparing first half vs second half of sessions (chronological). Positive = sessions getting longer.',good:'Within \u00b120%',bad:'Above +30% \u2014 context bloat creeping in'});
  }

  // Prompt length
  const allPL=F.flatMap(s=>s.prompt_lengths||[]).filter(v=>v>0);
  if(allPL.length>0){
    const sorted=[...allPL].sort((a,b)=>a-b);
    const medPL=sorted[sorted.length>>1];
    const short50=sorted.filter(v=>v<50).length,long10k=sorted.filter(v=>v>=10000).length;
    kpi(kHealth,'Prompt Length',medPL.toLocaleString()+' chars',`${allPL.length} prompts \u00b7 ${short50} short \u00b7 ${long10k} long`,null,
      {desc:'Median user prompt length in characters. Short (<50) prompts cause excessive exploration. Long (>10K) prompts waste context \u2014 use files instead.',good:'100-500 chars \u2014 focused and specific',bad:'<50 (vague) or >10K (paste-heavy)'});
  }

  // Model routing efficiency
  const opusLight=F.filter(s=>s.model&&s.model.toLowerCase().includes('opus')&&(s.tool_calls<10||s.output<5000));
  if(opusLight.length>0){
    const opusCost=sum(opusLight,'cost');
    const savingsEst=opusCost*0.4;
    kpi(kHealth,'Routing Savings',fmt.usd(savingsEst),`${opusLight.length} light Opus sessions`,savingsEst>10?'yellow':'green',
      {desc:'Estimated savings from routing lightweight Opus sessions (<10 tools or <5K output tokens) to Sonnet. Assumes ~40% cost reduction.',good:'Near $0 \u2014 already optimally routed',bad:'Large savings available from model routing'});
  }

  const tlr=sum(F,'lines_read'),tlg=sum(F,'lines_gen'),lrSessions=F.filter(s=>s.lines_read>0||s.lines_gen>0).length;
  if(lrSessions>0)kpi(kHealth,'Lines Read/Generated',tlg>0?(tlr/tlg).toFixed(1)+'x':'\u221e',`${tlr.toLocaleString()} read \u00b7 ${tlg.toLocaleString()} generated`,null,
    {desc:'Ratio of lines read from files vs net lines generated (Write + Edit delta). Shows how much context the AI consumes per line of output.',good:'Below 3x \u2014 focused, efficient generation',bad:'Above 10x \u2014 excessive reading relative to output'});

  // ── Gauges ──
  const gg=document.getElementById('gauges');gg.innerHTML='';
  dg(gg,'g1',or_net,.1,'#7c5aed',fmt.pct(or_net),'Output Ratio (net)',
    {desc:'Output tokens vs fresh input. Shows how much new content the model generates per unit of new input.',good:'Above 2% for coding tasks',bad:'Below 1% \u2014 heavy context overhead'});
  dg(gg,'g2',chr,1,'#22c55e',fmt.pct(chr),'Cache Hit Rate',
    {desc:'Fraction of input tokens served from cache (10x cheaper). Measures prompt prefix stability.',good:'Above 70%',bad:'Below 40% \u2014 prompts changing too much'});
  dg(gg,'g3',1-fr,1,fr<.1?'#22c55e':'#f59e0b',fmt.pct(fr),'Input Freshness',
    {desc:'Fraction of input that is uncached (new). Lower = stable prompts with good cache reuse.',good:'Below 10%',bad:'Above 30% \u2014 poor cache utilization'});
  if(tos.length)dg(gg,'g4',tov,1,tov>.3?'#ef4444':'#22c55e',fmt.pct(tov),'Tool Def Overhead',
    {desc:'Context window consumed by tool/function schemas before any messages.',good:'Below 15%',bad:'Above 30% \u2014 too many tools registered'});
  if(prod+tr>0)dg(gg,'g5',Math.min(prod/Math.max(tr,1),3),3,'#60a5fa',(prod/Math.max(tr,1)).toFixed(2),'Edit/Read Ratio',
    {desc:'Production actions (Edit+Write) vs exploration (Read). Shows whether sessions produce code or just read it.',good:'Above 1.0 \u2014 producing more than exploring',bad:'Below 0.5 \u2014 stuck in exploration loops'});

  // ── Burn chart (area) ──
  // Fill missing dates — only between first and last active day (skip long inactive tails)
  const bd=grp(F,'date'),rawDates=Object.keys(bd).filter(Boolean).sort();
  let bk=[];
  if(rawDates.length>=2){
    // Find first and last dates that actually have spend
    const activeDates=rawDates.filter(d=>sum(bd[d],'cost')>0);
    if(activeDates.length>=2){
      const d0=new Date(activeDates[0]+'T00:00:00'),d1=new Date(activeDates[activeDates.length-1]+'T00:00:00');
      for(let d=new Date(d0);d<=d1;d.setDate(d.getDate()+1)){bk.push(d.toISOString().slice(0,10))}
    } else {bk=rawDates}
  } else {bk=rawDates}
  const bc=bk.map(d=>bd[d]?sum(bd[d],'cost'):0),
    ba=bk.map((_,i)=>{const start=Math.max(0,i-6);const w=bc.slice(start,i+1);return w.reduce((a,b)=>a+b,0)/w.length});
  mc('c-burn',{type:'line',data:{labels:bk,datasets:[
    {label:'Daily Cost',data:bc,fill:true,backgroundColor:'rgba(124,90,237,.15)',borderColor:'#7c5aed',borderWidth:1.5,pointRadius:0,tension:.3},
    {label:'7d Avg',data:ba,borderColor:'#f59e0b',borderWidth:2,borderDash:[6,3],pointRadius:0,tension:.3},
  ]},options:{responsive:true,maintainAspectRatio:false,interaction:{intersect:false,mode:'index'},
    scales:{x:{ticks:{color:'#666',font:{size:10},maxRotation:45,autoSkip:true,maxTicksLimit:20},grid:{color:'rgba(255,255,255,.03)'}},y:{ticks:{color:'#666',font:{size:11},callback:v=>'$'+v},grid:{color:'rgba(255,255,255,.04)'}}},
    plugins:{legend:{labels:{color:'#888',font:{size:11}}},tooltip:{callbacks:{label:ctx=>ctx.dataset.label+': '+fmt.usd(ctx.raw)}}}}});

  // ── Platform donut ──
  const bp=grp(F,'source_name'),pn=Object.keys(bp);
  mc('c-plat',{type:'doughnut',data:{labels:pn,datasets:[{data:pn.map(k=>sum(bp[k],'cost')),backgroundColor:P.slice(0,pn.length),borderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'60%',plugins:{legend:{position:'bottom',labels:{color:'#888',padding:8,font:{size:10},boxWidth:10}},tooltip:{callbacks:{label:ctx=>`${ctx.label}: ${fmt.usd(ctx.raw)}`}}}}});

  // ── Model donut ──
  const bm=Object.entries(grp(F,'model')).map(([k,v])=>({n:k,c:sum(v,'cost')})).sort((a,b)=>b.c-a.c).slice(0,8);
  mc('c-model',{type:'doughnut',data:{labels:bm.map(x=>x.n),datasets:[{data:bm.map(x=>x.c),backgroundColor:P.slice(0,bm.length),borderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'60%',plugins:{legend:{position:'bottom',labels:{color:'#888',padding:8,font:{size:10},boxWidth:10}},tooltip:{callbacks:{label:ctx=>`${ctx.label}: ${fmt.usd(ctx.raw)}`}}}}});

  // ── Tools bar ──
  const ts2=Object.entries(tls).sort((a,b)=>b[1]-a[1]).slice(0,12);
  if(ts2.length)mc('c-tools',{type:'bar',data:{labels:ts2.map(t=>t[0]),datasets:[{data:ts2.map(t=>t[1]),backgroundColor:'rgba(124,90,237,.4)',hoverBackgroundColor:'rgba(124,90,237,.6)',borderRadius:4}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,scales:{x:{ticks:{color:'#666',font:{size:11}},grid:{color:'rgba(255,255,255,.04)'}},y:{ticks:{color:'#888',font:{size:11}},grid:{display:false}}},plugins:{legend:{display:false}}}});

  // ── Projects bar ──
  const pp=Object.entries(grp(F,'project')).map(([k,v])=>({n:k,c:sum(v,'cost')})).sort((a,b)=>b.c-a.c).slice(0,10);
  mc('c-proj',{type:'bar',data:{labels:pp.map(x=>x.n.length>28?x.n.slice(0,28)+'...':x.n),datasets:[{data:pp.map(x=>x.c),backgroundColor:'rgba(34,197,94,.4)',hoverBackgroundColor:'rgba(34,197,94,.6)',borderRadius:4}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,scales:{x:{ticks:{color:'#666',font:{size:11},callback:v=>'$'+v},grid:{color:'rgba(255,255,255,.04)'}},y:{ticks:{color:'#888',font:{size:11}},grid:{display:false}}},plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>fmt.usd(ctx.raw)}}}}});

  // ── Stop reasons ──
  const srK=Object.keys(sr);
  if(srK.length)mc('c-stop',{type:'doughnut',data:{labels:srK,datasets:[{data:srK.map(k=>sr[k]),backgroundColor:P.slice(0,srK.length),borderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'60%',plugins:{legend:{position:'bottom',labels:{color:'#888',padding:8,font:{size:10},boxWidth:10}},tooltip:{callbacks:{label:ctx=>`${ctx.label}: ${(ctx.raw/srt*100).toFixed(1)}%`}}}}});

  // ── Edit/Read/Write ──
  if(te||tw||tr)mc('c-erw',{type:'bar',data:{labels:['Edit','Write','Read'],datasets:[{data:[te,tw,tr],backgroundColor:['#7c5aed','#22c55e','#60a5fa'],borderRadius:4}]},
    options:{responsive:true,maintainAspectRatio:false,scales:{x:{ticks:{color:'#888',font:{size:11}},grid:{display:false}},y:{ticks:{color:'#666',font:{size:11}},grid:{color:'rgba(255,255,255,.04)'}}},plugins:{legend:{display:false}}}});

  // ── Session health histogram ──
  const bkts=[{l:'<100K',x:1e5},{l:'100K-1M',x:1e6},{l:'1M-10M',x:1e7},{l:'10M-50M',x:5e7},{l:'50M+',x:Infinity}];
  const hc=bkts.map(()=>0);F.forEach(s=>{for(let i=0;i<bkts.length;i++){if(s.tokens<=bkts[i].x){hc[i]++;break}}});
  mc('c-health',{type:'bar',data:{labels:bkts.map(b=>b.l),datasets:[{data:hc,backgroundColor:['#22c55e','#60a5fa','#7c5aed','#f59e0b','#ef4444'],borderRadius:4}]},
    options:{responsive:true,maintainAspectRatio:false,scales:{x:{ticks:{color:'#888',font:{size:11}},grid:{display:false}},y:{ticks:{color:'#666',font:{size:11}},grid:{color:'rgba(255,255,255,.04)'}}},plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>ctx.raw+' sessions'}}}}});

  // ── Turns before first write histogram ──
  const tbfwCard=document.getElementById('tbfw-card');
  if(tbfw.length>0){
    tbfwCard.style.display='';
    const tb=[{l:'0',x:0},{l:'1-5',x:5},{l:'6-10',x:10},{l:'11-20',x:20},{l:'21-50',x:50},{l:'50+',x:Infinity}];
    const tbc=tb.map(()=>0);tbfw.forEach(v=>{for(let i=0;i<tb.length;i++){if(v<=tb[i].x){tbc[i]++;break}}});
    mc('c-tbfw',{type:'bar',data:{labels:tb.map(b=>b.l),datasets:[{data:tbc,backgroundColor:'rgba(124,90,237,.4)',hoverBackgroundColor:'rgba(124,90,237,.6)',borderRadius:4}]},
      options:{responsive:true,maintainAspectRatio:false,scales:{x:{title:{display:true,text:'Exploration calls before first write',color:'#666',font:{size:11}},ticks:{color:'#888',font:{size:11}},grid:{display:false}},y:{ticks:{color:'#666',font:{size:11}},grid:{color:'rgba(255,255,255,.04)'}}},plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>ctx.raw+' sessions'}}}}});
  } else {tbfwCard.style.display='none'}

  // ── Prompt length histogram ──
  const plCard=document.getElementById('pl-card');
  if(allPL.length>0){
    plCard.style.display='';
    const plB=[{l:'<50',x:50},{l:'50-200',x:200},{l:'200-500',x:500},{l:'500-2K',x:2000},{l:'2K-10K',x:10000},{l:'10K+',x:Infinity}];
    const plC=plB.map(()=>0);allPL.forEach(v=>{for(let i=0;i<plB.length;i++){if(v<=plB[i].x){plC[i]++;break}}});
    mc('c-pl',{type:'bar',data:{labels:plB.map(b=>b.l),datasets:[{data:plC,backgroundColor:['#22c55e','#60a5fa','#7c5aed','#f59e0b','#f97316','#ef4444'],borderRadius:4}]},
      options:{responsive:true,maintainAspectRatio:false,scales:{x:{title:{display:true,text:'Characters',color:'#666',font:{size:11}},ticks:{color:'#888',font:{size:11}},grid:{display:false}},y:{ticks:{color:'#666',font:{size:11}},grid:{color:'rgba(255,255,255,.04)'}}},plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>ctx.raw+' prompts'}}}}});
  } else {plCard.style.display='none'}

  // ── Duration trend line ──
  const durCard=document.getElementById('dur-card');
  if(ds.length>2){
    durCard.style.display='';
    const durByDate=grp(ds.filter(s=>s.date),'date'),durDates=Object.keys(durByDate).sort();
    const durMeds=durDates.map(d=>{const vals=durByDate[d].map(s=>s.dur/60).sort((a,b)=>a-b);return vals[vals.length>>1]||0});
    const durRoll=durDates.map((_,i)=>{const start=Math.max(0,i-6);const w=durMeds.slice(start,i+1);return w.reduce((a,b)=>a+b,0)/w.length});
    mc('c-dur',{type:'line',data:{labels:durDates,datasets:[
      {label:'Median Duration',data:durMeds,fill:false,borderColor:'#60a5fa',borderWidth:1.5,pointRadius:0,tension:.3},
      {label:'7d Avg',data:durRoll,borderColor:'#f59e0b',borderWidth:2,borderDash:[6,3],pointRadius:0,tension:.3},
    ]},options:{responsive:true,maintainAspectRatio:false,interaction:{intersect:false,mode:'index'},
      scales:{x:{ticks:{color:'#666',font:{size:10},maxRotation:45,autoSkip:true,maxTicksLimit:20},grid:{color:'rgba(255,255,255,.03)'}},y:{title:{display:true,text:'Minutes',color:'#666',font:{size:11}},ticks:{color:'#666',font:{size:11}},grid:{color:'rgba(255,255,255,.04)'}}},
      plugins:{legend:{labels:{color:'#888',font:{size:11}}},tooltip:{callbacks:{label:ctx=>ctx.dataset.label+': '+ctx.raw.toFixed(1)+' min'}}}}});
  } else {durCard.style.display='none'}

  // ── Platform table ──
  let ph='<thead><tr><th>Platform</th><th class="num">Sessions</th><th class="num">Cost</th><th class="num">Avg</th><th class="num">Tools</th></tr></thead><tbody>';
  for(const[k,v]of Object.entries(bp)){const c=sum(v,'cost');ph+=`<tr><td>${k}</td><td class="num">${v.length.toLocaleString()}</td><td class="num">${fmt.usd(c)}</td><td class="num">${fmt.usd(c/v.length)}</td><td class="num">${sum(v,'tool_calls').toLocaleString()}</td></tr>`}
  if(tos.length)ph+=`<tr><td colspan="5" style="color:var(--text3);font-style:italic;font-size:11px">Tool def overhead: ${fmt.pct(tov)} of context window (${tos.length} sessions measured)</td></tr>`;
  ph+='</tbody>';document.getElementById('t1').innerHTML=ph;

  // ── Sessions table ──
  const top=[...F].sort((a,b)=>b.cost-a.cost).slice(0,10);
  let sh='<thead><tr><th>Project</th><th>Source</th><th class="num">Cost</th><th class="num">Tokens</th><th>Date</th></tr></thead><tbody>';
  top.forEach(s=>{sh+=`<tr><td title="${s.project}">${s.project.length>25?s.project.slice(0,25)+'\u2026':s.project}</td><td><span class="badge">${s.source_name}</span></td><td class="num">${fmt.usd(s.cost)}</td><td class="num">${fmt.tok(s.tokens)}</td><td>${s.date}</td></tr>`});
  sh+='</tbody>';document.getElementById('t2').innerHTML=sh;
}

// ── Card info tooltips ──
const CARD_INFO={
  burn:{title:'Daily Spend',desc:'Daily cost with 7-day rolling average. The area shows daily spend, the dashed line smooths out spikes. Days with $0 spend are included to show true gaps in usage.',good:'Stable or trending down',bad:'Sustained upward trend or unexpected spikes'},
  plat:{title:'Cost by Platform',desc:'Estimated cost distribution across all AI coding tools. Cost is computed from token usage with per-model pricing. Helps identify which tool consumes the most budget.',good:'Spend concentrated on high-value tools',bad:'Expensive tools used for low-value tasks'},
  model:{title:'Cost by Model',desc:'Cost breakdown by LLM model. Expensive models (Opus, GPT-5) should be used for complex tasks. Cheaper models (Haiku, GPT-5-mini) for exploration and simple actions.',good:'Expensive models <30% of total cost',bad:'Opus/GPT-5 used for >50% of sessions'},
  tools:{title:'Top Tools',desc:'Most frequently called tools across all sessions. Bash and Read dominate exploration. Edit and Write are production actions. High Bash count may indicate debugging loops.',good:'Balanced mix of exploration and production tools',bad:'Excessive Bash calls with few Edits (stuck loops)'},
  projects:{title:'Top Projects by Cost',desc:'Projects ranked by estimated cost. Helps identify which codebases consume the most AI budget and whether spend aligns with project priority.',good:'High-priority projects at the top',bad:'Low-priority or abandoned projects consuming budget'},
  stop:{title:'Stop Reasons',desc:'Why the AI stopped generating. tool_use = called a tool (agentic flow). end_turn = finished naturally. max_tokens = output was truncated (wasted generation).',good:'Mostly tool_use (agentic) + end_turn (complete)',bad:'High max_tokens rate = truncated output, wasted spend'},
  erw:{title:'Edit / Read / Write',desc:'Production actions (Edit + Write = code modifications) vs exploration (Read = understanding code). The ratio shows whether sessions are producing or just exploring.',good:'Edit+Write > Read (ratio > 1.0)',bad:'Heavy Read with few Edits = stuck in exploration'},
  health:{title:'Session Size Distribution',desc:'Histogram of session token counts. Most sessions should be under 10M tokens. Sessions over 50M indicate runaway context accumulation \u2014 prime targets for /clear or splitting.',good:'Most sessions in <1M and 1-10M buckets',bad:'Many sessions in 50M+ bucket'},
  tbfw:{title:'Turns Before First Write',desc:'How many exploration tool calls (Read, Bash, Grep) happen before the first production action (Edit, Write). Measures prompt specificity and ramp-up time.',good:'Median below 10 = focused prompts',bad:'Median above 25 = vague prompts causing excessive exploration'},
  platTable:{title:'Platform Comparison',desc:'Side-by-side comparison of all AI coding tools. Shows sessions, total cost, average cost per session, and tool calls. The footer shows tool definition overhead if available.',good:'Cost per session stable across platforms',bad:'One platform disproportionately expensive'},
  promptLen:{title:'Prompt Length Distribution',desc:'Histogram of user prompt lengths in characters. Short prompts (<50 chars) often lead to excessive exploration as the AI guesses intent. Long prompts (>10K) waste context window — consider using files or CLAUDE.md.',good:'Most prompts 100-500 chars — focused and specific',bad:'Many <50 (vague) or >10K (paste-heavy) prompts'},
  durTrend:{title:'Session Duration Trend',desc:'Daily median session duration with 7-day rolling average. Upward trends indicate context bloat or scope creep. Downward trends suggest better prompting or session hygiene.',good:'Stable or trending down',bad:'Sustained upward trend — sessions getting longer over time'},
  sessTable:{title:'Most Costly Sessions',desc:'Top sessions ranked by cost. These are your biggest optimization targets. Consider: was the cost justified by output? Could the session have been split earlier?',good:'Top sessions are complex, high-value tasks',bad:'Top sessions are simple tasks that ran too long'},
};

document.querySelectorAll('[data-info]').forEach(card=>{
  const key=card.dataset.info,info=CARD_INFO[key];
  if(!info)return;
  const h3=card.querySelector('h3');
  if(!h3)return;
  const wrap=document.createElement('div');wrap.className='card-hdr';
  const tip=document.createElement('button');tip.className='info-btn';
  tip.setAttribute('onmouseenter','positionTip(this)');
  tip.innerHTML=`i<div class="tooltip"><div class="tt-title">${info.title}</div>${info.desc}<div class="tt-good">\u2713 Good: ${info.good}</div><div class="tt-bad">\u2717 Bad: ${info.bad}</div></div>`;
  h3.parentNode.insertBefore(wrap,h3);
  wrap.appendChild(h3);wrap.appendChild(tip);
});

initF();render();

// ── Scroll-spy for sidebar nav ──
const navLinks=document.querySelectorAll('.sidebar-nav a[data-section]');
const sectionIds=[...navLinks].map(a=>a.dataset.section);
function updateNav(){
  const scrollY=window.scrollY||document.documentElement.scrollTop;
  let current='';
  for(const id of sectionIds){
    const el=document.getElementById(id);
    if(el&&el.offsetTop-120<=scrollY)current=id;
  }
  navLinks.forEach(a=>{a.classList.toggle('active',a.dataset.section===current)});
}
window.addEventListener('scroll',updateNav,{passive:true});
updateNav();

// Smooth scroll on nav click + close mobile sidebar
navLinks.forEach(a=>{
  a.addEventListener('click',e=>{
    e.preventDefault();
    const el=document.getElementById(a.dataset.section);
    if(el){
      // Expand section if collapsed
      const body=el.querySelector('.section-body');
      if(body&&body.classList.contains('hidden')){
        body.classList.remove('hidden');
        const hdr=el.querySelector('.section-hdr');
        if(hdr)hdr.classList.remove('collapsed');
      }
      el.scrollIntoView({behavior:'smooth',block:'start'});
    }
    document.getElementById('sidebar').classList.remove('open');
  });
});
</script></body></html>"""
)


def generate(sessions: list[NormalizedSession], source_names: dict, cutoff=None) -> Path:
    """Generate HTML dashboard. Returns path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dashboard_path = OUTPUT_DIR / "dashboard.html"

    data = _build_data(sessions, source_names)
    data_json = json.dumps(data, default=str)
    html = _HTML.replace("%%DATA_JSON%%", data_json)

    with open(dashboard_path, "w") as f:
        f.write(html)

    print(f"Dashboard: {dashboard_path}")
    return dashboard_path
