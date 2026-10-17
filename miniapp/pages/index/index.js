Page({
  data: { products: [] },
  onLoad() {
    wx.request({
      url: getApp().globalData.apiBase + '/api/products',
      success: (r) => this.setData({ products: r.data.data || [] })
    })
  },
  openProduct(event) {
    const id = event.currentTarget.dataset.id
    wx.navigateTo({ url: `/pages/product-detail/index?id=${id}` })
  },
  openFavorites() {
    wx.navigateTo({ url: '/pages/favorites/index' })
  }
})
