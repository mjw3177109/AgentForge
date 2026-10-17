CREATE TABLE user_product_favorite (
    id BIGINT NOT NULL AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uk_user_product_favorite UNIQUE (user_id, product_id),
    INDEX idx_favorite_user_created (user_id, created_at)
);
