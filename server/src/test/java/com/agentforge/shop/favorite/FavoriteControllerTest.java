package com.agentforge.shop.favorite;

import com.agentforge.shop.auth.CurrentUser;
import org.junit.jupiter.api.Test;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class FavoriteControllerTest {
    @Test
    void controllerUsesCurrentUserInsteadOfClientUserId() {
        FavoriteService service = mock(FavoriteService.class);
        FavoriteController controller = new FavoriteController(service);
        controller.add(9L, new CurrentUser(42L));
        verify(service).add(42L, 9L);
    }
}
