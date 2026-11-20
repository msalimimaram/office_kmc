# گزارش اجرای فاز یک — دفتر شواهد و جلوگیری از تکرار

**تاریخ ثبت:** 2026-11-20  
**مخزن:** `msalimimaram/office_kmc`  
**شاخه:** `main`  
**SHA مبنای اجرای محلی گزارش‌شده:** `8835f826ea386685de8d6132d2ab649fa08db2ee`  
**محیط:** Windows PowerShell، Python 3.13.1، Django 5.2.19، محیط مجازی `.venv`  
**پایگاه داده مؤثر:** SQLite، فایل `db.sqlite3` در ریشه پروژه  
**وضعیت فاز:** OPEN — تثبیت فنی در حال انجام  
**وضعیت انتشار:** NO-GO؛ این گزارش به معنی آمادگی Production نیست.

> این سند دفتر ثبت شواهد است. نتیجه‌ای که در اینجا با PASS ثبت شده، بدون تغییر SHA یا تغییر محیط/وابستگی/کد نباید بی‌دلیل دوباره اجرا شود. اگر بعداً SHA عوض شد، فقط آزمون‌های متأثر از تغییر و gate نهایی لازم اجرا شوند؛ تکرار کامل همه بررسی‌ها پیش‌فرض نیست.

## 1. نتایج قطعی و ثبت‌شده

| شناسه | کنترل | نتیجه | شواهد / تفسیر |
|---|---|---|---|
| P1-ENV-01 | ساخت تنظیمات محلی از `.env.local.example` | PASS | نمونه موجود بود؛ `.env` ابتدا وجود نداشت. کاربر آن را برای محیط توسعه محلی ساخت/آماده کرد. |
| P1-GIT-01 | شاخه و SHA | PASS (گزارش‌شده) | `main`، SHA برابر `8835f826ea386685de8d6132d2ab649fa08db2ee`. |
| P1-GIT-02 | وضعیت working tree | PASS (در زمان گزارش) | `git status --short` خالی گزارش شد. |
| P1-GIT-03 | حفاظت `.env` | PASS | `git check-ignore -v .env` فایل محلی را به‌واسطه ignore rule مستثنا کرد. راز محلی نباید commit شود. |
| P1-DJ-01 | `python manage.py check` | PASS | بدون خطا/هشدار مسدودکننده گزارش شد. |
| P1-DEP-01 | `python -m pip check` | PASS | ناسازگاری dependency گزارش نشد. |
| P1-MIG-01 | `python manage.py makemigrations --check --dry-run` | PASS | `No changes detected`؛ در زمان اجرا migration جدید موردنیاز مدل‌ها تشخیص داده نشد. |
| P1-SEED-01 | `core.tests.DemoSeedCommandSafetyTests` | PASS | 9 تست، 9 موفق، صفر failure/error؛ مدت گزارش‌شده 112.293 ثانیه. |
| P1-SEED-02 | one-shot/fail-closed seed safety | PASS | تست اجرای مجدد seed بدون mutation داده موجود موفق بود. این فقط نتیجه تست ایمنی است؛ فرمان seed روی دیتابیس توسعه اجرا نشده است. |
| P1-DB-01 | شناسایی دیتابیس محلی | PASS — EMPTY | SQLite: مسیر `db.sqlite3`، فایل موجود با اندازه صفر بایت، صفر جدول، جدول `django_migrations` وجود ندارد. هیچ جدول یا رکوردی برای حفظ در این فایل مشاهده نشد. |
| P1-PREFLIGHT-01 | `.\scripts\final_preflight.ps1 -NoMigrate` | BLOCKED — EXPECTED | پیش‌بررسی به‌دلیل اعمال‌نشده بودن migrationها در دیتابیس خالی متوقف شد. گزینه `-NoMigrate` عمداً مانع اعمال migration است. این نتیجه شکست تست یا خطای schema نیست. |

## 2. تفکیک دقیق PASS، BLOCKED و UNVERIFIED

### PASS
- پیکربندی توسعه توانست Django را بارگذاری کند.
- Django system check موفق بود.
- dependency check موفق بود.
- migration drift check موفق بود.
- تست‌های ایمنی seed با 9/9 موفق شدند.
- فایل `.env` در Git ignore است.
- دیتابیس SQLite بررسی‌شده خالی و صفر بایت بود.

### BLOCKED
- preflight با `-NoMigrate` از مرحله بررسی وضعیت migration متوقف شد؛ چون دیتابیس خالی است و هنوز migrationها روی آن اعمال نشده‌اند. رفتار مورد انتظار برای این ترکیب است.

