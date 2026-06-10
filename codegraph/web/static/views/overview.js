/* codegraph dashboard - Overview view */
'use strict';

CGViews.overview = function renderOverview(host) {
  const esc = CGUI.esc;
  const formatQn = CGUI.formatQn;
  const m = window.state.data.metrics, iss = window.state.data.issues;
  const card = (n, l, accent) => `
    <div class="stat-card">
      <div class="stat-num ${accent || ''}">${n}</div>
      <div class="stat-lbl">${l}</div>
    </div>`;
  const rows = obj => Object.entries(obj).sort((a,b)=>b[1]-a[1]).map(([k,v]) =>
    `<tr><td>${esc(k)}</td><td class="num">${v}</td></tr>`).join('');
  const hot = window.state.data.hotspots.map(h => `
    <tr>
      <td><span class="qn-mono text-[12.5px]">${formatQn(h.qualname, {maxParts: 4})}</span></td>
      <td class="text-ink-200"><code>${esc(h.file)}</code></td>
      <td class="num">${h.fan_in}</td>
      <td class="num">${h.fan_out}</td>
      <td class="num">${h.loc}</td>
      <td class="num"><span class="pill ${h.score>200?'pill-hot':h.score>80?'pill-warm':''}">${h.score}</span></td>
    </tr>`).join('');

  host.innerHTML = `
    <div class="p-8 space-y-6 max-w-7xl mx-auto">
      <div class="help-card">
        <i data-lucide="sparkles" class="icon w-4 h-4"></i>
        <div><b>Where to start.</b> Open <b>HLD</b> for a clean layered diagram of how the codebase is wired.
        Use <b>Call flows</b> to step through specific functions, or <b>Matrix</b> to see who calls whom in one glance.</div>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        ${card(m.nodes, 'Nodes')}
        ${card(m.edges, 'Edges')}
        ${card(m.unresolved, 'Unresolved', m.unresolved ? 'text-accent-amber' : '')}
        ${card(iss.cycles, 'Cycles', iss.cycles ? 'text-accent-rose' : '')}
        ${card(iss.dead, 'Dead-code candidates', iss.dead ? 'text-accent-amber' : '')}
        ${card(iss.untested, 'Untested fns', iss.untested ? 'text-accent-amber' : '')}
      </div>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div class="panel p-5"><div class="section-h"><h2>Nodes by kind</h2></div>
          <table class="data">${rows(m.by_kind)}</table></div>
        <div class="panel p-5"><div class="section-h"><h2>Edges by kind</h2></div>
          <table class="data">${rows(m.by_edge)}</table></div>
        <div class="panel p-5"><div class="section-h"><h2>Languages</h2></div>
          <table class="data">${rows(m.languages)}</table></div>
      </div>
      <div class="panel p-5">
        <div class="section-h"><h2>Top hotspots</h2>
          <span class="text-[11px] text-ink-200">score = fan_in*2 + fan_out + LOC/50</span></div>
        <table class="data">
          <thead><tr><th>Symbol</th><th>File</th><th class="num">Fan-in</th>
            <th class="num">Fan-out</th><th class="num">LOC</th><th class="num">Score</th></tr></thead>
          <tbody>${hot}</tbody>
        </table>
      </div>
    </div>`;
};
