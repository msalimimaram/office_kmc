# راهنمای راه‌اندازی و استقرار

## وضعیت

این راهنما برای آماده‌سازی محیط است؛ استقرار عملیاتی تا تکمیل کنترل‌های امنیتی، آزمون ارتقای دیتابیس و آزمون بازیابی تأییدشده محسوب نمی‌شود.

## پیش‌نیازها

- Python 3.11 یا 3.12
- SQLite برای smoke test محلی؛ PostgreSQL برای آزمون یکپارچه و محیط غیرتوسعه‌ای
- HTTPS termination در reverse proxy برای محیط عملیاتی
- فضای ذخیره‌سازی خصوصی برای فایل‌ها و برنامه پشتیبان‌گیری

## نصب توسعه‌ای Windows

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.local.example .env -Force
```

فایل .env.local.example به‌صورت پیش‌فرض SQLite را فعال می‌کند و برای اجرای اولیه به Docker نیاز ندارد. سپس:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py migrate
python manage.py test
python manage.py seed_demo
python manage.py runserver
```

برای جزئیات حساب‌های نمونه و سناریوهای پذیرش، docs/TESTING.md را ببینید.

## آزمون PostgreSQL محلی

```powershell
docker compose -f docker-compose.local.yml up -d db
```

در .env متغیر DATABASE_URL را فعال کنید:

```text
DATABASE_URL=postgresql://office_kmc:office_kmc@127.0.0.1:5432/office_kmc
```

پس از اجرای تست‌ها، سرویس را با docker compose -f docker-compose.local.yml down متوقف کنید. از این رمزهای محلی فقط برای Docker توسعه‌ای استفاده کنید.

## متغیرهای محیطی

- DJANGO_DEBUG: فقط True برای توسعه محلی؛ در تولید False.
- DJANGO_SECRET_KEY: راز تصادفی قوی و محرمانه.
- DJANGO_ALLOWED_HOSTS: فهرست میزبان‌های دقیق و مجاز، جداشده با کاما.
- DATABASE_URL: آدرس PostgreSQL در محیط غیرتوسعه‌ای.
- DB_SSLMODE: تنظیم TLS پایگاه داده متناسب با زیرساخت.
- REDIS_URL: cache مشترک الزامی برای محدودسازی ورود در محیط غیرتوسعه‌ای.
- DJANGO_SECURE_SSL_REDIRECT: در تولید معمولاً فعال؛ با reverse proxy هماهنگ شود.
- DJANGO_HSTS_SECONDS: فقط پس از اطمینان از HTTPS کامل، HSTS را فعال نگه دارید.
- DJANGO_HSTS_INCLUDE_SUBDOMAINS و DJANGO_HSTS_PRELOAD: فقط پس از بررسی تمام زیردامنه‌ها فعال شوند.
- DJANGO_SESSION_COOKIE_AGE: مهلت نشست برحسب ثانیه؛ پیش‌فرض ۱۸۰۰ ثانیه.

مقادیر واقعی را در secret manager محیط نگه دارید. .env نباید وارد Git شود. .env.local.example فقط برای توسعه محلی است و .env.example نمونه تنظیمات تولید است.

## Migrationها — مرحله اجباری

تمام migrationهای موجود در شاخه باید از Git دریافت شوند. در چرخه تست اولیه، migration جدید تولید نکنید. ابتدا این دستورها را اجرا کنید:

```powershell
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py migrate
python manage.py migrate --check
```

اگر Django تغییر مدل بدون migration گزارش کرد یا migration conflict نشان داد، پیش از ادامه آن را به‌عنوان مانع انتشار بررسی کنید. هرگز migration تولیدی را بدون backup و بررسی روی داده واقعی اجرا نکنید.

## بررسی پیش از انتشار

```powershell
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py migrate --check
python manage.py test
```

check --deploy باید با تنظیمات تولید واقعی اجرا شود. هشدارها را مستند و رفع یا با دلیل پذیرفته کنید.

## عملیات تولید

- اجرای برنامه با WSGI/ASGI server مناسب؛ از runserver برای تولید استفاده نکنید.
- سرو فایل static از مسیر استاندارد و عدم انتشار مستقیم private_media.
- محدودسازی دسترسی شبکه به پایگاه داده، پنل مدیریت و فضای فایل.
- پایش خطا، ظرفیت دیسک، پایگاه داده و انقضای گواهی TLS.
- پشتیبان‌گیری رمزگذاری‌شده و آزمون بازیابی منظم.
- ثبت نسخه commit و روش rollback در هر انتشار.
- مدیریت نگهداری داده مطابق سیاست مصوب سازمان.

## Rollback

rollback کد لزوماً rollback ایمن schema نیست؛ روش بازگشت پایگاه داده باید جداگانه طراحی و آزمایش شود. پیش از migrationهای مخرب backup معتبر تهیه کنید.
