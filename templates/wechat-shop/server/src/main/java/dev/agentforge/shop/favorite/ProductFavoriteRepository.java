package dev.agentforge.shop.favorite;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface ProductFavoriteRepository extends JpaRepository<ProductFavorite, Long> {
    boolean existsByUserIdAndProductId(long userId, long productId);
    void deleteByUserIdAndProductId(long userId, long productId);
    List<ProductFavorite> findByUserIdOrderByCreatedAtDesc(long userId);
}
