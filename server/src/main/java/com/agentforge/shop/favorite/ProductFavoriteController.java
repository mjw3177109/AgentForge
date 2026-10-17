package com.agentforge.shop.favorite;

import com.agentforge.shop.auth.CurrentUser;
import com.agentforge.shop.common.ApiResponse;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/products")
public class ProductFavoriteController {
    private final FavoriteService service;

    public ProductFavoriteController(FavoriteService service) {
        this.service = service;
    }

    @GetMapping("/{productId}/favorite-status")
    public ApiResponse<FavoriteStatus> status(@PathVariable long productId, CurrentUser currentUser) {
        return ApiResponse.ok(service.status(currentUser.getUserId(), productId));
    }
}
