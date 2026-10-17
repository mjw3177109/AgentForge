package com.agentforge.shop.product;

import com.agentforge.shop.common.ApiResponse;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import java.math.BigDecimal;
import java.util.List;

@RestController
@RequestMapping("/api/products")
public class ProductController {
    @GetMapping
    public ApiResponse<List<ProductSummary>> list() {
        return ApiResponse.ok(List.of(new ProductSummary(1L, "AgentForge Demo Product", new BigDecimal("99.00"))));
    }
}
