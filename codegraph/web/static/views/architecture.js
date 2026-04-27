/* Architecture view — infra topology + click-an-endpoint flow animation. */
'use strict';

(function () {
  const KIND_TIERS = {
    WEB_SERVER:   { tier: 1, label: 'Web / API'      },
    HTTP_CLIENT:  { tier: 2, label: 'HTTP clients'   },
    EXTERNAL_API: { tier: 2, label: 'External APIs'  },
    MESSAGING:    { tier: 2, label: 'Messaging'      },
    QUEUE:        { tier: 3, label: 'Queues'         },
    BROKER:       { tier: 3, label: 'Brokers'        },
    CACHE:        { tier: 4, label: 'Caches'         },
    SEARCH:       { tier: 4, label: 'Search'         },
    ORM:          { tier: 5, label: 'ORM / Query'    },
    DB:           { tier: 6, label: 'Databases'      },
    OBJECT_STORE: { tier: 6, label: 'Object storage' },
  };

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
      ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  }

  function renderArchitecture(host) {
    const arch = (window.state && window.state.data && window.state.data.architecture) || null;
    if (!arch || !arch.components || !arch.metrics) {
      host.innerHTML = '<div class="empty p-12 text-center text-ink-200">'
        + 'No infrastructure components detected. Make sure your project '
        + 'imports something from a supported package (express, redis, '
        + 'bullmq, pg, mongoose, sqlalchemy, ...). Then rebuild.</div>';
      return;
    }

    const m = arch.metrics;
    const components = arch.components || [];
    const handlers = arch.handlers || [];

    // Group components by tier.
    const byTier = new Map();
    for (const c of components) {
      const meta = KIND_TIERS[c.kind] || { tier: 9, label: c.kind };
      const tier = meta.tier;
      if (!byTier.has(tier)) byTier.set(tier, { tier, label: meta.label, items: [] });
      byTier.get(tier).items.push(c);
    }
    const tiers = Array.from(byTier.values()).sort((a, b) => a.tier - b.tier);

    const summaryCards = [
      { n: m.components,   l: 'Components'    },
      { n: m.handlers,     l: 'Endpoints'     },
      { n: m.import_sites, l: 'Import sites'  },
      { n: Object.keys(m.by_kind || {}).length, l: 'Component kinds' },
    ].map(c => `
      <div class="rounded-lg border border-ink-600/60 bg-ink-800/60 px-4 py-3">
        <div class="text-2xl font-semibold tracking-tight">${c.n}</div>
        <div class="text-[11px] uppercase tracking-[0.1em] text-ink-300 mt-1">${c.l}</div>
      </div>`).join('');

    host.innerHTML = `
      <div class="px-6 md:px-8 py-6 space-y-6">
        <div class="rounded-xl border border-brand-500/40 bg-gradient-to-br from-brand-700/15 via-ink-800/40 to-ink-800/40 px-5 py-4 text-sm text-ink-100">
          <b class="text-brand-300">Architecture view.</b>
          External services this project talks to (detected from imports).
          Click an endpoint on the right to highlight the components a request
          to that route reaches as it flows through the system.
        </div>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-3">${summaryCards}</div>

        <div class="grid grid-cols-1 lg:grid-cols-[1fr,360px] gap-5">
          <div class="rounded-xl border border-ink-600/60 bg-ink-800/40 p-5" id="arch-topology">
            <div class="text-[11px] uppercase tracking-[0.1em] text-ink-300 mb-3">Topology</div>
            <div id="arch-svg-host" class="overflow-auto"></div>
          </div>

          <aside class="rounded-xl border border-ink-600/60 bg-ink-800/40 p-4 max-h-[78vh] flex flex-col">
            <div class="text-[11px] uppercase tracking-[0.1em] text-ink-300 mb-2">Endpoints (${handlers.length})</div>
            <input id="arch-search" placeholder="Filter endpoints..." class="w-full mb-3 px-3 py-2 rounded-md bg-ink-900/70 border border-ink-600/60 text-sm focus:outline-none focus:border-brand-500"/>
            <div id="arch-handlers" class="flex-1 overflow-y-auto space-y-1.5 pr-1"></div>
            <div class="text-[11px] text-ink-300 mt-3 leading-relaxed">
              Click an endpoint to animate the request flow. Click again to clear.
            </div>
          </aside>
        </div>

        <div class="rounded-xl border border-ink-600/60 bg-ink-800/40 p-5">
          <div class="text-[11px] uppercase tracking-[0.1em] text-ink-300 mb-3">Component evidence</div>
          <div id="arch-evidence" class="space-y-3"></div>
        </div>
      </div>`;

    drawTopology(tiers, components, handlers);
    renderHandlerList(handlers, components);
    renderEvidence(components);
  }

  // ---------- Topology SVG ----------

  function drawTopology(tiers, components, handlers) {
    const svgHost = document.getElementById('arch-svg-host');
    const W = Math.max(820, svgHost.clientWidth || 820);
    const ROW_H = 110;
    const H = Math.max(360, tiers.length * ROW_H + 80);

    // Place a virtual "Client" + "App code" block at the top.
    const clientNode = { id: 'client', label: 'Client', kind: 'CLIENT', color: '#94a3b8', x: W * 0.5, y: 40 };
    const appNode    = { id: 'app',    label: 'Your code', kind: 'APP', color: '#a5b4fc', x: W * 0.5, y: 110 };

    // Spread each tier's components horizontally.
    const compPos = new Map();
    tiers.forEach((tier, ti) => {
      const y = 200 + ti * ROW_H;
      const items = tier.items;
      items.forEach((c, i) => {
        const x = ((i + 1) / (items.length + 1)) * W;
        compPos.set(c.id, { x, y, ...c });
      });
    });

    // Build edges: app -> every component (one per detected component).
    const edgeList = components.map(c => {
      const p = compPos.get(c.id);
      return { from: appNode, to: p, color: c.color, id: c.id };
    });

    let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" class="arch-svg" xmlns="http://www.w3.org/2000/svg">`;

    // Tier band labels.
    tiers.forEach((tier, ti) => {
      const y = 200 + ti * ROW_H;
      svg += `<text x="14" y="${y - 38}" fill="#5b6b8c" font-size="10" font-family="Inter,sans-serif" letter-spacing="1.2" text-transform="uppercase">${escapeHtml(tier.label)}</text>`;
      svg += `<line x1="14" y1="${y - 26}" x2="${W - 14}" y2="${y - 26}" stroke="#243049" stroke-dasharray="2,4"/>`;
    });

    // Edges.
    svg += '<g id="arch-edges">';
    for (const e of edgeList) {
      const d = `M ${e.from.x} ${e.from.y + 22} C ${e.from.x} ${(e.from.y + e.to.y) / 2}, ${e.to.x} ${(e.from.y + e.to.y) / 2}, ${e.to.x} ${e.to.y - 22}`;
      svg += `<path id="edge-${escapeHtml(e.id)}" d="${d}" fill="none" stroke="${e.color}" stroke-opacity="0.18" stroke-width="2" />`;
    }
    svg += '</g>';

    // Animated dot host (initially empty).
    svg += '<g id="arch-flow-dot"></g>';

    // Nodes.
    function rect(node, opts = {}) {
      const w = opts.w || 130, h = opts.h || 44;
      const x = node.x - w / 2, y = node.y - h / 2;
      return `
        <g class="arch-node" data-node-id="${escapeHtml(node.id)}" transform="translate(${x},${y})">
          <rect width="${w}" height="${h}" rx="10" ry="10"
                fill="${node.color}" fill-opacity="0.18"
                stroke="${node.color}" stroke-width="1.2"/>
          <text x="${w / 2}" y="${h / 2 + 4}" text-anchor="middle"
                fill="#e6ecf5" font-size="12" font-family="Inter,sans-serif"
                font-weight="500">${escapeHtml(node.label)}</text>
        </g>`;
    }

    svg += rect(clientNode, { w: 110, h: 36 });
    svg += rect(appNode,    { w: 140, h: 40 });
    svg += `<path d="M ${clientNode.x} ${clientNode.y + 18} L ${appNode.x} ${appNode.y - 20}" stroke="#5b6b8c" stroke-width="1.5" stroke-dasharray="4,3" fill="none"/>`;

    components.forEach(c => {
      const p = compPos.get(c.id);
      if (p) svg += rect(p);
    });
    svg += '</svg>';
    svgHost.innerHTML = svg;
  }

  // ---------- Endpoint list + flow animation ----------

  function renderHandlerList(handlers, components) {
    const compById = new Map(components.map(c => [c.id, c]));
    const host = document.getElementById('arch-handlers');
    if (!handlers.length) {
      host.innerHTML = '<div class="text-ink-300 text-xs px-2 py-3">No HANDLER-tagged routes found. Run <code>codegraph build</code> on a project with routes (FastAPI, Flask, NestJS, Express decorators, ...).</div>';
      return;
    }

    function methodColor(method) {
      const m = (method || '').toUpperCase();
      if (m === 'GET')    return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40';
      if (m === 'POST')   return 'bg-amber-500/20 text-amber-300 border-amber-500/40';
      if (m === 'PUT')    return 'bg-sky-500/20 text-sky-300 border-sky-500/40';
      if (m === 'PATCH')  return 'bg-violet-500/20 text-violet-300 border-violet-500/40';
      if (m === 'DELETE') return 'bg-rose-500/20 text-rose-300 border-rose-500/40';
      return 'bg-ink-600/40 text-ink-200 border-ink-500/40';
    }

    host.innerHTML = handlers.map((h, i) => `
      <button data-i="${i}" class="arch-handler w-full text-left rounded-md border border-ink-600/50 bg-ink-900/40 hover:border-brand-500/60 hover:bg-ink-700/40 px-3 py-2 transition">
        <div class="flex items-center gap-2">
          <span class="text-[10px] font-mono px-1.5 py-0.5 rounded border ${methodColor(h.method)}">${escapeHtml(h.method || '???')}</span>
          <span class="font-mono text-xs text-ink-100 truncate">${escapeHtml(h.path || h.name)}</span>
        </div>
        <div class="text-[10px] text-ink-300 mt-1 truncate" title="${escapeHtml(h.qualname)}">${escapeHtml(h.qualname || h.name)}</div>
        <div class="text-[10px] text-ink-300 mt-0.5">${(h.components || []).length} component${(h.components||[]).length === 1 ? '' : 's'}</div>
      </button>`).join('');

    host.querySelectorAll('.arch-handler').forEach(btn => {
      btn.addEventListener('click', () => {
        const i = parseInt(btn.dataset.i, 10);
        host.querySelectorAll('.arch-handler').forEach(b => b.classList.remove('ring-2', 'ring-brand-500'));
        btn.classList.add('ring-2', 'ring-brand-500');
        openLearnModal(handlers[i], compById, Array.from(compById.values()));
      });
    });

    const search = document.getElementById('arch-search');
    if (search) {
      search.addEventListener('input', e => {
        const q = e.target.value.toLowerCase();
        host.querySelectorAll('.arch-handler').forEach((btn, i) => {
          const h = handlers[i];
          const hay = ((h.method || '') + ' ' + (h.path || '') + ' ' + (h.qualname || '')).toLowerCase();
          btn.style.display = hay.includes(q) ? '' : 'none';
        });
      });
    }
  }

  // ---------- Learn Mode: full request lifecycle modal ----------

  function buildLifecycleStages(handler, components) {
    const reachable = (handler.components || [])
      .map(id => components.find(c => c.id === id))
      .filter(Boolean);
    const caches    = reachable.filter(c => c.kind === 'CACHE');
    const dbs       = reachable.filter(c => c.kind === 'DB' || c.kind === 'ORM');
    const queues    = reachable.filter(c => c.kind === 'QUEUE' || c.kind === 'BROKER');
    const externals = reachable.filter(c => c.kind === 'EXTERNAL_API' || c.kind === 'HTTP_CLIENT');
    const ws        = reachable.filter(c => c.kind === 'WEB_SERVER');
    const wsLabel   = ws[0]?.label || 'App Server';

    const lanes = [
      { id: 'client',  label: 'Mobile Client', color: '#94a3b8', icon: 'phone' },
      { id: 'net',     label: 'Internet',      color: '#5b6b8c', icon: 'globe' },
      { id: 'tls',     label: 'TLS Layer',     color: '#f59e0b', icon: 'lock' },
      { id: 'server',  label: wsLabel,         color: '#a78bfa', icon: 'server' },
      { id: 'mw',      label: 'Middleware',    color: '#22d3ee', icon: 'shield' },
      { id: 'handler', label: 'Route Handler', color: '#6366f1', icon: 'cpu' },
    ];
    if (caches.length)    lanes.push({ id: 'cache', label: caches[0].label,   color: caches[0].color,    icon: 'zap' });
    if (dbs.length)       lanes.push({ id: 'db',    label: dbs[0].label,      color: dbs[0].color,       icon: 'database' });
    if (queues.length)    lanes.push({ id: 'queue', label: queues[0].label,   color: queues[0].color,    icon: 'list' });
    if (externals.length) lanes.push({ id: 'ext',   label: externals[0].label,color: externals[0].color, icon: 'cloud' });

    const M = (handler.method || 'GET').toUpperCase();
    const P = handler.path || '/';

    const stages = [];
    const add = (from, to, label, detail, kind) => stages.push({ from, to, label, detail, kind: kind || 'app' });

    // ---- Phase 1: Network handshake (static) ----
    add('client', 'net',
      'DNS lookup',
      `Mobile resolves the API hostname into an IP address. The OS asks its configured DNS server (e.g. 8.8.8.8) for the A/AAAA record. Once it has the IP, it can open a TCP socket.`,
      'net');
    add('client', 'server',
      'TCP SYN',
      `Three-way handshake step 1. The client sends a TCP packet with the SYN flag set, proposing an initial sequence number. No data is sent yet — this is just "I want to talk to you."`,
      'net');
    add('server', 'client',
      'TCP SYN-ACK',
      `Step 2. Server replies acknowledging the client's SYN and sending its OWN SYN with its initial sequence number. Now both sides know each other's starting sequence.`,
      'net');
    add('client', 'server',
      'TCP ACK',
      `Step 3. Client acknowledges the server's SYN. The TCP connection is now ESTABLISHED — bytes can flow reliably and in-order in both directions.`,
      'net');

    // ---- Phase 2: TLS handshake ----
    add('client', 'tls',
      'TLS ClientHello',
      `For HTTPS, the client now starts a TLS handshake on top of TCP. ClientHello lists the TLS versions and cipher suites the client supports plus a random nonce. SNI (Server Name Indication) tells the server which hostname this connection is for.`,
      'tls');
    add('tls', 'client',
      'ServerHello + Certificate',
      `Server picks a cipher suite, sends its own random nonce, and presents its X.509 certificate chain. The client verifies the certificate against trusted CAs and checks that the hostname matches the SAN field.`,
      'tls');
    add('client', 'tls',
      'Key exchange + Finished',
      `Client and server agree on a shared symmetric key (ECDHE in modern TLS). Both sides send a "Finished" record encrypted with the new key, proving the handshake wasn't tampered with. Encryption is now active.`,
      'tls');

    // ---- Phase 3: HTTP request ----
    add('client', 'server',
      `HTTP ${M} ${P}`,
      `The actual API call. Now encrypted inside the TLS tunnel. Includes headers (Authorization, Content-Type, ...) and, for ${M === 'GET' || M === 'DELETE' ? 'most ' + M + ' requests, no body' : 'POST/PUT/PATCH, a JSON body'}.`,
      'app');
    add('server', 'mw',
      'Run middleware chain',
      `Express runs every middleware registered before this route — typically: body parser → CORS → request logger → auth (verify JWT / session cookie) → rate limit → validation. Any middleware can short-circuit with an error response.`,
      'app');
    add('mw', 'handler',
      `Dispatch to ${handler.name || 'handler'}()`,
      `Auth + validation passed. Express invokes the handler function registered for this route. ${handler.qualname ? 'Source: ' + handler.qualname : ''}`,
      'app');

    // ---- Phase 4: Project-specific data layer ----
    if (caches.length) {
      add('handler', 'cache',
        'GET cached value',
        `Handler checks ${caches[0].label} first to avoid hitting the DB. The lookup key is usually composed from request params — e.g. user:123:profile.`,
        'data');
      add('cache', 'handler',
        'cache miss / hit',
        `If cached, return immediately and skip the DB. If miss, fall through to DB and write-back to cache after.`,
        'data');
    }
    if (dbs.length) {
      add('handler', 'db',
        `Query ${dbs[0].label}`,
        `Handler issues a query through ${dbs[0].label}. Connection is reused from a pool. The DB plans the query, hits indexes, returns rows.`,
        'data');
      add('db', 'handler',
        'rows / documents',
        `Result set comes back as JS objects. Handler may shape them (filter fields, populate relations) before responding.`,
        'data');
    }
    if (queues.length) {
      add('handler', 'queue',
        'Enqueue background job',
        `Long-running work (sending email, generating report, calling slow third-party API) is pushed onto ${queues[0].label} so the response can return fast. A separate worker process picks it up.`,
        'data');
    }
    if (externals.length) {
      add('handler', 'ext',
        `Call ${externals[0].label}`,
        `Handler makes an outbound HTTP call. Each external call adds latency + failure modes — usually wrapped in a try/catch with timeout.`,
        'data');
    }

    // ---- Phase 5: response ----
    add('handler', 'mw',
      'res.json(payload)',
      `Handler builds the response payload (often a JSON object) and hands it back to Express. Response middleware (compression, CORS headers, logging) runs in reverse order.`,
      'app');
    add('mw', 'server',
      'Build HTTP response',
      `Express assembles the status line + headers + body. Status is 2xx for success, 4xx for client errors, 5xx for server errors.`,
      'app');
    add('server', 'tls',
      'TLS encrypt',
      `Response bytes are encrypted with the symmetric key established earlier and chunked into TLS records.`,
      'tls');
    add('tls', 'client',
      `HTTP ${M === 'POST' ? '201' : '200'} OK + body`,
      `The encrypted response travels back through TCP. Client decrypts, parses headers, hands the body to the app code. UI updates.`,
      'net');

    return { lanes, stages };
  }

  function openLearnModal(handler, compById, components) {
    closeLearnModal();
    const { lanes, stages } = buildLifecycleStages(handler, components);

    const overlay = document.createElement('div');
    overlay.id = 'learn-modal';
    overlay.className = 'fixed inset-0 z-[100] bg-ink-950/85 backdrop-blur-sm flex items-stretch';
    overlay.innerHTML = `
      <div class="flex-1 flex flex-col">
        <div class="flex items-center justify-between border-b border-ink-600/60 bg-ink-900/80 px-6 py-4">
          <div class="flex items-center gap-3 min-w-0">
            <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-brand-500 to-accent-cyan flex items-center justify-center text-ink-950 font-bold">
              <i data-lucide="route"></i>
            </div>
            <div class="min-w-0">
              <div class="text-[11px] uppercase tracking-[0.14em] text-ink-300">Request Lifecycle</div>
              <div class="text-lg font-semibold tracking-tight truncate">
                <span class="font-mono text-brand-300">${escapeHtml(handler.method || '???')}</span>
                <span class="font-mono text-ink-100 ml-2">${escapeHtml(handler.path || '')}</span>
              </div>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <button id="learn-prev" class="icon-btn" title="Previous step (←)"><i data-lucide="chevron-left"></i></button>
            <button id="learn-play" class="rounded-md bg-brand-600 hover:bg-brand-500 text-white px-3 py-1.5 text-sm font-medium flex items-center gap-1.5 transition">
              <i data-lucide="play" class="w-4 h-4"></i><span>Play</span>
            </button>
            <button id="learn-next" class="icon-btn" title="Next step (→)"><i data-lucide="chevron-right"></i></button>
            <button id="learn-close" class="icon-btn ml-2" title="Close (Esc)"><i data-lucide="x"></i></button>
          </div>
        </div>

        <div class="flex-1 grid grid-cols-1 lg:grid-cols-[1fr,360px] gap-0 min-h-0">
          <div class="overflow-auto p-6 bg-ink-900/40">
            <div id="learn-svg-host" class="rounded-xl border border-ink-600/60 bg-ink-800/50 p-4"></div>
          </div>
          <aside class="overflow-y-auto border-l border-ink-600/60 bg-ink-800/60 p-5">
            <div class="text-[11px] uppercase tracking-[0.1em] text-ink-300 mb-2">
              Step <span id="learn-step-num">1</span> / <span id="learn-step-total">${stages.length}</span>
            </div>
            <div id="learn-stage-label" class="text-base font-semibold tracking-tight mb-1"></div>
            <div id="learn-stage-kind" class="text-[11px] uppercase tracking-[0.1em] mb-4"></div>
            <div id="learn-stage-detail" class="text-sm leading-relaxed text-ink-100"></div>
            <div class="text-[11px] text-ink-300 mt-6 pt-4 border-t border-ink-600/60 leading-relaxed">
              <b class="text-ink-100">Keys:</b> ←/→ step, Space play/pause, Esc close.
            </div>
          </aside>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    drawLearnSequence(lanes, stages);

    let cur = 0;
    let playing = false;
    let timer = null;

    function setStep(i, opts) {
      cur = Math.max(0, Math.min(stages.length - 1, i));
      const s = stages[cur];
      document.getElementById('learn-step-num').textContent = cur + 1;
      document.getElementById('learn-stage-label').textContent = s.label;
      const kindEl = document.getElementById('learn-stage-kind');
      kindEl.textContent = s.kind === 'net' ? 'Network · TCP' :
                           s.kind === 'tls' ? 'Network · TLS' :
                           s.kind === 'data' ? 'Data layer' : 'Application';
      kindEl.style.color = s.kind === 'net' ? '#94a3b8' :
                           s.kind === 'tls' ? '#fbbf24' :
                           s.kind === 'data' ? '#22d3ee' : '#a78bfa';
      document.getElementById('learn-stage-detail').textContent = s.detail;
      highlightArrow(cur, opts && opts.animate);
    }
    function play() {
      if (cur >= stages.length - 1) cur = -1;
      playing = true;
      document.getElementById('learn-play').innerHTML = '<i data-lucide="pause" class="w-4 h-4"></i><span>Pause</span>';
      lucide.createIcons();
      tick();
    }
    function pause() {
      playing = false;
      if (timer) { clearTimeout(timer); timer = null; }
      document.getElementById('learn-play').innerHTML = '<i data-lucide="play" class="w-4 h-4"></i><span>Play</span>';
      lucide.createIcons();
    }
    function tick() {
      if (!playing) return;
      if (cur >= stages.length - 1) { pause(); return; }
      setStep(cur + 1, { animate: true });
      const dur = stages[cur].kind === 'data' ? 1400 : 1100;
      timer = setTimeout(tick, dur);
    }

    setStep(0, { animate: true });
    lucide.createIcons();
    document.getElementById('learn-play').onclick = () => playing ? pause() : play();
    document.getElementById('learn-prev').onclick = () => { pause(); setStep(cur - 1, { animate: true }); };
    document.getElementById('learn-next').onclick = () => { pause(); setStep(cur + 1, { animate: true }); };
    document.getElementById('learn-close').onclick = closeLearnModal;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeLearnModal(); });
    document.addEventListener('keydown', learnKeyHandler);

    function learnKeyHandler(e) {
      if (!document.getElementById('learn-modal')) {
        document.removeEventListener('keydown', learnKeyHandler);
        return;
      }
      if (e.key === 'Escape')      { closeLearnModal(); }
      else if (e.key === 'ArrowLeft')  { pause(); setStep(cur - 1, { animate: true }); }
      else if (e.key === 'ArrowRight') { pause(); setStep(cur + 1, { animate: true }); }
      else if (e.key === ' ')      { e.preventDefault(); playing ? pause() : play(); }
    }

    // Auto-play after a brief beat so user sees the first step.
    setTimeout(() => { if (document.getElementById('learn-modal')) play(); }, 600);
  }

  function closeLearnModal() {
    const m = document.getElementById('learn-modal');
    if (m) m.remove();
  }

  // Render the lane diagram into #learn-svg-host. Returns nothing — arrows
  // are looked up by id during animation.
  function drawLearnSequence(lanes, stages) {
    const host = document.getElementById('learn-svg-host');
    const W = Math.max(900, host.clientWidth || 900);
    const LANE_H_TOP = 70;
    const ROW_H = 56;
    const H = LANE_H_TOP + 30 + stages.length * ROW_H + 30;

    const laneX = new Map();
    lanes.forEach((L, i) => {
      laneX.set(L.id, ((i + 0.5) / lanes.length) * W);
    });

    let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" xmlns="http://www.w3.org/2000/svg" id="learn-svg">`;

    // Vertical lifelines
    lanes.forEach(L => {
      const x = laneX.get(L.id);
      svg += `<line x1="${x}" y1="${LANE_H_TOP}" x2="${x}" y2="${H - 20}" stroke="${L.color}" stroke-opacity="0.25" stroke-width="1.5" stroke-dasharray="2,4"/>`;
    });

    // Lane headers
    lanes.forEach(L => {
      const x = laneX.get(L.id);
      const w = Math.min(160, (W / lanes.length) - 10);
      svg += `
        <g transform="translate(${x - w / 2}, 14)">
          <rect width="${w}" height="44" rx="10" ry="10"
                fill="${L.color}" fill-opacity="0.18" stroke="${L.color}" stroke-width="1.4"/>
          <text x="${w / 2}" y="27" text-anchor="middle"
                fill="#e6ecf5" font-size="12" font-family="Inter,sans-serif" font-weight="600">${escapeHtml(L.label)}</text>
        </g>`;
    });

    // Step rows + arrows
    stages.forEach((s, i) => {
      const y = LANE_H_TOP + 30 + i * ROW_H + ROW_H / 2;
      const x1 = laneX.get(s.from);
      const x2 = laneX.get(s.to);
      if (x1 == null || x2 == null) return;
      const dir = x2 >= x1 ? 1 : -1;
      const color = s.kind === 'net' ? '#94a3b8' :
                    s.kind === 'tls' ? '#fbbf24' :
                    s.kind === 'data' ? '#22d3ee' : '#a78bfa';
      const ax1 = x1 + dir * 6;
      const ax2 = x2 - dir * 6;

      // Step number gutter
      svg += `<text x="14" y="${y + 4}" font-size="10" fill="#5b6b8c" font-family="Inter,sans-serif">${i + 1}</text>`;

      // Faint baseline arrow (dimmed when inactive)
      svg += `<g class="learn-arrow" id="learn-arrow-${i}" data-color="${color}" opacity="0.25">
                <line x1="${ax1}" y1="${y}" x2="${ax2}" y2="${y}"
                      stroke="${color}" stroke-width="2" marker-end="url(#learn-head-${i})"/>
                <text x="${(ax1 + ax2) / 2}" y="${y - 8}" text-anchor="middle"
                      fill="#e6ecf5" font-size="11" font-family="Inter,sans-serif"
                      font-weight="500">${escapeHtml(s.label)}</text>
              </g>
              <defs>
                <marker id="learn-head-${i}" viewBox="0 0 10 10" refX="9" refY="5"
                        markerWidth="6" markerHeight="6" orient="auto">
                  <path d="M0,0 L10,5 L0,10 z" fill="${color}"/>
                </marker>
              </defs>`;
    });

    // Animated dot host
    svg += '<g id="learn-dot-host"></g>';
    svg += '</svg>';
    host.innerHTML = svg;
  }

  function highlightArrow(i, animate) {
    document.querySelectorAll('.learn-arrow').forEach((g, idx) => {
      const past = idx < i;
      const cur = idx === i;
      g.setAttribute('opacity', cur ? '1' : (past ? '0.55' : '0.18'));
      const line = g.querySelector('line');
      if (line) line.setAttribute('stroke-width', cur ? '3.2' : '2');
    });
    if (!animate) return;
    const g = document.getElementById('learn-arrow-' + i);
    if (!g) return;
    const line = g.querySelector('line');
    if (!line) return;
    const x1 = parseFloat(line.getAttribute('x1'));
    const y1 = parseFloat(line.getAttribute('y1'));
    const x2 = parseFloat(line.getAttribute('x2'));
    const color = g.getAttribute('data-color') || '#22d3ee';
    const host = document.getElementById('learn-dot-host');
    if (!host) return;
    const ns = 'http://www.w3.org/2000/svg';
    const dot = document.createElementNS(ns, 'circle');
    dot.setAttribute('r', '5');
    dot.setAttribute('fill', color);
    dot.setAttribute('cy', y1);
    dot.setAttribute('cx', x1);
    host.appendChild(dot);
    const start = performance.now();
    const dur = 700;
    function step(now) {
      const t = Math.min(1, (now - start) / dur);
      const eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      dot.setAttribute('cx', x1 + (x2 - x1) * eased);
      if (t < 1) requestAnimationFrame(step);
      else { dot.setAttribute('opacity', '0'); setTimeout(() => dot.remove(), 180); }
    }
    requestAnimationFrame(step);
  }

  // ---------- Component evidence ----------

  function renderEvidence(components) {
    const host = document.getElementById('arch-evidence');
    if (!components.length) {
      host.innerHTML = '<div class="text-ink-300 text-xs">none</div>';
      return;
    }
    host.innerHTML = components.map(c => `
      <div class="rounded-md border border-ink-600/50 bg-ink-900/40 px-3 py-2.5">
        <div class="flex items-center gap-2 mb-1.5">
          <span class="inline-block w-2.5 h-2.5 rounded-sm" style="background:${c.color}"></span>
          <span class="font-medium text-sm">${escapeHtml(c.label)}</span>
          <span class="text-[10px] uppercase tracking-[0.1em] text-ink-300">${escapeHtml(c.kind)}</span>
          <span class="ml-auto text-[10px] text-ink-300">${c.count} import${c.count === 1 ? '' : 's'} in ${c.files.length} file${c.files.length === 1 ? '' : 's'}</span>
        </div>
        <div class="text-[11px] font-mono text-ink-200 space-y-0.5">
          ${(c.evidence || []).map(e => `<div class="truncate">${escapeHtml(e)}</div>`).join('')}
        </div>
      </div>`).join('');
  }

  // Expose entry point so app.js can dispatch into us.
  window.renderArchitectureView = renderArchitecture;
})();
