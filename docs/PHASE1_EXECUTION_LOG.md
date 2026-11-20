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


## 9. نتیجه ممیزی workflow و ریشه‌یابی وضعیت دیتابیس — گزارش مالک، 2026-11-20

**فرمان:** `python manage.py audit_workflows`  
**نتیجه:** FAIL / پیکربندی گردش‌کار ناقص  
**خروجی مالک:** 19 کد workflow فاقد تعریف فعال؛ `CommandError: ممیزی گردش‌کار ناموفق بود؛ 19 فرآیند فاقد گردش‌کار و 1 مغایرت.`

### تفسیر دقیق شمارنده خطا

بازبینی سورس `core/management/commands/audit_workflows.py` نشان می‌دهد شمارنده «1 مغایرت» یک مغایرت مستقل دوم نیست. کد برای کل مجموعه 19 workflow مفقود، یک پیام تجمیعی به `errors` اضافه می‌کند؛ بنابراین `len(missing)=19` و `len(errors)=1`. در این اجرا هیچ تعریف فعالی وجود نداشت تا ممیزی مراحل/انتقال‌های آن تعریف‌ها انجام شود. نباید «یک نقص مستقل دیگر» گزارش شود.

### 19 workflow مفقود

`add_coverage`, `anonymous_plan`, `asset_endorsement_approval`, `asset_policy_approval`, `asset_valuation_approval`, `base_insurance_waiver`, `claim_objection`, `claim_review`, `contract_approval`, `contract_termination`, `document_request`, `excess_coverage`, `iban_change`, `identity_change`, `management_report_approval`, `medical_assistance`, `other`, `person_change`, `remove_coverage`.

### ریشه‌یابی ساختار و داده

- Migration اولیه `workflow.0001_initial` فقط جداول مدل‌های workflow را می‌سازد و یک `BusinessCalendar` پایه با کد `iran-default` ایجاد می‌کند؛ workflow definition/step/transition ایجاد نمی‌کند.
- کد `seed_demo` نیز داده‌های نمایشی کسب‌وکار را می‌سازد و guard آن تنها تقویم پایه pristine را به‌عنوان زیرساخت مجاز می‌شناسد؛ این فرمان سازوکار bootstrap پیکربندی workflow نیست و طبق سیاست قبلی روی دیتابیس فعلی اجرا نشود.
- `WorkflowDefinition` دارای created_by اجباری است؛ فعال‌سازی نیازمند approved_by با نقش رئیس اداره یا مدیر سامانه است و انتشار به اعتبارسنجی مدل متکی است. تعریف منتشرشده immutable است.
- رابط Django admin برای پیکربندی workflow وجود دارد، اما این موضوع به‌تنهایی جایگزین پیکربندی اولیه نسخه‌بندی‌شده، قابل بازبینی و قابل استقرار نیست.
- probe قبلی `0|1` با شواهد migration و seed guard سازگار است: صفر workflow فعال و یک مدل کاربردی دارای ردیف زیرساختی (تقویم پایه). این شمارش به‌تنهایی اثبات نمی‌کند که آن یک جدول حتماً BusinessCalendar است، اما migration و guard آن را محتمل و قابل انتظار می‌کنند؛ برای قطعیت نام جدول، در صورت نیاز یک probe read-only جداگانه لازم است.

### تصمیم و اقدام اصلاحی

این یک نقص واقعی در آمادگی پیکربندی محیط تازه است: پس از migrate، سامانه 19 workflow ضروری را به‌صورت فعال و منتشرشده در دیتابیس ندارد. اصلاح نباید با اجرای `seed_demo`، ساخت دستی رکوردهای ناقص، غیرفعال‌کردن audit یا تضعیف قواعد نقش/انتقال انجام شود.

