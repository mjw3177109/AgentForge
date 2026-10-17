package com.agentforge.shop.auth;

import org.springframework.core.MethodParameter;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.context.request.RequestAttributes;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

public class CurrentUserArgumentResolver implements HandlerMethodArgumentResolver {
    @Override
    public boolean supportsParameter(MethodParameter parameter) {
        return CurrentUser.class.equals(parameter.getParameterType());
    }

    @Override
    public Object resolveArgument(
            MethodParameter parameter,
            ModelAndViewContainer mavContainer,
            NativeWebRequest webRequest,
            WebDataBinderFactory binderFactory) {
        Object raw = webRequest.getAttribute(AuthenticationAttributes.USER_ID, RequestAttributes.SCOPE_REQUEST);
        if (raw instanceof Number) {
            return new CurrentUser(((Number) raw).longValue());
        }
        if (raw instanceof String) {
            try {
                return new CurrentUser(Long.parseLong((String) raw));
            } catch (NumberFormatException ignored) {
                throw new MissingCurrentUserException();
            }
        }
        throw new MissingCurrentUserException();
    }
}
