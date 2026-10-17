Page({
  data: { productIds: [] },
  onShow() {
    wx.request({
      url: getApp().globalData.apiBase + '/api/favorites',
      success: (r) => this.setData({ productIds: r.data.data || [] })
    })
  },
  openProduct(event) {
    wx.navigateTo({ url: `/pages/product-detail/index?id=${event.currentTarget.dataset.id}` })
  }
})
