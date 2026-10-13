import os
import pyodbc
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException

load_dotenv()
app = FastAPI(title="Reporter Assistant", version="0.1.0")

def connect():
    values = {k: os.getenv(k, "") for k in ("DB_SERVER", "DB_NAME", "DB_USER", "DB_PASSWORD")}
    if not all(values.values()):
        raise HTTPException(503, "Database configuration is incomplete")
    return pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        + "SERVER=" + values["DB_SERVER"] + ";DATABASE=" + values["DB_NAME"]
        + ";UID=" + values["DB_USER"] + ";PWD=" + values["DB_PASSWORD"]
        + ";Encrypt=yes;TrustServerCertificate=no;ApplicationIntent=ReadOnly",
        timeout=5
    )

def authorize(x_api_key):
    if not os.getenv("APP_API_KEY") or x_api_key != os.getenv("APP_API_KEY"):
        raise HTTPException(401, "Unauthorized")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/db/test")
def db_test(x_api_key: str = Header(default="")):
    authorize(x_api_key)
    try:
        with connect() as connection:
            row = connection.cursor().execute("SELECT DB_NAME(), @@SERVERNAME").fetchone()
            return {"connected": True, "database": row[0], "server": row[1]}
    except pyodbc.Error:
        raise HTTPException(503, "Database connection failed")

@app.get("/api/schema/tables")
def tables(x_api_key: str = Header(default="")):
    authorize(x_api_key)
    try:
        with connect() as connection:
            rows = connection.cursor().execute(
                "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' ORDER BY TABLE_SCHEMA, TABLE_NAME"
            ).fetchall()
            return [{"schema": r[0], "table": r[1]} for r in rows]
    except pyodbc.Error:
        raise HTTPException(503, "Database metadata unavailable")
