function createFavoriteModel(api, productId) {
  let favorite = false

  return {
    async load() {
      const result = await api.status(productId)
      favorite = Boolean(result.favorite)
      return favorite
    },
    async toggle() {
      if (favorite) {
        await api.remove(productId)
        favorite = false
      } else {
        await api.add(productId)
        favorite = true
      }
      return favorite
    },
    value() {
      return favorite
    }
  }
}

module.exports = { createFavoriteModel }
