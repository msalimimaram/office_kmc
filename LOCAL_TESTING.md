# راهنمای تست محلی

این پروژه برای تست محلی با PostgreSQL طراحی شده است.

## 1) دریافت و آماده‌سازی

```bash
git clone https://github.com/msalimimaram/office_kmc.git
cd office_kmc
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.local.example .env
```

## 2) اجرای PostgreSQL محلی

در صورت استفاده از Docker:

```bash
docker compose -f docker-compose.local.yml up -d db
```

اگر PostgreSQL محلی دیگری دارید، فقط `DATABASE_URL` داخل `.env` را متناسب با آن تنظیم کنید.

## 3) بررسی Django و دیتابیس

```bash
python manage.py check
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py migrate
python manage.py showmigrations
python manage.py collectstatic --noinput
```

`check --deploy` در محیط local ممکن است به دلیل HTTP/HTTPS و تنظیمات امنیتی چند هشدار داشته باشد؛ معیار اصلی برای شروع تست محلی، نبودن خطای واقعی در `check` و موفق بودن migrationها است.

## 4) ایجاد داده نمونه

```bash
python manage.py seed_demo
```

داده نمونه فقط در `DEBUG=True` ایجاد می‌شود و کاربران نمونه رمز قابل استفاده ندارند.

برای تعیین رمز محلی برای یک کاربر:

```bash
python manage.py shell
```

سپس:

```python
from accounts.models import User
u = User.objects.get(username="employee.a")
u.set_password("یک-رمز-محلی-حداقل-۱۲-کاراکتری")
u.must_change_password = False
u.save()
```

همین کار را برای حساب‌های دیگر نمونه انجام دهید.

## 5) اجرای تست‌ها

```bash
python manage.py test
```

در صورت مشاهده خطا، خروجی کامل traceback را ارسال کنید.

## 6) اجرای برنامه

```bash
python manage.py runserver
```

سپس:

```text
http://127.0.0.1:8000/
```

## 7) سناریوی تست اجباری

### مدیر سامانه
- ورود
- مشاهده داشبورد مدیریتی
- مشاهده KPIها
- مشاهده شرکت‌ها
- مشاهده بیمه‌شده‌ها
- مشاهده خسارت‌ها
- مشاهده درخواست‌ها
- مشاهده اطلاعات محرمانه

### رئیس اداره
- ورود
- بررسی KPIها
- مشاهده backlog
- بررسی درخواست محرمانه
- تغییر وضعیت درخواست
- بررسی گزارش‌ها

### کارشناس اداره
- مشاهده درخواست‌های غیرمحرمانه مجاز
- Claim کردن یک درخواست
- تغییر وضعیت‌های مجاز
- تلاش برای تأیید/رد و اطمینان از رد شدن عملیات غیرمجاز
- اطمینان از عدم مشاهده درخواست محرمانه پزشکی

### نماینده شرکت
- مشاهده فقط داده‌های شرکت خودش
- مشاهده خسارت‌های شرکت خودش
- ایجاد درخواست
- تلاش برای مشاهده رکورد شرکت دیگر و اطمینان از خطای دسترسی

### بیمه‌شده
- مشاهده فقط اطلاعات خودش و افراد تحت تکفل
- مشاهده خسارت‌های خودش
- ثبت درخواست
- مشاهده وضعیت درخواست
- تلاش برای مشاهده رکورد بیمه‌شده دیگر و اطمینان از عدم دسترسی

### بیمه‌گر
- مشاهده فقط خسارت‌های بیمه‌گر خودش
- تلاش برای مشاهده خسارت بیمه‌گر دیگر و اطمینان از عدم دسترسی

## 8) تست IDOR

برای هر صفحه دارای شناسه در URL، شناسه یک رکورد متعلق به کاربر/شرکت دیگر را به‌صورت دستی جایگزین کنید.

مواردی که باید بررسی شوند:

- Claim detail
- Service request detail
- Document download
- Import records
- Company/person detail
- هر endpoint تغییردهنده داده

نتیجه مورد انتظار: `403` یا `404` متناسب با سیاست endpoint؛ هرگز نباید اطلاعات رکورد دیگر نمایش داده شود.

## 9) تست فایل خصوصی

- یک فایل مجاز بارگذاری کنید.
- از طریق UI آن را دریافت کنید.
- سپس با کاربر فاقد دسترسی، همان فایل را دریافت کنید.
- دسترسی مستقیم به مسیر `private_media` نباید بدون authorization امکان‌پذیر باشد.

## 10) تست import

- فایل معتبر
- فایل با header اشتباه
- ردیف تکراری
- مبلغ منفی
- تاریخ نامعتبر
- فایل بزرگ
- فایل با پسوند مجاز ولی محتوای نامعتبر
- تأیید import
- اطمینان از عدم ثبت بخشی در صورت شکست transaction

## 11) قبل از ورود داده واقعی

تا زمانی که این موارد تأیید نشده‌اند، داده واقعی وارد نکنید:

- `migrate` موفق است.
- `test` موفق است.
- سناریوهای role/scope موفق‌اند.
- فایل خصوصی واقعاً private است.
- backup/restore آزمایش شده است.
- HTTPS و secretهای Production تنظیم شده‌اند.
- MFA واقعی برای حساب‌های حساس فعال شده است.
