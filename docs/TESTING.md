# راهنمای آزمون محلی و پذیرش

این پروژه عمداً GitHub Actions ندارد. اجرای تست‌ها در این مرحله از روی سیستم توسعه‌دهنده انجام می‌شود.

## 1. آماده‌سازی محیط محلی Windows

از Python 3.11 یا 3.12 استفاده کنید. فایل .env.local.example برای اجرای سریع با SQLite آماده است و Docker لازم نیست.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.local.example .env -Force
```

اگر PowerShell اجرای اسکریپت فعال‌سازی را مسدود کرد، فقط برای پنجره فعلی اجرا کنید:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 2. بررسی کد و migrationها

ابتدا دستورهای بدون تغییر پایگاه داده را اجرا کنید:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py showmigrations
```

انتظار: check بدون خطای سیستمی تمام شود؛ makemigrations اعلام کند تغییر مدل بدون migration وجود ندارد؛ migrate --plan برنامه مهاجرت‌ها را نشان دهد. اگر هرکدام خطا داد، خروجی کامل را نگه دارید و قبل از ادامه گزارش کنید.

سپس روی دیتابیس محلی خالی:

```powershell
python manage.py migrate
python manage.py showmigrations
```

تمام migrationهای برنامه باید علامت [X] داشته باشند.

## 3. اجرای تست‌های خودکار

```powershell
python manage.py test
```

برای اجرای گروهی تست‌های مهم:

```powershell
python manage.py test accounts organizations claims requests_portal imports workflow correspondence assets documents tasks
```

در صورت شکست، خروجی کامل اولین خطا و traceback را ذخیره کنید. تا رفع خطاهای تست و migration، شاخه را در main ادغام نکنید.

## 4. ساخت داده ساختگی و اجرای سایت

```powershell
python manage.py seed_demo
python manage.py runserver
```

سپس نشانی http://127.0.0.1:8000/ را باز کنید.

رمز مشترک حساب‌های نمونه فقط در محیط توسعه: **DemoPass!2026**

| حساب | نقش | هدف آزمون |
|---|---|---|
| admin.demo | مدیر سامانه | تنظیمات و دسترسی سراسری |
| head.demo | رئیس اداره | مشاهده سراسری و نظارت |
| specialist.demo | کارشناس درمان | دسترسی تخصصی رشته درمان |
| companya.demo | نماینده شرکت الف | محدوده شرکت الف |
| companyb.demo | نماینده شرکت ب | محدوده شرکت ب |
| employee.a | بیمه‌شده شرکت الف | مشاهده و ثبت درخواست شخصی |
| employee.b | بیمه‌شده شرکت ب | جداسازی سوابق شرکت ب |
| insurer.demo | نماینده بیمه‌گر نمونه | ورود اطلاعات و دامنه بیمه‌گر |

این حساب‌ها فقط داده ساختگی دارند. برای آزمون پنل Django Admin با تمام مجوزهای پیش‌فرض، یک superuser جداگانه با دستور createsuperuser بسازید.

## 5. سناریوهای دستی پذیرش

1. با companya.demo وارد شوید و بررسی کنید داده‌های شرکت ب قابل مشاهده یا جست‌وجو نباشند.
2. با companyb.demo وارد شوید و همین آزمون را برای شرکت الف انجام دهید.
3. با employee.a وارد شوید و بررسی کنید سوابق و درخواست‌های کارمند دیگر نمایش داده نشود.
4. با specialist.demo دسترسی درمان را بررسی کنید؛ رشته‌های فاقد انتصاب نباید قابل دسترسی باشند.
5. با insurer.demo بررسی کنید اطلاعات بیمه‌گر دیگر قابل مشاهده یا ثبت نباشد.
6. درخواست محرمانه درمان را ایجاد/مشاهده کنید و دسترسی نماینده شرکت و کارشناس عادی را با دسترسی رئیس اداره مقایسه کنید.
7. در ورود Excel، فایل نامعتبر، تاریخ نامعتبر، مبلغ منفی و فایل دارای ستون اجباری ناقص را امتحان کنید.
8. در گردش کار، مشاهده، تأیید مشاهده، ارجاع با توضیح اجباری و اقدام غیرمجاز را بررسی کنید.
9. در پرداخت، ثبت قسط، تأیید مستقل و برگشت پرداخت را با داده ساختگی بررسی کنید.

## 6. آزمون PostgreSQL (پیشنهادی پیش از پذیرش نهایی)

SQLite برای smoke test محلی است. شماره‌گذاری هم‌زمان مکاتبات، قفل ردیف‌ها و برخی constraintها باید روی PostgreSQL هم بررسی شوند.

```powershell
docker compose -f docker-compose.local.yml up -d db
```

در فایل .env خط DATABASE_URL را فعال کنید:

```text
DATABASE_URL=postgresql://office_kmc:office_kmc@127.0.0.1:5432/office_kmc
```

سپس یک پایگاه داده تمیز بسازید و مراحل بخش 2 و 3 را دوباره اجرا کنید. بعد از اتمام:

```powershell
docker compose -f docker-compose.local.yml down
```

## 7. معیار خروج از تست محلی

- [ ] نصب وابستگی‌ها بدون خطا
- [ ] manage.py check بدون خطا
- [ ] نبود migration جاافتاده یا conflict حل‌نشده
- [ ] اجرای موفق migrationها روی دیتابیس خالی
- [ ] اجرای موفق کل تست‌ها
- [ ] اجرای موفق فرمان seed_demo
- [ ] ورود موفق حساب‌های نمونه
- [ ] جداسازی شرکت‌ها و رشته‌ها در آزمون دستی
- [ ] آزمون فایل‌های خصوصی و محرمانگی
- [ ] آزمون PostgreSQL و هم‌زمانی برای مسیرهای حساس

موفقیت تست محلی با داده ساختگی، مجوز استفاده از داده واقعی یا انتشار عملیاتی نیست. آزمون ارتقای دیتابیس موجود، امنیت فایل‌ها، backup/restore و آزمون بار باید جداگانه انجام شود.
