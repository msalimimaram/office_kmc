# راهنمای استقرار نسخه عملیاتی سامانه اداره بیمه

این پروژه باید قبل از ورود اطلاعات واقعی از محیط توسعه جدا شود. این runbook عمداً GitHub Actions را وارد فرآیند استقرار نمی‌کند.

## 1) ترتیب استقرار

1. PostgreSQL مستقل و دارای backup تهیه شود.
2. دامنه و TLS/HTTPS روی reverse proxy (مثلاً Nginx) تنظیم شود؛ نمونه پیکربندی در `deploy/nginx/office-kmc.conf.example` قرار دارد.
3. سرویس ClamAV در شبکه خصوصی برنامه نصب و به‌روزرسانی امضاهای آن زمان‌بندی شود؛ پورت TCP آن فقط از میزبان/کانتینر برنامه قابل دسترسی باشد. `CLAMD_HOST`، `CLAMD_PORT` و `CLAMD_TIMEOUT` در `.env` تنظیم شوند. برنامه در Production بدون `CLAMD_HOST` شروع نمی‌شود و در صورت قطع اسکنر، فایل جدید را fail-closed رد می‌کند.
4. متغیرهای `.env` واقعی روی سرور قرار گیرد؛ فایل secrets هرگز commit نشود.
5. `pip install -r requirements.txt` اجرا شود.
6. Migrationهای نسخه‌بندی‌شده موجود در مخزن را ابتدا روی دیتابیس خالی و یک کپی از داده آزمایشی بررسی کنید. `makemigrations --check --dry-run`، `migrate --plan` و `migrate` باید بدون اختلاف اجرا شوند؛ Migration جدید فقط پس از بررسی state مدل و تست upgrade ثبت شود.
7. `python manage.py migrate` اجرا شود.
8. `python manage.py collectstatic --noinput` اجرا شود.
9. `python manage.py check --deploy` و `python manage.py audit_workflows` اجرا شوند؛ هر دو باید بدون خطا باشند.
10. یک superuser اولیه ساخته، انتصاب معتبر `SYSTEM_ADMIN` یا `DEPARTMENT_HEAD` برای مسئول واقعی ایجاد، و رمز قوی و MFA واقعی برای حساب‌های privileged فعال شود.
11. پس از ایجاد انتصاب معتبر رئیس اداره/مدیر سامانه، `python manage.py seed_operational_workflows` اجرا شود؛ این فرمان گردش‌های پایه تأیید قرارداد، فسخ قرارداد، ارزیابی دارایی، دوره بیمه‌نامه دارایی، الحاقیه دارایی و اصلاح اطلاعات بیمه‌شده را به‌صورت نسخه‌دار منتشر می‌کند. پس از آن باید انتصاب‌های معتبر و محدود به شرکت/رشته برای نمایندگان شرکت و انتصاب‌های محدود به بیمه‌گر/رشته برای کارشناسان بیمه‌گر ایجاد شوند. گردش‌های عمومی درخواست‌ها و اعتراض‌ها همچنان باید مطابق ماتریس مصوب کسب‌وکار پیکربندی شوند.
12. Gunicorn با نمونه واحد systemd در `deploy/systemd/office-kmc.service.example` فقط روی `127.0.0.1` اجرا شود و پشت reverse proxy قرار گیرد.
13. مسیر `/private-media/` نباید در Nginx alias یا expose شود؛ نمونه پیکربندی آن را صریحاً رد می‌کند. دانلود فایل فقط از view دارای authorization انجام شود.
14. backup و restore آزمایشی قبل از go-live انجام شود.

## 2) حداقل متغیرهای محیط تولید