### هنوز اجرا/تأیید نشده
- اجرای تمام test suite روی همین SHA و همین محیط.
- `verify_database_schema` پس از ساخت schema.
- `audit_workflows` روی دیتابیس دارای schema.
- بررسی `showmigrations` پس از migrate.
- PostgreSQL fresh install و upgrade.
- ClamAV واقعی (فایل clean، EICAR و service-down).
- backup/restore drill، بار/هم‌زمانی، MFA واقعی، ممیزی کامل IDOR و UAT.
- سازگاری کامل Python 3.13؛ `pip check` به‌تنهایی سازگاری runtime تمام پکیج‌ها را ثابت نمی‌کند. README نسخه‌های 3.11/3.12 را توصیه می‌کند؛ این تفاوت فعلاً یادداشت است، نه failure اثبات‌شده.

## 3. تصمیم درباره دیتابیس و اقدام مجاز بعدی

بررسی read-only دیتابیس نشان داد فایل `db.sqlite3` صفر بایت و فاقد هرگونه جدول است. بر اساس همین شواهد، فایل محلی مورد بررسی داده‌ای برای حفظ ندارد و می‌توان schema توسعه را با migrationهای مخزن ایجاد کرد.

**اقدام بعدی واحد:** روی همین checkout و فقط همین دیتابیس محلی خالی، یک بار اجرا شود:

```powershell
python manage.py migrate
```

این دستور فقط برای ساخت schema توسعه محلی است؛ آن را به دیتابیس Production یا هر دیتابیس دیگری تعمیم ندهید. قبل از اجرا، اگر `.env` یا `DATABASE_URL` تغییر کرده یا مقصد DB عوض شده، ابتدا مقصد را دوباره شناسایی کنید.

پس از migrate، از اجرای دوباره کنترل‌های قبلاً PASS شده خودداری شود. فقط این دروازه جامع یک‌بار اجرا شود:

```powershell
.\scripts\final_preflight.ps1 -NoMigrate
```

این preflight باید full suite و کنترل‌های تعریف‌شده در اسکریپت را روی schema حاضر اجرا کند. خروجی کامل و SHA را ثبت کنید. اگر preflight باز هم متوقف شد، فقط مرحله ناموفق را بررسی کنید؛ تست‌های سبز قبلی را تکرار نکنید مگر تغییر کد/محیط به آن‌ها اثر گذاشته باشد.

سپس، بدون اجرای مجدد suite، در صورت موفقیت preflight:
1. `python manage.py verify_database_schema`
2. `python manage.py audit_workflows`

این دو فرمان باید روی همان دیتابیس migrate‌شده اجرا و خروجی‌شان ثبت شود. اگر اسکریپت preflight خودش این فرمان‌ها را اجرا کرد، اجرای جداگانه تکراری انجام نشود.

## 4. سیاست جلوگیری از تست بی‌مورد

- تست 9تایی Seed روی SHA ثبت‌شده PASS است؛ تا تغییر کد seed، تنظیمات مرتبط یا نیاز به regression ناشی از تغییرات بعدی، دوباره اجرا نشود.
- `manage.py check`، `pip check` و `makemigrations --check --dry-run` در این snapshot PASS هستند؛ فقط پس از تغییر dependency/settings/models یا پیش از gate نهاییِ لازم، دوباره اجرا شوند.
- full suite هنوز نتیجه ندارد؛ یک اجرای جامع پس از migrate لازم است، نه چند اجرای پراکنده و تکراری.
- هیچ تستی برای تولید خروجی سبز صوری تکرار نشود؛ شکست واقعی ثبت و علت ریشه‌ای رفع شود.
- `seed_demo` روی دیتابیس توسعه اجرا نشود. تست ایمنی seed با اجرای واقعی seed یکی نیست. سیاست فعلی one-shot/fail-closed است؛ طراحی idempotent آینده اگر همچنان الزام مالک محصول باشد، کار مستقلی با معیار پذیرش مشخص است.
- از reset، حذف فایل DB، `flush`، اجرای seed یا migration روی دیتابیس ناشناخته/دارای داده خودداری شود.

## 5. خلاصه تصمیم

**فاز صفر بسته است. فاز یک باز است.**  
زیرمجموعه‌ای از کنترل‌های پایه و تست ایمنی seed PASS شده‌اند. preflight به‌علت خالی بودن دیتابیس و انتخاب `-NoMigrate` به‌صورت قابل توضیح BLOCKED شده است. دیتابیس محلی بررسی‌شده صفر بایت و خالی است؛ بنابراین قدم بعدی ساخت schema محلی یک بار و سپس اجرای تنها preflight جامع است.  
**Production = NO-GO** تا عبور از فازهای فنی، امنیتی، زیرساختی و پذیرش کسب‌وکار.

