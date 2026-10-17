package com.agentforge.shop.auth;

public final class CurrentUser {
    private final long userId;
    public CurrentUser(long userId) { this.userId = userId; }
    public long getUserId() { return userId; }
}
