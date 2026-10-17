package dev.agentforge.shop.favorite;

import dev.agentforge.shop.security.CurrentUserProvider;
import org.springframework.web.bind.annotation.*;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/favorites")
public class FavoriteController {
    private final FavoriteService favoriteService;
    private final CurrentUserProvider currentUser;

    public FavoriteController(FavoriteService favoriteService, CurrentUserProvider currentUser) {
        this.favoriteService = favoriteService;
        this.currentUser = currentUser;
    }

    @PostMapping("/{productId}")
    public void favorite(@PathVariable long productId) {
        favoriteService.favorite(currentUser.currentUserId(), productId);
    }

    @DeleteMapping("/{productId}")
    public void unfavorite(@PathVariable long productId) {
        favoriteService.unfavorite(currentUser.currentUserId(), productId);
    }

    @GetMapping
    public List<Long> list() {
        return favoriteService.favoriteProductIds(currentUser.currentUserId());
    }

    @GetMapping("/{productId}/status")
    public Map<String, Boolean> status(@PathVariable long productId) {
        return Map.of("favorite", favoriteService.isFavorite(currentUser.currentUserId(), productId));
    }
}
