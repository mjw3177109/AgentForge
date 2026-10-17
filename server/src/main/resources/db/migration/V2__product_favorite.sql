CREATE TABLE IF NOT EXISTS user_product_favorite (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  product_id BIGINT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uk_user_product_favorite UNIQUE (user_id, product_id),
  CONSTRAINT fk_favorite_user FOREIGN KEY (user_id) REFERENCES shop_user(id),
  CONSTRAINT fk_favorite_product FOREIGN KEY (product_id) REFERENCES product(id)
);