اقدام مهندسی بعدی:
1. تهیه ماتریس canonical برای هر 19 کد شامل عنوان، مراحل منطبق با statusهای دامنه، نقش‌ها/سطوح سمت، SLA، transitionها، گیرندگان و اختیار بستن.
2. تطبیق هر گردش با قواعد کسب‌وکار تثبیت‌شده (به‌ویژه مسیر نماینده شرکت/کارشناس/بیمه‌گر، بستن نهایی، و درخواست‌های حساس).
3. طراحی bootstrap پیکربندی امن و نسخه‌دار برای محیط تازه؛ باید هویت actor و approver واقعی را بگیرد، فقط روی تعریف‌های غیرفعال/غیرمنتشرشده عمل کند، conflict را fail-closed کند، transaction داشته باشد و قابلیت audit/re-run امن داشته باشد. هرگز شناسه کاربر یا role را حدس نزند.
4. افزودن تست‌های هدفمند برای bootstrap و تأیید اینکه پس از provision، `audit_workflows` PASS می‌شود. این تست‌ها جایگزین تکرار suite کامل نیستند.
5. سپس روی دیتابیس محلی مورد بحث، با حفظ تقویم پایه و بدون پاک‌کردن داده، provisioning پس از بازبینی و تعیین کاربر تأییدکننده اجرا شود.

### جلوگیری از تکرار

- `audit_workflows` در وضعیت فعلی با صفر workflow فعال اجرا شده و کمبود 19 مورد را ثابت کرده است؛ تا ایجاد/تغییر پیکربندی workflow دوباره اجرا نشود.
- `verify_database_schema` قبلاً PASS شده و تا تغییر schema تکرار نشود.
- full suite 358/358 PASS قبلی است و تکرار نمی‌شود مگر تغییرات بعدی به کدهای تحت پوشش آن suite نیاز به regression هدفمند/اجرای نهایی بدهد.

**فاز یک:** OPEN — workflow configuration bootstrap / provisioning یک مانع اصلی است.  
**Production:** NO-GO.


## 10. طراحی مرجع provisioning گردش‌کارها — 2026-11-20

**سند جدید:** `docs/WORKFLOW_PROVISIONING_DESIGN.md`  
**Commit:** `49585287a3e865d4af178254e48ce122f56519e9`

### کار انجام‌شده
- قرارداد ساختاری و قواعد سخت‌گیرانه `audit_workflows` از سورس استخراج و در سند مستقل ثبت شد.
- ۱۰ نوع درخواست عمومی از `ServiceRequest.Kind` و ۹ فرآیند دامنه‌ای از کد ممیزی تفکیک شدند.
- وضعیت‌های دامنه، مراحل آغازین اجباری و کنترل‌های ممیزی خاص برای خسارت، اعتراض، قرارداد، دارایی، اصلاح اطلاعات شخص و گزارش مدیریتی ثبت شدند.
- قواعد غیرقابل مذاکره نقش/مسیر ثبت شد: نماینده بیمه‌گر حق بستن ندارد؛ درخواست عمومی فقط با رئیس/مدیر بسته می‌شود؛ `person_change` استثنای محدود خودش را دارد؛ محرمانگی درمان، scope شرکت/بیمه‌گر/رشته و ادامه SLA در انتظار حفظ می‌شوند.
- قرارداد طراحی provisioning امن شامل actor/approver واقعی، dry-run، opt-in انتشار، transaction اتمیک، fail-closed، عدم overwrite نسخه منتشرشده و اجرای audit پس از provision تعریف شد.
- تست‌های هدفمند لازم مشخص شدند؛ تکرار suite 358 تست درخواست نشده است.

### وضعیت
این commit صرفاً سند طراحی است؛ هنوز کد provisioning یا workflow data در DB ایجاد نشده است. عمداً از تولید/انتشار workflow با قواعد حدسی خودداری شد، چون انتشار immutable است و اختیارهای بستن/ارجاع، اثر مستقیم بر عملیات بیمه دارند.

### مانع محیط
probe قبلی فقط `0 active / 1 populated table` را ثابت می‌کند؛ نام جدول را ثابت نمی‌کند. همچنین وجود actor/approver واقعی با انتصاب فعال رئیس اداره/مدیر سامانه هنوز در DB محلی اثبات نشده است. چون `WorkflowDefinition.created_by` اجباری و انتشار نیازمند `approved_by` معتبر است، هیچ user ID یا نقش تأییدکننده‌ای حدس زده نمی‌شود.

### اقدام بعدی فنی
1. تکمیل کاتالوگ اجرایی بر اساس تمام status sync hooks و transition services؛
2. پیاده‌سازی command مستقل provisioning با `--dry-run` و `--publish`؛
3. تست‌های واحد/امنیتی/تکرارپذیری و rollback؛
4. اجرای dry-run و سپس انتشار فقط با actor/approver واقعی در محیط محلی؛
5. اجرای یک‌باره `audit_workflows` پس از تغییر پیکربندی.

