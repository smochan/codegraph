/* codegraph dashboard - Matrix view */
'use strict';

CGViews.matrix = function renderMatrix(host) {
  const esc = CGUI.esc;
  const showTip = CGUI.showTip;
  const hideTip = CGUI.hideTip;
  const m = window.state.data.matrix;
  if (!m.modules.length) {
    host.innerHTML = `<div class="p-8 text-ink-200">No cross-module CALLS recorded.</div>`;
    return;
  }
  const max = m.max || 1;
  const colour = v => {
    if (!v) return 'transparent';
    const t = v / max;
    // Cool indigo -> violet -> warm rose for heat.
    const stops = [
      [42,  57,  87],   // ink-500
      [99,  102, 241],  // brand-600
      [167, 139, 250],  // accent-violet
      [248, 113, 113],  // accent-rose
    ];
    const seg = Math.min(stops.length - 2, Math.floor(t * (stops.length - 1)));
    const lt  = (t * (stops.length - 1)) - seg;
    const a = stops[seg], b = stops[seg + 1];
    const r = Math.round(a[0] + lt * (b[0] - a[0]));
    const g = Math.round(a[1] + lt * (b[1] - a[1]));
    const bl= Math.round(a[2] + lt * (b[2] - a[2]));
    return `rgb(${r},${g},${bl})`;
  };
  let html = `<div class="p-8 max-w-7xl mx-auto">
    <div class="help-card mb-6">
      <i data-lucide="grid-3x3" class="icon w-4 h-4"></i>
      <div><b>Module call matrix.</b> Each row is a caller, each column a callee. Cell color and number = number of calls.
      Rotate your head 45° to read column labels - or hover any cell for the exact pair.</div>
    </div>
    <div class="panel p-4">
      <div class="matrix-wrap"><table class="matrix"><thead><tr><th class="corner"></th>`;
  m.modules.forEach(mod => {
    html += `<th title="${esc(mod.qualname)}">${esc(mod.name)}</th>`;
  });
  html += `</tr></thead><tbody>`;
  m.modules.forEach((row, i) => {
    html += `<tr><th title="${esc(row.qualname)}">${esc(row.qualname)}</th>`;
    m.counts[i].forEach((v, j) => {
      const tip = v ? `<b>${esc(row.name)}</b> -> <b>${esc(m.modules[j].name)}</b><br>${v} call${v===1?'':'s'}` : '';
      html += `<td class="cell" data-tip="${tip}" style="background:${colour(v)}">${v || ''}</td>`;
    });
    html += `</tr>`;
  });
  html += `</tbody></table></div>
    <div class="flex items-center gap-3 mt-4 text-[11px] text-ink-200">
      <span>0</span>
      <div class="h-2.5 w-48 rounded-full" style="background:linear-gradient(90deg,#2a3957,#6366f1,#a78bfa,#f87171)"></div>
      <span class="font-mono">${max}</span>
    </div></div></div>`;
  host.innerHTML = html;
  host.querySelectorAll('td.cell').forEach(c => {
    c.addEventListener('mousemove', e => {
      const t = e.target.dataset.tip;
      if (t) showTip(t, e.clientX, e.clientY);
    });
    c.addEventListener('mouseleave', hideTip);
  });
};
