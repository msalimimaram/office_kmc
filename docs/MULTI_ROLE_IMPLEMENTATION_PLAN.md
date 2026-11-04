# طرح معماری و مهاجرت امن به مدل چندنقشی — اداره بیمه

**نسخه:** 0.1  
**وضعیت:** طرح اجرایی مبتنی بر قواعد تأییدشده کسب‌وکار  
**اسناد مرجع:** `PRODUCT_SPEC.md`, `docs/BUSINESS_RULES_AND_WORKFLOWS.md`, `docs/ACCESS_CONTROL_MATRIX.md`, `docs/WORKFLOW_CATALOG.md`

## 1. مسئله نسخه فعلی

بازبینی کد فعلی نشان می‌دهد مدل عملیاتی هنوز با قواعد جدید هم‌راستا نیست:

- `accounts.User` یک فیلد واحد `role` دارد؛ نقش‌های مالی/حقوقی/حسابرس نیز هنوز در choices وجود داشتند.
- `User.company` و `User.insurer` هر کدام یک رابطه مستقیم هستند و برای چند انتصاب/چند محدوده و انتخاب شرکت فعال کافی نیستند.
- `Person` مستقیماً به یک شرکت وصل است؛ تاریخچه اشتغال و انتقال شرکت در مدل مستقل نگهداری نمی‌شود.
- قواعد دسترسی در چند view و helper بر اساس `user.role` تکرار شده‌اند؛ نمونه‌های بررسی‌شده: `core/permissions.py`, `core/policies.py`, `dashboard/views.py`, `assets/views.py`, `documents/views.py`, `correspondence/views.py`, `announcements/views.py`, `organizations/views.py`.
- قرارداد و بیمه‌نامه اجرایی در مدل فعلی به اندازه کافی از هم تفکیک نشده‌اند.
- مدل خسارت یک مقدار تجمعی `paid_amount` و یک `payment_date` دارد؛ برای پرداخت‌های مرحله‌ای رکورد مستقل لازم است.
- درخواست‌ها وضعیت و مسئول جاری دارند، اما تاریخچه ساختاریافته هر ارجاع، مشاهده، تأیید رسمی مشاهده، اقدام و پاسخ به‌صورت مستقل مدل نشده است.
- `InternalTask` تاریخچه کامل انتقال مسئولیت و رویدادهای زمانی را ندارد.
- مدل مکاتبات شماره‌گذاری داخلی ترتیبی و مشترک روزانه را به‌صورت سرویس اتمیک مدل نکرده است.
- مدل اسناد فعلی برای نسخه‌بندی، سطح محرمانگی چهارگانه و ثبت دسترسی فایل به تکمیل نیاز دارد.
- ورود Excel به قالب‌های نسخه‌دار و فیلدهای قابل‌تعریف متصل نیست.
- مدل ممیزی باید در Admin و مسیرهای دیگر واقعاً append-only شود؛ ثبت رویداد به‌تنهایی تضمین تغییرناپذیری نیست.

این‌ها یافته‌های ایستا از کد هستند؛ هنوز تست اجرایی روی محیط Django و پایگاه داده عملیاتی انجام نشده است.

## 2. مدل دامنه پیشنهادی

### 2.1 هویت و اشخاص

#### Person
هویت حقیقی مستقل از شرکت و حساب:
- national_id (UniqueConstraint سراسری و نرمال‌سازی‌شده)
- نام، نام خانوادگی، تاریخ تولد، موبایل و اطلاعات پایه
- وضعیت هویتی و زمان ایجاد/آخرین اصلاح

کد ملی باید پیش از ذخیره نرمال شود و فقط مقدار canonical (۱۰ رقم) نگهداری شود. تغییر کد ملی نباید عملیات معمول ویرایش باشد؛ مسیر اصلاح هویت با تأیید و ثبت سابقه لازم دارد.

#### User
حساب ورود:
- OneToOne یا رابطه کنترل‌شده با Person
- وضعیت فعال، رمز، نیاز به تغییر رمز، MFA و نشست‌ها
- بدون فیلد role به‌عنوان منبع نهایی مجوزدهی
- username برای بیمه‌شده اصلی از کد ملی canonical تعیین می‌شود.

