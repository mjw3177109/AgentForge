package com.agentforge.shop.favorite;

public final class FavoriteStatus {
    private final long productId;
    private final boolean favorite;

    public FavoriteStatus(long productId, boolean favorite) {
        this.productId = productId;
        this.favorite = favorite;
    }

    public long getProductId() { return productId; }
    public boolean isFavorite() { return favorite; }
}
