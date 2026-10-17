package com.agentforge.shop.auth;

import org.junit.jupiter.api.Test;
import org.springframework.core.MethodParameter;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.ServletWebRequest;
import java.lang.reflect.Method;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class CurrentUserArgumentResolverTest {
    static class Target {
        public void endpoint(CurrentUser currentUser) { }
    }

    private MethodParameter parameter() throws Exception {
        Method method = Target.class.getMethod("endpoint", CurrentUser.class);
        return new MethodParameter(method, 0);
    }

    @Test
    void resolvesOnlyServerSideRequestAttribute() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute(AuthenticationAttributes.USER_ID, 42L);
        CurrentUserArgumentResolver resolver = new CurrentUserArgumentResolver();
        CurrentUser user = (CurrentUser) resolver.resolveArgument(parameter(), null, new ServletWebRequest(request), null);
        assertEquals(42L, user.getUserId());
    }

    @Test
    void missingContextIsRejected() throws Exception {
        CurrentUserArgumentResolver resolver = new CurrentUserArgumentResolver();
        assertThrows(MissingCurrentUserException.class,
                () -> resolver.resolveArgument(parameter(), null, new ServletWebRequest(new MockHttpServletRequest()), null));
    }
}