**فاز یک:** OPEN — سند طراحی تکمیل شد؛ پیاده‌سازی provisioning و اثبات محلی باقی است.  
**Production:** NO-GO.  
**تست‌های قبلی غیرمرتبط:** full suite 358/358 PASS، schema 60 tables PASS و PowerShell launcher PASS؛ هیچ‌کدام تکرار نشوند.


## 11. تأیید مستقیم وضعیت هویت و داده در دیتابیس محلی — 2026-11-20

**روش:** probe فقط‌خواندنی با Django ORM؛ بدون نمایش شناسه، نام کاربری، شماره ملی، شماره همراه یا محتوای رکوردها.

**خروجی عینی مالک:**
```text
ACTIVE_USERS 0
POPULATED workflow.BusinessCalendar 1
```

### نتیجه قطعی
- هیچ حساب کاربری فعال در دیتابیس وجود ندارد.
- هیچ انتصاب فعال مدیر سامانه یا رئیس اداره در probe گزارش نشده است.
- تنها مدل دارای داده `workflow.BusinessCalendar` با یک رکورد است.
- این خروجی با دیتابیس پایه پس از migration سازگار است؛ اما مجوز اجرای seed نمایشی یا ایجاد گردش‌کار نیست.
- به علت نبود حساب فعال، در این لحظه actor واقعی برای ایجاد تعریف‌ها و approver معتبر برای انتشار در دسترس نیست.

### بازبینی تکمیلی کد مجوزدهی
- مقادیر نقش‌ها از `RoleAssignment.Role` استفاده می‌کنند: `system_admin`, `department_head`, `insurance_specialist`, `subsidiary_rep`, `insurer_representative`, `insured_person`.
- `RoleAssignment.save()` اعتبارسنجی مدل را اجرا می‌کند و برای نقش‌های سراسری `is_staff` را در صورت وجود انتصاب فعال تنظیم می‌کند.
- فیلدهای `granted_by` و `approved_by` در مدل انتساب نقش nullable هستند؛ بنابراین ایجاد انتصاب سراسری از نظر مدل لزوماً به معنی ثبت تأیید مستقل نیست. این موضوع نباید به‌عنوان اثبات هویت یا تأیید مدیریتی تلقی شود.
- `WorkflowDefinition` انتشار را با انتصاب فعال `SYSTEM_ADMIN` یا `DEPARTMENT_HEAD` برای approver کنترل می‌کند؛ مدل فعلی در قطعه بررسی‌شده شرط مستقلی برای متفاوت بودن created_by و approved_by ندارد. پیش از provisioning باید این کنترل تفکیک وظایف به‌صورت صریح طراحی و آزموده شود، نه اینکه با یک حساب واحد دور زده شود.

### تصمیم اجرایی
هیچ کاربر، انتصاب نقش، workflow definition، step یا transition در دیتابیس مالک ایجاد نشد. هیچ داده‌ای حذف یا تغییر نکرد. اجرای `seed_demo` ممنوع باقی می‌ماند.

گام فنی بعدی در مخزن:
1. تعریف مسیر bootstrap اولیه مدیر سامانه با محدودیت دیتابیس کاملاً خالی از حساب‌ها/داده‌های عملیاتی، دریافت رمز فقط به‌صورت تعاملی، ثبت علت و کنترل one-shot؛
2. طراحی تأییدکننده مستقل (رئیس اداره یا مدیر دوم) و الزام جدایی actor/approver برای provisioning؛
3. سپس تکمیل blueprintهای ۱۹ گردش‌کار و فرمان dry-run/publish به‌صورت اتمیک؛
4. تست‌های هدفمند bootstrap و provisioning، بدون تکرار suite کامل ۳۵۸تایی.

**فاز یک:** OPEN — مانع هویت/تفکیک وظایف تأیید شد؛ هیچ provisioning انجام نشده است.  
**Production:** NO-GO.


## 12. ایمن‌سازی فرمان انتشار گردش‌کارها — 2026-11-20

