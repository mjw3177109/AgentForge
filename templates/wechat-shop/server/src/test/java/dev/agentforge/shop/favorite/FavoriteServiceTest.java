package dev.agentforge.shop.favorite;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;

class FavoriteServiceTest {
    @Test
    void duplicateFavoriteIsIdempotent() {
        ProductFavoriteRepository repo = mock(ProductFavoriteRepository.class);
        when(repo.existsByUserIdAndProductId(7L, 99L)).thenReturn(true);
        FavoriteService service = new FavoriteService(repo);
        service.favorite(7L, 99L);
        verify(repo, never()).save(any());
    }

    @Test
    void firstFavoriteIsPersisted() {
        ProductFavoriteRepository repo = mock(ProductFavoriteRepository.class);
        when(repo.existsByUserIdAndProductId(7L, 99L)).thenReturn(false);
        FavoriteService service = new FavoriteService(repo);
        service.favorite(7L, 99L);
        verify(repo).save(any(ProductFavorite.class));
    }

    @Test
    void statusDelegatesToRepository() {
        ProductFavoriteRepository repo = mock(ProductFavoriteRepository.class);
        when(repo.existsByUserIdAndProductId(7L, 99L)).thenReturn(true);
        assertTrue(new FavoriteService(repo).isFavorite(7L, 99L));
    }
}
