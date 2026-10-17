package com.agentforge.shop.product;

import java.math.BigDecimal;

public final class ProductSummary {
    private final long id;
    private final String name;
    private final BigDecimal price;
    public ProductSummary(long id, String name, BigDecimal price) { this.id=id; this.name=name; this.price=price; }
    public long getId(){ return id; }
    public String getName(){ return name; }
    public BigDecimal getPrice(){ return price; }
}
