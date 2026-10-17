package dev.agentforge.shop.favorite;

import javax.persistence.*;
import java.time.Instant;

@Entity
@Table(name = "user_product_favorite", uniqueConstraints = @UniqueConstraint(name = "uk_user_product_favorite", columnNames = {"user_id", "product_id"}))
public class ProductFavorite {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    @Column(name = "user_id", nullable = false)
    private Long userId;
    @Column(name = "product_id", nullable = false)
    private Long productId;
    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    protected ProductFavorite() {}
    public ProductFavorite(long userId, long productId) {
        this.userId = userId;
        this.productId = productId;
        this.createdAt = Instant.now();
    }
    public Long getId() { return id; }
    public Long getUserId() { return userId; }
    public Long getProductId() { return productId; }
    public Instant getCreatedAt() { return createdAt; }
}
