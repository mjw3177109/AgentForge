package com.agentforge.shop.order;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;
class OrderStatusTest {
    @Test void paid_status_is_stable(){ assertEquals("PAID", OrderStatus.PAID.name()); }
}
