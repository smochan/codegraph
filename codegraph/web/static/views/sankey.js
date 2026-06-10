/* codegraph dashboard - Sankey view */
'use strict';

CGViews.sankey = function renderSankey(host) {
  const esc = CGUI.esc;
  const showTip = CGUI.showTip;
  const hideTip = CGUI.hideTip;
  const data = window.state.data.sankey;
  host.innerHTML = `<div class="p-8 max-w-7xl mx-auto">
    <div class="help-card mb-6">
      <i data-lucide="waves" class="icon w-4 h-4"></i>
      <div><b>Inter-module call flows.</b> Width of each ribbon = number of calls between two modules.
      Hover anything for exact counts.</div>
    </div>
    <div class="panel p-5">
      <div class="section-h"><h2>Top call flows</h2><span class="text-[11px] text-ink-200">${data.links.length} flows</span></div>
      ${data.links.length ? '<svg id="sankey" class="w-full" style="height:680px"></svg>'
                          : '<div class="text-ink-200 p-12 text-center">No cross-module flows yet.</div>'}
    </div></div>`;
  if (!data.links.length) return;
  const svg = d3.select('#sankey');
  const { width, height } = svg.node().getBoundingClientRect();
  const sk = d3.sankey().nodeWidth(14).nodePadding(10)
    .extent([[6, 6], [width - 6, height - 6]]);
  const g = sk({
    nodes: data.nodes.map(d => ({...d})),
    links: data.links.map(d => ({...d})),
  });
  const colour = d3.scaleOrdinal()
    .range(['#818cf8','#22d3ee','#34d399','#fbbf24','#f87171','#a78bfa','#fb923c']);
  svg.append('g').selectAll('rect').data(g.nodes).join('rect')
    .attr('x', d => d.x0).attr('y', d => d.y0)
    .attr('height', d => d.y1 - d.y0).attr('width', d => d.x1 - d.x0)
    .attr('fill', d => colour(d.package || d.name))
    .attr('rx', 2)
    .on('mousemove', (e, d) => showTip(`<b>${esc(d.qualname)}</b><br>value: ${Math.round(d.value)}`, e.clientX, e.clientY))
    .on('mouseleave', hideTip);
  svg.append('g').attr('fill', 'none').selectAll('path').data(g.links).join('path')
    .attr('d', d3.sankeyLinkHorizontal())
    .attr('stroke', d => colour(d.source.package || d.source.name))
    .attr('stroke-width', d => Math.max(1, d.width))
    .attr('stroke-opacity', 0.4)
    .on('mousemove', (e, d) => showTip(
      `${esc(d.source.qualname)} → ${esc(d.target.qualname)}<br>${d.value} call(s)`,
      e.clientX, e.clientY))
    .on('mouseleave', hideTip);
  svg.append('g').attr('class', 'd3-label').selectAll('text').data(g.nodes).join('text')
    .attr('x', d => d.x0 < width / 2 ? d.x1 + 8 : d.x0 - 8)
    .attr('y', d => (d.y1 + d.y0) / 2).attr('dy', '0.35em')
    .attr('text-anchor', d => d.x0 < width / 2 ? 'start' : 'end')
    .text(d => d.name);
};
