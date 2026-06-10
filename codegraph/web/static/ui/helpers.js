/* codegraph dashboard - shared UI helpers */
'use strict';

// Global namespaces used by all view scripts.
window.CGUI = window.CGUI || {};
window.CGViews = window.CGViews || {};

// ---- esc ----
CGUI.esc = function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
};

// ---- shortQn ----
CGUI.shortQn = function shortQn(qn) {
  const parts = String(qn).split('.');
  return parts.length > 3 ? '…' + parts.slice(-3).join('.') : qn;
};

/* HTML version of shortQn that dims the parent path and highlights the leaf.
   Returns sanitized markup. */
CGUI.formatQn = function formatQn(qn, opts) {
  const esc = CGUI.esc;
  const max = (opts && opts.maxParts) || 3;
  const parts = String(qn ?? '').split('.');
  if (!parts.length) return '';
  const leaf = parts[parts.length - 1];
  const headParts = parts.slice(0, -1);
  const truncated = headParts.length > max - 1;
  const visibleHead = truncated ? headParts.slice(-(max - 1)) : headParts;
  const prefix = truncated ? '…' : '';
  const head = visibleHead.length
    ? `<span class="qn-dim">${prefix}${esc(visibleHead.join('.'))}.</span>`
    : (truncated ? `<span class="qn-dim">${prefix}</span>` : '');
  return `${head}<span class="qn-key">${esc(leaf)}</span>`;
};

// ---- Tooltip ----
CGUI.showTip = function showTip(html, x, y) {
  const tt = document.getElementById('tooltip');
  tt.innerHTML = html;
  const r = tt.getBoundingClientRect();
  let lx = x + 14, ly = y + 14;
  if (lx + r.width > innerWidth - 8) lx = x - r.width - 14;
  if (ly + r.height > innerHeight - 8) ly = y - r.height - 14;
  tt.style.left = lx + 'px';
  tt.style.top = ly + 'px';
  tt.style.opacity = '1';
};
CGUI.hideTip = function hideTip() {
  document.getElementById('tooltip').style.opacity = '0';
};

// ---- Toast ----
CGUI.toast = function toast(msg, kind) {
  const host = document.getElementById('toast-host');
  const el = document.createElement('div');
  el.className = 'toast ' + (kind || '');
  el.textContent = msg;
  host.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s';
    setTimeout(() => el.remove(), 350); }, 2400);
};

// ---- Mermaid theme helpers ----
CGUI.mermaidThemeVars = function mermaidThemeVars() {
  const light = document.documentElement.classList.contains('theme-light');
  return light
    ? { fontFamily: 'Inter, system-ui, sans-serif', fontSize: '14px',
        background: 'transparent',
        primaryColor: '#eef2ff', primaryTextColor: '#0f172a',
        primaryBorderColor: '#a5b4fc', lineColor: '#6366f1',
        secondaryColor: '#f5f3ff', tertiaryColor: '#ffffff',
        clusterBkg: 'rgba(238,242,255,0.7)', clusterBorder: '#a5b4fc',
        nodeBorder: '#a5b4fc', mainBkg: '#eef2ff',
        edgeLabelBackground: '#ffffff', titleColor: '#1e293b' }
    : { fontFamily: 'Inter, system-ui, sans-serif', fontSize: '14px',
        background: 'transparent',
        primaryColor: '#1d2942', primaryTextColor: '#e6ecf5',
        primaryBorderColor: '#3b4a6a', lineColor: '#5b6b8c',
        secondaryColor: '#161f33', tertiaryColor: '#0f1626',
        clusterBkg: 'rgba(15,22,38,0.6)', clusterBorder: '#3b4a6a',
        nodeBorder: '#3b4a6a', mainBkg: '#1d2942',
        edgeLabelBackground: '#0a0f1c', titleColor: '#c4cfe2' };
};

// ---- HLD symbol kind helpers (shared by hld.js) ----
CGUI.kindIcon = function kindIcon(k) {
  return k === 'CLASS' ? 'box' : k === 'METHOD' ? 'corner-down-right' : 'function-square';
};
CGUI.kindColor = function kindColor(k) {
  return k === 'CLASS' ? 'var(--accent-violet)'
       : k === 'METHOD' ? 'var(--accent-cyan)'
       : 'var(--accent-emerald)';
};

// ---- pyvisHref (shared by explorers + files views) ----
CGUI.pyvisHref = function pyvisHref(path) {
  const t = document.documentElement.classList.contains('theme-light') ? 'light' : 'dark';
  return path + '?theme=' + t;
};
