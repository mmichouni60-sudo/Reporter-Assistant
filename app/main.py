import os
import pyodbc
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from app.assistant_engine import ask as ask_ai
from app.schema_catalog import discover as discover_schema
from decimal import Decimal
from pathlib import Path
from fastapi.responses import FileResponse

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
        + ";Encrypt=yes;TrustServerCertificate=" + ("yes" if os.getenv("DB_TRUST_SERVER_CERTIFICATE", "no").lower() in ("yes", "true", "1") else "no") + ";ApplicationIntent=ReadOnly",
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

@app.get("/api/reports/sales/monthly")
def monthly_sales(year: int = Query(..., ge=1300, le=1600), x_api_key: str = Header(default="")):
    """Monthly confirmed sales in IRR, using the Persian calendar."""
    authorize(x_api_key)
    sql = """
    SELECT d.jyear, d.jmonthN,
           SUM(CASE WHEN f.Is_Return=0 THEN ISNULL(f.Net_Price,0) ELSE 0 END) AS Gross_Sales,
           SUM(CASE WHEN f.Is_Return=1 THEN ISNULL(f.Net_Price,0) ELSE 0 END) AS Return_Amount,
           SUM(CASE WHEN f.Is_Return=0 THEN ISNULL(f.Net_Price,0)
                    WHEN f.Is_Return=1 THEN -ISNULL(f.Net_Price,0) ELSE 0 END) AS Net_Sales,
           SUM(CASE WHEN f.Is_Return=0 THEN ISNULL(f.Invoice_QTY,0)
                    WHEN f.Is_Return=1 THEN -ISNULL(f.Invoice_QTY,0) ELSE 0 END) AS Net_Qty
    FROM sale.Fact_Invoice AS f
    INNER JOIN sale.Dim_Date AS d ON f.Creation_Date_ID=d.MiladiDateKey
    WHERE d.jyear=? AND f.Invoice_Status IN (2,11)
    GROUP BY d.jyear,d.jmonthN
    ORDER BY d.jyear,d.jmonthN
    """
    try:
        with connect() as connection:
            rows = connection.cursor().execute(sql, year).fetchall()
            return {
                "year": year,
                "currency": "IRR",
                "months": [
                    {"year": int(r[0]), "month": int(r[1]),
                     "gross_sales": str(r[2] or Decimal(0)),
                     "return_amount": str(r[3] or Decimal(0)),
                     "net_sales": str(r[4] or Decimal(0)),
                     "net_qty": str(r[5] or Decimal(0))}
                    for r in rows
                ]
            }
    except pyodbc.Error:
        raise HTTPException(503, "Sales report unavailable")

@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(Path(__file__).with_name("dashboard.html"), media_type="text/html")

class AssistantQuestion(BaseModel):
    question: str = Field(min_length=5, max_length=1000)

@app.post("/api/assistant/ask")
def assistant_ask(payload: AssistantQuestion, x_api_key: str = Header(default="")):
    authorize(x_api_key)
    return ask_ai(payload.question, connect)

@app.get("/api/schema/catalog")
def schema_catalog(schema: str | None = Query(default=None, min_length=1, max_length=128),
                   x_api_key: str = Header(default="")):
    """Read-only table/column/FK discovery; no business rows."""
    authorize(x_api_key)
    return discover_schema(connect, schema)
