package com.agentforge.shop.points;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTimeoutPreemptively;

import com.agentforge.shop.auth.CurrentUserProvider;
import java.math.BigDecimal;
import java.time.Duration;
import java.util.Optional;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.test.context.junit.jupiter.SpringExtension;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;

/**
 * Trusted maintainer-owned behavior gate, injected ONLY into a disposable
 * copy of generated sources. Never part of a coding Agent's write scope.
 * A real isolated MySQL schema and Spring transactional proxy are required.
 */
@ExtendWith(SpringExtension.class)
@ContextConfiguration(classes = TrustedPointsExactlyOnceTest.TrustedConfiguration.class)
class TrustedPointsExactlyOnceTest {
    private static final long USER_ID = 984101L;

    @Configuration(proxyBeanMethods = false)
    @EnableTransactionManagement
    static class TrustedConfiguration {
        @Bean
        DriverManagerDataSource dataSource() {
            String url = System.getenv("AGENTFORGE_V41_JDBC_URL");
            if (url == null || !url.matches(
                    "jdbc:mysql://127\\.0\\.0\\.1:3306/agentforge_v41_[A-Za-z0-9_]+\\?.*")) {
                throw new IllegalStateException("V41 JDBC URL must point to the isolated localhost schema");
            }
            DriverManagerDataSource ds = new DriverManagerDataSource();
            ds.setDriverClassName("com.mysql.cj.jdbc.Driver");
            ds.setUrl(url);
            ds.setUsername("root");
            ds.setPassword(System.getenv("AGENTFORGE_V20_MYSQL_PASSWORD"));
            return ds;
        }
        @Bean JdbcTemplate jdbcTemplate(DriverManagerDataSource dataSource) {
            return new JdbcTemplate(dataSource);
        }
        @Bean PlatformTransactionManager transactionManager(DriverManagerDataSource ds) {
            return new DataSourceTransactionManager(ds);
        }
        @Bean CurrentUserProvider currentUserProvider() {
            return () -> USER_ID;
        }
        @Bean PointsLedgerRepository pointsLedgerRepository(JdbcTemplate jdbc) {
            return new PointsLedgerRepository(jdbc);
        }
        @Bean PointsAccountRepository pointsAccountRepository(JdbcTemplate jdbc) {
            return new PointsAccountRepository(jdbc);
        }
        @Bean PointsBalanceCache pointsBalanceCache() {
            return new PointsBalanceCache() {
                public Optional<Long> get(long userId) { return Optional.empty(); }
                public void put(long userId, long balance) { }
                public void evict(long userId) { }
            };
        }
        @Bean PointsService pointsService(CurrentUserProvider identity,
                PointsAccountRepository accounts, PointsLedgerRepository ledger,
                PointsBalanceCache cache) {
            return new PointsService(identity, accounts, ledger, cache);
        }
    }

    @Autowired JdbcTemplate jdbc;
    @Autowired PointsService service;

    @BeforeEach
    void resetIsolatedDatabase() {
        jdbc.update("DELETE FROM points_ledger");
        jdbc.update("DELETE FROM points_account");
    }

    private void assertExactlyOnce(String businessNo, long points) {
        assertEquals(1L, jdbc.queryForObject(
            "SELECT COUNT(*) FROM points_ledger WHERE business_no = ?", Long.class, businessNo).longValue());
        assertEquals(points, jdbc.queryForObject(
            "SELECT balance_points FROM points_account WHERE user_id = ?", Long.class, USER_ID).longValue());
    }

    @Test
    void sequentialDuplicateEventCannotDoubleCredit() {
        service.earnAfterPayment("V41-SEQ-0001", new BigDecimal("100.50"));
        service.earnAfterPayment("V41-SEQ-0001", new BigDecimal("100.50"));
        assertExactlyOnce("V41-SEQ-0001", 100L);
    }

    @Test
    void concurrentDuplicateEventCannotDoubleCredit() {
        assertTimeoutPreemptively(Duration.ofSeconds(35), () -> {
            ExecutorService executor = Executors.newFixedThreadPool(2);
            CountDownLatch go = new CountDownLatch(1);
            Callable<Boolean> job = () -> {
                go.await();
                service.earnAfterPayment("V41-CONCURRENT-0001", new BigDecimal("100.50"));
                return true;
            };
            try {
                Future<Boolean> first = executor.submit(job);
                Future<Boolean> second = executor.submit(job);
                go.countDown();
                first.get();
                second.get();
                assertExactlyOnce("V41-CONCURRENT-0001", 100L);
            } finally {
                executor.shutdownNow();
            }
        });
    }
}
