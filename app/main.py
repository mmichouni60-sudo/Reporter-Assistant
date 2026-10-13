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

@app.get("/api/schema/columns")
def columns(schema: str, table: str, x_api_key: str = Header(default="")):
    authorize(x_api_key)
    sql = """SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
             FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA=? AND TABLE_NAME=?
             ORDER BY ORDINAL_POSITION"""
    try:
        with connect() as connection:
            rows = connection.cursor().execute(sql, schema, table).fetchall()
            return [{"name": r[0], "type": r[1], "nullable": r[2] == "YES"} for r in rows]
    except pyodbc.Error:
        raise HTTPException(503, "Database metadata unavailable")

@app.get("/api/schema/relationships")
def relationships(x_api_key: str = Header(default="")):
    authorize(x_api_key)
    sql = """SELECT fk.name, ps.name, pt.name, pc.name, rs.name, rt.name, rc.name
             FROM sys.foreign_key_columns fkc
             JOIN sys.foreign_keys fk ON fk.object_id=fkc.constraint_object_id
             JOIN sys.tables pt ON pt.object_id=fkc.parent_object_id
             JOIN sys.schemas ps ON ps.schema_id=pt.schema_id
             JOIN sys.columns pc ON pc.object_id=pt.object_id AND pc.column_id=fkc.parent_column_id
             JOIN sys.tables rt ON rt.object_id=fkc.referenced_object_id
             JOIN sys.schemas rs ON rs.schema_id=rt.schema_id
             JOIN sys.columns rc ON rc.object_id=rt.object_id AND rc.column_id=fkc.referenced_column_id"""
    try:
        with connect() as connection:
            rows = connection.cursor().execute(sql).fetchall()
            return [{"foreign_key": r[0],
                     "from": {"schema": r[1], "table": r[2], "column": r[3]},
                     "to": {"schema": r[4], "table": r[5], "column": r[6]}} for r in rows]
    except pyodbc.Error:
        raise HTTPException(503, "Database metadata unavailable")
