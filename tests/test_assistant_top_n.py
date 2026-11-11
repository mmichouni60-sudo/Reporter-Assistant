"""Regression checks for explicit top-N limits and commercial product grouping."""
import unittest
from app.assistant_engine import requested_top_n, validate_sql

SQL = (
    "SELECT p.Product_Code, p.Product_Name, "
    "SUM(CASE WHEN f.Is_Return = 0 THEN f.Net_Price ELSE -f.Net_Price END) AS Net_Sales "
    "FROM sale.Fact_Invoice AS f "
    "JOIN sale.Dim_Date AS d ON f.Creation_Date_ID = d.MiladiDateKey "
    "JOIN sale.Dim_Product AS p ON f.Product_ID = p.Product_ID_BK "
    "WHERE d.jyear = '1405' AND f.Invoice_Status IN (2, 11) "
    "GROUP BY p.Company_ID, p.Product_ID, p.Product_Code, p.Product_Name "
    "ORDER BY Net_Sales DESC"
)


class TopNTests(unittest.TestCase):
    def test_persian_digits(self):
        self.assertEqual(requested_top_n("۱۰ کالای پرفروش سال ۱۴۰۵"), 10)

    def test_ascii_digits(self):
        self.assertEqual(requested_top_n("20 کالای پرفروش سال 1405"), 20)

    def test_year_alone_is_not_limit(self):
        self.assertIsNone(requested_top_n("فروش خالص سال ۱۴۰۵"))

    def test_top_limit_is_enforced(self):
        result = validate_sql(SQL, top_n=10)
        self.assertIn("TOP 10", result.upper().replace("(", "").replace(")", ""))

    def test_default_limit(self):
        result = validate_sql(SQL)
        self.assertIn("TOP 200", result.upper().replace("(", "").replace(")", ""))

    def test_mixed_unit_quantity_rejected(self):
        sql = SQL.replace(
            " AS Net_Sales ",
            " AS Net_Sales, SUM(f.Invoice_QTY) AS Net_QTY "
        )
        with self.assertRaisesRegex(ValueError, "Product_Unit"):
            validate_sql(sql, top_n=10)

    def test_unit_grouped_quantity_allowed(self):
        sql = SQL.replace(
            " AS Net_Sales ",
            " AS Net_Sales, SUM(f.Invoice_QTY) AS Net_QTY "
        ).replace(
            "p.Product_Name ORDER BY",
            "p.Product_Name, p.Product_Unit ORDER BY"
        )
        result = validate_sql(sql, top_n=10)
        self.assertIn("Product_Unit", result)

    def test_invalid_limit_rejected(self):
        with self.assertRaises(ValueError):
            validate_sql(SQL, top_n=201)


if __name__ == "__main__":
    unittest.main()
