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
