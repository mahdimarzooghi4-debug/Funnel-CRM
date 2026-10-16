# تصمیم فنی ۰۰۹: ماندگاری و migration پایگاه داده

- وضعیت: انتخاب‌شده برای پیاده‌سازی زیرساخت CRM
- دامنه: لایه‌ی ماندگاری پایگاه داده‌ی عملیاتی و نسخه‌بندی تغییرات schema

## تصمیم

- PostgreSQL پایگاه داده‌ی عملیاتی است؛ جداسازی tenant با RLS در بسته‌ی امنیتی بعدی پیاده می‌شود.
- مدل داده و دسترسی پایگاه داده با SQLAlchemy 2.x نوشته می‌شود.
- مسیرهای I/O پایگاه داده از API به‌صورت async و با dialect سازگار با asyncio اجرا می‌شوند.
- تغییرات schema با migrationهای نسخه‌دار Alembic اعمال می‌شوند؛ تغییر دستی schema در محیط‌ها مجاز نیست.
- آزمون‌های یکپارچه‌ی PostgreSQL با همان migrationهای نسخه‌دار اجرا می‌شوند.

## دلیل

SQLAlchemy مسیر رسمی asyncio و پشتیبانی از dialectهای async را فراهم می‌کند. Alembic ابزار migration متناظر با SQLAlchemy است و نسخه‌های schema را قابل‌بازتولید می‌کند. این انتخاب با API مبتنی بر ASGI و نیاز به کنترل کلیدهای خارجی ترکیبی برای tenant سازگار است.

## منابع رسمی

- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [SQLAlchemy constraints](https://docs.sqlalchemy.org/en/20/core/constraints.html)
- [Alembic](https://alembic.sqlalchemy.org/en/latest/)
