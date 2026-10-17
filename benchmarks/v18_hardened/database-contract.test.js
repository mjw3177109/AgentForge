const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const sql = () => fs.readFileSync('database/migrations/V980100__points.sql', 'utf8');

test('migration uses verified authoritative table names', () => {
  const text = sql();
  assert.match(text, /CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?`?points_account`?/i);
  assert.match(text, /CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?`?points_ledger`?/i);
  assert.doesNotMatch(text, /user_points_(account|ledger)/i);
});

test('ledger enforces business_no uniqueness', () => {
  const text = sql();
  assert.match(text, /business_no/i);
  assert.match(text, /(UNIQUE[^;]*business_no|business_no[^,;]*UNIQUE)/is);
});
