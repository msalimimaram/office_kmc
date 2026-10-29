# ارزیابی عمیق پروژه اداره بیمه

**تاریخ ارزیابی:** 2026-10-29  
**شاخه مبنا:** `main`  
**commit مبنا:** `fab307aa271ce975bdaaf5fb156429adce743ac9`  
**نوع بررسی:** static architectural / functional / business / authorization review بر اساس کد و مستندات مخزن؛ این سند جایگزین اجرای کامل تست، تست مرورگر، تست نفوذ یا تأیید مالک کسب‌وکار نیست.

## 1. خلاصه مدیریتی

پروژه در وضعیت **MVP نسبتاً بالغ از نظر اسکلت فنی، ولی هنوز غیرعملیاتی برای داده واقعی** قرار دارد. معماری Django ماژولار است، مدل کاربر سفارشی، نقش‌ها، tenant/insurer scoping، گردش وضعیت درخواست، audit event، ورود Excel با preview/confirm، فایل خصوصی از مسیر view و رابط RTL وجود دارند.

نقطه قوت اصلی این است که پروژه از ابتدا با نگاه امنیت و جداسازی داده طراحی شده و بسیاری از قواعد مهم کسب‌وکار در مدل‌ها و querysetهای مشترک منعکس شده‌اند.

اما چند شکاف مهم وجود دارد که قبل از استفاده عملیاتی باید بسته شوند:

1. migrationهای نسخه‌بندی‌شده کامل در مخزن نیستند و باید تولید/بازبینی/commit شوند.
2. ماتریس مجوز هنوز به صورت یک policy مرکزی و قابل آزمون در همه endpointها و Admin تثبیت نشده است.
3. مدل کاربری `mfa_enabled` دارد اما MFA واقعی نیست.
4. تغییرات حساس افراد، شماره شبا و داده‌های سازمانی workflow تأیید کامل ندارند.
5. audit history برای تغییرات مهم دامنه به اندازه کافی سیستماتیک نیست.
6. فایل‌ها validation دارند اما malware scanning / quarantine / retention / storage policy کامل نیست.
7. import Excel هنوز synchronous است و برای حجم بالا یا پردازش طولانی مناسب production نیست.
8. dashboard و navigation نقش‌محور هستند، اما بعضی policyها در template به صورت شرط‌های تکراری نوشته شده‌اند و مستعد drift هستند.
9. مدل `Claim` قواعد مبلغی خوبی دارد، اما workflow تغییر وضعیت و actor/history آن هنوز هم‌سطح `ServiceRequest` نیست.
10. برای نسخه عملیاتی باید تست‌های منفی cross-company، cross-insurer، direct-file access، IDOR و role matrix به صورت exhaustive اجرا شوند.

**نتیجه کلی:** پایه پروژه خوب است و ارزش ادامه توسعه دارد؛ پیشنهاد نمی‌شود از صفر بازنویسی شود. بهترین مسیر، تثبیت policy/permission، workflowهای دامنه، audit/history، migration، فایل امن و تست جامع است و سپس تکمیل UX و گزارش‌ها.

## 2. چیزی که اکنون داریم

### فناوری و معماری

- Django 5.2.x، Python، Django ORM، server-rendered templates.
- PostgreSQL برای محیط غیرتوسعه‌ای و SQLite برای development.
- رابط فارسی و RTL با CSS مشترک.
- custom user model در `accounts.User`.
- middleware برای session/auth، اجبار تغییر رمز و محدودکردن Django Admin.
- CI برای Python 3.11 و 3.12.
- ساختار اپلیکیشنی domain-oriented.

### ماژول‌های موجود

- `accounts`: هویت، نقش، رمز، throttling.
- `organizations`: شرکت، کارکنان، وابستگان.
- `insurance`: بیمه‌گر، رشته، قرارداد و اصلاحیه.
- `claims`: خسارت و اعتراض.
- `requests_portal`: درخواست‌های بیمه‌شده و گردش وضعیت.
- `tasks`: وظایف داخلی و مهلت.
- `documents`: اسناد و دانلود کنترل‌شده.
- `imports`: ورود Excel و preview/confirmation.
- `auditlog`: رویداد حسابرسی.
- `assets`: دارایی بیمه‌شده.
- `announcements`: اطلاعیه.
- `correspondence`: مکاتبات.
- `dashboard`: داشبورد.
- `core`: permission و upload validation.

