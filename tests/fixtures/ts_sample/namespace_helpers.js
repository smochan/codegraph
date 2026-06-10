/* Plain-script namespace API pattern (no ES modules). */
'use strict';

window.CGUI = window.CGUI || {};

CGUI.esc = function esc(s) {
  return String(s ?? '');
};

CGUI.short = (qn) => String(qn).split('.').pop();

window.CGViews.flows = function renderFlows(host) {
  CGUI.esc(host.id);
  return host;
};

CGUI.VERSION = '1.0';
CGUI[dynamicKey] = function hidden() { return 1; };
