# راهنمای استقرار نسخه عملیاتی سامانه اداره بیمه

این پروژه باید قبل از ورود اطلاعات واقعی از محیط توسعه جدا شود. این runbook عمداً GitHub Actions را وارد فرآیند استقرار نمی‌کند.

## 1) ترتیب استقرار

1. PostgreSQL مستقل و دارای backup تهیه شود.
2. دامنه و TLS/HTTPS روی reverse proxy (مثلاً Nginx) تنظیم شود.
3. متغیرهای `.env` واقعی روی سرور قرار گیرد؛ فایل secrets هرگز commit نشود.
4. `pip install -r requirements.txt` اجرا شود.
5. **مهاجرت‌های versioned برای تمام appها تولید، review و commit شوند.** در وضعیت فعلی repository هنوز migrations قابل اتکای پروژه را ندارد؛ تا این مرحله انجام نشده، ورود اطلاعات واقعی ممنوع است.
6. `python manage.py migrate` اجرا شود.
7. `python manage.py collectstatic --noinput` اجرا شود.
8. `python manage.py check --deploy` اجرا شود.
9. یک superuser اولیه ساخته و بلافاصله رمز قوی و MFA واقعی برای آن فعال شود.
10. Gunicorn اجرا و پشت reverse proxy قرار گیرد.
11. `/private_media` نباید مستقیماً از وب قابل دسترس باشد؛ دانلود فایل فقط از view دارای authorization انجام شود.
12. backup و restore آزمایشی قبل از go-live انجام شود.

## 2) حداقل متغیرهای محیط تولید

- `DJANGO_DEBUG=False`
- `DJANGO_SECRET_KEY` تصادفی و بلند
- `DJANGO_ALLOWED_HOSTS` فقط دامنه‌های واقعی
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://...`
- `DATABASE_URL` برای PostgreSQL
- `DB_SSLMODE=require` در صورت پشتیبانی سرویس DB
- `DJANGO_SECURE_SSL_REDIRECT=True`
- HSTS پس از اطمینان از HTTPS کامل فعال بماند.

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
- [ ] تغییر شبا/اطلاعات حساس بدون workflow تأیید نهایی نمی‌شود

### عملیات
- [ ] import اکسل duplicate-safe است
- [ ] import نامعتبر هیچ رکورد ناقصی ایجاد نمی‌کند
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

## 5) روند توسعه بعد از go-live

همه تغییرات این پروژه بنا بر تصمیم فعلی مستقیماً روی `main` اعمال می‌شوند. برای هر تغییر ابتدا منطق کسب‌وکار و authorization، سپس تست و در پایان UI پیاده‌سازی می‌شود. GitHub Actions جزو فرآیند استقرار نیست.
