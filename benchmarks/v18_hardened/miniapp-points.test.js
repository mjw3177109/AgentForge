const test = require('node:test');
const assert = require('node:assert/strict');
const { getMyPoints, previewRedeem } = require('../src/api/points');

test('queries verified current-user balance endpoint without identity headers', async () => {
  let captured;
  await getMyPoints(async (options) => {
    captured = options;
    return { data: { balancePoints: 123 } };
  });
  assert.equal(captured.url, '/api/points/balance');
  assert.equal(captured.method, 'GET');
  assert.equal(captured.header, undefined);
  assert.equal(captured.headers, undefined);
});

test('redeem preview uses verified POST JSON contract', async () => {
  let captured;
  await previewRedeem(async (options) => {
    captured = options;
    return { data: { discountAmountYuan: 20 } };
  }, 100);
  assert.equal(captured.method, 'POST');
  assert.equal(captured.url, '/api/points/redeem-preview');
  assert.deepEqual(captured.data, { orderPaidAmountYuan: 100 });
  assert.equal(captured.header, undefined);
  assert.equal(captured.headers, undefined);
});
