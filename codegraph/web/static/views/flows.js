/* codegraph dashboard - Flows view */
'use strict';

CGViews.flows = function renderFlows(host) {
  const esc = CGUI.esc;
  const formatQn = CGUI.formatQn;
  const flows = window.state.data.flows;
  if (!flows.length) {
    host.innerHTML = `<div class="p-8 text-ink-200">No call chains found.</div>`;
    return;
  }
  if (window.state.flowSel >= flows.length) window.state.flowSel = 0;
  host.innerHTML = `
    <div class="p-8 max-w-7xl mx-auto">
      <div class="help-card mb-6">
        <i data-lucide="git-fork" class="icon w-4 h-4"></i>
        <div><b>Call flow inspector.</b> Pick an entry point on the left to see its real downstream call tree (BFS depth 4).
        Highlighted node = entry; arrows = CALLS edges from the actual graph.</div>
      </div>
      <div class="grid grid-cols-[300px_1fr] gap-4">
        <div class="panel p-3 max-h-[78vh] overflow-y-auto">
          <div class="search-wrap mb-3">
            <i data-lucide="search"></i>
            <input class="search" id="flow-search" placeholder="Filter entry points…">
          </div>
          <div id="flow-list" class="space-y-1"></div>
        </div>
        <div class="panel p-5 min-h-[600px]">
          <div class="section-h"><h2 id="flow-title">Flow</h2>
            <span class="pill" id="flow-meta"></span></div>
          <div class="mermaid-host" id="flow-canvas"></div>
        </div>
      </div>
    </div>`;
  const list = document.getElementById('flow-list');
  flows.forEach((f, i) => {
    const el = document.createElement('div');
    el.className = 'flow-item';
    el.innerHTML = `<div class="qn">${formatQn(f.qualname, {maxParts: 3})}</div>
      <div class="meta"><i data-lucide="zap" style="width:11px;height:11px"></i>
      ${esc(f.reason)} <span class="text-ink-300">· ${esc(f.file)}</span></div>`;
    el.onclick = () => _selectFlow(i);
    list.appendChild(el);
  });
  document.getElementById('flow-search').addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    [...list.children].forEach((el, i) => {
      el.style.display = JSON.stringify(flows[i]).toLowerCase().includes(q) ? '' : 'none';
    });
  });
  _selectFlow(window.state.flowSel);
};

function _selectFlow(i) {
  const esc = CGUI.esc;
  const formatQn = CGUI.formatQn;
  window.state.flowSel = i;
  const flow = window.state.data.flows[i];
  if (!flow) return;
  document.querySelectorAll('.flow-item').forEach((el, j) =>
    el.classList.toggle('active', j === i));
  document.getElementById('flow-title').innerHTML = formatQn(flow.qualname, {maxParts: 4});
  document.getElementById('flow-title').classList.add('qn-mono');
  document.getElementById('flow-meta').textContent = flow.reason;
  const canvas = document.getElementById('flow-canvas');
  canvas.innerHTML = `<pre class="mermaid">${esc(flow.mermaid)}</pre>`;
  mermaid.run({ nodes: canvas.querySelectorAll('.mermaid') });
}