افراد تحت تکفل Person دارند ولی User مستقل ندارند.

#### PersonEmployment
تاریخچه اشتغال:
- person
- company
- organizational_unit (اختیاری)
- job_title / employment_type
- start_date و end_date
- status (active, transferred, retired, terminated)
- source/import reference
- created_by / approved_by / audit fields

انتقال، رکورد اشتغال قبلی را نمی‌نویسد؛ اشتغال جدید ساخته می‌شود.

#### PersonRelationship
رابطه بیمه‌شده اصلی و وابسته:
- primary_person
- dependent_person
- relationship_type (spouse, child, father, mother)
- valid_from / valid_until
- status

در صورت وجود سیاست مجاز، یک شخص وابسته می‌تواند در دوره‌های مختلف یا با شرایط تعریف‌شده به بیش از یک بیمه‌شده مرتبط باشد؛ قیود دقیق باید از تصمیم کسب‌وکار تبعیت کند.

### 2.2 ساختار سازمانی و انتصاب دسترسی

#### OrganizationalUnit
درخت اداره بیمه و زیرواحدها:
- parent
- name, code, is_active
- scope/line restrictions

#### OrganizationalPosition
عنوان سمت:
- معاونت، مدیر، رئیس، سرپرست، مسئول، کارشناس
- ترتیب سلسله‌مراتب
- نوع سمت و ظرفیت

#### Role
نقش عملیاتی مستقل از عنوان سمت:
- system_admin
- department_head
- insurance_specialist
- subsidiary_representative
- insurer_representative
- insured_person

نقش‌های مالی، حقوقی و حسابرس تعریف نمی‌شوند.

#### RoleAssignment
انتصاب مجوز:
- user/person
- role
- company (nullable)
- insurer (nullable)
- organizational_unit (nullable)
- position (nullable)
- insurance_lines (از طریق رابطه M2M)
- valid_from / valid_until
- status
- granted_by / approved_by
- reason
- scope metadata

قواعد مهم:
- نماینده شرکت باید به شرکت مشخص متصل باشد و شخص در همان شرکت اشتغال معتبر داشته باشد.
- چهار جایگاه عادی شرکت (کل، درمان/عمر، خودرو، مسئولیت/آتش) کنترل شوند.
- استثنای چندشرکتی به‌صورت یک AuthorizationException مستقل با دلیل، شرکت‌ها، رشته‌ها، بازه اعتبار، صادرکننده و تأییدکننده ثبت شود.
- انتصاب چندرشته‌ای کارشناس باید مجوز رئیس اداره/مدیر سامانه داشته باشد.
- پایان اعتبار انتصاب، مجوز ناشی از آن را در لحظه درخواست متوقف کند.
- انتخاب شرکت فعال، فقط از انتصاب‌های معتبر مجاز انجام شود؛ شرکت فعال در session ذخیره و در هر درخواست سمت سرور اعتبارسنجی شود.

#### PermissionGrant / WorkflowPermission
مجوز اقدام قابل پیکربندی:
- role/assignment/organizational level
- workflow type
- action (view, create, edit, approve, reject, refer, close, lock, export)
- company/line scope
- constraints and validity
- granted_by, approved_by

اختیار تأیید و رد معاون/مدیر/سرپرست/مسئول برای هر نوع پرونده به‌صورت مستقل تعریف می‌شود.

### 2.3 رشته، قرارداد، بیمه‌نامه و پوشش

#### InsuranceLine
به‌جای choices ثابت، جدول قابل مدیریت:
- code, name, is_active, configuration/version
- created_by / approved_by

فقط مدیر سامانه امکان ایجاد رشته جدید و تعریف فیلدهای اصلی آن را دارد.

#### InsuranceContract
قرارداد مادر با بیمه‌گر، رشته، شماره، تاریخ اعتبار، شرایط، نسخه و وضعیت.

#### InsurancePolicy
بیمه‌نامه اجرایی:
- contract
- insurer
- company
- location/site (مثل دفتر تهران یا کارخانه)
- policy_number, dates, status
- dynamic attributes

