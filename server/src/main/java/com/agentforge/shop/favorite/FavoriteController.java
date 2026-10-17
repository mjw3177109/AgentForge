package com.agentforge.shop.favorite;

import com.agentforge.shop.auth.CurrentUser;
import com.agentforge.shop.common.ApiResponse;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import java.util.List;

@RestController
@RequestMapping("/api/favorites")
public class FavoriteController {
    private final FavoriteService service;

    public FavoriteController(FavoriteService service) {
        this.service = service;
    }

    @PostMapping("/{productId}")
    public ApiResponse<FavoriteStatus> add(@PathVariable long productId, CurrentUser currentUser) {
        return ApiResponse.ok(service.add(currentUser.getUserId(), productId));
    }

    @DeleteMapping("/{productId}")
    public ApiResponse<FavoriteStatus> remove(@PathVariable long productId, CurrentUser currentUser) {
        return ApiResponse.ok(service.remove(currentUser.getUserId(), productId));
    }

    @GetMapping
    public ApiResponse<List<Long>> list(CurrentUser currentUser) {
        return ApiResponse.ok(service.listProductIds(currentUser.getUserId()));
    }
}