**تغییرات main:**
- `d250e0445c99ffa4afee775dee6a33d70c821a79` — حذف انتخاب خودکار اولین مدیر/رئیس از `seed_operational_workflows`؛ الزام شناسه ایجادکننده و تأییدکننده مستقل؛ dry-run پیش‌فرض؛ audit درون تراکنش.
- `a33e55ffd5dd87cfd5d19889c6f7c04b19ce1168` — اصلاح هر دو خانواده workflow تا تمام ۱۹ تعریف، `created_by` و `approved_by` جداگانه و صحیح دریافت کنند.
- `bf0e0e482b05231296da039da07ab0c0a767042a` — به‌روزرسانی تست‌های provisioning موجود برای هویت‌های جداگانه و گزینه `--publish`.
- `e8763a780819d6e6085b1d4061004076e3566e14` — افزودن تست رد creator=approver و rollback کامل dry-run.
- `ba2bea7a092a7780f299907d06b140f622cf9539` و `170accce0cc8815e5cddda1917be2dca5f4e371c` — هم‌راستاسازی سند طراحی با قرارداد اجرایی.

### قرارداد جدید فرمان

```powershell
# فقط اعتبارسنجی؛ بدون باقی ماندن هیچ تغییری در دیتابیس
python manage.py seed_operational_workflows --created-by <CREATOR_USER_ID> --approved-by <APPROVER_USER_ID>

# انتشار واقعی؛ فقط پس از بررسی dry-run و داشتن backup معتبر
python manage.py seed_operational_workflows --created-by <CREATOR_USER_ID> --approved-by <APPROVER_USER_ID> --publish
```

- هر دو حساب باید فعال و موجود باشند.
- تأییدکننده باید انتصاب معتبر و تاریخ‌دار `system_admin` یا `department_head` داشته باشد.
- ایجادکننده و تأییدکننده نمی‌توانند یک حساب باشند.
- ممیزی `audit_workflows` قبل از commit و در همان تراکنش اجرا می‌شود؛ خطا موجب rollback کامل است.
- انتخاب خودکار اولین انتصاب حذف شده است.
- اجرای فرمان بدون `--publish` تمام writeها را rollback می‌کند.

### وضعیت اعتبارسنجی

این تغییرات از طریق GitHub ثبت شده‌اند، اما تست‌های جدید هنوز روی محیط محلی مالک اجرا نشده‌اند؛ بنابراین PASS بودن آن‌ها ادعا نمی‌شود. اجرای suite کامل ۳۵۸تایی لازم نیست؛ ابتدا فقط تست‌های هدفمند provisioning باید اجرا شوند.

### مانع قطعی باقی‌مانده

Probe محلی مالک نشان داد `ACTIVE_USERS 0`. بنابراین هنوز هیچ شناسه واقعی برای ایجادکننده/تأییدکننده وجود ندارد و انتشار ۱۹ workflow روی دیتابیس محلی ممکن نیست. bootstrap نخستین مدیر باید با احراز هویت سازمانی و کنترل دسترسی به محیط اجرا شود؛ هیچ حسابی در مخزن یا دیتابیس مالک به‌صورت حدسی ساخته نشده است.

**فاز یک:** OPEN — فرمان provisioning امن‌تر و تست‌های هدفمند اضافه شده‌اند؛ اجرای تست محلی، bootstrap هویت، dry-run و انتشار واقعی هنوز باقی است.  
**Production:** NO-GO.
## 13. پیاده‌سازی مسیر bootstrap نخستین مدیر سامانه — 2026-11-20

**Commitهای main:**
- `bef52a69b6d54ca32873688b0a72740c799f14e2` — افزودن فرمان تعاملی و یک‌باره `bootstrap_first_system_admin`.
- `21f456b0d2e3d3cc258a437c2e6ba80e9c711c27` — اصلاح الگوهای اعتبارسنجی ورودی کد ملی و موبایل.
- `9e33391997ff296985e2a6122b4172ea6803a173` — افزودن تست‌های bootstrap و ثبت audit.
- `d9ae79511af80cad5dd398eb3b05ff993168b4ed` — مستندسازی کنترل‌های bootstrap در سند provisioning.
- `36c08a348986c7f14fb1f406bfd6c66ceab26406` — رد bootstrap در صورت وجود داده عملیاتی یا بیش از یک تقویم پایه.
- `3c11a7a6b295efd3fb7c88c1e134bffbae2fbce0` — افزودن تست توقف در حضور داده عملیاتی.
- `64f86bac2e64938c2b1d7f6c945e64ac297ef672` — شفاف‌سازی شرط دیتابیس pristine در سند طراحی.
- `fea0acee85c9380d89d0ed22da7c8667ab38ed14` — تبدیل خطای password validator به پیام امن CommandError.
- `61b688b6441a0e0d12786df694957242add4c27b` — افزودن تست رد رمز ضعیف بر اساس policy پیکربندی‌شده.

