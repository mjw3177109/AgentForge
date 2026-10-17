Page({
  data: { productId: null, favorite: false },
  onLoad(options) {
    const productId = Number(options.id)
    this.setData({ productId })
    this.loadFavoriteStatus()
  },
  loadFavoriteStatus() {
    wx.request({
      url: `${getApp().globalData.apiBase}/api/products/${this.data.productId}/favorite-status`,
      success: (r) => this.setData({ favorite: !!(r.data.data && r.data.data.favorite) })
    })
  },
  toggleFavorite() {
    const method = this.data.favorite ? 'DELETE' : 'POST'
    wx.request({
      url: `${getApp().globalData.apiBase}/api/favorites/${this.data.productId}`,
      method,
      success: (r) => this.setData({ favorite: !!(r.data.data && r.data.data.favorite) })
    })
  }
})
