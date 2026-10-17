package com.agentforge.shop.points;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class VerifiedPointsContractTest {
    private String productionSources() throws IOException {
        Path root = Path.of("src/main/java/com/agentforge/shop/points");
        assertTrue(Files.isDirectory(root), "points source directory must exist");
        StringBuilder text = new StringBuilder();
        try (var stream = Files.walk(root)) {
            for (Path path : stream.filter(Files::isRegularFile).filter(p -> p.toString().endsWith(".java")).toList()) {
                text.append(Files.readString(path)).append(System.lineSeparator());
            }
        }
        return text.toString();
    }

    @Test
    void usesVerifiedIdentityAndDoesNotExposeEarnEndpoint() throws Exception {
        String text = productionSources();
        assertTrue(text.contains("CurrentUserProvider"));
        assertFalse(text.toLowerCase().contains("x-user-id"));
        assertFalse(text.contains("@PostMapping(\"/earn\")"));
        assertFalse(text.contains("@PostMapping(\"earn\")"));
    }

    @Test
    void usesVerifiedDatabaseAndApiContracts() throws Exception {
        String text = productionSources();
        assertTrue(text.contains("points_account"));
        assertTrue(text.contains("points_ledger"));
        assertFalse(text.contains("user_points_account"));
        assertFalse(text.contains("user_points_ledger"));
        assertTrue(text.contains("/balance"));
        assertTrue(text.contains("redeem-preview"));
        assertTrue(text.contains("/ledger"));
        assertTrue(text.contains("orderPaidAmountYuan"));
    }
}
