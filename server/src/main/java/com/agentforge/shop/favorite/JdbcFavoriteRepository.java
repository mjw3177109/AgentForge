package com.agentforge.shop.favorite;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import java.util.List;

@Repository
public class JdbcFavoriteRepository implements FavoriteRepository {
    private final JdbcTemplate jdbcTemplate;

    public JdbcFavoriteRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public void add(long userId, long productId) {
        jdbcTemplate.update(
                "INSERT IGNORE INTO user_product_favorite(user_id, product_id) VALUES (?, ?)",
                userId,
                productId);
    }

    @Override
    public void remove(long userId, long productId) {
        jdbcTemplate.update(
                "DELETE FROM user_product_favorite WHERE user_id = ? AND product_id = ?",
                userId,
                productId);
    }

    @Override
    public boolean exists(long userId, long productId) {
        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM user_product_favorite WHERE user_id = ? AND product_id = ?",
                Integer.class,
                userId,
                productId);
        return count != null && count > 0;
    }

    @Override
    public List<Long> listProductIds(long userId) {
        return jdbcTemplate.query(
                "SELECT product_id FROM user_product_favorite WHERE user_id = ? ORDER BY id DESC",
                (rs, rowNum) -> rs.getLong(1),
                userId);
    }
}
