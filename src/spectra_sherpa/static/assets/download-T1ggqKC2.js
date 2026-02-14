function o(t){return t.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}function C(){return`
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #0f172a; color: #e2e8f0; line-height: 1.6;
      max-width: 1000px; margin: 0 auto; padding: 40px 24px;
    }
    h1 { font-size: 1.8rem; color: #f8fafc; margin-bottom: 8px; }
    h2 { font-size: 1.3rem; color: #f8fafc; margin: 32px 0 16px; border-bottom: 1px solid #334155; padding-bottom: 8px; }
    h3 { font-size: 1.05rem; color: #cbd5e1; margin: 20px 0 10px; }
    .meta-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin: 16px 0; }
    .meta-item { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 12px; }
    .meta-label { font-size: 0.75rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }
    .meta-value { font-size: 0.95rem; color: #f8fafc; margin-top: 4px; }
    .hash { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 0.8rem; color: #4ade80; word-break: break-all; }
    .node-card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 16px; margin: 12px 0; }
    .node-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
    .node-type-badge { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
    .badge-data { background: rgba(59,130,246,0.2); color: #60a5fa; }
    .badge-preprocess { background: rgba(168,85,247,0.2); color: #c084fc; }
    .badge-model { background: rgba(34,197,94,0.2); color: #4ade80; }
    .badge-output { background: rgba(251,146,60,0.2); color: #fb923c; }
    .badge-other { background: rgba(148,163,184,0.2); color: #94a3b8; }
    .params-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
    .params-table th, .params-table td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #1e293b; font-size: 0.85rem; }
    .params-table th { color: #64748b; font-weight: 500; }
    .params-table td { color: #e2e8f0; }
    .params-table code { background: #0f172a; padding: 1px 4px; border-radius: 3px; font-size: 0.8rem; }
    .connection-table { width: 100%; border-collapse: collapse; }
    .connection-table th, .connection-table td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #334155; font-size: 0.85rem; }
    .connection-table th { background: #1e293b; color: #64748b; }
    .connection-table td { color: #e2e8f0; }
    .plot-gallery { display: grid; grid-template-columns: 1fr; gap: 16px; margin: 16px 0; }
    .plot-card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; overflow: hidden; }
    .plot-card img { width: 100%; display: block; }
    .plot-card .plot-caption { padding: 8px 12px; font-size: 0.85rem; color: #94a3b8; }
    .footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #334155; font-size: 0.8rem; color: #64748b; text-align: center; }
    .run-card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 16px; margin: 12px 0; }
    .run-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
    .status-badge { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
    .status-completed { background: rgba(34,197,94,0.2); color: #4ade80; }
    .status-error { background: rgba(239,68,68,0.2); color: #f87171; }
    .status-partial { background: rgba(251,191,36,0.2); color: #fbbf24; }
    .status-running { background: rgba(59,130,246,0.2); color: #60a5fa; }
    .comparison-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
    .comparison-table th, .comparison-table td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #334155; font-size: 0.85rem; }
    .comparison-table th { background: #1e293b; color: #64748b; font-weight: 500; }
    .comparison-table td { color: #e2e8f0; }
    .metric-best { color: #4ade80; font-weight: 600; }
    .delta-positive { color: #60a5fa; font-weight: 500; }
    .delta-negative { color: #f87171; font-weight: 500; }
    .narrative-section { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 20px 24px; margin: 16px 0; line-height: 1.8; font-size: 0.9rem; }
    .narrative-section p { margin-bottom: 12px; }
    .label-tag { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 0.7rem; background: rgba(59,130,246,0.2); color: #60a5fa; margin-right: 4px; }
    @media print {
      body { background: #fff; color: #1e293b; }
      .node-card, .meta-item, .plot-card, .run-card, .narrative-section { border-color: #d1d5db; }
      .hash { color: #16a34a; }
    }
  `}function D(t){const i=t.split(".")[0];return{data:"badge-data",preprocess:"badge-preprocess",normalize:"badge-preprocess",baseline:"badge-preprocess",smooth:"badge-preprocess",derivative:"badge-preprocess",model:"badge-model",classification:"badge-model",analysis:"badge-model",output:"badge-output",stats:"badge-output",synthesis:"badge-data"}[i]||"badge-other"}function M(t){return{completed:"status-completed",error:"status-error",partial:"status-partial",running:"status-running"}[t]||"status-partial"}function k(t){return t==null?"—":typeof t=="number"?Number.isInteger(t)?String(t):t.toFixed(4):Array.isArray(t)?`[${t.slice(0,3).map(e=>typeof e=="number"?e.toFixed(2):String(e)).join(", ")}${t.length>3?"...":""}]`:String(t)}function T(t,i){const e=D(t.nodeType),a=Object.entries(t.parameters||{});let r=`<div class="node-card">
    <div class="node-header">
      <span class="node-type-badge ${e}">${o(t.nodeType)}</span>
      <strong>${o(t.label)}</strong>
      <span style="margin-left:auto;font-size:0.75rem;color:#64748b">ID: ${o(t.nodeId)}</span>
    </div>`;if(t.outputShape&&(r+=`<div style="font-size:0.8rem;color:#94a3b8;margin-bottom:8px">Output: ${t.outputType||"unknown"} [${t.outputShape.join(" x ")}]</div>`),a.length>0){r+='<table class="params-table"><tr><th>Parameter</th><th>Value</th></tr>';for(const[d,c]of a){const g=typeof c=="object"?JSON.stringify(c):String(c);r+=`<tr><td><code>${o(d)}</code></td><td>${o(g)}</td></tr>`}r+="</table>"}return i&&(r+=`<div style="margin-top:12px"><img src="${i}" alt="Plot for ${o(t.label)}" style="width:100%;border-radius:4px" /></div>`),r+="</div>",r}function L(t,i){var c;const e=M(t.status),a=t.executed_at?new Date(t.executed_at).toLocaleString():"Unknown date";let r=`<div class="run-card">
    <div class="run-header">
      <strong>${o(t.name)}</strong>
      <span class="status-badge ${e}">${o(t.status)}</span>
      <span style="margin-left:auto;font-size:0.8rem;color:#64748b">${o(a)}</span>
    </div>`;if(t.labels&&t.labels.length>0){r+='<div style="margin-bottom:10px">';for(const g of t.labels)r+=`<span class="label-tag">${o(g)}</span>`;r+="</div>"}const d=[];for(const[g,n]of Object.entries(t.results_summary))if(typeof n=="object"&&n!==null)for(const[l,b]of Object.entries(n)){const p=((c=i.find(x=>x.nodeId===g))==null?void 0:c.label)||g;d.push([p,l,b])}if(d.length>0){r+='<table class="params-table"><tr><th>Node</th><th>Metric</th><th>Value</th></tr>';for(const[g,n,l]of d)r+=`<tr><td>${o(g)}</td><td><code>${o(n)}</code></td><td>${o(k(l))}</td></tr>`;r+="</table>"}return r+="</div>",r}function P(t,i){var a;if(!t.diagnostics||Object.keys(t.diagnostics).length===0)return"";let e=`<h3>${o(t.name)} — Diagnostics</h3>`;for(const[r,d]of Object.entries(t.diagnostics)){if(typeof d!="object"||d===null||Object.keys(d).length===0)continue;const c=((a=i.find(g=>g.nodeId===r))==null?void 0:a.label)||r;e+=`<div class="node-card"><strong>${o(c)}</strong>`,e+='<table class="params-table"><tr><th>Key</th><th>Value</th></tr>';for(const[g,n]of Object.entries(d))e+=`<tr><td><code>${o(g)}</code></td><td>${o(k(n))}</td></tr>`;e+="</table></div>"}return e}const B=new Set(["r2","accuracy","explained_variance","silhouette_score"]);function _(t,i){if(i.metric_keys.length===0)return"";let e='<table class="comparison-table"><tr><th>Metric</th>';for(const a of t)e+=`<th>${o(a.name)}</th>`;t.length===2&&(e+="<th>Delta</th>"),e+="</tr>";for(const a of i.metric_keys){const r=a.split(".").pop()||a,d=i.diff[a]||{},c=[];for(const[l,b]of Object.entries(d))typeof b=="number"&&!isNaN(b)&&c.push({runId:l,val:b});const g=B.has(r);let n=null;c.length>=2&&(n=[...c].sort((b,p)=>g?p.val-b.val:b.val-p.val)[0].runId),e+=`<tr><td><code>${o(r)}</code></td>`;for(const l of t){const b=d[String(l.id)],x=n===String(l.id)?' class="metric-best"':"";e+=`<td${x}>${o(k(b))}</td>`}if(t.length===2&&c.length===2){const l=c[1].val-c[0].val,b=l>0?"+":"",p=l>0?"delta-positive":l<0?"delta-negative":"",x=Number.isInteger(l)?String(l):l.toFixed(4);e+=`<td class="${p}">${b}${x}</td>`}else t.length===2&&(e+="<td>—</td>");e+="</tr>"}return e+="</table>",e}function F(t){return t.split(`

`).map(i=>{const e=i.trim();if(!e)return"";if(e.startsWith("### "))return`<h3>${o(e.slice(4))}</h3>`;if(e.startsWith("## "))return`<h3>${o(e.slice(3))}</h3>`;if(e.startsWith("# "))return`<h3>${o(e.slice(2))}</h3>`;let a=o(e);return a=a.replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>"),a=a.replace(/\*(.+?)\*/g,"<em>$1</em>"),`<p>${a}</p>`}).join(`
`)}function A(t){const{workflowName:i,workflowDescription:e,integrityHash:a,generatedAt:r,nodes:d,edges:c,plotImages:g,terminalMetrics:n,technique:l,sampleType:b,runs:p,comparison:x,narrativeMarkdown:w,sections:m}=t,S=(m==null?void 0:m.pipelineDetails)??!0,j=(m==null?void 0:m.connections)??!0,z=(m==null?void 0:m.executionResults)??!0,N=(m==null?void 0:m.diagnostics)??!1,O=(m==null?void 0:m.runComparison)??!1,R=(m==null?void 0:m.aiNarrative)??!1,I=H(d,c);let s=`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Report: ${o(i)}</title>
  <style>${C()}</style>
</head>
<body>
  <h1>${o(i)}</h1>`;if(e&&(s+=`<p style="color:#94a3b8;margin-bottom:16px">${o(e)}</p>`),R&&w&&(s+=`<h2>Summary</h2><div class="narrative-section">${F(w)}</div>`),s+=`<h2>Metadata</h2><div class="meta-grid">
    <div class="meta-item"><div class="meta-label">Generated</div><div class="meta-value">${o(r)}</div></div>
    <div class="meta-item"><div class="meta-label">Nodes</div><div class="meta-value">${d.length}</div></div>
    <div class="meta-item"><div class="meta-label">Connections</div><div class="meta-value">${c.length}</div></div>`,l&&(s+=`<div class="meta-item"><div class="meta-label">Technique</div><div class="meta-value">${o(l)}</div></div>`),b&&(s+=`<div class="meta-item"><div class="meta-label">Sample Type</div><div class="meta-value">${o(b)}</div></div>`),a&&(s+=`<div class="meta-item" style="grid-column: 1/-1"><div class="meta-label">Integrity Hash (SHA-256)</div><div class="meta-value hash">${o(a)}</div></div>`),s+="</div>",j&&c.length>0){s+='<h2>Connections</h2><table class="connection-table"><tr><th>From</th><th>To</th><th>Ports</th></tr>';for(const h of c){const f=d.find($=>$.nodeId===h.fromNodeId),u=d.find($=>$.nodeId===h.toNodeId),v=(f==null?void 0:f.label)||h.fromNodeId,y=(u==null?void 0:u.label)||h.toNodeId;s+=`<tr><td>${o(v)}</td><td>${o(y)}</td><td>${o(h.fromOutput)} &rarr; ${o(h.toInput)}</td></tr>`}s+="</table>"}if(S){s+="<h2>Pipeline Steps</h2>";for(const f of I){const u=g.get(f.nodeId);s+=T(f,u)}const h=Array.from(g.entries()).filter(([f])=>!I.find(u=>u.nodeId===f));if(h.length>0){s+='<h2>Additional Plots</h2><div class="plot-gallery">';for(const[f,u]of h)s+=`<div class="plot-card"><img src="${u}" alt="Plot ${o(f)}" /><div class="plot-caption">Node: ${o(f)}</div></div>`;s+="</div>"}}if(Object.keys(n).length>0){s+="<h2>Results</h2>";for(const[h,f]of Object.entries(n)){const u=d.find(v=>v.nodeId===h);s+=`<h3>${o((u==null?void 0:u.label)||h)}</h3>`,s+='<table class="params-table"><tr><th>Metric</th><th>Value</th></tr>';for(const[v,y]of Object.entries(f)){const $=typeof y=="number"?y.toFixed(6):String(y);s+=`<tr><td><code>${o(v)}</code></td><td>${o($)}</td></tr>`}s+="</table>"}}if(z&&p&&p.length>0){s+="<h2>Execution Runs</h2>";for(const h of p)s+=L(h,d)}if(N&&p&&p.length>0&&p.some(f=>f.diagnostics&&Object.keys(f.diagnostics).length>0)){s+="<h2>Diagnostics</h2>";for(const f of p)s+=P(f,d)}return O&&x&&p&&p.length>=2&&(s+="<h2>Run Comparison</h2>",s+=_(p,x)),s+=`<div class="footer">
    Generated by SpectraSherpa &mdash; ${o(r)}
    ${a?`<br/>Integrity Hash: <span class="hash">${o(a)}</span>`:""}
  </div>
</body>
</html>`,s}function H(t,i){var g;const e=new Map(t.map(n=>[n.nodeId,n])),a=new Map,r=new Map;for(const n of t)a.set(n.nodeId,0),r.set(n.nodeId,[]);for(const n of i)a.set(n.toNodeId,(a.get(n.toNodeId)||0)+1),(g=r.get(n.fromNodeId))==null||g.push(n.toNodeId);const d=[];for(const[n,l]of a)l===0&&d.push(n);const c=[];for(;d.length>0;){const n=d.shift(),l=e.get(n);l&&c.push(l);for(const b of r.get(n)||[]){const p=(a.get(b)||1)-1;a.set(b,p),p===0&&d.push(b)}}return c}const V=(t,i)=>{const e=URL.createObjectURL(t),a=document.createElement("a");a.href=e,a.download=i,document.body.appendChild(a),a.click(),document.body.removeChild(a),URL.revokeObjectURL(e)},U=(t,i,e)=>{V(new Blob([t],{type:e}),i)},E=(t,i)=>{const e=JSON.stringify(t,null,2);U(e,i,"application/json")};export{V as a,E as b,U as d,A as g,H as t};