### UI / template structure

ساختار template شامل `base.html` و templateهای مجزا برای claims، requests، dashboard، documents، imports، organizations، insurance، tasks، assets، announcements، correspondence و registration است. این نشان می‌دهد separation در لایه نمایش از ابتدا در نظر گرفته شده است.

## 3. مدل نقش‌ها

نقش‌های فعلی:

| نقش | هدف کسب‌وکار | دامنه پیشنهادی |
|---|---|---|
| مدیر سامانه | تنظیمات، کاربران و کنترل فنی | privileged / administration |
| رئیس اداره بیمه | نظارت و تصمیم‌گیری سراسری | global business scope |
| کارشناس بیمه | رسیدگی عملیاتی | assigned/specialty scope |
| نماینده شرکت تابعه | عملیات شرکت خود | company scope |
| بیمه‌شده | پرونده و درخواست خود | self + authorized dependents |
| نماینده بیمه‌گر | پرونده‌های بیمه‌گر مرتبط | insurer scope |
| مالی | داده‌های مرتبط با مأموریت مالی | minimal scope |
| حقوقی | داده‌های مرتبط با مأموریت حقوقی | minimal scope |
| حسابرس | مشاهده برای audit | broad read-only / non-confidential where policy allows |

### نکته معماری مهم

`role` به تنهایی authorization نیست. scope باید از رابطه کاربر با company، insurer، person، assignment و confidentiality به دست بیاید. این اصل در `core.permissions` تا حد خوبی رعایت شده و باید به policy رسمی تبدیل شود.

## 4. مسیرهای اصلی کاربران

### 4.1 بیمه‌شده

`Login -> Password Change در صورت نیاز -> Dashboard -> Claims -> Claim Detail/Objection`  
یا  
`Dashboard -> Requests -> Create -> Tracking -> Detail`

داده مورد انتظار: فقط رکوردهای خود کاربر و وابستگان مجاز در همان company.

**وضعیت:** مسیر پایه وجود دارد و scoping برای claims و requests دیده می‌شود. برای production باید همه فرم‌ها و endpointهای جانبی نیز با همین scope تست شوند.

### 4.2 نماینده شرکت تابعه

`Login -> Dashboard -> Company-scoped Claims/Requests/People/Assets/Tasks -> Follow-up`

**وضعیت:** scoping شرکت برای claims و requests وجود دارد. باید برای assets، documents، correspondence، people و خروجی‌ها نیز به صورت یک policy یکپارچه اثبات شود.

### 4.3 کارشناس بیمه

`Login -> Queue -> Assigned/Unassigned Requests -> Review -> Need Info/Refer -> Head/Admin Decision`

برای درخواست‌ها workflow نسبتاً مشخص است و specialist نمی‌تواند تصمیم نهایی approved/rejected/completed/closed را بگیرد.

**نقطه قوت:** claim کردن درخواست unassigned در هنگام شروع review و استفاده از row lock برای جلوگیری از overwrite همزمان.

**نیاز:** assignment، SLA، escalation و ownership باید explicit شوند؛ «unassigned queue» در نسخه فعلی بیشتر یک رفتار view است تا یک workflow کامل.

### 4.4 رئیس اداره

`Dashboard -> Global queues -> Review -> Approve/Reject/Complete/Close -> Reports`

این نقش باید global business visibility داشته باشد ولی هنوز باید تصمیم گرفته شود کدام داده‌ها واقعاً برای او لازم است و کدام داده‌های حساس باید حداقل‌سازی شوند.

### 4.5 بیمه‌گر

`Login -> Insurer-scoped Claims -> Excel Import -> Tasks/Assets/Correspondence`

در import نیز insurer با `insurer_id` خود محدود می‌شود و افراد از طریق قراردادهای فعال آن بیمه‌گر محدود می‌شوند.

**ریسک:** policy بین import، list، detail، assets و documents باید با یک helper مرکزی مشترک شود تا اختلاف scope ایجاد نشود.

### 4.6 مالی / حقوقی / حسابرس

این نقش‌ها عمدتاً navigation و capability محدود دارند، اما محدودکردن لینک در template نباید کنترل امنیتی اصلی باشد. endpoint باید مستقل از UI مجوز را enforce کند.

