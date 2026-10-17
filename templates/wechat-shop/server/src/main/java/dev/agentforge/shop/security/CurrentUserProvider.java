package dev.agentforge.shop.security;

/** Project authentication boundary defined by FACT-AUTH-001. */
public interface CurrentUserProvider {
    long currentUserId();
}
