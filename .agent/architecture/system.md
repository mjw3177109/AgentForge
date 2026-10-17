# System Architecture

- Client: native WeChat Mini Program
- Admin: Vue 3 + Vite
- Backend: Spring Boot 2.7.18 / Java 17
- DB: MySQL + Flyway
- Cache: Redis
- Payment: WeChat Pay API v3 official Java SDK
- Delivery: feature branch -> CI -> review -> PR -> merge -> memory

Cross-module work must be represented as a Task DAG. Frontend agents consume contracts/facts instead of inventing backend behavior.