### رفتار پیاده‌سازی‌شده
- فرمان فقط روی دیتابیس مهاجرت‌شده دارای تقویم پایه `iran-default` اجرا می‌شود و برای جلوگیری از اجرای هم‌زمان روی همان ردیف قفل تراکنشی می‌گیرد.
- وجود حتی یک حساب (فعال یا غیرفعال)، یا هر سابقه انتصاب نقش/سمت، باعث توقف پیش از دریافت اطلاعات می‌شود.
- فرمان هیچ credential را از آرگومان نمی‌گیرد؛ کد ملی، نام و موبایل تعاملی دریافت می‌شوند و رمز با `getpass` مخفی است.
- کد ملی ۱۰ رقمی، موبایل با قالب `09xxxxxxxxx` و رمز با password validators پروژه کنترل می‌شوند.
- حساب نخست `SYSTEM_ADMIN` است، `is_superuser=False` می‌ماند و تغییر رمز در اولین ورود اجباری است.
- حساب، انتصاب و audit event در یک تراکنش ذخیره می‌شوند؛ actor رویداد audit عمداً null است تا ایجادکنندهٔ حساب به‌اشتباه خود حساب تازه‌ساخته‌شده معرفی نشود. رمز در audit ثبت نمی‌شود.
- احراز هویت واقعی شخص از طریق سازمان خارج از سامانه و پیش از اجرای فرمان، مسئولیت اپراتور مجاز میزبان است؛ فرمان جایگزین فرایند احراز هویت سازمانی نیست.

### تست‌های افزوده‌شده — هنوز اجرا نشده‌اند
- ساخت اولین مدیر با حداقل دسترسی و audit بدون credential؛
- رد هر نوع حساب موجود، حتی غیرفعال، پیش از prompt؛
- رد confirmation نادرست؛
- رد کد ملی و موبایل نامعتبر؛
- رد دیتابیس دارای داده عملیاتی، پیش از دریافت اطلاعات؛
- رد رمز ضعیف مطابق password validators و رد عدم تطابق رمز؛
- rollback کامل حساب، انتصاب و audit در سناریوهای رد.

**محدودیت اعتبارسنجی:** کد و تست‌ها در GitHub main ثبت شده‌اند، اما در این محیط به checkout محلی/venv پروژه دسترسی اجرایی ندارم؛ بنابراین تست‌های جدید را PASS اعلام نمی‌کنم. اجرای آن‌ها باید در یک اجرای متمرکز اعتبارسنجی شود، نه با تکرار full suite 358تایی که قبلاً گزارش PASS شده است.

### گام بعدی فاز یک
1. اجرای فقط `accounts.tests.InitialSystemAdminBootstrapCommandTests` روی checkout همگام‌شده با main؛
2. در دیتابیس عملیاتی/دارای داده این فرمان هرگز اجرا نشود. فقط روی دیتابیس تازه و بررسی‌شدهٔ محیط هدف، پس از تأیید مقصد و backup، اپراتور مجاز نخستین مدیر را bootstrap کند؛
3. مدیر اول از مسیر رسمی، مدیر/رئیس دوم مستقل را ایجاد کند؛
4. تست‌های focused provisioning قبلی را در همان checkout اجرا و سپس dry-run فرمان `seed_operational_workflows` را با شناسه‌های واقعی و مستقل انجام دهد؛
5. پس از بازبینی خروجی dry-run، انتشار واقعی و `audit_workflows` فقط در محیط هدف و با مجوز مالک اجرا شود.

**فاز یک:** OPEN — مسیر bootstrap کدنویسی و تست‌نویسی شده؛ اجرای تست‌های تازه، bootstrap واقعی، تأمین تأییدکننده مستقل و انتشار ۱۹ گردش‌کار باقی است. **Production: NO-GO.**