- `DJANGO_DEBUG=False`
- `DJANGO_SECRET_KEY` تصادفی و بلند
- `DJANGO_ALLOWED_HOSTS` فقط دامنه‌های واقعی
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://...`
- `DATABASE_URL` برای PostgreSQL
- `CLAMD_HOST`، `CLAMD_PORT` و `CLAMD_TIMEOUT` برای اسکنر ClamAV در شبکه خصوصی؛ بدون اسکنر، بارگذاری فایل در Production رد می‌شود.
- `DB_SSLMODE=require` در صورت پشتیبانی سرویس DB
- `DJANGO_SECURE_SSL_REDIRECT=True`
- `DJANGO_TRUST_PROXY_SSL_HEADER=True` فقط وقتی TLS در Nginx خاتمه می‌یابد و Nginx هدر `X-Forwarded-Proto` را خودش بازنویسی می‌کند؛ پورت Gunicorn باید از اینترنت قابل دسترسی نباشد.
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain` با scheme و دامنه واقعی.
- `SESSION_COOKIE_SECURE` و `CSRF_COOKIE_SECURE` در Production به‌صورت اجباری فعال‌اند.
- HSTS یک‌ساله پس از اطمینان از HTTPS کامل فعال بماند؛ `includeSubDomains` و `preload` فقط پس از بررسی همه زیردامنه‌ها.

## 3) معیار پذیرش قبل از ورود اولین بیمه‌شده

### داده و پایگاه‌داده
- [ ] migration از دیتابیس خالی بدون خطا
- [ ] migration روی snapshot/backup موجود بدون از دست رفتن داده
- [ ] indexهای لازم روی foreign key و فیلدهای جستجو بررسی شده
- [ ] backup روزانه و restore drill موفق

### دسترسی
- [ ] کاربر شرکت A نمی‌تواند داده شرکت B را با تغییر URL ببیند
- [ ] بیمه‌گر A نمی‌تواند خسارت بیمه‌گر B را ببیند
- [ ] بیمه‌شده فقط خودش و افراد تحت تکفل مجاز را می‌بیند
- [ ] درخواست محرمانه پزشکی برای کارشناس عادی قابل مشاهده نیست
- [ ] فایل خصوصی با URL مستقیم قابل دریافت نیست
- [ ] ClamAV در دسترس است؛ فایل پاک پذیرفته و فایل آزمایشی EICAR رد می‌شود؛ قطع سرویس اسکنر نیز باعث رد upload می‌شود
- [ ] تغییر شبا/اطلاعات حساس بدون workflow تأیید نهایی نمی‌شود

### عملیات
- [ ] import اکسل duplicate-safe است
- [ ] import نامعتبر هیچ رکورد ناقصی ایجاد نمی‌کند
- [ ] تمام انواع درخواست گردش‌کار فعال دارند و `python manage.py audit_workflows` موفق است
- [ ] transitionهای غیرمجاز workflow رد می‌شوند
- [ ] تغییرات حساس audit trail دارند
- [ ] صفحات list/detail برای داده بزرگ pagination دارند

### داشبورد
- [ ] KPIهای مدیر سامانه و رئیس اداره از querysetهای scoped استفاده می‌کنند
- [ ] رتبه‌بندی‌ها تعریف کسب‌وکاری روشن دارند
- [ ] نمودارها با داده واقعی تست شده‌اند
- [ ] dashboard بیمه‌شده اطلاعات حداقلی و privacy-safe نمایش می‌دهد

## 4) مقیاس‌پذیری

برای چند هزار تا چند ده هزار بیمه‌شده، PostgreSQL + Gunicorn + reverse proxy برای شروع مناسب است، به شرط pagination، index، query optimization و عدم اجرای گزارش‌های سنگین در هر request.

برای رشد بیشتر:

- cache برای KPIهای مدیریتی
- job queue برای import و گزارش‌های سنگین
- object storage برای فایل‌ها
- connection pooling
- monitoring و error tracking
- retention/archive policy

## 5) زمان‌بندی چرخه عمر قرارداد

پس از اعمال migration قرارداد و تعریف/انتشار گردش‌کارهای contract_approval و contract_termination، فرمان زیر باید روزانه اجرا شود تا نسخه‌های تأییدشده در تاریخ اثر اعمال و قراردادهای منقضی غیرفعال شوند:

```bash
python manage.py apply_due_contract_revisions
```

نمونه‌های systemd در مسیرهای زیر قرار دارند:

- `deploy/systemd/office-kmc-contract-lifecycle.service.example`
- `deploy/systemd/office-kmc-contract-lifecycle.timer.example`

پس از بازبینی مسیرها، کاربر سرویس و EnvironmentFile، فایل‌ها را در `/etc/systemd/system/` نصب و timer را فعال کنید:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now office-kmc-contract-lifecycle.timer
sudo systemctl start office-kmc-contract-lifecycle.service
sudo systemctl status office-kmc-contract-lifecycle.timer
```

این زمان‌بند برای تاریخ‌های اثر آینده و انقضای قرارداد ضروری است؛ بدون اجرای روزانه، نسخه تأییدشده ممکن است در وضعیت انتظار اثر باقی بماند.

## 6) روند توسعه بعد از go-live

همه تغییرات این پروژه بنا بر تصمیم فعلی مستقیماً روی `main` اعمال می‌شوند. برای هر تغییر ابتدا منطق کسب‌وکار و authorization، سپس تست و در پایان UI پیاده‌سازی می‌شود. GitHub Actions جزو فرآیند استقرار نیست.


## 7) زمان‌بندی دوره‌های بیمه‌نامه دارایی

پس از اجرای migration مربوط به وضعیت‌های تأیید دارایی و انتشار گردش‌کارهای پایه، فرمان زیر باید روزانه اجرا شود تا دوره‌های بیمه‌نامه‌ای که قبلاً تأیید شده‌اند و تاریخ شروع آن‌ها رسیده است فعال شوند؛ دوره‌های منقضی نیز به وضعیت منقضی منتقل می‌شوند:

```bash
python manage.py apply_due_asset_policy_periods
```

این فرمان فقط دوره‌های تأییدشده را پردازش می‌کند و دوره‌های در انتظار تأیید را فعال نمی‌کند. نمونه‌های systemd برای اجرای روزانه:

- `deploy/systemd/office-kmc-asset-policy.service.example`
- `deploy/systemd/office-kmc-asset-policy.timer.example`

سرویس دارایی با همان کاربر `officekmc`، گروه `www-data` و فایل محیطی سرویس اصلی اجرا می‌شود. پس از بررسی مسیرها و مجوزها، واحدها را نصب و فعال کنید:

```bash
sudo cp deploy/systemd/office-kmc-asset-policy.service.example /etc/systemd/system/office-kmc-asset-policy.service
sudo cp deploy/systemd/office-kmc-asset-policy.timer.example /etc/systemd/system/office-kmc-asset-policy.timer
sudo systemctl daemon-reload
sudo systemctl enable --now office-kmc-asset-policy.timer
sudo systemctl start office-kmc-asset-policy.service
sudo systemctl status office-kmc-asset-policy.timer
```

زمان‌بند روزانه ساعت 00:30 به وقت محلی میزبان اجرا می‌شود؛ منطقه زمانی میزبان باید با منطقه زمانی عملیاتی سامانه هماهنگ باشد.
