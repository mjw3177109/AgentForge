const test = require('node:test')
const assert = require('node:assert/strict')
const { createFavoriteApi } = require('../src/api/favorites')
const { createFavoriteModel } = require('../src/pages/product-detail/favorite-model')

test('favorite API uses ADR paths', async () => {
  const calls = []
  const api = createFavoriteApi(async (options) => {
    calls.push(options)
    return { favorite: false }
  })
  await api.status(99)
  await api.add(99)
  await api.remove(99)
  assert.deepEqual(calls, [
    { url: '/api/favorites/99/status', method: 'GET' },
    { url: '/api/favorites/99', method: 'POST' },
    { url: '/api/favorites/99', method: 'DELETE' }
  ])
})

test('favorite model loads and toggles state', async () => {
  const events = []
  const api = {
    async status() { return { favorite: false } },
    async add(id) { events.push(['add', id]) },
    async remove(id) { events.push(['remove', id]) }
  }
  const model = createFavoriteModel(api, 42)
  assert.equal(await model.load(), false)
  assert.equal(await model.toggle(), true)
  assert.equal(await model.toggle(), false)
  assert.deepEqual(events, [['add', 42], ['remove', 42]])
})
