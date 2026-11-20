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

- [نقشه راه جامع تکمیل پروژه و معیارهای بستن هر فاز](docs/MASTER_COMPLETION_ROADMAP.md)
- [مشخصات محصول](PRODUCT_SPEC.md)
- [قواعد کسب‌وکار و گردش‌کارها](docs/BUSINESS_RULES_AND_WORKFLOWS.md)
- [ماتریس دسترسی](docs/ACCESS_CONTROL_MATRIX.md)
- [کاتالوگ چرخه‌های عملیاتی](docs/WORKFLOW_CATALOG.md)
- [طرح معماری و مهاجرت چندنقشی](docs/MULTI_ROLE_IMPLEMENTATION_PLAN.md)
- [سند جامع زنده و ممیزی اجزای پروژه](docs/PROJECT_MASTER.md)
- [فهرست سایر مستندات](docs/README.md)
- [چک‌لیست اولویت‌دار فاز صفر: تثبیت خط مبنا و آمادگی پذیرش](docs/PHASE0_BASELINE_CHECKLIST.md)

**قاعده راهبری:** نقشه راه جامع تکمیل پروژه مرجع ترتیب اجرا و معیار خروج فازهاست. در هر زمان فقط یک فاز فعال می‌شود؛ فاز پس از PASS شدن معیارهای خروج بسته خواهد شد. قابلیت‌های خارج از دامنه به backlog منتقل می‌شوند و باعث باز ماندن فاز نمی‌شوند.

قواعد تأییدشده در اسناد کسب‌وکار و ماتریس دسترسی، مرجع طراحی محصول هستند. کد فعلی در همه بخش‌ها هنوز با این مدل هدف هم‌راستا نشده است.

## نمای کلی فنی

- **فناوری:** Python، Django، Django ORM و قالب‌های سمت سرور؛ رابط فارسی/RTL و CSS واکنش‌گرا.
- **پایگاه داده:** SQLite برای توسعه محلی؛ PostgreSQL برای محیط غیرتوسعه‌ای.
- **هویت و دسترسی هدف:** یک شخص با کد ملی یکتای سراسری، چند انتصاب زمان‌دار، محدوده شرکت و رشته، و مجوزهای متمرکز.
- **ساختار برنامه فعلی:** ۱۵ اپ عملیاتی و زیرساختی شامل accounts, organizations, insurance, claims, requests_portal, tasks, documents, imports, auditlog, assets, announcements, correspondence, dashboard, workflow و core.
- **استقرار هدف:** زیرساخت داخلی سازمان، پشت HTTPS و با پایگاه داده و فضای فایل خصوصی.

## شروع سریع در Windows PowerShell

راهنمای کامل کاربران Command Prompt ویندوز: [راه‌اندازی و آزمون با CMD](docs/WINDOWS_CMD_SETUP.md).

پیش‌نیاز: Python 3.11 یا 3.12 و pip. فایل `.env.local.example` برای اجرای محلی با SQLite آماده شده است؛ `.env.example` فقط نمونه تنظیمات تولید است.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.local.example .env -Force
```

برای توسعه محلی، در فایل `.env` مقدار `DJANGO_DEBUG=True` را فقط روی دستگاه توسعه قرار دهید. سپس:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py migrate
python manage.py test
python manage.py runserver
```

**ساخت داده نمایشی فقط پس از سبز شدن کل تست‌ها و روی یک دیتابیس محلیِ تازه و دورریختنی مجاز است.** فرمان `seed_demo` فقط در `DEBUG=True` اجرا می‌شود و متغیر محیطی `DEMO_SEED_PASSWORD` را برای حساب‌های تازه‌ساخته‌شده لازم دارد. این فرمان یک‌باره است و قبل از شروع، خالی‌بودن همه جدول‌های داده‌ای برنامه (به‌جز جدول‌های زیرساختی خود Django) را کنترل می‌کند. اگر حتی یک جدول کاربردی داده داشته باشد، یا fixture موجود فاقد فهرست راستی‌آزمایی کامل باشد، یا حساب موجود فاقد رمز قابل استفاده دیده شود، فرمان با rollback متوقف می‌شود. حساب، پرونده، سند، تخصیص یا داده موجود هرگز با seed تکمیل، اصلاح یا بازنشانی نمی‌شود. برای ساخت مجدد سناریوی نمایشی، دیتابیس آزمایشی تازه بسازید؛ seed را روی دیتابیس حاوی داده‌ای که باید حفظ شود اجرا نکنید. در PowerShell:

```powershell
$secure = Read-Host "Enter a new demo password" -AsSecureString
$env:DEMO_SEED_PASSWORD = [System.Net.NetworkCredential]::new("", $secure).Password
Remove-Variable secure
python manage.py seed_demo
Remove-Item Env:DEMO_SEED_PASSWORD
```

فرمان داده ساختگی مرتبط و گردش‌کارهای پایه را ایجاد می‌کند؛ اجرای جداگانه `seed_operational_workflows` پس از آن لازم نیست. اجرای عادی `scripts/final_preflight.ps1` به‌صورت پیش‌فرض seed را اجرا نمی‌کند؛ فقط گزینه صریح `-SeedDemo` در اجرای محلی و روی دیتابیس تازه، آن را پس از موفقیت تست‌ها اجرا می‌کند. برای ممیزی اولیه فاز صفر بدون اعمال migration روی دیتابیس توسعه، گزینه `-NoMigrate` را به اسکریپت بدهید؛ جزئیات در `docs/TESTING.md` است.
