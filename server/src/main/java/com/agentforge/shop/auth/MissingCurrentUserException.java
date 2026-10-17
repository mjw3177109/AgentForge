package com.agentforge.shop.auth;

public class MissingCurrentUserException extends RuntimeException {
    public MissingCurrentUserException() {
        super("Authenticated user context is missing");
    }
}
