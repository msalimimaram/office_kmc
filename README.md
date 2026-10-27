# Office KMC — Insurance Operations Management

**Project summary (English):** A Django-based, Persian/RTL web application project for organizing insurance operations such as organizational records, policies, claims, requests, tasks, documents, bulk imports, and audit-related workflows.

**Technology:** Python · Django · Django ORM · Server-rendered templates · SQLite for local development · PostgreSQL as the intended non-development database.

**Current status:** Under development; intended for controlled evaluation with synthetic data only. Do not use real employee, customer, or insured-person data until the outstanding security, access-control, and deployment requirements have been completed and verified.

**Repository:** [Source code and technical documentation](https://github.com/msalimimaram/office_kmc)

---

# اداره بیمه | سامانه سازمانی مدیریت بیمه

سامانه وب فارسی و راست‌چین برای ثبت و پیگیری اطلاعات بیمه‌ای، قراردادها، خسارت‌ها، درخواست‌ها، دارایی‌های بیمه‌شده و مکاتبات اداره بیمه. این پروژه مستقل از GAMva است.

> **وضعیت انتشار:** نسخه در حال توسعه و آماده بررسی کنترل‌شده با داده ساختگی است؛ تا تکمیل موارد امنیتی و استقرار، برای داده واقعی کارکنان یا بیمه‌شدگان استفاده نشود.

## نمای کلی

- **فناوری:** Python، Django، Django ORM و قالب‌های سمت سرور؛ رابط فارسی/RTL و CSS واکنش‌گرا.
- **پایگاه داده:** SQLite برای توسعه محلی؛ PostgreSQL برای استقرار غیرتوسعه‌ای.
- **هویت و دسترسی:** مدل کاربر سفارشی، نقش‌های سازمانی و فیلترهای محدوده داده در بخش‌هایی از برنامه.
- **آزمون و CI:** workflow گیت‌هاب برای بررسی سیستمی و اجرای تست‌ها در Python 3.11 و 3.12.
- **استقرار هدف:** زیرساخت داخلی سازمان، پشت HTTPS و با پایگاه داده و فضای فایل خصوصی.

## قابلیت‌ها و اپ‌ها

| اپ | مسئولیت اصلی | راهنمای فنی |
|---|---|---|
| `accounts` | کاربران، نقش‌ها، تغییر اجباری رمز | [راهنما](accounts/README.md) |
| `organizations` | شرکت‌ها، کارکنان و افراد تحت تکفل | [راهنما](organizations/README.md) |
| `insurance` | بیمه‌گران، رشته‌ها، قراردادها و اصلاحیه‌ها | [راهنما](insurance/README.md) |
| `claims` | ثبت و پیگیری خسارت و مبالغ اعلام‌شده | [راهنما](claims/README.md) |
| `requests_portal` | درخواست‌های بیمه‌شدگان و گردش وضعیت | [راهنما](requests_portal/README.md) |
| `tasks` | وظایف داخلی و مهلت‌ها | [راهنما](tasks/README.md) |
| `documents` | اسناد اداری و دسترسی به فایل‌ها | [راهنما](documents/README.md) |
| `imports` | عملیات ورود گروهی Excel | [راهنما](imports/README.md) |
| `auditlog` | رویدادهای حسابرسی | [راهنما](auditlog/README.md) |
| `assets` | دارایی‌های بیمه‌شده | [راهنما](assets/README.md) |
| `announcements` | اطلاعیه‌ها و بخشنامه‌ها | [راهنما](announcements/README.md) |
| `correspondence` | مکاتبات و پیگیری‌ها | [راهنما](correspondence/README.md) |
| `dashboard` | صفحه اصلی و نمای کلی | [راهنما](dashboard/README.md) |
| `core` | مجوزهای مشترک و اعتبارسنجی فایل | [راهنما](core/README.md) |
| `config` | تنظیمات، URLهای ریشه و نقاط ورود WSGI/ASGI | [راهنما](config/README.md) |

## شروع سریع در Windows PowerShell

پیش‌نیاز: Python 3.11 یا 3.12 و pip.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

برای توسعه محلی، در فایل `.env` مقدار `DJANGO_DEBUG=True` را فقط روی دستگاه توسعه قرار دهید. سپس:

```powershell
python manage.py makemigrations accounts organizations insurance claims requests_portal tasks documents imports auditlog assets announcements correspondence
python manage.py migrate
python manage.py check
python manage.py test
python manage.py createsuperuser
python manage.py runserver
```

برنامه محلی به‌صورت پیش‌فرض روی `http://127.0.0.1:8000/` در دسترس است. از داده ساختگی استفاده کنید.

## تنظیمات محیط

متغیرهای اصلی در `.env.example` آمده‌اند. در محیط غیرتوسعه‌ای، `DJANGO_DEBUG=False`، کلید محرمانه قوی، میزبان‌های مجاز صریح و `DATABASE_URL` معتبر PostgreSQL الزامی است. متغیرهای واقعی محیط بر مقادیر فایل محلی اولویت دارند. فایل `.env` را commit نکنید.

راهنمای کامل: [پیکربندی و استقرار](docs/DEPLOYMENT.md)، [معماری](docs/ARCHITECTURE.md)، [آزمون](docs/TESTING.md)، [بازبینی امنیتی](docs/SECURITY_REVIEW.md)، [چک‌لیست انتشار](docs/RELEASE_CHECKLIST.md)، [مشارکت در توسعه](CONTRIBUTING.md)، [گزارش تغییرات](CHANGELOG.md)، [سیاست امنیت](SECURITY.md) و [مشخصات محصول](PRODUCT_SPEC.md).

## قرارداد ورود Excel خسارت

سرستون‌های الزامی: `claim_number`، `national_id` و `service_type`. سرستون‌های اختیاری: `service_date`، `registered_date`، `requested_amount`، `assessed_amount`، `payable_amount`، `paid_amount` و `payment_date`. قالب تاریخ `YYYY-MM-DD` است. جزئیات و محدودیت‌های پردازش در [راهنمای imports](imports/README.md) آمده است.

## وضعیت آمادگی و محدودیت‌های شناخته‌شده

موفقیت CI به معنی تأیید کامل محصول، آزمون مرورگر موبایل یا ممیزی امنیتی نیست. قبل از بهره‌برداری عملیاتی:
1. migrationهای واقعی را تولید، بازبینی و commit کنید؛ CI نباید جایگزین migrationهای نسخه‌بندی‌شده شود.
2. مجوزهای تمام مسیرها، فایل‌ها، خروجی‌ها و پنل مدیریت را با حساب‌های هر نقش آزمایش کنید.
3. احراز هویت چندمرحله‌ای واقعی، محدودسازی تلاش ورود و بازیابی امن حساب را تکمیل کنید؛ فیلد `mfa_enabled` به‌تنهایی MFA نیست.
4. اسکن بدافزار، ذخیره‌سازی خصوصی و سیاست نگهداری فایل‌ها را پیاده‌سازی و آزمون کنید.
5. HTTPS، پایگاه داده پشتیبانی‌شده، پشتیبان رمزگذاری‌شده، بازیابی آزمایشی، پایش و آزمون بار را آماده کنید.
6. رابط را در عرض‌های 360، 390 و 430 پیکسل و مرورگرهای هدف بررسی کنید.
7. گردش‌کارها و ماتریس رسمی دسترسی را با مالک کسب‌وکار تأیید کنید.

سامانه پرداخت بانکی انجام نمی‌دهد. مبالغ پرداخت‌شده فقط به‌عنوان اطلاعات اعلام‌شده از منبع معتبر ثبت می‌شوند. تصویر مدارک پزشکی نباید بارگذاری شود.
