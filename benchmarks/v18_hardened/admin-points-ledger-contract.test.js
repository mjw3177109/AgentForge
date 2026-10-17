import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

test('admin view reads authoritative balance and ledger endpoints', () => {
  const text = fs.readFileSync('admin-web/src/PointsLedgerView.vue', 'utf8');
  assert.match(text, /\/api\/points\/balance/);
  assert.match(text, /\/api\/points\/ledger/);
  assert.doesNotMatch(text, /X-User-Id/i);
});