## 5. منطق کسب‌وکار موجود

### خسارت

مدل Claim تفکیک مناسبی بین:

- مبلغ ثبت‌شده/درخواستی
- مبلغ ارزیابی‌شده
- مبلغ قابل پرداخت
- مبلغ پرداخت‌شده طبق منبع

دارد. همچنین قواعد non-negative و `paid <= payable` وجود دارد. تاریخ پرداخت بدون مبلغ نیز رد می‌شود.

این با اصل مهم محصول سازگار است که سامانه تراکنش بانکی انجام نمی‌دهد و فقط وضعیت اعلام‌شده از منبع معتبر را ثبت می‌کند.

### اعتراض خسارت

اعتراض برای employee و subsidiary representative قابل ثبت است و actor در audit event ثبت می‌شود.

**کمبود:** workflow کامل اعتراض (`open -> in_review -> answered -> closed`) در view فعلی به اندازه service request پیاده نشده است؛ پاسخ‌دهی، actor، deadline و تصمیم نهایی باید مسیر مشخص داشته باشد.

### درخواست‌ها

انواع درخواست شامل درمان، طرح بی‌نام، مازاد تعهدات، اصلاح هویت، شبا، افزایش/کاهش پوشش، فرم/مدرک و سایر موارد است.

گردش فعلی:

`submitted -> in_review / needs_info / referred / rejected`

`in_review -> needs_info / referred / approved / rejected / completed`

`needs_info -> in_review / rejected`

`referred -> in_review / approved / rejected`

`approved -> completed / closed`

`rejected -> closed`

`completed -> closed`

این ساختار برای MVP مناسب است ولی برای هر `kind` احتمالاً باید policy متفاوت داشته باشیم. مثلاً اصلاح شبا نباید دقیقاً همان workflow کمک‌هزینه درمان را داشته باشد.

### کمک‌هزینه درمان

در زمان ایجاد درخواست، `medical_assistance` محرمانه می‌شود. specialist به درخواست محرمانه دسترسی ندارد و queue آن برای privilegedها باقی می‌ماند.

این تصمیم معماری خوبی است، ولی باید دقیقاً مشخص شود چه کسی می‌تواند attachment، description، response و audit event محرمانه را ببیند.

### import Excel

فرآیند فعلی:

`Upload -> Parse -> Validate -> Collect errors + preview -> Create ImportBatch(VALIDATED) -> Explicit POST confirm -> Create Claims`

نقاط مثبت:

- محدودیت 10,000 ردیف.
- required headers.
- validation تاریخ و مبلغ.
- duplicate detection.
- tenant/insurer filtering.
- preview قبل از commit.
- transaction و `select_for_update` برای confirmation.
- batch audit event.

نقاط ضعف:

- parsing هنوز synchronous است.
- preview در JSON داخلی batch ذخیره می‌شود و برای حجم بالا می‌تواند سنگین شود.
- نسخه‌بندی import و rollback/reconciliation کامل نیست.
- malware scanning برای فایل Excel باید اضافه شود.
- import authorization باید دقیقاً مشخص کند system_admin/department_head چه محدوده‌ای را می‌توانند وارد کنند.

## 6. بررسی authorization

### موارد خوب

`scoped_claims_for` و `scoped_requests_for` مرز مهمی بین role و data scope ایجاد کرده‌اند. در claim detail نیز object از scoped queryset گرفته می‌شود، بنابراین تغییر ID به تنهایی نباید رکورد tenant دیگر را نشان دهد.

در request detail نیز object از scoped queryset گرفته می‌شود و هنگام update دوباره با `select_for_update` از همان scoped queryset خوانده می‌شود.

### ریسک‌های مهم

1. همه domainها helper scope معادل claims/requests ندارند.
2. UI capability در `dashboard/views.py` و `templates/base.html` به صورت دو منبع مستقل تعریف شده است.
3. بعضی شرط‌های template طولانی و مستعد خطای منطقی هستند.
4. Django Admin فقط برای system_admin/superuser باز شده، اما policy سطح مدل/field در Admin باید جداگانه بررسی شود.
5. export/report/API باید صریحاً همان scope را اعمال کند؛ مستندات هم این را requirement اعلام کرده‌اند.

### اولویت بالا