برای درمان و عمر قرارداد مادر مشترک مجموعه می‌تواند چند بیمه‌نامه اجرایی متعلق به شرکت‌ها/محل‌ها داشته باشد. سایر رشته‌ها قرارداد/بیمه‌نامه مستقل برای شرکت و بیمه‌گرهای مختلف دارند.

#### ContractEndorsement / ContractRevision
الحاقیه و نسخه با تاریخ اثر، سند، شرح تغییر، نویسنده، تأییدکننده و اثرات محاسبه‌شده.

#### ContractTermination
درخواست فسخ:
- target contract/policy
- reason, requested_at, notification_date, effective_date
- supporting documents
- open claims/coverage impact snapshot
- specialist, head approval
- status and audit events

#### PersonCoverage
پوشش شخص:
- person/dependent
- insurance_line
- policy
- contract revision at relevant date
- coverage_start/end
- plan, coverage attributes, status
- source and evidence metadata

### 2.4 خسارت، اعتراض و پرداخت

#### Claim
خسارت اصلی با اتصال به:
- person (بیمار)
- primary insured
- employer/company history at event date
- line, policy, contract revision, insurer
- source claim reference and dates
- amount fields separately
- source duplicate declaration fields

کلیدهای مورد توجه بیمه‌گر (بیمه‌گر، شماره پرونده، کد ملی بیمار، شماره قرارداد، تاریخ ثبت، تاریخ خسارت) ذخیره و نمایش داده می‌شوند. سامانه صرفاً بر اساس تطبیق این داده‌ها تکراری بودن را قطعی نمی‌کند؛ وضعیت duplicate باید از منبع بیمه‌گر برسد.

#### ClaimPayment
هر مرحله پرداخت یک رکورد:
- claim
- amount, paid_at
- source insurer/reference
- source document
- recorded_by, confirmed_by
- status/reversal reference

مبلغ پرداخت‌شده Claim از مجموع پرداخت‌های مستقل حاصل می‌شود. اصلاح پرداخت قبلی با رویداد جبرانی/اصلاحی انجام می‌شود، نه حذف یا بازنویسی خام.

#### ClaimObjection
اعتراض مستقل با تاریخ ارسال نتیجه اولیه، deadline = sent_at + 60 روز تقویمی، دلیل، پرونده، وضعیت، گردش و پاسخ.

### 2.5 موتور گردش کار

#### WorkflowDefinition / WorkflowVersion
قالب گردش کار:
- نوع دامنه (درخواست، خسارت، اعتراض، قرارداد، مکاتبه، تغییر اطلاعات و ...)
- نسخه، وضعیت انتشار، ایجادکننده و تأییدکننده
- effective_from / retired_at

#### WorkflowStep
- کد، عنوان، ترتیب نمایشی
- مسئول‌های مجاز (role/position/line)
- مهلت SLA
- اقدامات ممکن
- شرایط ورود/خروج

#### WorkflowTransition
- source step
- action
- target step
- مجاز بودن بازگشت/ارجاع
- مقصدهای مجاز
- شرط و اعتبارسنجی

#### WorkflowInstance
نمونه اجرایی روی یک رکورد کسب‌وکار:
- workflow_version
- object reference
- current step/status
- current assignee/organizational unit
- opened_at, closed_at, locked_at
- SLA calendar version
- current ownership

#### WorkflowEvent
جدول append-only رویدادها:
- instance
- actor and actor assignment
- action, previous/next status
- from/to assignee and step
- explanation
- occurred_at
- source and target event refs

برای مشاهده:
- هر بازشدن صفحه رویداد VIEWED مستقل دارد.
- تأیید رسمی مشاهده رویداد ACKNOWLEDGED مستقل دارد.
- اولین اقدام رویداد FIRST_ACTION دارد.
- پاسخ و ارجاع بعدی نیز رویداد مستقل دارند.

ارجاع موفق، assignee جاری را اتمیک تغییر می‌دهد. فرستنده بعد از ارجاع فقط مشاهده می‌کند مگر دوباره تخصیص بگیرد.

### 2.6 تقویم و SLA

