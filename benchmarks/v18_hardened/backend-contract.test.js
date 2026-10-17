const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

function javaText() {
  const root = 'server/src/main/java/com/agentforge/shop/points';
  assert.ok(fs.existsSync(root), 'points source directory must exist');
  return fs.readdirSync(root)
    .filter((name) => name.endsWith('.java'))
    .map((name) => fs.readFileSync(path.join(root, name), 'utf8'))
    .join('\n');
}

test('backend follows verified database names', () => {
  const text = javaText();
  assert.match(text, /points_account/);
  assert.match(text, /points_ledger/);
  assert.doesNotMatch(text, /user_points_(account|ledger)/);
});

test('backend exposes only the verified public user API', () => {
  const text = javaText();
  assert.match(text, /CurrentUserProvider/);
  assert.match(text, /\/api\/points/);
  assert.match(text, /\/balance/);
  assert.match(text, /redeem-preview/);
  assert.match(text, /\/ledger/);
  assert.match(text, /orderPaidAmountYuan/);
  assert.doesNotMatch(text, /X-User-Id/i);
  assert.doesNotMatch(text, /@PostMapping\s*\(\s*["']\/?earn["']/);
});
