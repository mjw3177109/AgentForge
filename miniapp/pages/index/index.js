Page({ data:{products:[]}, onLoad(){ wx.request({url:getApp().globalData.apiBase+'/api/products',success:r=>this.setData({products:r.data.data||[]})}) } })
