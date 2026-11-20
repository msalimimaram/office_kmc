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


## 7. تشخیص قطعی PowerShell 5.1 و اصلاح انتقال کد shell — 2026-11-20

**شناسه:** P1-PREFLIGHT-PS51-01  
**SHA checkout محلی تأییدشده توسط مالک:** `8835f826ea386685de8d6132d2ab649fa08db2ee`  
**شاخه/وضعیت Git محلی:** `main...origin/main`، working tree پاک  
**نسخه PowerShell:** `5.1.19041.1151`

### شواهد قطعی علت

مالک، همان probe حداقلی را با کد زیر اجرا کرد:

```powershell
$probe = 'active_workflows=1; populated_application_tables=2; print(f"{active_workflows}|{populated_application_tables}")'
& $python manage.py shell -c $probe
```

در خطای Python، کد دریافتی به این شکل ثبت شد:

```python
active_workflows=1; populated_application_tables=2; print(f{active_workflows}|{populated_application_tables})
```

کوتیشن‌های موجود در آرگومان قبل از رسیدن به Django shell حذف شده‌اند. این بازتولید مستقل، علت را به لایه انتقال آرگومان PowerShell 5.1 به executable بومی محدود می‌کند؛ خطای syntax از خود منطق workflow یا مدل‌های Django نیست.

### اصلاح اعمال‌شده روی main

در `scripts/final_preflight.ps1` تابع `ConvertTo-PythonShellLauncher` اضافه شد. این تابع کد Python را به آرایه بایت‌های UTF-8 تبدیل و یک launcher بدون کوتیشن به شکل `exec(bytes([...] ))` تولید می‌کند. فراخوانی shell برای هر دو بخش workflow-state probe و production settings check از این مسیر امن استفاده می‌کند.

این اصلاح:
- منطق و معیارهای business/workflow را تغییر نمی‌دهد.
- تست‌ها، migrationها، داده‌ها یا seed را اجرا نمی‌کند.
- مشکل مشابه کوتیشن را در production settings probe نیز پیشگیری می‌کند.
- نیازمند اجرای مجدد مجموعه کامل 358 تست نیست؛ تغییر صرفاً در اسکریپت preflight است.

### وضعیت اعتبارسنجی اصلاح

- بازتولید مشکل در PowerShell 5.1: **CONFIRMED**.
- اصلاح اسکریپت در GitHub main: **COMMITTED**.
- اجرای محلی نسخه اصلاح‌شده و تأیید خروجی probe: **PENDING**.
- اجرای `verify_database_schema` و تصمیم gate / اجرای `audit_workflows`: **PENDING**.
- مجموعه 358 تست قبلی: همچنان **PASS** طبق گزارش مالک؛ به علت اصلاح صرفاً اسکریپت، تکرار نمی‌شود.

### دستور بعدی مالک — فقط preflight محدود، بدون اجرای suite

برای جلوگیری از اجرای دوباره 358 تست، فعلاً کل `final_preflight.ps1` اجرا نشود؛ چون این اسکریپت در حال حاضر full suite را قبل از workflow gate اجرا می‌کند. ابتدا نسخه اصلاح‌شده را دریافت کنید:

```powershell
git pull --ff-only origin main
```

سپس فقط انتقال آرگومان را با probe quote-free تأیید کنید:

```powershell
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
$probeCode = 'print(f"{1}|{2}")'
$bytes = [System.Text.Encoding]::UTF8.GetBytes($probeCode)
$byteList = [string]::Join(",", [string[]]$bytes)
$launcher = "exec(bytes([$byteList]))"
& $python manage.py shell -c $launcher
```

خروجی مورد انتظار: `1|2`. این probe فقط Django shell را بالا می‌آورد و هیچ داده‌ای را تغییر نمی‌دهد.

پس از موفقیت probe، فقط:
```powershell
python manage.py verify_database_schema
```
و در صورت وجود داده/تعریف workflow فعال، `python manage.py audit_workflows` اجرا شود. اگر دیتابیس خالی از داده‌های کاربردی است، نتیجه probe وضعیت تعداد workflow فعال و جدول‌های دارای داده را تعیین می‌کند؛ در آن حالت اجرای اجباری audit روی baseline خالی لازم نیست. هیچ‌یک از این مراحل نیازمند تکرار suite نیست.

**وضعیت فاز یک:** OPEN تا تأیید محلی اصلاح، schema و workflow gate.  
**Production:** NO-GO.


## 8. تأیید محلی اصلاح PowerShell و schema — گزارش مالک، 2026-11-20

**Checkout پس از pull:** مالک با موفقیت `git pull --ff-only origin main` را اجرا کرد؛ fast-forward از `8835f82` به `56c5a92`.  
**نسخه PowerShell:** 5.1.19041.1151 (ثبت‌شده در بخش 7).

| کنترل | نتیجه | شاهد |
|---|---|---|
| دریافت اصلاح main | PASS | fast-forward موفق؛ فایل‌های docs و `scripts/final_preflight.ps1` دریافت شدند. |
| probe انتقال کد shell | **PASS** | launcher بایت UTF-8 در PowerShell 5.1 خروجی `1|2` داد؛ مشکل حذف کوتیشن برطرف شد. |
| `python manage.py verify_database_schema` | **PASS** | `PASS: all 60 managed model and many-to-many tables exist.` |
| وضعیت داده/workflow | **0 active / 1 populated** | probe read-only خروجی `0|1` داد؛ workflow فعال صفر، اما یک جدول کاربردی دارای داده است. |
| `audit_workflows` | **PENDING — REQUIRED** | چون populated application tables برابر 1 است، gate اعمال می‌شود؛ صفر بودن workflow فعال به‌معنی معافیت نیست و ممیزی باید کمبود تعریف‌های فعال لازم را گزارش کند. |

### اقدام بعدی

فقط فرمان زیر اجرا شود؛ کد command در مخزن بررسی شده و منطق آن خواندنی/اعتبارسنجی است و داده‌ای ایجاد یا تغییر نمی‌دهد:

```powershell
python manage.py audit_workflows
```

خروجی کامل را ثبت کنید. انتظار می‌رود با توجه به صفر بودن workflowهای فعال، ممیزی کمبودهای گردش‌کار را گزارش کند؛ اگر چنین شد، آن را به‌عنوان مغایرت واقعی پیکربندی/داده ثبت می‌کنیم، نه خطای زیرساخت یا تست. هیچ seed یا ساخت workflow بدون تصمیم و بررسی مستقل انجام نشود.

### مواردی که نباید تکرار شوند

- full Django suite: 358/358 PASS گزارش‌شده؛ تکرار نشود.
- probe کوتیشن PowerShell: PASS؛ تکرار نشود مگر اسکریپت/روش فراخوانی تغییر کند.
- `verify_database_schema`: PASS برای schema فعلی؛ تا تغییر migration/schema تکرار نشود.

**فاز یک:** OPEN تا تعیین تکلیف audit workflow.  
**Production:** NO-GO.
