# Verified database contract

REQ-980100 uses exactly two authoritative MySQL tables: `points_account` and `points_ledger`.
The migration is exactly `database/migrations/V980100__points.sql`.
`points_ledger.business_no` must be unique so repeated processing cannot double-credit points.
Do not create `user_points_account`, `user_points_ledger`, aliases, or compatibility views.
See `.agent/contracts/DB-POINTS-980100.yaml`.