یک policy layer واحد پیشنهاد می‌شود:

- `can_view_claim(user, claim)`
- `scope_claims(user)`
- `can_view_person(user, person)`
- `scope_people(user)`
- `can_view_document(user, document)`
- `scope_documents(user)`
- `can_process_request(user, request)`
- `can_transition_request(user, request, target_status)`
- `can_edit_iban(user, person)`

و template فقط capabilityهای همین policy را مصرف کند.

## 7. بررسی مدل داده

### Company / Person

Unique constraint روی `(company, national_id)` تصمیم خوبی برای جلوگیری از ambiguity در tenant است. رابطه dependent به employee نیز company consistency را validate می‌کند.

**نیاز مهم:** وضعیت رابطه، تاریخ شروع/پایان پوشش، تاریخ استخدام/خروج، تاریخ تولد و تاریخ اعتبار پوشش در مدل کسب‌وکار واقعی باید مشخص شوند. در غیر این صورت تاریخچه پوشش قابل بازسازی نیست.

### User

وجود `company` و `insurer` روی User برای scoping مناسب است.

اما `mfa_enabled` صرفاً یک flag است و MFA واقعی نیست. نباید تا زمان پیاده‌سازی factor/secret/recovery code/verification flow به عنوان MFA محصول تلقی شود.

### Claim

مدل فعلی برای MVP خوب است ولی باید history داشته باشد. تغییر `assessed_amount`, `payable_amount`, `paid_amount`, `status`, `insurer`, `person` و `contract` باید قابل ردیابی باشد.

### ServiceRequest

مدل ساده و مناسب شروع است. برای production احتمالاً باید request history / transition model مستقل ایجاد شود تا به جای append کردن متن در `response`، eventهای ساختاریافته داشته باشیم.

### Task

Task فعلاً assignment و status دارد، اما scope امنیتی آن بسیار عمومی است. باید مشخص شود آیا task به company/person/request محدود است یا صرفاً task داخلی است.

## 8. فایل‌ها و امنیت storage

`MEDIA_ROOT` روی `private_media` تعریف شده و download اسناد از view کنترل می‌شود. این خوب است، ولی صرفاً private بودن directory کافی نیست.

باید تضمین شود web server هرگز `/private_media` را مستقیم سرو نکند.

همچنین برای همه uploadها نیاز داریم:

- MIME/content validation
- extension allowlist
- size limits
- filename normalization
- malware scanning
- quarantine قبل از release
- retention policy
- deletion policy
- access audit
- backup/restore policy

برای اسناد حساس، storage object-level authorization باید معیار پذیرش باشد.

## 9. UI / Template review

### نقاط مثبت

- `base.html` یک shell مشترک دارد.
- RTL و زبان فارسی در HTML صریحاً تعریف شده است.
- navigation بر اساس role محدود می‌شود.
- messages و logout POST با CSRF وجود دارد.
- templateهای domain جدا شده‌اند.

### مشکلات ساختاری

1. شرط‌های role در `base.html` بسیار طولانی هستند و تکرار دارند.
2. capability mapping در dashboard و template همگام‌سازی دستی دارد.
3. بعضی roleها در navigation لینک‌هایی دارند که باید با endpoint policy دوباره بررسی شوند.
4. هنوز evidence از browser acceptance در 360/390/430px وجود ندارد.
5. برای فرم‌های حساس، UX تأیید، هشدار، تاریخچه تغییر و وضعیت workflow باید واضح‌تر شود.
6. برای عملیات حساس بهتر است status badge، timeline و actor/history در UI first-class باشند.

### پیشنهاد طراحی

به جای role شرطی در template:

```text
navigation = policy.visible_navigation(user)
capabilities = policy.capabilities(user)
```

و template فقط render کند.

## 10. CI، migration و کیفیت release

CI وجود دارد و تست‌ها برای Python 3.11/3.12 طراحی شده‌اند، اما مستندات صریحاً هشدار می‌دهند که CI جایگزین migration واقعی نیست.

**Blocker:** migrationهای واقعی باید در Git موجود باشند، روی دیتابیس خالی و دیتابیس دارای داده تست شوند و قبل از release بررسی شوند.

همچنین باید در pipeline موارد زیر اضافه شوند:

- `python manage.py check --deploy`
- `makemigrations --check --dry-run`
- `migrate --check`
- test matrix نقش‌ها
- coverage threshold برای authorization/workflow
- dependency/security scan
- lint/format/type checks در صورت پذیرش تیم

## 11. ماتریس تست پیشنهادی

برای هر domain حداقل این ترکیب باید تست شود:

`Role × SameCompany × OtherCompany × SameInsurer × OtherInsurer × Self × Dependent × Unrelated × DirectURL × Download`

و برای workflow:

`CurrentStatus × TargetStatus × ActorRole × Assignment × Confidentiality`

حداقل سناریوهای ضروری:

- employee A نتواند claim employee B را با تغییر URL ببیند.
- employee A نتواند request employee B را ببیند.
- subsidiary A نتواند person/company B را ببیند.
- insurer A نتواند claim insurer B را ببیند.
- direct media URL بدون authorization قابل استفاده نباشد.
- confidential medical request برای specialist قابل مشاهده نباشد.
- specialist نتواند request را approved/rejected کند.
- invalid status transition رد شود.
- concurrent request update داده را overwrite نکند.
- duplicate import دو بار claim نسازد.
- invalid import هیچ partial rowی ایجاد نکند.
- تغییر شبا بدون workflow تأیید قابل ثبت نهایی نباشد.
- audit event برای تغییرات حساس ایجاد شود.

## 12. اولویت‌بندی کارها

### P0 — قبل از هر داده واقعی

1. migrationهای واقعی.
2. audit کامل authorization تمام endpointها.
3. private media deployment validation.
4. MFA واقعی و account recovery.
5. malware scanning / quarantine.
6. cross-tenant negative tests.
7. audit/history برای تغییرات حساس.
8. backup + restore drill.

### P1 — برای نسخه عملیاتی اول

1. workflow رسمی اصلاح هویت و IBAN.
2. workflow مستقل کمک‌هزینه درمان.
3. claim history و request transition history.
4. assignment/SLA/escalation برای task/request.
5. report/query/export با policy scope.
6. async import.
7. dashboard مدیریتی.
8. central authorization policy.

### P2 — بلوغ محصول

1. UX حرفه‌ای‌تر و component library.
2. notification center.
3. advanced search/filter.
4. saved views.
5. configurable workflows.
6. operational metrics.
7. archival/retention automation.

## 13. پیشنهاد معماری هدف

```text
                    Browser / RTL UI
                           |
                    Authentication
                           |
                Policy / Authorization Layer
                           |
        +------------------+------------------+
        |                  |                  |
   Domain Services      Query Scopes       Audit Events
        |                  |                  |
        +------------------+------------------+
                           |
                   Django Domain Apps
                           |
        +---------+--------+---------+---------+
        |         |        |         |         |
     Claims   Requests  People   Documents   Tasks
        |         |        |         |         |
        +---------+--------+---------+---------+
                           |
                  PostgreSQL / Private Storage
                           |
              Background Jobs / Import Queue
```

اصل مهم: **UI نباید منبع truth برای permission باشد؛ domain policy باید منبع truth باشد.**

## 14. تعریف وضعیت فعلی پروژه

**Architecture:** خوب / قابل ادامه  
**Domain modeling:** متوسط رو به خوب  
**Authorization foundation:** خوب، ولی incomplete  
**Workflow:** خوب برای MVP، ناقص برای production  
**Auditability:** متوسط  
**File security:** foundation موجود، production incomplete  
**Import:** MVP خوب، production ناقص  
**UI structure:** خوب، ولی role logic پراکنده  
**Testing:** foundation موجود، exhaustive authorization testing لازم  
**Deployment readiness:** هنوز آماده production نیست  

## 15. تصمیم پیشنهادی برای ادامه

بازنویسی کامل توصیه نمی‌شود. پروژه باید به صورت مرحله‌ای تثبیت شود:

**مرحله 1:** Permission/Policy مرکزی + migration + authorization tests  
**مرحله 2:** Workflowهای حساس + audit/history  
**مرحله 3:** private files + malware scanning + MFA/recovery  
**مرحله 4:** async imports + reports + dashboard  
**مرحله 5:** UI/UX polish + browser acceptance + release hardening

این سند باید در هر بازبینی عمده به‌روزرسانی شود و به عنوان baseline تصمیم‌گیری توسعه استفاده شود.