#### WorkCalendar / Workday / Holiday
تقویم مشترک مجموعه با:
- روزهای کاری؛
- ساعت شروع و پایان؛
- تعطیلات رسمی و موردی؛
- نسخه‌بندی و تاریخ اعتبار.

SLA هرگز pause نمی‌شود. زمان انتظار برای گزارش مدیریتی جدا ثبت می‌شود ولی از ساعت محاسبه SLA کم نمی‌شود.

شاخص‌ها:
- پرونده از ثبت تا پایان؛
- هر مرحله از ارجاع تا پایان؛
- هر فرد از ارجاع تا مشاهده، مشاهده تا اقدام و اقدام تا پاسخ؛
- زمان انتظار بیرونی به‌صورت تفکیکی، بدون توقف SLA.

### 2.7 فرم پویا و Excel

#### FieldDefinition / FieldOption
- domain/module/insurance line
- code/name/type
- required, validation schema, options
- display order, sensitivity classification
- searchable/reportable flags
- version/effective dates
- created_by / approved_by (مدیر سامانه)

#### ExcelTemplate / ExcelTemplateVersion
- scope/line
- ordered field mappings
- headers, data types, required, instructions
- date/currency formatting
- version and active state

سیستم نمونه Excel را از نسخه قالب تولید می‌کند و هر batch را به همان نسخه متصل می‌سازد.

#### ImportBatch / ImportRow / ImportDecision
- uploaded file, uploader, source insurer, template version
- preview rows, validation errors, row index, column key
- per-row action: create, ignore, field_merge, whole_record_replace
- previous/new values snapshot
- approved_by, applied_at, rollback/reconciliation reference

مقادیر قبلی پاک نمی‌شوند. تشخیص تکرار به اعلام بیمه‌گر وابسته است.

### 2.8 اسناد و مکاتبات

#### Document / DocumentVersion / DocumentAccessEvent
- file private storage
- four-level security classification
- business object relation
- version chain
- created_by, approved_by, reason
- view/preview/download/print/export events

مدارک پزشکی اصل فقط رئیس اداره و مدیر سامانه؛ گیرنده ارجاع فقط اطلاعات حداقلی.

#### CorrespondenceNumberSequence
شمارنده مشترک روزانه برای تمام مکاتبات:
- Persian/Gregorian date mapping
- daily sequence with row lock and unique constraint
- format `YYYYMMDDNNN` (sequence expands if needed)
- inbound/outbound use the same sequence
- never recycle numbers.

#### CorrespondenceRelation / CorrespondenceEvent
ارتباط چندبه‌چند مکاتبه با پرونده، شرکت، قرارداد، خسارت و درخواست؛ به‌علاوه رویدادهای پیگیری و مسئول.

### 2.9 اعلان، گزارش و ممیزی

- NotificationPreference برای انتخاب اعلان‌های کاربر؛ خاموش بودن اعلان، ثبت رویدادهای عملیاتی و ممیزی را متوقف نمی‌کند.
- ReportDefinition و ReportRun برای گزارش‌ساز، فیلترها، نسخه خروجی و گردش تأیید سلسله‌مراتبی.
- PerformanceMetric snapshots یا محاسبه قابل بازتولید از WorkflowEventها.
- AuditEvent append-only با ثبت actor، زمان، object، قبل/بعد، دلیل و correlation id.
- Admin باید فقط خواندن/عملیات کنترل‌شده داشته باشد؛ هیچ مسیر عادی برای ویرایش یا حذف AuditEvent نباشد.

## 3. راهبرد مهاجرت بدون از دست دادن داده

