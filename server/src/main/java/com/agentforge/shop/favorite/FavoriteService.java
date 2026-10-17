package com.agentforge.shop.favorite;

import org.springframework.stereotype.Service;
import java.util.List;

@Service
public class FavoriteService {
    private final FavoriteRepository repository;

    public FavoriteService(FavoriteRepository repository) {
        this.repository = repository;
    }

    public FavoriteStatus add(long userId, long productId) {
        repository.add(userId, productId);
        return new FavoriteStatus(productId, true);
    }

    public FavoriteStatus remove(long userId, long productId) {
        repository.remove(userId, productId);
        return new FavoriteStatus(productId, false);
    }

    public FavoriteStatus status(long userId, long productId) {
        return new FavoriteStatus(productId, repository.exists(userId, productId));
    }

    public List<Long> listProductIds(long userId) {
        return repository.listProductIds(userId);
    }
}
