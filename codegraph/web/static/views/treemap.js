/* codegraph dashboard - Treemap view */
'use strict';

CGViews.treemap = function renderTreemap(host) {
  const esc = CGUI.esc;
  const showTip = CGUI.showTip;
  const hideTip = CGUI.hideTip;
  host.innerHTML = `<div class="p-8 max-w-7xl mx-auto">
    <div class="help-card mb-6">
      <i data-lucide="square-stack" class="icon w-4 h-4"></i>
      <div><b>Codebase footprint.</b> Each rectangle = one module. Area = LOC; brighter color = higher hotspot score.
      Hover any cell for full details.</div>
    </div>
    <div class="panel p-5">
      <div class="section-h"><h2>LOC landscape</h2></div>
      <svg id="treemap" class="w-full" style="height:720px"></svg>
    </div></div>`;
  const root = d3.hierarchy(window.state.data.treemap)
    .sum(d => d.value || 0).sort((a, b) => b.value - a.value);
  const svg = d3.select('#treemap');
  const { width, height } = svg.node().getBoundingClientRect();
  d3.treemap().size([width, height]).paddingInner(3).paddingTop(22).round(true)(root);
  const maxScore = d3.max(root.leaves(), d => d.data.score) || 1;
  const colour = d3.scaleSequential([0, maxScore], d3.interpolateInferno);

  const pkg = svg.append('g').selectAll('g')
    .data(root.descendants().filter(d => d.depth === 1))
    .join('g').attr('transform', d => `translate(${d.x0},${d.y0})`);
  pkg.append('rect').attr('width', d => d.x1 - d.x0).attr('height', d => d.y1 - d.y0)
    .attr('fill', '#131c2e').attr('stroke', '#243049').attr('rx', 4);
  pkg.append('text').attr('x', 8).attr('y', 14).attr('fill', '#cbd5e1')
    .style('font-size', '11px').style('font-weight', '600').text(d => d.data.name);

  const leaf = svg.append('g').selectAll('g').data(root.leaves())
    .join('g').attr('transform', d => `translate(${d.x0},${d.y0})`);
  leaf.append('rect').attr('width', d => Math.max(0, d.x1 - d.x0))
    .attr('height', d => Math.max(0, d.y1 - d.y0))
    .attr('fill', d => d.data.score ? colour(d.data.score) : '#243049')
    .attr('stroke', '#0b1220').attr('stroke-width', 1).attr('rx', 2)
    .style('cursor', 'pointer')
    .on('mousemove', (e, d) => showTip(
       `<b>${esc(d.data.name)}</b><br>${esc(d.data.file)}<br>` +
       `LOC: ${d.data.value} · symbols: ${d.data.symbols} · score: ${d.data.score}`,
       e.clientX, e.clientY))
    .on('mouseleave', hideTip);
  leaf.append('text').attr('x', 6).attr('y', 14).attr('fill', '#fff')
    .style('font-size', '10.5px').style('font-weight', '500')
    .style('pointer-events', 'none')
    .text(d => {
      const w = d.x1 - d.x0, h = d.y1 - d.y0;
      if (w < 60 || h < 22) return '';
      const name = d.data.name.split('.').pop();
      return name.length * 6 > w - 12 ? name.slice(0, Math.floor((w-12)/6)) + '…' : name;
    });
};
