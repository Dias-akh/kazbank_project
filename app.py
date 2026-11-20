import os
import time
from decimal import Decimal, InvalidOperation

import psycopg
from psycopg import errors as pg_errors
from psycopg_pool import ConnectionPool, PoolTimeout
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()
app = Flask(__name__)


pool = ConnectionPool(
    conninfo=os.environ["DATABASE_URL"],
    min_size=2,
    max_size=8,
    timeout=5.0,
    open=True,
)
print("ConnectionPool created: min=2, max=8")


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.errorhandler(psycopg.OperationalError)
@app.errorhandler(PoolTimeout)
def db_unavailable(e):
    return jsonify({"error": "Database unavailable"}), 503


def parse_amount(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


@app.route("/customers", methods=["GET"])
def list_customers():
    city = request.args.get("city", default=None)

    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT customer_id, full_name, city, email FROM customers "
            "WHERE (%s::text IS NULL OR city = %s) "
            "ORDER BY customer_id",
            (city, city),
        ).fetchall()

    return jsonify([
        {"id": r[0], "name": r[1], "city": r[2], "email": r[3]} for r in rows
    ]), 200


@app.route("/customers", methods=["POST"])
def create_customer():
    data = request.get_json(force=True)
    try:
        with pool.connection() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO customers (full_name, city, email) "
                    "VALUES (%s, %s, %s) RETURNING customer_id",
                    (data.get("full_name"), data.get("city", "Almaty"), data.get("email")),
                )
                new_id = cur.fetchone()[0]
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return jsonify({"customer_id": new_id}), 201

    except pg_errors.UniqueViolation:
        return jsonify({"error": "Email already registered"}), 409
    except pg_errors.NotNullViolation as e:
        return jsonify({"error": f"Missing required field: {e.diag.column_name}"}), 400


@app.route("/customers/<int:cid>", methods=["PUT"])
def update_customer(cid):
    data = request.get_json(force=True)
    with pool.connection() as conn:
        cur = conn.execute(
            "UPDATE customers SET full_name = %s, city = %s WHERE customer_id = %s",
            (data.get("full_name"), data.get("city"), cid),
        )
        conn.commit()
    if cur.rowcount == 0:
        return jsonify({"error": "customer not found"}), 404
    return jsonify({"updated": cid}), 200


@app.route("/customers/<int:cid>", methods=["DELETE"])
def delete_customer(cid):
    try:
        with pool.connection() as conn:
            cur = conn.execute("DELETE FROM customers WHERE customer_id = %s", (cid,))
            conn.commit()
    except pg_errors.ForeignKeyViolation:
        return jsonify({"error": "customer has accounts"}), 409
    if cur.rowcount == 0:
        return jsonify({"error": "customer not found"}), 404
    return jsonify({"deleted": cid}), 200


@app.route("/accounts", methods=["GET"])
def list_accounts():
    customer_id = request.args.get("customer_id", type=int)
    if customer_id is None:
        return jsonify({"error": "customer_id is required"}), 400

    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT account_id, account_number, balance FROM accounts "
            "WHERE customer_id = %s ORDER BY account_id",
            (customer_id,),
        ).fetchall()

    return jsonify([
        {"account_id": r[0], "account_number": r[1], "balance": float(r[2])}
        for r in rows
    ]), 200


@app.route("/accounts/lookup", methods=["GET"])
def lookup_account():
    number = request.args.get("number", default=None)
    if not number:
        return jsonify({"error": "number is required"}), 400

    with pool.connection() as conn:
        row = conn.execute(
            "SELECT a.account_id, a.account_number, c.full_name "
            "FROM accounts a JOIN customers c ON c.customer_id = a.customer_id "
            "WHERE a.account_number = %s",
            (number.strip().upper(),),
        ).fetchone()

    if row is None:
        return jsonify({"error": "account not found"}), 404

    parts = row[2].split()
    owner = parts[0] + (" " + parts[1][0] + "." if len(parts) > 1 else "")
    return jsonify({"account_id": row[0], "account_number": row[1], "owner": owner}), 200


@app.route("/transactions", methods=["GET"])
def list_transactions():
    account_id = request.args.get("account_id", type=int)
    if account_id is None:
        return jsonify({"error": "account_id is required"}), 400

    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT tx_id, amount, tx_type, created_at FROM transactions "
            "WHERE account_id = %s ORDER BY tx_id",
            (account_id,),
        ).fetchall()

    return jsonify([
        {"tx_id": r[0], "amount": float(r[1]), "tx_type": r[2],
         "created_at": r[3].isoformat()}
        for r in rows
    ]), 200


