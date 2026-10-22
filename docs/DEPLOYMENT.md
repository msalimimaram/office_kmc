# راهنمای راه‌اندازی و استقرار

## وضعیت

این راهنما برای آماده‌سازی محیط است؛ استقرار عملیاتی تا ثبت migrationها، تکمیل کنترل‌های امنیتی و آزمون بازیابی تأییدشده محسوب نمی‌شود.

## پیش‌نیازها

- Python 3.11 یا 3.12 سازگار با CI
- PostgreSQL برای محیط غیرتوسعه‌ای
- HTTPS termination در reverse proxy
- فضای ذخیره‌سازی خصوصی برای فایل‌ها و برنامه پشتیبان‌گیری
- دسترسی محدود به محیط و متغیرهای محرمانه

## نصب توسعه‌ای Windows

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

در `.env` توسعه‌ای، `DJANGO_DEBUG=True` قرار دهید. سپس migrationها را تولید و بررسی کنید:

```powershell
python manage.py makemigrations accounts organizations insurance claims requests_portal tasks documents imports auditlog assets announcements correspondence
python manage.py migrate
python manage.py check
python manage.py test
python manage.py createsuperuser
python manage.py runserver
```

## متغیرهای محیطی

- `DJANGO_DEBUG`: فقط `True` برای توسعه محلی؛ در تولید `False`.
- `DJANGO_SECRET_KEY`: راز تصادفی قوی و محرمانه.
- `DJANGO_ALLOWED_HOSTS`: فهرست میزبان‌های دقیق و مجاز، جداشده با کاما.
- `DATABASE_URL`: آدرس PostgreSQL در محیط غیرتوسعه‌ای.
- `DB_SSLMODE`: تنظیم TLS پایگاه داده متناسب با زیرساخت.
- `DJANGO_SECURE_SSL_REDIRECT`: در تولید معمولاً فعال؛ با reverse proxy درست هماهنگ شود.
- `DJANGO_HSTS_SECONDS`: فقط پس از اطمینان از HTTPS کامل، HSTS را فعال نگه دارید.
- `DJANGO_HSTS_INCLUDE_SUBDOMAINS` و `DJANGO_HSTS_PRELOAD`: به‌صورت پیش‌فرض خاموش‌اند؛ فقط پس از بررسی تمام زیردامنه‌ها و تصمیم آگاهانه مالک زیرساخت فعال شوند.
- `DJANGO_SESSION_COOKIE_AGE`: مهلت بی‌فعالیتی نشست برحسب ثانیه؛ پیش‌فرض ۱۸۰۰ ثانیه (۳۰ دقیقه). نشست با فعالیت تمدید می‌شود و با بستن مرورگر نیز منقضی می‌شود.

مقادیر واقعی را در secret manager محیط نگه دارید. `.env` نباید وارد Git شود. مقادیر `.env.example` نمونه‌اند و رمز واقعی نیستند.

## Migrationها — مرحله اجباری

مخزن فعلی فایل‌های migration اولیه را برای همه مدل‌ها به‌صورت کامل در Git ندارد. workflow CI می‌تواند برای ساخت دیتابیس آزمایشی migration تولید کند، اما این کار جای نسخه‌بندی migrationهای برنامه را نمی‌گیرد.

پیش از انتشار:
1. در محیط توسعه با نسخه پایتون/وابستگی سازگار `makemigrations` اجرا کنید.
2. فایل‌های تولیدشده را بازبینی کنید؛ تغییرات ناخواسته یا حذف داده را نپذیرید.
3. migrationها را commit کنید.
4. روی دیتابیس خالی `migrate` را اجرا کنید.
5. روی کپی امن از دیتابیس آزمایشیِ نسخه قبلی، مسیر ارتقا را بررسی کنید.
6. `python manage.py makemigrations --check --dry-run` و `python manage.py migrate --check` را اجرا کنید.

هرگز migration تولیدی را بدون بررسی روی داده واقعی اجرا نکنید.

## بررسی پیش از انتشار

```powershell
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py migrate --check
python manage.py test
```

بررسی `check --deploy` باید در محیطی اجرا شود که تنظیمات تولید واقعی را دارد. هشدارها را مستند و رفع یا با دلیل پذیرفته کنید.

## عملیات تولید

- اجرای برنامه با WSGI/ASGI server مناسب؛ از `runserver` برای تولید استفاده نکنید.
- سرو فایل static از مسیر استقرار استاندارد و عدم انتشار مستقیم `private_media`.
- محدودسازی دسترسی شبکه به پایگاه داده، پنل مدیریت و فضای فایل.
- پایش خطا، ظرفیت دیسک، پایگاه داده و انقضای گواهی TLS.
- پشتیبان‌گیری رمزگذاری‌شده و آزمون بازیابی منظم.
- ثبت نسخه commit و روش rollback در هر انتشار.
- مدیریت حذف/نگهداری داده مطابق سیاست مصوب سازمان.

## Rollback

برای هر انتشار، نسخه برنامه و migrationهای اجراشده را ثبت کنید. rollback کد لزوماً rollback ایمن schema نیست؛ روش بازگشت پایگاه داده باید جداگانه طراحی و آزمایش شود. پیش از migrationهای مخرب backup معتبر تهیه کنید.
