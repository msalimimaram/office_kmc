# Office KMC — Insurance Operations

Office KMC is a Django project for internal insurance-office workflows. It is intended to become a multi-organization operational portal for insured employees, subsidiary-company representatives, insurer representatives and the insurance department.

**Built with:** Python, Django, Django ORM and server-rendered Persian RTL templates. SQLite is used for local development; PostgreSQL is the intended production database.

**Status:** Under development. Use synthetic data only until the access-control redesign, migrations, security controls, backup/restore process and acceptance tests are completed. The approved business rules describe the target system and do not imply every target capability is already implemented.

**[View the source code and technical notes](https://github.com/msalimimaram/office_kmc)**

---

# اداره بیمه | پورتال عملیاتی مدیریت بیمه

سامانه وب فارسی و راست‌چین برای مدیریت کارکنان و بیمه‌شدگان، قراردادها و بیمه‌نامه‌ها، پوشش‌ها، خسارت‌ها، درخواست‌ها، دارایی‌ها، مکاتبات، اسناد، ارجاع‌ها، SLA و گزارش‌های مدیریتی. این پروژه مستقل از هر سامانه دیگری است.

> **وضعیت انتشار:** در حال توسعه و مناسب بررسی کنترل‌شده با داده ساختگی است. تا تکمیل بازطراحی هویت و مجوزهای چندنقشی، مهاجرت‌ها، امنیت فایل‌ها و آزمون‌های پذیرش، برای داده واقعی کارکنان یا بیمه‌شدگان استفاده نشود.

## اسناد مرجع

- [مشخصات محصول](PRODUCT_SPEC.md)
- [قواعد کسب‌وکار و گردش‌کارها](docs/BUSINESS_RULES_AND_WORKFLOWS.md)
- [ماتریس دسترسی](docs/ACCESS_CONTROL_MATRIX.md)
- [کاتالوگ چرخه‌های عملیاتی](docs/WORKFLOW_CATALOG.md)
- [طرح معماری و مهاجرت چندنقشی](docs/MULTI_ROLE_IMPLEMENTATION_PLAN.md)
- [فهرست سایر مستندات](docs/README.md)

قواعد تأییدشده در اسناد کسب‌وکار و ماتریس دسترسی، مرجع طراحی محصول هستند. کد فعلی در همه بخش‌ها هنوز با این مدل هدف هم‌راستا نشده است.

## نمای کلی فنی

- **فناوری:** Python، Django، Django ORM و قالب‌های سمت سرور؛ رابط فارسی/RTL و CSS واکنش‌گرا.
- **پایگاه داده:** SQLite برای توسعه محلی؛ PostgreSQL برای محیط غیرتوسعه‌ای.
- **هویت و دسترسی هدف:** یک شخص با کد ملی یکتای سراسری، چند انتصاب زمان‌دار، محدوده شرکت و رشته، و مجوزهای متمرکز.
- **ساختار برنامه فعلی:** ماژول‌های accounts, organizations, insurance, claims, requests_portal, tasks, documents, imports, auditlog, assets, announcements, correspondence, dashboard و core.
- **استقرار هدف:** زیرساخت داخلی سازمان، پشت HTTPS و با پایگاه داده و فضای فایل خصوصی.

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
python manage.py migrate
python manage.py check
python manage.py test
python manage.py createsuperuser
python manage.py runserver
```

از داده ساختگی استفاده کنید. پیش از تولید migration جدید، وضعیت migrationها را بررسی و فایل‌های migration را بازبینی و نسخه‌بندی کنید.

## تنظیمات محیط

متغیرهای اصلی در `.env.example` آمده‌اند. در محیط غیرتوسعه‌ای، `DJANGO_DEBUG=False`، کلید محرمانه قوی، میزبان‌های مجاز صریح و `DATABASE_URL` معتبر PostgreSQL الزامی است. متغیرهای واقعی محیط بر مقادیر فایل محلی اولویت دارند. فایل `.env` را commit نکنید.

راهنماها: [پیکربندی و استقرار](docs/DEPLOYMENT.md)، [معماری](docs/ARCHITECTURE.md)، [آزمون](docs/TESTING.md)، [بازبینی امنیتی](docs/SECURITY_REVIEW.md)، [چک‌لیست انتشار](docs/RELEASE_CHECKLIST.md)، [مشارکت در توسعه](CONTRIBUTING.md)، [گزارش تغییرات](CHANGELOG.md)، [سیاست امنیت](SECURITY.md).

## ورود Excel

هدف محصول، قالب‌های Excel تعریف‌پذیر و نسخه‌دار است. مدیر سامانه فیلدهای اصلی و گزینه‌ها را تعریف می‌کند؛ کارشناس رشته قالب و ترتیب ستون‌ها را مشخص می‌کند؛ سیستم نمونه Excel تولید می‌کند؛ و پیش‌نمایش، اعتبارسنجی ردیف/ستون و تصمیم‌های ثبت/نادیده‌گرفتن/ادغام/جایگزینی قبل از اعمال نهایی انجام می‌شود. مستندات محصول، مرجع رفتار هدف هستند؛ پیاده‌سازی موجود هنوز لزوماً این چرخه کامل را فراهم نمی‌کند.

## داده پزشکی و اسناد محرمانه

در محصول هدف، بعضی فایل‌های پزشکی در موارد لازم ذخیره می‌شوند؛ دسترسی به اصل آن‌ها فقط برای رئیس اداره بیمه و مدیر سامانه مجاز است. گیرنده ارجاع فقط اطلاعات حداقلی موردنیاز را می‌بیند. تمام فایل‌ها باید خصوصی باشند و مشاهده، دانلود، چاپ و خروجی آن‌ها جداگانه مجوزدهی و ممیزی شود.

## وضعیت آمادگی

موفقیت یک تست یا بررسی ایستا به معنی آماده بودن محصول برای داده واقعی نیست. قبل از بهره‌برداری:
1. مدل چندنقشی و انتصاب‌های زمان‌دار پیاده‌سازی و داده‌ها با مسیر مهاجرت امن منتقل شوند.
2. تمام viewها، فرم‌ها، داشبوردها، پنل مدیریت، فایل‌ها و خروجی‌ها از سیاست مرکزی دسترسی استفاده کنند.
3. احراز هویت چندمرحله‌ای، محدودسازی تلاش ورود و بازیابی امن حساب تکمیل و آزمایش شوند.
4. اسکن بدافزار، ذخیره‌سازی خصوصی، نسخه‌بندی و سیاست نگهداری فایل‌ها پیاده‌سازی شوند.
5. قرارداد/بیمه‌نامه، پوشش، خسارت، پرداخت مرحله‌ای و گردش‌های تأیید کامل شوند.
6. گردش‌کار نسخه‌دار، ثبت رویدادهای زمانی، تقویم شمسی و SLA غیرقابل توقف پیاده‌سازی شوند.
7. آزمون مهاجرت روی پایگاه داده خالی و نسخه دارای داده، آزمون دسترسی منفی، هم‌زمانی، بار، backup و restore اجرا شود.

سامانه پرداخت بانکی انجام نمی‌دهد. مبالغ پرداخت‌شده فقط به‌عنوان اطلاعات اعلام‌شده از منبع معتبر ثبت می‌شوند.
