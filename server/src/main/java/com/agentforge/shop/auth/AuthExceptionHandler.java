package com.agentforge.shop.auth;

import com.agentforge.shop.common.ApiResponse;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class AuthExceptionHandler {
    @ExceptionHandler(MissingCurrentUserException.class)
    @ResponseStatus(HttpStatus.UNAUTHORIZED)
    public ApiResponse<Void> missingCurrentUser(MissingCurrentUserException ignored) {
        return ApiResponse.error("UNAUTHENTICATED");
    }
}
