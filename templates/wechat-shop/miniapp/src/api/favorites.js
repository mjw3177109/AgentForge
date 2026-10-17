function createFavoriteApi(request) {
  return {
    status(productId) {
      return request({ url: `/api/favorites/${productId}/status`, method: 'GET' })
    },
    add(productId) {
      return request({ url: `/api/favorites/${productId}`, method: 'POST' })
    },
    remove(productId) {
      return request({ url: `/api/favorites/${productId}`, method: 'DELETE' })
    },
    list() {
      return request({ url: '/api/favorites', method: 'GET' })
    }
  }
}

module.exports = { createFavoriteApi }