1. از پایگاه داده عملیاتی backup قابل بازیابی گرفته شود و restore آزمایش شود.
2. تعداد کاربران هر role فعلی، شرکت/بیمه‌گر متصل، کد ملی‌های تکراری، اشخاص فاقد اتصال و اشتباهات رابطه dependent استخراج شود.
3. برای هر User موجود، Person مرکزی بر اساس کد ملی canonical تطبیق/ایجاد شود.
4. نقش فعلی به RoleAssignment تبدیل شود، فقط در صورتی که معادل کسب‌وکاری معتبر داشته باشد.
5. نقش‌های finance/legal/auditor به‌صورت خودکار به employee تبدیل نشوند. حساب‌های دارای این نقش‌ها باید غیرفعال و برای تعیین تکلیف دستی گزارش شوند؛ داده و سابقه آنان حذف نمی‌شود.
6. User.company/insurer به انتصاب‌های scopeدار تبدیل شود؛ ناسازگاری یا چندشرکتی بودن به فهرست بررسی دستی منتقل شود.
7. Person.company به PersonEmploymentهای تاریخ‌دار تبدیل شود؛ تا زمانی که داده انتقال قابل اعتماد نیست، سابقه‌های حدسی ایجاد نشوند.
8. قبل از حذف فیلدهای legacy، تمام viewها، forms، dashboardها، admin، tests، templates و import scopes باید از RoleAssignment/central policy استفاده کنند.
9. نسخه سازگاری موقت فقط در دوره مهاجرت وجود دارد و پس از انتقال کامل حذف می‌شود.
10. مهاجرت روی یک کپی دیتابیس واقعی اجرا و گزارش رکوردهای نامتصل/مبهم تأیید می‌شود.
11. Rollback به معنی بازگردانی backup یا migration معکوس آزموده‌شده است؛ در هیچ مرحله داده عملیاتی بدون نسخه پشتیبان حذف نمی‌شود.

## 4. ترتیب پیاده‌سازی

### فاز 0 — حفاظت و ممیزی
- تثبیت snapshot و backup/restore plan؛
- فهرست مسیرهای استفاده‌کننده از `user.role`؛
- فهرست Admin bypassها؛
- تست پایه مجوز و migration؛
- شناسایی داده‌های موجود که به نقش‌های حذف‌شده متصل‌اند.

### فاز 1 — هویت، اشتغال و چندنقشی
- Person canonical با unique national ID؛
- PersonEmployment و PersonRelationship؛
- RoleAssignment و OrganizationalUnit/Position؛
- active company selector؛
- انتقال داده قدیمی و خاموش‌سازی امن نقش‌های حذف‌شده؛
- مهاجرت تمام view و policyها به مجوز متمرکز.

### فاز 2 — موتور گردش کار و SLA
- workflow definition/version/step/transition;
- instance/event/assignment;
- timestamps for view/ack/action/reply;
- calendar and non-pausing SLA;
- mobile change request workflow as first complete reference process.

### فاز 3 — بیمه و خسارت
- contract/policy/endorsement/termination;
- person coverage;
- claim payments and source duplicate flag;
- objections and 60-day deadline.

### فاز 4 — فیلدهای پویا و ورود گروهی
- field schema;
- template version and Excel sample generator;
- preview, per-row validation, merge/replace/ignore;
- insurer-declared duplicate metadata.

### فاز 5 — اسناد و عملیات اداری
- versioned documents and fine-grained access events;
- correspondence number sequence;
- task delegation and hierarchy;
- notifications.

### فاز 6 — گزارش و پذیرش
- report builder and approval workflow;
- performance analytics;
- positive/negative authorization matrix;
- security, concurrency, performance and restore tests.

## 5. دروازه پذیرش هر فاز

هیچ فاز صرفاً به دلیل تکمیل کد پذیرفته نمی‌شود. برای پذیرش لازم است:
- migration از DB خالی و DB دارای داده موفق باشد؛
- تست‌های unit، integration و permission pass شوند؛
- دسترسی متقاطع شرکت/بیمه‌گر/رشته رد شود؛
- مسیر Admin همان سیاست‌های کنترل را رعایت کند؛
- نسخه قبلی داده و تاریخچه حفظ شود؛
- خطا و rollback مستند باشد؛
- `python manage.py check` و `makemigrations --check` اجرا شوند؛
- تست‌های workflow و concurrency مربوطه اجرا شوند.

**محدودیت فعلی:** ابزار اتصال GitHub در این مرحله امکان بازبینی و ثبت فایل‌ها را می‌دهد، اما اجرای محلی Django، PostgreSQL، migration و تست runtime انجام نشده است. هرگونه ادعای موفقیت اجرایی باید پس از اجرای واقعی این دروازه‌ها انجام شود.
