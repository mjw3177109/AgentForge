package com.agentforge.shop.favorite;

import java.util.List;

public interface FavoriteRepository {
    void add(long userId, long productId);
    void remove(long userId, long productId);
    boolean exists(long userId, long productId);
    List<Long> listProductIds(long userId);
}
