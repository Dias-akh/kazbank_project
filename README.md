# KazBank Transaction API — Python + PostgreSQL

Flask REST API over PostgreSQL using psycopg3 and a ConnectionPool.

## Files

| File | Purpose |
|---|---|
| `step1_connect.py` | Step 1: connect via `.env`, print server version and `autocommit` |
| `step2_schema.py` | Step 2: create schema (customers, accounts, transactions), seed 10 customers / 15 accounts with `executemany()`, UNIQUE on `account_number` + duplicate test |
| `app.py` | Steps 3–7: REST API, transactions, SAVEPOINT, SERIALIZABLE + retry, error handling, ConnectionPool, `/health` |
| `load_test.py` | Step 6: 20 concurrent requests, prints pool statistics |

## Run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # put your PostgreSQL password into .env
# create database "kazbank" in pgAdmin (or: createdb kazbank)

python step1_connect.py
python step2_schema.py      # re-creates and seeds the schema
python app.py               # http://127.0.0.1:5001
```

Port 5001 is used because port 5000 is taken by AirPlay Receiver on macOS.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/customers` (`?city=Almaty`) | list customers, optional city filter |
| POST | `/customers` | create customer — 201 / 409 duplicate email / 400 missing field |
| PUT | `/customers/<id>` | update customer |
| DELETE | `/customers/<id>` | delete customer |
| GET | `/accounts?customer_id=n` | accounts of a customer |
| GET | `/transactions?account_id=n` | transaction history of an account |
| POST | `/transactions` | debit / credit, balance can't go below 0 |
| POST | `/transfer` | atomic transfer, SERIALIZABLE + retry, SAVEPOINT, sorted lock order |
| GET | `/health` | DB check + `pool.get_stats()` |

Every write endpoint uses an explicit transaction (`commit()` / `rollback()`).
All queries use `%s` parameters (no SQL injection).

## Sample curl commands

```bash
U=http://127.0.0.1:5001

curl "http://127.0.0.1:5001/customers" 
curl "http://127.0.0.1:5001/customers?city=Almaty"
curl "http://127.0.0.1:5001/accounts?customer_id=1"
curl "http://127.0.0.1:5001/transactions?account_id=1"

# create customer -> 201
curl -X POST http://127.0.0.1:5001/customers -H "Content-Type: application/json" \
     -d '{"full_name": "Test User", "city": "Almaty", "email": "test@kazbank.kz"}'

# duplicate email -> 409
curl -X POST http://127.0.0.1:5001/customers -H "Content-Type: application/json" \
     -d '{"full_name": "Copy", "email": "arman@kazbank.kz"}'

# missing full_name -> 400
curl -X POST http://127.0.0.1:5001/customers -H "Content-Type: application/json" \
     -d '{"city": "Almaty"}'

# debit / credit
curl -X POST http://127.0.0.1:5001/transactions -H "Content-Type: application/json" \
     -d '{"account_id": 1, "amount": 5000, "tx_type": "debit"}'

# transfer -> 200
curl -X POST http://127.0.0.1:5001/transfer -H "Content-Type: application/json" \
     -d '{"from_account": 1, "to_account": 3, "amount": 10000}'

# insufficient funds -> 400, nothing changes
curl -X POST http://127.0.0.1:5001/transfer -H "Content-Type: application/json" \
     -d '{"from_account": 13, "to_account": 1, "amount": 999999}'

# SQL injection attempt -> [] (value is a parameter, not SQL)
curl "http://127.0.0.1:5001/customers?city=Almaty'%20OR%20'1'='1"

# pool stats
curl "http://127.0.0.1:5001/health"

# database down (stop PostgreSQL) -> 503 on any endpoint
```

## Error codes

| Situation | Exception | HTTP |
|---|---|---|
| duplicate email | `UniqueViolation` | 409 |
| missing required field | `NotNullViolation` | 400 |
| database unreachable / pool timeout | `OperationalError` / `PoolTimeout` | 503 |
| serialization conflict after all retries | `SerializationFailure` | 409 |
| not found | — | 404 |

## Deadlock demo (Step 4, Task 4)

Two sessions (two pgAdmin Query Tool tabs on `kazbank`, or two `psql` windows), run in this order:

```sql
-- A: BEGIN; UPDATE accounts SET balance = balance - 1 WHERE account_id = 1;
-- B: BEGIN; UPDATE accounts SET balance = balance - 1 WHERE account_id = 2;
-- A: UPDATE accounts SET balance = balance + 1 WHERE account_id = 2;   -- waits
-- B: UPDATE accounts SET balance = balance + 1 WHERE account_id = 1;   -- ERROR 40P01: deadlock detected
-- then ROLLBACK; in both sessions
```

`/transfer` avoids this by always locking the lower `account_id` first.