---

## 6. اجرای جامع پس از ایجاد schema — گزارش مالک، 2026-11-20

**شناسه اجرا:** P1-SUITE-01  
**SHA checkout محلی:** در خروجی ارسالی این اجرا درج نشده؛ انتساب نتیجه به SHA فعلی GitHub ممکن نیست.  
**محیط:** همان مسیر محلی گزارش‌شده در این گفتگو؛ نسخه دقیق Python/Django برای این اجرای خاص مجدداً در خروجی درج نشده است.

### نتایج

| کنترل | نتیجه | جزئیات |
|---|---|---|
| مجموعه کامل Django | **PASS** | 358 تست، صفر failure/error؛ زمان 832.123 ثانیه. پیام صریح اسکریپت: `PASS: Complete Django test suite`. |
| تخریب test database | PASS | دیتابیس تست حافظه‌ای `file:memorydb_default?mode=memory&cache=shared` پس از تست تخریب شد. |
| تشخیص وضعیت publication gate در Preflight | **BLOCKED — SCRIPT/LOCAL-CHECKOUT ISSUE** | دستور Python فراخوانی‌شده از `manage.py shell -c` با `SyntaxError` متوقف شد: `print(f{active_workflows}|{populated_application_tables})`. سپس PowerShell پیام داد امکان تعیین شمول workflow publication gate وجود ندارد. |
| ممیزی واقعی workflow publication | **NOT RUN / UNVERIFIED** | چون مرحله تشخیص gate شکست خورد، نمی‌توان نتیجه `audit_workflows` را PASS دانست. |

### تشخیص خطا

این خطا پس از پیام موفقیت مجموعه کامل تست‌ها رخ داده است؛ بنابراین **358 تست موفق‌اند و خطای بعدی، شکست تست نیست**. خطا در مرحله بررسی وضعیت workflow gate و ساخت/ارسال قطعه کد Python به shell است.

بازبینی نسخه فعلی `scripts/final_preflight.ps1` در GitHub روی `main` نشان می‌دهد خط 97 در نسخه remote از نظر syntax به شکل زیر است:

```python
print(f"{active_workflows}|{populated_application_tables}")
```

اما متن خطای محلی، شکل متفاوت و نامعتبر `print(f{...}|{...})` را نشان می‌دهد. در نتیجه محتمل است فایل محلی `scripts/final_preflight.ps1` با نسخه remote متفاوت باشد، یا متن فرمان در مسیر اجرا تغییر کرده باشد. بدون SHA و محتوای فایل محلی، علت دقیق قطعی نیست.

### اقدام بعدی محدود؛ بدون اجرای مجدد تست‌ها

در checkout محلی فقط این دستورات read-only اجرا شوند:

```powershell
git rev-parse HEAD
git status --short --branch
git diff -- scripts/final_preflight.ps1
Select-String -Path .\scripts\final_preflight.ps1 -Pattern 'print\(' -Context 2,2
```

- اگر فایل محلی با نسخه remote فرق دارد، ابتدا اختلاف را بررسی و checkout را با `main` همگام کنید؛ هیچ reset یا دورریختن تغییر محلی انجام نشود.
- اگر فایل محلی دقیقاً همان نسخه remote است، خروجی خط‌های 86 تا 101 و نسخه PowerShell را بررسی کنید تا نحوه انتقال here-string مشخص شود.
- سپس فقط مرحله workflow gate و ادامه preflight از همان نقطه اجرا شود؛ **مجموعه 358 تست را دوباره اجرا نکنید**. برای این کار می‌توان پس از رفع مشکل، فرمان‌های read-only `python manage.py audit_workflows` و `python manage.py verify_database_schema` را اجرا کرد، مشروط به اینکه وضعیت و داده‌های دیتابیس مقصد تأیید شده باشند. اگر اسکریپت preflight با امکان resume/skip suite اصلاح شد، اجرای دوباره suite لازم نیست.

### وضعیت به‌روزشده فاز یک

- مجموعه کامل تست‌ها: **PASS — 358/358** (گزارش مالک؛ SHA محلی هنوز ثبت نشده).
- workflow publication gate: **BLOCKED** به علت خطای syntax در probe.
- `audit_workflows` و `verify_database_schema`: نتیجه هنوز تأیید نشده، مگر آنکه خروجی جداگانه‌ای ارائه شود.
- فاز یک: **OPEN** تا تکمیل کنترل schema/workflow و ثبت SHA اجرای محلی.
- Production: **NO-GO**؛ عبور از suite به‌تنهایی پذیرش امنیتی/عملیاتی یا آمادگی انتشار نیست.
