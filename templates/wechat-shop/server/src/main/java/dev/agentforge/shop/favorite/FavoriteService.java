package dev.agentforge.shop.favorite;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.List;
import java.util.stream.Collectors;

@Service
public class FavoriteService {
    private final ProductFavoriteRepository repository;

    public FavoriteService(ProductFavoriteRepository repository) {
        this.repository = repository;
    }

    @Transactional
    public void favorite(long userId, long productId) {
        if (!repository.existsByUserIdAndProductId(userId, productId)) {
            repository.save(new ProductFavorite(userId, productId));
        }
    }

    @Transactional
    public void unfavorite(long userId, long productId) {
        if (repository.existsByUserIdAndProductId(userId, productId)) {
            repository.deleteByUserIdAndProductId(userId, productId);
        }
    }

    @Transactional(readOnly = true)
    public boolean isFavorite(long userId, long productId) {
        return repository.existsByUserIdAndProductId(userId, productId);
    }

    @Transactional(readOnly = true)
    public List<Long> favoriteProductIds(long userId) {
        return repository.findByUserIdOrderByCreatedAtDesc(userId).stream()
            .map(ProductFavorite::getProductId)
            .collect(Collectors.toList());
    }
}
