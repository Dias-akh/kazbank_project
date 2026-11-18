import os
import psycopg
from dotenv import load_dotenv

load_dotenv()
conn_str = os.environ["DATABASE_URL"]

with psycopg.connect(conn_str) as conn:
    print("autocommit =", conn.autocommit)
    with conn.cursor() as cur:
        cur.execute("SELECT version()")
        print(cur.fetchone()[0])