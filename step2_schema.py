import os
import psycopg
from dotenv import load_dotenv

load_dotenv()
conn_str = os.environ["DATABASE_URL"]

DDL = """
DROP TABLE IF EXISTS transactions, accounts, customers CASCADE;

CREATE TABLE customers (
    customer_id SERIAL PRIMARY KEY,
    full_name   TEXT NOT NULL,
    city        TEXT DEFAULT 'Almaty',
    email       TEXT UNIQUE
);

CREATE TABLE accounts (
    account_id     SERIAL PRIMARY KEY,
    customer_id    INTEGER NOT NULL REFERENCES customers(customer_id),
    account_number TEXT NOT NULL,
    balance        NUMERIC(15,2) NOT NULL DEFAULT 0 CHECK (balance >= 0)
);

CREATE TABLE transactions (
    tx_id      SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    amount     NUMERIC(15,2) NOT NULL CHECK (amount > 0),
    tx_type    TEXT NOT NULL CHECK (tx_type IN ('debit', 'credit')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

ADD_UNIQUE = """
ALTER TABLE accounts
    ADD CONSTRAINT uq_account_number UNIQUE (account_number);
"""

SEED_CUSTOMERS = [
    ("Arman Bekov",        "Almaty",    "arman@kazbank.kz"),
    ("Zarina Seiit",       "Astana",    "zarina@kazbank.kz"),
    ("Daniyar Nurlan",     "Shymkent",  "daniyar@kazbank.kz"),
    ("Aigerim Tulegen",    "Almaty",    "aigerim@kazbank.kz"),
    ("Yerlan Abenov",      "Karaganda", "yerlan@kazbank.kz"),
    ("Madina Ospanova",    "Almaty",    "madina@kazbank.kz"),
    ("Bekzat Amanov",      "Astana",    "bekzat@kazbank.kz"),
    ("Dana Sagyndykova",   "Aktobe",    "dana@kazbank.kz"),
    ("Sanzhar Yerbolov",   "Almaty",    "sanzhar@kazbank.kz"),
    ("Aliya Kenzhebekova", "Atyrau",    "aliya@kazbank.kz"),
]

SEED_ACCOUNTS = [
    (1,  "KZ0001", 500000), (1,  "KZ0002", 120000),
    (2,  "KZ0003", 300000), (3,  "KZ0004",  75000),
    (3,  "KZ0005",  20000), (4,  "KZ0006", 910000),
    (5,  "KZ0007",  45000), (6,  "KZ0008", 260000),
    (6,  "KZ0009",  10000), (7,  "KZ0010", 150000),
    (8,  "KZ0011",  88000), (9,  "KZ0012", 400000),
    (9,  "KZ0013",   5000), (10, "KZ0014", 230000),
    (10, "KZ0015",  64000),
]

with psycopg.connect(conn_str) as conn:
    conn.execute(DDL)
    conn.execute(ADD_UNIQUE)

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO customers (full_name, city, email) VALUES (%s, %s, %s)",
            SEED_CUSTOMERS,
        )
        cur.executemany(
            "INSERT INTO accounts (customer_id, account_number, balance) VALUES (%s, %s, %s)",
            SEED_ACCOUNTS,
        )
    conn.commit()

    n_c = conn.execute("SELECT count(*) FROM customers").fetchone()[0]
    n_a = conn.execute("SELECT count(*) FROM accounts").fetchone()[0]
    print(f"Создано: {n_c} клиентов, {n_a} счетов")

    try:
        conn.execute(
            "INSERT INTO accounts (customer_id, account_number, balance) VALUES (%s, %s, %s)",
            (2, "KZ0001", 1000),
        )
        conn.commit()
        print("Ошибка: дубликат вставился, UNIQUE не работает")
    except psycopg.errors.UniqueViolation as e:
        conn.rollback()
        print("UNIQUE работает, дубликат отклонён:")
        print("  ", e.diag.message_primary)