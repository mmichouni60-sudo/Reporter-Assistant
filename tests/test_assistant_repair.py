"""Tests for single-attempt SQL repair; no API or database calls."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from app.assistant_engine import validate_or_repair_sql

BASE = (
    "SELECT p.Product_Code, SUM(f.Net_Price) AS Net_Sales "
    "FROM sale.Fact_Invoice AS f "
    "JOIN sale.Dim_Date AS d ON f.Creation_Date_ID = d.MiladiDateKey "
    "JOIN sale.Dim_Product AS p ON f.Product_ID = p.Product_ID_BK "
    "WHERE d.jyear = '1405' AND f.Invoice_Status IN (2, 11) "
    "GROUP BY p.Company_ID, p.Product_ID, p.Product_Code "
    "ORDER BY Net_Sales DESC"
)
INVALID = BASE.replace("SUM(f.Net_Price)", "SUM(f.Invoice_QTY)")
VALID = BASE


def fake_client(repaired_sql):
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(
        output_text=json.dumps({
            "sql": repaired_sql, "title": "Test", "chart": "table", "clarification": ""
        })
    )
    return client


class RepairTests(unittest.TestCase):
    def test_valid_sql_never_calls_model_again(self):
        client = fake_client(VALID)
        sql, repaired = validate_or_repair_sql({"sql": VALID}, "۱۰ کالای پرفروش سال ۱۴۰۵", client)
        self.assertFalse(repaired)
        self.assertIn("TOP 10", sql.upper().replace("(", "").replace(")", ""))
        client.responses.create.assert_not_called()

    def test_invalid_sql_repaired_once(self):
        client = fake_client(VALID)
        sql, repaired = validate_or_repair_sql({"sql": INVALID}, "۱۰ کالای پرفروش سال ۱۴۰۵", client)
        self.assertTrue(repaired)
        self.assertIsNotNone(sql)
        client.responses.create.assert_called_once()

    def test_invalid_repair_is_rejected(self):
        client = fake_client(INVALID)
        sql, repaired = validate_or_repair_sql({"sql": INVALID}, "۱۰ کالای پرفروش سال ۱۴۰۵", client)
        self.assertIsNone(sql)
        self.assertFalse(repaired)
        client.responses.create.assert_called_once()

    def test_repair_api_error_is_rejected(self):
        client = fake_client(VALID)
        client.responses.create.side_effect = RuntimeError("network error")
        sql, repaired = validate_or_repair_sql({"sql": INVALID}, "۱۰ کالای پرفروش سال ۱۴۰۵", client)
        self.assertIsNone(sql)
        self.assertFalse(repaired)
        client.responses.create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
