# راه‌اندازی و آزمون در Windows CMD

این راهنما برای Command Prompt است و به PowerShell وابسته نیست.

## 1. بررسی Python

از ریشه مخزن اجرا کنید:

```cmd
python --version
python -c "import sys; print(sys.executable)"
```

نسخه توصیه‌شده پروژه Python 3.12 است. اگر `python --version` نسخه دیگری نشان می‌دهد، از مسیر کامل فایل اجرایی Python 3.12 استفاده کنید؛ مسیر را از نصب واقعی سیستم خود بردارید و حدس نزنید.

## 2. ساخت محیط مجازی

اگر محیط مجازی قبلی با نسخه دیگری ساخته شده، ابتدا آن را نگه دارید و نامش را تغییر دهید؛ حذف نکنید:

```cmd
deactivate
ren .venv .venv-py313-backup
python -m venv .venv
.venv\Scripts\activate.bat
python --version
```

در این مرحله باید Python 3.12.x نمایش داده شود. اگر نسخه اشتباه است، ادامه ندهید و interpreter درست را انتخاب کنید.

## 3. نصب وابستگی‌ها و تنظیم توسعه

```cmd
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
copy /Y .env.local.example .env
python -m pip check
```

فایل `.env.local.example` فقط برای توسعه محلی و داده ساختگی است. آن را برای Production استفاده نکنید و فایل `.env` را commit نکنید.

## 4. بررسی‌های بدون تغییر داده

```cmd
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py showmigrations
```

اگر هر فرمان خطا داد، خروجی کامل را نگه دارید و قبل از اجرای migrate گزارش کنید. در این مرحله migration جدید تولید نکنید.

## 5. مهاجرت دیتابیس توسعه

فقط پس از تأیید برنامه مهاجرت و اطمینان از اینکه `.env` به دیتابیس محلی/آزمایشی اشاره می‌کند:

```cmd
python manage.py migrate
python manage.py migrate --check
python manage.py verify_database_schema
```

## 6. تست و داده ساختگی

```cmd
python manage.py test --verbosity 2
python manage.py seed_demo
python manage.py seed_operational_workflows
python manage.py audit_workflows
python manage.py runserver
```

حساب‌ها و رمزهای seed فقط برای داده ساختگی در محیط DEBUG هستند. هیچ داده واقعی کارکنان یا بیمه‌شدگان را وارد نکنید.

## 7. تشخیص خطاهای متداول CMD

- اگر `where` شناخته نشد، از مسیر کامل `C:\Windows\System32\where.exe` استفاده کنید.
- اگر `python` نسخه اشتباه را نشان داد، محیط مجازی را فعال و `python -c "import sys; print(sys.executable)"` را بررسی کنید.
- اگر GitHub روی پورت 443 در دسترس نبود، clone مجدد یا reset نکنید؛ وضعیت محلی را حفظ کنید و اتصال شبکه را جداگانه بررسی کنید.
- اگر `DJANGO_SECRET_KEY must be set` دریافت شد، فایل توسعه `.env.local.example` را به `.env` کپی کنید و بررسی کنید `DJANGO_DEBUG=True` باشد.
- اگر اسکریپت `final_preflight.cmd` PowerShell پیدا نکرد، خطا را دور نزنید؛ دستورات معادل بالا را دستی اجرا کنید و نتیجه هر مرحله را ثبت کنید.

## 8. هشدار

SQLite برای smoke test محلی است. آزمون هم‌زمانی، قفل ردیف‌ها، شماره‌گذاری و قیود حساس باید روی PostgreSQL در staging انجام شود. اجرای تست محلی یا موفقیت `check` به معنی مجوز Production نیست.
