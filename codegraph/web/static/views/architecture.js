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

  // ---------- DF4 / Phase 4: per-handler dataflow trace ----------

  // Role → swimlane id + colour. Matches role palette in graph3d_transform.js
  // (HANDLER amber, SERVICE blue, COMPONENT green, REPO purple).
  const DF_ROLE_LANES = {
    COMPONENT: { id: 'df-component', label: 'Component',  color: '#22c55e', icon: 'layout' },
    HANDLER:   { id: 'df-handler',   label: 'Handler',    color: '#fbbf24', icon: 'cpu' },
    SERVICE:   { id: 'df-service',   label: 'Service',    color: '#60a5fa', icon: 'cog' },
    REPO:      { id: 'df-repo',      label: 'Repository', color: '#a78bfa', icon: 'database' },
    DB:        { id: 'df-db',        label: 'Storage',    color: '#22d3ee', icon: 'hard-drive' },
  };

  // Map a hop to a lane id given its role/kind.
  function hopLaneId(hop) {
    if (!hop) return 'df-handler';
    if (hop.kind === 'FETCH_CALL') return 'df-component';
    if (hop.kind === 'READS_FROM' || hop.kind === 'WRITES_TO') return 'df-db';
    if (hop.role && DF_ROLE_LANES[hop.role]) return DF_ROLE_LANES[hop.role].id;
    if (hop.kind === 'ROUTE') return 'df-handler';
    return 'df-service';
  }

  // Format args list as compact "(a, b)" string.
  function formatHopArgs(hop) {
    const args = (hop && hop.args) || [];
    if (!args.length) return '';
    return '(' + args.map(a => String(a)).join(', ') + ')';
  }

  // Short label for hop based on its kind + qualname.
  function hopLabel(hop) {
    const qn = hop.qualname || '';
    const tail = qn.includes('::') ? qn.split('::').pop()
               : qn.split('.').pop();
    const argTxt = formatHopArgs(hop);
    if (hop.kind === 'FETCH_CALL') return 'fetch ' + (tail || qn) + argTxt;
    if (hop.kind === 'ROUTE')      return 'dispatch → ' + (tail || qn) + argTxt;
    if (hop.kind === 'READS_FROM') return 'read ' + (tail || qn);
    if (hop.kind === 'WRITES_TO')  return 'write ' + (tail || qn);
    return (tail || qn) + argTxt;
  }

  // Build a Phase 4 segment: lanes + stages + meta from the handler's
  // dataflow.hops. Returns { lanes, stages, meta } or null when no data.
  // Pure function, suitable for unit testing.
  function buildDataflowSegment(handler) {
    const df = handler && handler.dataflow;
    if (!df) {
      return { lanes: [], stages: [], meta: { available: false, hopCount: 0, confidence: 0 } };
    }
    const hops = Array.isArray(df.hops) ? df.hops : [];
    const confidence = typeof df.confidence === 'number' ? df.confidence : 0;
    if (!hops.length) {
      return { lanes: [], stages: [],
        meta: { available: true, hopCount: 0, confidence, empty: true } };
    }

    // Collect needed lanes in encounter order, dedupe.
    const lanes = [];
    const seen = new Set();
    function addLane(id) {
      if (seen.has(id)) return;
      seen.add(id);
      const proto = Object.values(DF_ROLE_LANES).find(L => L.id === id)
                 || DF_ROLE_LANES.SERVICE;
      lanes.push({ ...proto, id });
    }

    // Always start chain from 'handler' lane (the upstream side of the first
    // hop) so the sequence connects to Phase 3's mw → handler arrow.
    const stages = [];
    let prev = 'handler';
    for (const hop of hops) {
      const lane = hopLaneId(hop);
      addLane(lane);
      const label = hopLabel(hop);
      const detail = (hop.file ? (hop.file + (hop.line ? ':' + hop.line : '')) : hop.qualname || '')
        + (hop.role ? '  ·  role=' + hop.role : '')
        + (hop.kind ? '  ·  kind=' + hop.kind : '');
      stages.push({
        from: prev, to: lane,
        label, detail,
        kind: 'data',
        hop,
      });
      prev = lane;
    }

    return {
      lanes, stages,
      meta: {
        available: true,
        hopCount: hops.length,
        confidence,
        lowConfidence: confidence < 0.5,
        empty: false,
      },
    };
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
    // Prefer real dataflow.hops when the backend HLD payload includes them
    // (codegraph >= v0.3). Fall back to the generic infra-component animation
    // otherwise so older builds still render something useful.
    const dfSeg = buildDataflowSegment(handler);
    let dataflowMeta = dfSeg.meta;
    if (dfSeg.stages.length) {
      // Wire DF lanes onto the swim lane list (avoid id collisions with the
      // generic lanes by giving them df-* prefixes inside DF_ROLE_LANES).
      dfSeg.lanes.forEach(L => lanes.push(L));
      // Re-anchor the first hop's "from" to the existing 'handler' lane that
      // Phase 3 already established. dfSeg.stages[0].from is already 'handler'.
      dfSeg.stages.forEach(s => stages.push(s));
    } else {
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

    return { lanes, stages, dataflowMeta };
  }

  // Tiny chip shown next to the method/path in the modal header. Communicates
  // whether Phase 4 is rendering real DF4 data, the empty fallback, or a
  // low-confidence trace.
  function renderDataflowChip(meta) {
    if (!meta || !meta.available) return '';
    if (meta.empty) {
      return `<div data-df-chip="empty"
        class="mt-1 inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.1em]
               px-2 py-0.5 rounded-full border border-amber-500/40 bg-amber-500/10 text-amber-200">
        <i data-lucide="alert-triangle" style="width:10px;height:10px"></i>
        no trace data — run <code class="font-mono">codegraph build</code> first
      </div>`;
    }
    if (meta.lowConfidence) {
      return `<div data-df-chip="low-confidence"
        class="mt-1 inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.1em]
               px-2 py-0.5 rounded-full border border-amber-500/40 bg-amber-500/10 text-amber-200">
        <i data-lucide="alert-circle" style="width:10px;height:10px"></i>
        low-confidence trace (${(meta.confidence * 100).toFixed(0)}%)
      </div>`;
    }
    return `<div data-df-chip="ok"
      class="mt-1 inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.1em]
             px-2 py-0.5 rounded-full border border-emerald-500/40 bg-emerald-500/10 text-emerald-200">
      <i data-lucide="git-branch" style="width:10px;height:10px"></i>
      ${meta.hopCount} hop${meta.hopCount === 1 ? '' : 's'} · ${(meta.confidence * 100).toFixed(0)}%
    </div>`;
  }

  function openLearnModal(handler, compById, components) {
    closeLearnModal();
    const { lanes, stages, dataflowMeta } = buildLifecycleStages(handler, components);

    const VALID_MODES = ['pipeline', 'diagram', 'lanes'];
    let mode = 'pipeline';
    try {
      const saved = localStorage.getItem('arch.lifecycleMode');
      if (VALID_MODES.includes(saved)) mode = saved;
    } catch (_) {}

    ensurePipelineStyles();
    ensureDiagramStyles();

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
              ${renderDataflowChip(dataflowMeta)}
            </div>
          </div>
          <div class="flex items-center gap-2">
            <div class="learn-mode-toggle flex rounded-md border border-ink-600/60 overflow-hidden mr-1" title="Cycle visualization (V)">
              <button id="learn-mode-pipeline" class="learn-mode-btn">Pipeline</button>
              <button id="learn-mode-diagram"  class="learn-mode-btn">Diagram</button>
              <button id="learn-mode-lanes"    class="learn-mode-btn">Lanes</button>
            </div>
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
              <b class="text-ink-100">Keys:</b> ←/→ step, Space play/pause, V toggle view, Esc close.
            </div>
          </aside>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    let cur = 0;
    let playing = false;
    let timer = null;

    function applyStep(i, animate) {
      if      (mode === 'pipeline') pipelineSetStep(i, animate, lanes, stages);
      else if (mode === 'diagram')  diagramSetStep(i, animate, lanes, stages);
      else                          highlightArrow(i, animate);
    }

    function renderForMode() {
      if      (mode === 'pipeline') drawPipeline(lanes, stages);
      else if (mode === 'diagram')  drawDiagram(lanes, stages);
      else                          drawLearnSequence(lanes, stages);
      updateModeButtons();
      applyStep(cur, false);
      if (window.lucide) lucide.createIcons();
    }

    function updateModeButtons() {
      ['pipeline', 'diagram', 'lanes'].forEach(m => {
        const el = document.getElementById('learn-mode-' + m);
        if (el) el.classList.toggle('is-active', mode === m);
      });
    }

    function switchMode(newMode) {
      if (newMode === mode) return;
      mode = newMode;
      try { localStorage.setItem('arch.lifecycleMode', mode); } catch (_) {}
      renderForMode();
    }

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
      applyStep(cur, opts && opts.animate);
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

    renderForMode();
    setStep(0, { animate: true });
    lucide.createIcons();
    document.getElementById('learn-play').onclick = () => playing ? pause() : play();
    document.getElementById('learn-prev').onclick = () => { pause(); setStep(cur - 1, { animate: true }); };
    document.getElementById('learn-next').onclick = () => { pause(); setStep(cur + 1, { animate: true }); };
    document.getElementById('learn-close').onclick = closeLearnModal;
    document.getElementById('learn-mode-pipeline').onclick = () => switchMode('pipeline');
    document.getElementById('learn-mode-diagram').onclick  = () => switchMode('diagram');
    document.getElementById('learn-mode-lanes').onclick    = () => switchMode('lanes');
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
      else if (e.key === 'v' || e.key === 'V') {
        const order = ['pipeline', 'diagram', 'lanes'];
        switchMode(order[(order.indexOf(mode) + 1) % order.length]);
      }
    }

    // Auto-play after a brief beat so user sees the first step.
    setTimeout(() => { if (document.getElementById('learn-modal')) play(); }, 600);
  }

  function closeLearnModal() {
    const m = document.getElementById('learn-modal');
    if (m) m.remove();
  }

  // ---------- Pipeline mode (horizontal strip + scrolling log) ----------

  function ensurePipelineStyles() {
    if (document.getElementById('arch-pipeline-styles')) return;
    const style = document.createElement('style');
    style.id = 'arch-pipeline-styles';
    style.textContent = `
      .learn-mode-btn {
        background: rgba(15,23,42,0.55);
        color: #94a3b8;
        padding: 6px 12px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        transition: background 0.15s, color 0.15s;
      }
      .learn-mode-btn:hover { background: rgba(99,102,241,0.18); color: #c7d2fe; }
      .learn-mode-btn.is-active {
        background: linear-gradient(135deg, #6366f1, #06b6d4);
        color: #0b1020;
      }

      #learn-pipeline-host { display:flex; flex-direction:column; gap:18px; }

      #pipe-strip {
        position: relative;
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px;
        padding: 18px 16px 14px;
        background: rgba(15,23,42,0.45);
        border: 1px solid rgba(91,107,140,0.35);
        border-radius: 14px;
      }
      .pipe-box {
        --lane-color: #94a3b8;
        display: flex; align-items: center; gap: 7px;
        padding: 9px 13px; border-radius: 10px;
        background: rgba(15,23,42,0.65);
        border: 1.5px solid rgba(148,163,184,0.35);
        color: #e2e8f0;
        font-size: 12px; font-weight: 500;
        opacity: 0.55;
        transition: all 0.18s ease;
        white-space: nowrap;
      }
      .pipe-box.is-past {
        opacity: 0.85;
        background: rgba(15,23,42,0.7);
        border-color: var(--lane-color);
      }
      .pipe-box.is-active {
        opacity: 1;
        background: rgba(15,23,42,0.85);
        border-color: var(--lane-color);
        box-shadow: 0 0 0 3px rgba(99,102,241,0.18),
                    0 0 22px rgba(99,102,241,0.35);
        transform: translateY(-1px);
      }
      .pipe-arrow {
        color: rgba(148,163,184,0.55);
        font-size: 16px;
        user-select: none;
      }
      #pipe-dot {
        position: absolute;
        width: 11px; height: 11px;
        border-radius: 50%;
        background: #22d3ee;
        box-shadow: 0 0 14px #22d3ee, 0 0 4px #fff;
        pointer-events: none;
        opacity: 0;
        transition: left 600ms cubic-bezier(0.4,0,0.2,1),
                    top 600ms cubic-bezier(0.4,0,0.2,1),
                    opacity 0.2s linear;
        z-index: 5;
      }
      #pipe-dot.is-on { opacity: 1; }

      #pipe-log {
        max-height: 360px;
        overflow-y: auto;
        padding: 12px 16px;
        background: rgba(2,6,23,0.7);
        border: 1px solid rgba(91,107,140,0.35);
        border-radius: 12px;
        font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 12px;
        line-height: 1.7;
      }
      .pipe-log-row {
        display: grid;
        grid-template-columns: 28px 90px auto 1fr;
        gap: 10px;
        padding: 1px 0;
        animation: pipeLogIn 0.32s ease both;
      }
      .pipe-log-row .col-num   { color: #475569; }
      .pipe-log-row .col-time  { color: #64748b; }
      .pipe-log-row .col-tag   { font-weight: 500; white-space: nowrap; }
      .pipe-log-row .col-msg   { color: #cbd5e1; }
      .pipe-log-row.is-current .col-num,
      .pipe-log-row.is-current .col-time { color: #94a3b8; }
      .pipe-log-row.is-current .col-msg  { color: #f8fafc; font-weight: 500; }
      @keyframes pipeLogIn {
        from { opacity: 0; transform: translateY(4px); }
        to   { opacity: 1; transform: translateY(0); }
      }
    `;
    document.head.appendChild(style);
  }

  function drawPipeline(lanes /*, stages */) {
    const host = document.getElementById('learn-svg-host');
    if (!host) return;
    let html = '<div id="learn-pipeline-host">';
    html += '<div id="pipe-strip">';
    lanes.forEach((L, i) => {
      if (i > 0) html += '<div class="pipe-arrow">→</div>';
      html += `<div class="pipe-box" data-lane="${escapeHtml(L.id)}" style="--lane-color:${L.color}; color:#e6ecf5;">
        <i data-lucide="${escapeHtml(L.icon)}" style="width:14px;height:14px;color:${L.color};"></i>
        <span>${escapeHtml(L.label)}</span>
      </div>`;
    });
    html += '<div id="pipe-dot"></div>';
    html += '</div>';
    html += '<div id="pipe-log" aria-live="polite"></div>';
    html += '</div>';
    host.innerHTML = html;
  }

  function pipelineSetStep(i, animate, lanes, stages) {
    const stripBoxes = document.querySelectorAll('#pipe-strip .pipe-box');
    if (!stripBoxes.length) return;
    const stage = stages[i];
    if (!stage) return;

    const visited = new Set();
    for (let k = 0; k <= i; k++) {
      visited.add(stages[k].from);
      visited.add(stages[k].to);
    }
    stripBoxes.forEach(box => {
      const lane = box.dataset.lane;
      box.classList.remove('is-active', 'is-past');
      if (lane === stage.from || lane === stage.to) box.classList.add('is-active');
      else if (visited.has(lane)) box.classList.add('is-past');
    });

    const log = document.getElementById('pipe-log');
    if (log) {
      const have = new Map();
      log.querySelectorAll('.pipe-log-row').forEach(r => {
        have.set(parseInt(r.dataset.step, 10), r);
      });
      have.forEach((row, idx) => { if (idx > i) row.remove(); });
      for (let k = 0; k <= i; k++) {
        if (!have.has(k)) log.appendChild(buildLogRow(k, stages[k]));
      }
      log.querySelectorAll('.pipe-log-row').forEach(r => {
        r.classList.toggle('is-current', parseInt(r.dataset.step, 10) === i);
      });
      // Pin newest line into view.
      const last = log.querySelector(`.pipe-log-row[data-step="${i}"]`);
      if (last) log.scrollTop = last.offsetTop - 24;
    }

    movePipelineDot(stage.to, animate);
    if (window.lucide) lucide.createIcons();
  }

  function buildLogRow(i, stage) {
    const row = document.createElement('div');
    row.className = 'pipe-log-row';
    row.dataset.step = String(i);
    const color = stage.kind === 'net' ? '#94a3b8' :
                  stage.kind === 'tls' ? '#fbbf24' :
                  stage.kind === 'data' ? '#22d3ee' : '#a78bfa';
    // Cosmetic monotonic timestamp (not real time).
    const totalMs = i * 23 + 12;
    const sec = Math.floor(totalMs / 1000) % 60;
    const ms  = totalMs % 1000;
    const ts  = `18:42:${String(sec).padStart(2,'0')}.${String(ms).padStart(3,'0')}`;
    row.appendChild(buildLogCell('col-num', String(i + 1).padStart(2, '0')));
    row.appendChild(buildLogCell('col-time', ts));
    const tag = buildLogCell('col-tag', '[' + stage.from + ' → ' + stage.to + ']');
    tag.style.color = color;
    row.appendChild(tag);
    const msg = buildLogCell('col-msg', stage.label);
    const hop = stage.hop;
    if (hop && hop.qualname) {
      msg.dataset.hopQn = hop.qualname;
      if (hop.file) msg.dataset.hopFile = hop.file;
      if (hop.line) msg.dataset.hopLine = String(hop.line);
      msg.style.cursor = 'pointer';
      msg.title = (hop.file || hop.qualname) + (hop.line ? ':' + hop.line : '');
      msg.addEventListener('click', () => {
        if (typeof window !== 'undefined' && typeof window.jumpToQualname === 'function') {
          window.jumpToQualname(hop.qualname);
        }
      });
    }
    row.appendChild(msg);
    return row;
  }

  function buildLogCell(cls, text) {
    const span = document.createElement('span');
    span.className = cls;
    span.textContent = String(text);
    return span;
  }

  function movePipelineDot(laneId, animate) {
    const strip = document.getElementById('pipe-strip');
    const dot   = document.getElementById('pipe-dot');
    if (!strip || !dot) return;
    const target = strip.querySelector(`.pipe-box[data-lane="${laneId}"]`);
    if (!target) return;
    const stripRect = strip.getBoundingClientRect();
    const tRect     = target.getBoundingClientRect();
    const left = tRect.left - stripRect.left + tRect.width / 2 - 5.5;
    const top  = tRect.top  - stripRect.top  - 14;
    if (!animate) {
      const prev = dot.style.transition;
      dot.style.transition = 'none';
      dot.style.left = `${left}px`;
      dot.style.top  = `${top}px`;
      dot.classList.add('is-on');
      // restore transition next frame
      requestAnimationFrame(() => { dot.style.transition = prev || ''; });
    } else {
      dot.classList.add('is-on');
      dot.style.left = `${left}px`;
      dot.style.top  = `${top}px`;
    }
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

      // Faint baseline arrow (dimmed when inactive). For dataflow hops we
      // attach data-hop-qn so the click handler can jumpToQualname().
      const hop = s.hop;
      const hopAttrs = hop && hop.qualname
        ? ` data-hop-qn="${escapeHtml(hop.qualname)}"`
          + ` data-hop-file="${escapeHtml(hop.file || '')}"`
          + ` data-hop-line="${escapeHtml(String(hop.line || ''))}"`
          + ` style="cursor:pointer"`
        : '';
      svg += `<g class="learn-arrow" id="learn-arrow-${i}" data-color="${color}" opacity="0.25"${hopAttrs}>
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

    // Wire hop click → jumpToQualname for swimlane arrows.
    host.querySelectorAll('.learn-arrow[data-hop-qn]').forEach(g => {
      g.addEventListener('click', () => {
        const qn = g.getAttribute('data-hop-qn');
        if (qn && typeof window !== 'undefined' && typeof window.jumpToQualname === 'function') {
          window.jumpToQualname(qn);
        }
      });
    });
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

  // ---------- Diagram mode (ByteMonk-style system map + traveling packet) ----------

  const DIAG_ROW = {
    client: 0, net: 0, tls: 0,
    server: 1, mw: 1, handler: 1,
    cache: 2, db: 2, queue: 2, ext: 2,
  };

  function ensureDiagramStyles() {
    if (document.getElementById('arch-diagram-styles')) return;
    const style = document.createElement('style');
    style.id = 'arch-diagram-styles';
    style.textContent = `
      #diagram-host {
        position: relative;
        background:
          radial-gradient(ellipse at top, rgba(99,102,241,0.07), transparent 60%),
          rgba(2,6,23,0.55);
        border: 1px solid rgba(91,107,140,0.35);
        border-radius: 14px;
        overflow: hidden;
      }
      #diagram-svg { display: block; }
      .diag-card {
        --lane-color: #94a3b8;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 4px;
        background: rgba(15,23,42,0.85);
        border: 1.5px solid rgba(148,163,184,0.32);
        border-radius: 14px;
        padding: 10px 8px;
        color: #e6ecf5;
        font-size: 12px; font-weight: 500;
        text-align: center;
        transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease, opacity 0.22s ease;
        opacity: 0.65;
        box-sizing: border-box;
        z-index: 2;
      }
      .diag-card .diag-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 36px; height: 36px;
        border-radius: 50%;
        background: color-mix(in srgb, var(--lane-color) 18%, rgba(15,23,42,0.6));
        margin-bottom: 2px;
      }
      .diag-card .diag-label { line-height: 1.2; padding: 0 2px; }
      .diag-card.is-visited {
        opacity: 0.92;
        border-color: var(--lane-color);
      }
      .diag-card.is-active {
        opacity: 1;
        border-color: var(--lane-color);
        box-shadow:
          0 0 0 3px rgba(34,211,238,0.22),
          0 0 26px rgba(34,211,238,0.45);
      }
      .diag-card.is-pulse { animation: diagPulse 0.6s ease both; }
      @keyframes diagPulse {
        0%   { transform: scale(1); }
        45%  { transform: scale(1.07); }
        100% { transform: scale(1); }
      }
      .diag-badge {
        position: absolute;
        top: -8px; right: -8px;
        min-width: 20px; height: 20px;
        padding: 0 6px;
        border-radius: 999px;
        background: linear-gradient(135deg, #6366f1, #06b6d4);
        color: #0b1020;
        font-size: 11px; font-weight: 700;
        display: flex; align-items: center; justify-content: center;
        border: 2px solid #0b1020;
        z-index: 3;
      }
      #diag-active-label {
        position: absolute;
        padding: 6px 10px;
        background: rgba(2,6,23,0.92);
        border: 1px solid rgba(34,211,238,0.6);
        border-radius: 999px;
        font-size: 11px; font-weight: 500;
        color: #e6ecf5;
        white-space: nowrap;
        pointer-events: none;
        transform: translate(-50%, -50%);
        opacity: 0;
        transition: opacity 0.2s ease, left 0.6s cubic-bezier(0.4,0,0.2,1), top 0.6s cubic-bezier(0.4,0,0.2,1);
        z-index: 4;
      }
      #diag-active-label.is-on { opacity: 1; }
    `;
    document.head.appendChild(style);
  }

  function diagBezierPath(x1, y1, x2, y2) {
    if (Math.abs(y1 - y2) < 30) {
      // same row → arc upward to avoid overlapping cards
      const mx = (x1 + x2) / 2;
      const cy = y1 - 50;
      return `M ${x1} ${y1} Q ${mx} ${cy} ${x2} ${y2}`;
    }
    const my = (y1 + y2) / 2;
    return `M ${x1} ${y1} C ${x1} ${my} ${x2} ${my} ${x2} ${y2}`;
  }

  function drawDiagram(lanes, stages) {
    const host = document.getElementById('learn-svg-host');
    if (!host) return;
    const W = Math.max(640, host.clientWidth || 920);
    const cardW = 132, cardH = 84;
    const ROW_Y = [80, 240, 400];
    const H = ROW_Y[2] + cardH / 2 + 40;

    const rows = [[], [], []];
    lanes.forEach(L => {
      const r = DIAG_ROW[L.id] != null ? DIAG_ROW[L.id] : 1;
      rows[r].push(L);
    });

    const pos = new Map();
    rows.forEach((rowLanes, r) => {
      const n = rowLanes.length;
      rowLanes.forEach((L, i) => {
        const x = ((i + 1) / (n + 1)) * W;
        pos.set(L.id, { x, y: ROW_Y[r] });
      });
    });

    // Unique edges from real stage transitions.
    const seen = new Set();
    const edges = [];
    stages.forEach(s => {
      const k = s.from + '|' + s.to;
      if (seen.has(k) || !pos.has(s.from) || !pos.has(s.to)) return;
      seen.add(k);
      edges.push({ from: s.from, to: s.to });
    });

    let html = `<div id="diagram-host" style="width:${W}px;height:${H}px;">`;
    html += `<svg id="diagram-svg" width="${W}" height="${H}" xmlns="http://www.w3.org/2000/svg" style="position:absolute;inset:0;pointer-events:none;">`;
    html += `<defs>
      <filter id="diag-glow" x="-100%" y="-100%" width="300%" height="300%">
        <feGaussianBlur stdDeviation="5"/>
      </filter>
    </defs>`;
    html += '<g id="diagram-edges">';
    edges.forEach(e => {
      const a = pos.get(e.from), b = pos.get(e.to);
      const d = diagBezierPath(a.x, a.y, b.x, b.y);
      const id = `dge-${escapeHtml(e.from)}-${escapeHtml(e.to)}`;
      html += `<path id="${id}" d="${d}" stroke="rgba(148,163,184,0.22)" stroke-width="1.5" fill="none"/>`;
    });
    html += '</g>';
    html += '<circle id="diag-packet-glow" r="14" fill="#22d3ee" opacity="0" filter="url(#diag-glow)"/>';
    html += '<circle id="diag-packet" r="6" fill="#22d3ee" stroke="#fff" stroke-width="1.5" opacity="0"/>';
    html += '</svg>';

    lanes.forEach(L => {
      const p = pos.get(L.id);
      if (!p) return;
      const left = p.x - cardW / 2;
      const top  = p.y - cardH / 2;
      html += `
        <div class="diag-card" data-lane="${escapeHtml(L.id)}"
             style="position:absolute;left:${left}px;top:${top}px;width:${cardW}px;height:${cardH}px;--lane-color:${L.color};">
          <span class="diag-badge" style="display:none">1</span>
          <div class="diag-icon"><i data-lucide="${escapeHtml(L.icon)}" style="width:20px;height:20px;color:${L.color};"></i></div>
          <div class="diag-label">${escapeHtml(L.label)}</div>
        </div>`;
    });
    html += '<div id="diag-active-label"></div>';
    html += '</div>';
    host.innerHTML = html;
    if (window.lucide) lucide.createIcons();
  }

  function diagramSetStep(i, animate, lanes, stages) {
    const stage = stages[i];
    if (!stage) return;
    const cards = document.querySelectorAll('#diagram-host .diag-card');
    if (!cards.length) return;

    // First step number per lane (so we keep the entry order on the badge).
    const visitNum = new Map();
    for (let k = 0; k <= i; k++) {
      const s = stages[k];
      if (!visitNum.has(s.from)) visitNum.set(s.from, k + 1);
      if (!visitNum.has(s.to))   visitNum.set(s.to,   k + 1);
    }

    cards.forEach(card => {
      const lane = card.dataset.lane;
      const isActive = (lane === stage.from || lane === stage.to);
      const visited = visitNum.has(lane);
      card.classList.remove('is-active', 'is-visited', 'is-pulse');
      if (isActive) card.classList.add('is-active');
      else if (visited) card.classList.add('is-visited');
      const badge = card.querySelector('.diag-badge');
      if (badge) {
        if (visited) {
          badge.style.display = '';
          badge.textContent = String(visitNum.get(lane));
        } else {
          badge.style.display = 'none';
        }
      }
    });

    // Edge highlighting.
    document.querySelectorAll('#diagram-edges path').forEach(p => {
      p.setAttribute('stroke', 'rgba(148,163,184,0.18)');
      p.setAttribute('stroke-width', '1.5');
    });
    const edgeId = `dge-${stage.from}-${stage.to}`;
    const activeEdge = document.getElementById(edgeId);
    const kindColor = stage.kind === 'net' ? '#94a3b8' :
                      stage.kind === 'tls' ? '#fbbf24' :
                      stage.kind === 'data' ? '#22d3ee' : '#a78bfa';
    if (activeEdge) {
      activeEdge.setAttribute('stroke', kindColor);
      activeEdge.setAttribute('stroke-width', '2.5');
    }

    animateDiagPacket(activeEdge, stage, animate, kindColor);
  }

  function animateDiagPacket(pathEl, stage, animate, color) {
    const dot  = document.getElementById('diag-packet');
    const glow = document.getElementById('diag-packet-glow');
    const lab  = document.getElementById('diag-active-label');
    if (!dot || !glow) return;

    if (!pathEl) {
      dot.setAttribute('opacity', '0');
      glow.setAttribute('opacity', '0');
      if (lab) lab.classList.remove('is-on');
      return;
    }
    dot.setAttribute('fill', color);
    glow.setAttribute('fill', color);

    const len = pathEl.getTotalLength();
    const dur = 700;

    const setAt = (t) => {
      const p = pathEl.getPointAtLength(len * t);
      dot.setAttribute('cx', p.x); dot.setAttribute('cy', p.y);
      glow.setAttribute('cx', p.x); glow.setAttribute('cy', p.y);
      if (lab && t > 0.45 && t < 0.6) {
        lab.style.left = p.x + 'px';
        lab.style.top  = (p.y - 22) + 'px';
      }
    };

    dot.setAttribute('opacity', '1');
    glow.setAttribute('opacity', '0.55');
    if (lab) {
      lab.textContent = stage.label;
      lab.classList.add('is-on');
      const mid = pathEl.getPointAtLength(len * 0.5);
      lab.style.left = mid.x + 'px';
      lab.style.top  = (mid.y - 22) + 'px';
    }

    if (!animate) { setAt(1); return; }

    const start = performance.now();
    function step(now) {
      const t = Math.min(1, (now - start) / dur);
      const eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      setAt(eased);
      if (t < 1) {
        requestAnimationFrame(step);
      } else {
        const target = document.querySelector(`.diag-card[data-lane="${stage.to}"]`);
        if (target) {
          target.classList.remove('is-pulse');
          // restart the animation
          void target.offsetWidth;
          target.classList.add('is-pulse');
        }
      }
    }
    requestAnimationFrame(step);
  }


  // Expose entry point so app.js can dispatch into us.
  if (typeof window !== 'undefined') {
    window.renderArchitectureView = renderArchitecture;
  }

  // CommonJS export for Node `--test` unit tests. Exposes only the pure
  // helpers (no DOM dependency).
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      buildDataflowSegment,
      hopLaneId,
      hopLabel,
      formatHopArgs,
      DF_ROLE_LANES,
      renderDataflowChip,
    };
  }
})();
