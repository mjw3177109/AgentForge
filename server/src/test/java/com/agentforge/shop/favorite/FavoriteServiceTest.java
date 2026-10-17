package com.agentforge.shop.favorite;

import org.junit.jupiter.api.Test;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class FavoriteServiceTest {
    @Test
    void addUsesAuthenticatedUserIdAndProductId() {
        FavoriteRepository repository = mock(FavoriteRepository.class);
        FavoriteService service = new FavoriteService(repository);
        FavoriteStatus result = service.add(42L, 9L);
        verify(repository).add(42L, 9L);
        assertTrue(result.isFavorite());
    }

    @Test
    void statusComesFromRepository() {
        FavoriteRepository repository = mock(FavoriteRepository.class);
        when(repository.exists(42L, 9L)).thenReturn(false);
        FavoriteStatus result = new FavoriteService(repository).status(42L, 9L);
        assertFalse(result.isFavorite());
    }

    @Test
    void listIsScopedByCurrentUser() {
        FavoriteRepository repository = mock(FavoriteRepository.class);
        when(repository.listProductIds(42L)).thenReturn(List.of(9L, 8L));
        new FavoriteService(repository).listProductIds(42L);
        verify(repository).listProductIds(42L);
    }
}
