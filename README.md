# Reporter Assistant — Phase 1

دستیار گزارش‌ساز سازمانی، نسخه آزمایشی اتصال و شناسایی ساختار SQL Server.

## پیش‌نیازها
- Python 3.11+
- Microsoft ODBC Driver 18 for SQL Server
- SQL Server read-only account
- SQL Server TLS certificate trusted by application host

## راه‌اندازی در Windows PowerShell
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python run.py
```

در `.env` مقادیر واقعی اتصال و یک APP_API_KEY تصادفی طولانی را وارد کنید. فایل `.env` را هرگز commit نکنید.

Swagger: http://127.0.0.1:8000/docs

برای endpointهای محافظت‌شده هدر `x-api-key` را ارسال کنید.

## Endpoints
- `GET /health`
- `GET /api/db/test`
- `GET /api/schema/tables?schema=SLS3`
- `GET /api/schema/columns?schema=SLS3&table=InvoiceItem`
- `GET /api/schema/relationships?schema=SLS3`

## Security
- نسخه فعلی فقط به localhost گوش می‌دهد؛ برای استفاده سازمانی پشت reverse proxy با HTTPS و احراز هویت قرار دهید.
- هیچ endpoint اجرای SQL دلخواه وجود ندارد.
- ApplicationIntent=ReadOnly جایگزین مجوزهای فقط خواندنی SQL Server نیست.
- مشاهده metadata تابع مجوزهای SQL Server است؛ VIEW DEFINITION را تنها در صورت نیاز اعطا کنید.
- پیش از تولید: rate limiting، audit logging، user authorization، secret management و محدودسازی schemaها لازم است.

## Roadmap
1. اتصال و metadata (این فاز)
2. Semantic layer و تعاریف شاخص‌های فروش
3. موتور پرسش فارسی به SQL کنترل‌شده
4. جدول، نمودار و خروجی Excel/PDF
