# اپ config — پیکربندی پروژه Django

## مسئولیت
- `settings.py`: متغیرهای محیطی، اپ‌های نصب‌شده، middleware، پایگاه داده، زبان، زمان و تنظیمات امنیتی.
- `urls.py`: اتصال URLهای اصلی به اپ‌ها و مسیرهای مدیریت.
- `wsgi.py` و `asgi.py`: نقاط ورود سرویس‌دهی برنامه.

## تنظیمات محیط
در محیط غیرتوسعه‌ای، تنظیمات fail-closed هستند: `DJANGO_SECRET_KEY`، `DJANGO_ALLOWED_HOSTS` و `DATABASE_URL` PostgreSQL باید مشخص شوند. در توسعه محلی، SQLite قابل استفاده است. جزئیات متغیرها در `docs/DEPLOYMENT.md` آمده است.

## امنیت
پیش از تغییر middleware ترتیب احراز هویت و RequirePasswordChange را بررسی کنید. تغییر `AUTH_USER_MODEL` پس از ایجاد دیتابیس عملیاتی تغییر پرریسکی است. تنظیمات SSL/HSTS باید با reverse proxy واقعی هماهنگ شود.

## تست‌های مهم
شروع برنامه با متغیرهای لازم/ناقص، محیط DEBUG و غیر DEBUG، اتصال PostgreSQL، مسیرهای URL و `check --deploy`.

## موارد باز
پیکربندی واقعی production، پایش، مدیریت secret، سیاست backup و استقرار سرویس‌دهنده باید توسط تیم عملیات تأیید شود.