@app.route("/transactions", methods=["POST"])
def create_transaction():
    data = request.get_json(force=True)
    account_id = data.get("account_id")
    tx_type = data.get("tx_type")
    amount = parse_amount(data.get("amount"))

    if tx_type not in ("debit", "credit"):
        return jsonify({"error": "tx_type must be 'debit' or 'credit'"}), 400
    if amount is None or amount <= 0:
        return jsonify({"error": "amount must be a number > 0"}), 400

    with pool.connection() as conn:
        with conn.transaction():
            row = conn.execute(
                "SELECT balance FROM accounts WHERE account_id = %s FOR UPDATE",
                (account_id,),
            ).fetchone()
            if row is None:
                return jsonify({"error": "account not found"}), 404

            balance = row[0]
            new_balance = balance - amount if tx_type == "debit" else balance + amount
            if new_balance < 0:
                return jsonify({"error": "insufficient funds",
                                "balance": float(balance)}), 400

            conn.execute(
                "UPDATE accounts SET balance = %s WHERE account_id = %s",
                (new_balance, account_id),
            )
            tx_id = conn.execute(
                "INSERT INTO transactions (account_id, amount, tx_type) "
                "VALUES (%s, %s, %s) RETURNING tx_id",
                (account_id, amount, tx_type),
            ).fetchone()[0]

    return jsonify({"tx_id": tx_id, "account_id": account_id,
                    "new_balance": float(new_balance)}), 201


def with_retry(fn, max_retries=5):
    for attempt in range(max_retries):
        try:
            return fn()
        except pg_errors.SerializationFailure:
            if attempt == max_retries - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise RuntimeError("Max retries exceeded")


def do_transfer(from_acc, to_acc, amount):
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")

            first, second = sorted([from_acc, to_acc])
            found = 0
            for acc in (first, second):
                row = conn.execute(
                    "SELECT 1 FROM accounts WHERE account_id = %s FOR UPDATE",
                    (acc,),
                ).fetchone()
                if row is not None:
                    found += 1
            if found < 2:
                return {"error": "account not found"}, 404

            try:
                with conn.transaction():
                    conn.execute(
                        "UPDATE accounts SET balance = balance - %s WHERE account_id = %s",
                        (amount, from_acc),
                    )
            except pg_errors.CheckViolation:
                balance = conn.execute(
                    "SELECT balance FROM accounts WHERE account_id = %s",
                    (from_acc,),
                ).fetchone()[0]
                return {"error": "insufficient funds", "balance": float(balance)}, 400

            conn.execute(
                "UPDATE accounts SET balance = balance + %s WHERE account_id = %s",
                (amount, to_acc),
            )
            conn.execute(
                "INSERT INTO transactions (account_id, amount, tx_type) "
                "VALUES (%s, %s, 'debit'), (%s, %s, 'credit')",
                (from_acc, amount, to_acc, amount),
            )

    return {"from_account": from_acc, "to_account": to_acc,
            "amount": float(amount), "status": "ok"}, 200


@app.route("/transfer", methods=["POST"])
def transfer():
    data = request.get_json(force=True)
    from_acc = data.get("from_account")
    to_acc = data.get("to_account")
    amount = parse_amount(data.get("amount"))

    if not isinstance(from_acc, int) or not isinstance(to_acc, int):
        return jsonify({"error": "from_account and to_account must be integers"}), 400
    if amount is None or amount <= 0:
        return jsonify({"error": "amount must be a number > 0"}), 400
    if from_acc == to_acc:
        return jsonify({"error": "cannot transfer to the same account"}), 400

    try:
        body, code = with_retry(lambda: do_transfer(from_acc, to_acc, amount))
    except pg_errors.SerializationFailure:
        return jsonify({"error": "too many concurrent transfers, try again"}), 409
    return jsonify(body), code


@app.route("/health", methods=["GET"])
def health():
    try:
        pool.check()
        with pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
        return jsonify({"status": "ok", "pool": pool.get_stats()}), 200
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 503


if __name__ == "__main__":
    app.run(port=5001, threaded=True)