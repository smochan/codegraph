/* Tests for Phase 4 dataflow rendering in the Architecture view's Learn Mode
 * modal. Covers buildDataflowSegment + the small DOM-free helpers exported
 * from architecture.js.
 *
 * Run with:  node --test tests/test_architecture_phase4.js
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const A = require(
  path.join(__dirname, '..', 'codegraph', 'web', 'static', 'views', 'architecture.js')
);
const {
  buildDataflowSegment,
  hopLaneId,
  hopLabel,
  formatHopArgs,
  renderDataflowChip,
  DF_ROLE_LANES,
  ARG_PALETTE,
  argColor,
  getArgFlowKeys,
  hopArgLocalName,
  renderArgPicker,
  argHighlightForStage,
  highlightLabelHtml,
} = A;

// ---- Fixture: a 5-hop dataflow payload matching the v0.3 contract --------

function fiveHopHandler() {
  return {
    qualname: 'app.api.users.get_user',
    method: 'GET',
    path: '/api/users/{id}',
    framework: 'fastapi',
    role: 'HANDLER',
    dataflow: {
      hops: [
        { kind: 'FETCH_CALL',
          qualname: 'src/UserCard.tsx::fetchUser',
          file: 'src/UserCard.tsx', line: 42,
          args: ['userId'], body_keys: [], role: 'COMPONENT' },
        { kind: 'ROUTE',
          qualname: 'app.api.users.get_user',
          file: 'app/api/users.py', line: 11,
          args: ['id'], role: 'HANDLER' },
        { kind: 'CALL',
          qualname: 'app.services.user.UserService.get',
          file: 'app/services/user.py', line: 7,
          args: ['user_id'], role: 'SERVICE' },
        { kind: 'CALL',
          qualname: 'app.repos.user.UserRepo.find_by_id',
          file: 'app/repos/user.py', line: 11,
          args: ['user_id'], role: 'REPO' },
        { kind: 'READS_FROM',
          qualname: 'app.models.User',
          file: 'app/models.py', line: 8,
          args: ['user_id'], role: null },
      ],
      confidence: 0.92,
    },
  };
}

// ---- Tests ---------------------------------------------------------------

test('5-hop fixture renders 5 stages with one swimlane per role', () => {
  const seg = buildDataflowSegment(fiveHopHandler());
  assert.equal(seg.stages.length, 5);
  // Lanes should include component, handler, service, repo, db (5 roles).
  const laneIds = seg.lanes.map(L => L.id).sort();
  assert.deepEqual(laneIds,
    ['df-component', 'df-db', 'df-handler', 'df-repo', 'df-service']);
  // First stage starts from the upstream 'handler' lane Phase 3 established.
  assert.equal(seg.stages[0].from, 'handler');
  // Stages chain: each stage's `from` matches the previous stage's `to`.
  for (let i = 1; i < seg.stages.length; i++) {
    assert.equal(seg.stages[i].from, seg.stages[i - 1].to,
      `stage ${i} should chain off stage ${i - 1}`);
  }
});

test('hop labels embed args from the fixture (DF0 args)', () => {
  const seg = buildDataflowSegment(fiveHopHandler());
  // First hop: fetchUser(userId)
  assert.match(seg.stages[0].label, /\(userId\)/);
  // Second hop: dispatch → get_user(id)
  assert.match(seg.stages[1].label, /\(id\)/);
  // Service + Repo: each carries (user_id)
  assert.match(seg.stages[2].label, /\(user_id\)/);
  assert.match(seg.stages[3].label, /\(user_id\)/);
});

test('hop stages carry the original hop payload for click-through', () => {
  const seg = buildDataflowSegment(fiveHopHandler());
  // Each stage should embed the full hop so the click handler can call
  // jumpToQualname(hop.qualname).
  seg.stages.forEach(s => {
    assert.ok(s.hop, 'stage should carry hop payload');
    assert.equal(typeof s.hop.qualname, 'string');
    assert.equal(s.kind, 'data');
  });
  assert.equal(seg.stages[2].hop.qualname,
    'app.services.user.UserService.get');
  assert.equal(seg.stages[2].hop.file, 'app/services/user.py');
  assert.equal(seg.stages[2].hop.line, 7);
});

test('empty hops payload returns empty stages and an empty meta flag', () => {
  const handler = {
    qualname: 'x.y.z',
    method: 'GET', path: '/x',
    dataflow: { hops: [], confidence: 0.0 },
  };
  const seg = buildDataflowSegment(handler);
  assert.deepEqual(seg.stages, []);
  assert.deepEqual(seg.lanes, []);
  assert.equal(seg.meta.available, true);
  assert.equal(seg.meta.empty, true);
  assert.equal(seg.meta.hopCount, 0);
});

test('handler without dataflow field returns available:false meta', () => {
  const seg = buildDataflowSegment({ qualname: 'h' });
  assert.equal(seg.meta.available, false);
  assert.equal(seg.stages.length, 0);
});

test('low-confidence trace (<0.5) flags meta.lowConfidence', () => {
  const handler = fiveHopHandler();
  handler.dataflow.confidence = 0.3;
  const seg = buildDataflowSegment(handler);
  assert.equal(seg.meta.lowConfidence, true);
  assert.equal(seg.meta.confidence, 0.3);
});

test('confidence >= 0.5 is not flagged as low-confidence', () => {
  const seg = buildDataflowSegment(fiveHopHandler());
  assert.equal(seg.meta.lowConfidence, false);
});

test('hopLaneId routes FETCH_CALL → component, READS_FROM → db', () => {
  assert.equal(hopLaneId({ kind: 'FETCH_CALL' }), 'df-component');
  assert.equal(hopLaneId({ kind: 'READS_FROM' }), 'df-db');
  assert.equal(hopLaneId({ kind: 'WRITES_TO' }), 'df-db');
  assert.equal(hopLaneId({ kind: 'ROUTE',  role: 'HANDLER' }), 'df-handler');
  assert.equal(hopLaneId({ kind: 'CALL',   role: 'SERVICE' }), 'df-service');
  assert.equal(hopLaneId({ kind: 'CALL',   role: 'REPO' }),    'df-repo');
});

test('formatHopArgs renders comma-joined args in parens', () => {
  assert.equal(formatHopArgs({ args: ['a', 'b', 'c'] }), '(a, b, c)');
  assert.equal(formatHopArgs({ args: [] }), '');
  assert.equal(formatHopArgs({}), '');
});

test('hopLabel uses verb prefixes per kind', () => {
  assert.match(
    hopLabel({ kind: 'FETCH_CALL', qualname: 'src/X.tsx::fetchUser', args: ['id'] }),
    /^fetch fetchUser\(id\)/);
  assert.match(
    hopLabel({ kind: 'ROUTE', qualname: 'a.b.c', args: ['id'] }),
    /^dispatch → c\(id\)/);
  assert.match(
    hopLabel({ kind: 'READS_FROM', qualname: 'a.b.User' }),
    /^read User/);
});

test('renderDataflowChip(empty) emits the fallback message', () => {
  const html = renderDataflowChip({ available: true, empty: true,
    hopCount: 0, confidence: 0 });
  assert.match(html, /no trace data/);
  assert.match(html, /codegraph build/);
  assert.match(html, /data-df-chip="empty"/);
});

test('renderDataflowChip(low-confidence) shows the warning chip', () => {
  const html = renderDataflowChip({
    available: true, empty: false, lowConfidence: true,
    hopCount: 5, confidence: 0.3,
  });
  assert.match(html, /low-confidence/);
  assert.match(html, /30%/);
  assert.match(html, /data-df-chip="low-confidence"/);
});

test('renderDataflowChip(ok) shows hop count + confidence percent', () => {
  const html = renderDataflowChip({
    available: true, empty: false, lowConfidence: false,
    hopCount: 5, confidence: 0.92,
  });
  assert.match(html, /5 hops/);
  assert.match(html, /92%/);
  assert.match(html, /data-df-chip="ok"/);
});

test('renderDataflowChip(unavailable) returns empty string', () => {
  assert.equal(renderDataflowChip({ available: false }), '');
  assert.equal(renderDataflowChip(null), '');
});

test('DF_ROLE_LANES match the role palette (HANDLER amber, SERVICE blue, COMPONENT green, REPO purple)', () => {
  assert.equal(DF_ROLE_LANES.HANDLER.color,   '#fbbf24');  // amber
  assert.equal(DF_ROLE_LANES.SERVICE.color,   '#60a5fa');  // blue
  assert.equal(DF_ROLE_LANES.COMPONENT.color, '#22c55e');  // green
  assert.equal(DF_ROLE_LANES.REPO.color,      '#a78bfa');  // purple
});

test('sequence + pipeline modes render the same hop count', () => {
  // Both modes consume the same `stages` array; the segment's stage count is
  // what they render. This guards against future drift.
  const seg = buildDataflowSegment(fiveHopHandler());
  // Pipeline mode renders one log row per stage.
  // Sequence mode renders one arrow per stage.
  // Both count against seg.stages.length — this is the invariant.
  assert.equal(seg.stages.length, 5);
  assert.equal(seg.meta.hopCount, 5);
});

test('click-target metadata: each stage carries qualname for jumpToQualname', () => {
  const seg = buildDataflowSegment(fiveHopHandler());
  const expected = [
    'src/UserCard.tsx::fetchUser',
    'app.api.users.get_user',
    'app.services.user.UserService.get',
    'app.repos.user.UserRepo.find_by_id',
    'app.models.User',
  ];
  assert.deepEqual(seg.stages.map(s => s.hop.qualname), expected);
});

// ---- DF5 / arg-flow stretch fixtures + tests --------------------------------

// Mirrors the v0.3 stretch contract: per-hop arg_flow maps the starting
// param key to the local name at that hop (or null when dropped).
function argFlowHandler() {
  return {
    qualname: 'app.api.users.get_user',
    method: 'GET',
    path: '/api/users/{id}',
    dataflow: {
      confidence: 0.9,
      hops: [
        { kind: 'FETCH_CALL', qualname: 'src/UserCard.tsx::fetchUser',
          file: 'src/UserCard.tsx', line: 42, args: ['userId', 'email'],
          role: 'COMPONENT',
          arg_flow: { userId: 'userId', email: 'email' } },
        { kind: 'ROUTE', qualname: 'app.api.users.get_user',
          file: 'app/api/users.py', line: 11, args: ['id'], role: 'HANDLER',
          arg_flow: { userId: 'id', email: null } },
        { kind: 'CALL', qualname: 'app.services.user.UserService.get',
          file: 'app/services/user.py', line: 7, args: ['user_id'],
          role: 'SERVICE',
          arg_flow: { userId: 'user_id', email: null } },
        { kind: 'READS_FROM', qualname: 'app.models.User',
          file: 'app/models.py', line: 8, args: ['user_id'], role: null,
          arg_flow: { userId: 'user_id', email: null } },
      ],
    },
  };
}

function singleArgHandler() {
  return {
    qualname: 'h.x',
    method: 'GET', path: '/x',
    dataflow: {
      confidence: 0.8,
      hops: [
        { kind: 'ROUTE', qualname: 'h.x', file: 'a.py', line: 1,
          args: ['id'], role: 'HANDLER',
          arg_flow: { id: 'id' } },
        { kind: 'CALL', qualname: 'h.svc', file: 'a.py', line: 2,
          args: ['pk'], role: 'SERVICE',
          arg_flow: { id: 'pk' } },
      ],
    },
  };
}

test('arg_flow with one key → picker has 1 chip, default-selected', () => {
  const keys = getArgFlowKeys(singleArgHandler());
  assert.deepEqual(keys, ['id']);
  const html = renderArgPicker(keys, keys[0]);
  const chipMatches = html.match(/data-arg-key=/g) || [];
  assert.equal(chipMatches.length, 1);
  assert.match(html, /data-arg-key="id"/);
  assert.match(html, /aria-pressed="true"/);
  assert.match(html, /class="cg-arg-chip is-active"/);
});

test('arg_flow with multiple keys → picker has all of them, first selected', () => {
  const keys = getArgFlowKeys(argFlowHandler());
  assert.deepEqual(keys, ['userId', 'email']);
  const html = renderArgPicker(keys, keys[0]);
  const chipMatches = html.match(/data-arg-key=/g) || [];
  assert.equal(chipMatches.length, 2);
  assert.match(html, /data-arg-key="userId"[\s\S]*aria-pressed="true"/);
  assert.match(html, /data-arg-key="email"[\s\S]*aria-pressed="false"/);
});

test('empty arg_flow → no picker rendered', () => {
  const handler = {
    dataflow: { confidence: 0.9, hops: [
      { kind: 'ROUTE', qualname: 'h', file: 'a', line: 1, role: 'HANDLER',
        args: [], arg_flow: {} },
    ] },
  };
  assert.deepEqual(getArgFlowKeys(handler), []);
  assert.equal(renderArgPicker([], null), '');
  // Handler with arg_flow missing entirely also yields no picker.
  const noField = { dataflow: { confidence: 0.5, hops: [
    { kind: 'ROUTE', qualname: 'h', file: 'a', line: 1, args: [] },
  ] } };
  assert.deepEqual(getArgFlowKeys(noField), []);
});

test('selected param highlights at hops where arg_flow[selected] is non-null', () => {
  const handler = argFlowHandler();
  const seg = buildDataflowSegment(handler);
  const color = argColor(0);
  // userId is present at every hop in this fixture.
  const stages = seg.stages;
  const hits = stages
    .map(s => argHighlightForStage(s, 'userId', color))
    .filter(Boolean);
  assert.equal(hits.length, 4);
  // Every hit advertises the colour we passed in.
  hits.forEach(h => assert.equal(h.color, color));
});

test('selected param hop with rename → rename annotation present', () => {
  const handler = argFlowHandler();
  const seg = buildDataflowSegment(handler);
  // Hop 1 (ROUTE) renames userId → id.
  const stage = seg.stages[1];
  const hl = argHighlightForStage(stage, 'userId', '#fbbf24');
  assert.ok(hl, 'highlight should fire at the renamed hop');
  assert.equal(hl.local, 'id');
  assert.equal(hl.isRename, true);
  // Pipeline / sequence wrapping must surface the (was userId) annotation.
  const html = highlightLabelHtml(stage.label, hl);
  assert.match(html, /class="cg-arg-rename"/);
  assert.match(html, /\(was userId\)/);
  assert.match(html, /class="cg-arg-active"/);
});

test('arg_flow[selected]=null at a hop → no highlight, but hop still in stages', () => {
  const handler = argFlowHandler();
  const seg = buildDataflowSegment(handler);
  // email is dropped at hops 1, 2, 3 (only present at hop 0).
  const dropped = seg.stages.slice(1)
    .map(s => argHighlightForStage(s, 'email', '#fb7185'));
  dropped.forEach(h => assert.equal(h, null));
  // Stage list itself is unchanged.
  assert.equal(seg.stages.length, 4);
});

test('switching selection re-renders highlights with the new colour', () => {
  const handler = argFlowHandler();
  const seg = buildDataflowSegment(handler);
  const stage = seg.stages[2]; // SERVICE hop, both keys live here? no - email dropped
  // userId is live, email is dropped at this hop.
  const c0 = argColor(0);
  const c1 = argColor(1);
  const hUser = argHighlightForStage(stage, 'userId', c0);
  const hEmail = argHighlightForStage(stage, 'email', c1);
  assert.ok(hUser);
  assert.equal(hUser.color, c0);
  assert.equal(hEmail, null);
  // Pick a hop where both parameters exist (hop 0) to verify colour swap.
  const stage0 = seg.stages[0];
  const hUser0 = argHighlightForStage(stage0, 'userId', c0);
  const hEmail0 = argHighlightForStage(stage0, 'email', c1);
  assert.equal(hUser0.color, c0);
  assert.equal(hEmail0.color, c1);
  assert.notEqual(c0, c1);
});

test('colour assignment is stable: same param key gets the same colour across renders', () => {
  const handler = argFlowHandler();
  // Render 1
  const keys1 = getArgFlowKeys(handler);
  const colorMap1 = new Map(keys1.map((k, i) => [k, argColor(i)]));
  // Render 2 (e.g. after switching modes / re-opening the modal)
  const keys2 = getArgFlowKeys(handler);
  const colorMap2 = new Map(keys2.map((k, i) => [k, argColor(i)]));
  assert.deepEqual(keys1, keys2);
  for (const k of keys1) {
    assert.equal(colorMap1.get(k), colorMap2.get(k),
      `param ${k} should keep the same colour across renders`);
  }
  // Palette is the documented 5-colour set.
  assert.equal(ARG_PALETTE.length, 5);
});

test('hopArgLocalName distinguishes missing key, dropped param, and present', () => {
  const hop = { arg_flow: { userId: 'user_id', email: null } };
  assert.deepEqual(hopArgLocalName(hop, 'userId'), { local: 'user_id' });
  assert.deepEqual(hopArgLocalName(hop, 'email'),  { local: null });
  // Missing key is treated as "no info" → null lookup.
  assert.equal(hopArgLocalName(hop, 'other'), null);
  // Hop with no arg_flow at all also returns null.
  assert.equal(hopArgLocalName({}, 'userId'), null);
});

test('highlightLabelHtml wraps the matched local name with cg-arg-active span', () => {
  const hl = { local: 'user_id', color: '#fbbf24', isRename: true, selected: 'userId' };
  const html = highlightLabelHtml('UserService.get(user_id)', hl);
  assert.match(html, /<span class="cg-arg-active" style="color:#fbbf24">user_id<\/span>/);
  assert.match(html, /\(was userId\)/);
  // No-rename case omits the annotation.
  const hl2 = { local: 'userId', color: '#38bdf8', isRename: false, selected: 'userId' };
  const html2 = highlightLabelHtml('fetch fetchUser(userId)', hl2);
  assert.doesNotMatch(html2, /\(was/);
  assert.match(html2, /<span class="cg-arg-active"/);
});
