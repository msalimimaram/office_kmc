# ماتریس ردیابی نیازمندی‌ها — Office KMC

**نسخه:** 1.0  
**تاریخ baseline:** 2026-11-20  
**HEAD بررسی‌شده:** `0d5c987965044add29a6db871a53164cefeec380`  
**مبنای بررسی:** اسناد کسب‌وکار و معماری به‌همراه بررسی ایستای فایل‌های کد و تست  
**محدودیت:** این ماتریس گزارش اجرای تست یا تأیید عملیاتی نیست.

## راهنمای وضعیت

- **STATIC_PRESENT:** مدل/سرویس/مسیر یا تست مرتبط در سورس دیده شده؛ رفتار runtime هنوز باید اثبات شود.
- **PARTIAL:** بخشی از نیازمندی وجود دارد، اما مسیر کامل یا پوشش پذیرش اثبات نشده است.
- **NEEDS_DECISION:** رفتار نهایی به تصمیم مالک کسب‌وکار/امنیت/زیرساخت نیاز دارد.
- **UNVERIFIED:** بدون اجرای آزمون یا بررسی محیط واقعی نمی‌توان وضعیت را تأیید کرد.
- **OUT_OF_SCOPE:** عمداً در دامنه تکمیل فعلی نیست.

وجود یک کلاس یا تست در ستون شواهد به معنی PASS شدن آن نیست.

## ماتریس

| شناسه | نیازمندی/قاعده | شواهد ایستا در مخزن | وضعیت baseline | فاز |
|---|---|---|---|---|
| GOV-01 | فقط main شاخه توسعه مرجع باشد | GitHub branches API: فقط main | STATIC_PRESENT | 0 |
| GOV-02 | GitHub Actions ایجاد/استفاده نشود | درخت فعلی فاقد .github/workflows؛ اجراهای تاریخی تا 2026-10-29 | STATIC_PRESENT | 0 |
| GOV-03 | نقش‌های مالی، حقوقی و حسابرس نقش فعال نباشند | شش گزینه در User.Role و RoleAssignment.Role؛ اسناد تاریخی قدیمی | STATIC_PRESENT؛ پاکسازی برچسب اسناد | 0 |
| GOV-04 | هر فاز معیار خروج مستقل داشته باشد | MASTER_COMPLETION_ROADMAP و این گزارش | STATIC_PRESENT | همه |
| ID-01 | هویت شخص حقیقی با کد ملی یکتا باشد | organizations.Person؛ accounts.User.national_id قدیمی | PARTIAL؛ آزمون یکتایی/مهاجرت لازم | 2 |
| ID-02 | حساب از شخص، اشتغال، سمت و پوشش جدا باشد | User، Person، PersonEmployment، PositionAssignment، RoleAssignment | STATIC_PRESENT؛ یکپارچگی مسیرها نیازمند آزمون | 2 |
| ID-03 | افراد تحت تکفل از حساب بیمه‌شده اصلی استفاده کنند | PersonRelationship و قواعد کسب‌وکار | PARTIAL؛ آزمون کامل دسترسی لازم | 2 |
| ID-04 | فرد فاقد پوشش و انتصاب معتبر حساب فعال غیرضروری نداشته باشد | قواعد کسب‌وکار؛ مسیرهای حساب نیازمند ردیابی کامل | UNVERIFIED | 2 |
| ID-05 | رمز اولیه موبایل و تغییر اجباری اولین ورود | User.mobile، must_change_password و middleware | STATIC_PRESENT؛ آزمون نقش‌محور لازم | 2 |
| ID-06 | MFA واقعی برای نقش‌های مصوب | فقط فیلد mfa_enabled در مدل دیده شده؛ MFA واقعی اثبات نشده | NEEDS_DECISION + UNVERIFIED | 2/7 |
| ORG-01 | اشتغال چنددوره‌ای و انتقال بین شرکت‌ها حفظ شود | PersonEmployment و قید یکتایی اشتغال فعال | STATIC_PRESENT؛ سناریوهای انتقال نیازمند آزمون | 2 |
| ORG-02 | سمت سازمانی با مجوز دسترسی یکی نباشد | OrganizationalUnit، OrganizationalPosition، PositionAssignment | STATIC_PRESENT | 2 |
| ORG-03 | نماینده شرکت وابسته به همان شرکت باشد | RoleAssignment با company scope و validation | STATIC_PRESENT؛ تست کامل scope لازم | 2 |
| ORG-04 | سقف سه نماینده برای هر شرکت رعایت شود | قاعده در نیازمندی؛ enforcement ایستا در این بررسی اثبات نشده | UNVERIFIED | 2 |
| ORG-05 | استثنای چندشرکتی با دلیل، شرکت/رشته و اعتبار زمانی تأیید شود | RoleAssignment scope و valid dates؛ مسیر exception کامل نیازمند بررسی | PARTIAL | 2 |
| ORG-06 | سمت مدیران شرکت تابعه با شرکت/اشتغال و تاریخچه تطبیق داشته باشد | CompanyLeadershipPosition، CompanyLeadershipTitle و PersonEmployment | STATIC_PRESENT؛ runtime لازم | 2 |
| AUTH-01 | مجوزها از انتصاب معتبر و scope شرکت/بیمه‌گر/رشته حاصل شوند | RoleAssignment و accounts access architecture | PARTIAL؛ مهاجرت همه views/adminها نیازمند audit | 2 |
| AUTH-02 | انقضا/لغو انتصاب فوراً اقدام جدید را منع کند | valid_from/valid_until/is_active و تست‌های workflow | STATIC_PRESENT؛ اجرای تست لازم | 2 |
| AUTH-03 | کاربر پس از ارجاع حق اقدام جاری را از دست بدهد | WorkflowEvent و تست previous assignee | STATIC_PRESENT؛ runtime لازم | 3 |
| AUTH-04 | دسترسی cross-company و cross-insurer بسته باشد | scopeهای workflow و تست‌های موجود | PARTIAL؛ تست جامع همه endpointها لازم | 2 |
| AUTH-05 | superuser فنی به‌تنهایی مجوز تصمیم کسب‌وکاری نداشته باشد | تست‌های workflow و سیاست دسترسی | PARTIAL؛ ممیزی کامل admin bypass لازم | 2 |
| AUTH-06 | تغییر مجوز و انتصاب audit شود و تاریخچه حذف نشود | RoleAssignment محافظت‌شده و AuditEvent | STATIC_PRESENT؛ آزمون دورزدن ORM لازم | 2 |
| PII-01 | تغییر موبایل با زنجیره بیمه‌شده ← نماینده شرکت ← بیمه‌گر ← نماینده شرکت انجام شود | قواعد کسب‌وکار و PersonChangeRequest؛ پوشش end-to-end کامل اثبات نشده | PARTIAL | 3 |
| PII-02 | اصلاح اطلاعات هویتی/تماس/شبا با تأیید مجاز و ثبت قبل/بعد باشد | PersonChangeRequest و workflow؛ مجوزهای اخیر اصلاح شده‌اند | PARTIAL؛ regression runtime لازم | 3 |
| PII-03 | نماینده شرکت نتواند درخواست بیمه‌گر را نهایی ببندد | Workflow transition rules و تست insurer cannot close | STATIC_PRESENT؛ runtime لازم | 3 |
| WF-01 | گردش‌ها نسخه‌دار و تغییر پس از انتشار محدود باشد | WorkflowDefinition/Step/Transition و تست immutable | STATIC_PRESENT | 3 |
| WF-02 | زمان اولین مشاهده و اولین اقدام ثبت شود | WorkflowCase و تست SLA/first view/first action | STATIC_PRESENT؛ runtime لازم | 3 |
| WF-03 | SLA در WAITING متوقف نشود | workflow test با نام test_sla_deadline_keeps_running_while_waiting_for_expert_and_first_view_is_recorded | STATIC_PRESENT؛ runtime لازم | 3 |
| WF-04 | SLA بر اساس تقویم کاری/تعطیلات و escalation محاسبه شود | BusinessCalendar و CalendarHoliday | PARTIAL؛ آستانه‌ها و escalation نیازمند تصمیم | 3 |
| WF-05 | تفویض دارای اعتبار، scope، provenance و لغو قابل حسابرسی باشد | اپ delegations و migrationهای workflow | STATIC_PRESENT؛ پذیرش end-to-end لازم | 3 |
| CLM-01 | تکراری بودن خسارت فقط با اعلام بیمه‌گر ثبت شود | Claim.DuplicateStatus و source_duplicate_*؛ constraint الزام insurer | STATIC_PRESENT | 4 |
| CLM-02 | پرداخت‌های مرحله‌ای و برگشت پرداخت تاریخچه مستقل داشته باشند | ClaimPayment و constraintهای مبلغ/برگشت | STATIC_PRESENT؛ reconciliation لازم | 4 |
| CLM-03 | اعتراض خسارت و مهلت آن گردش کامل داشته باشد | ClaimObjection و Workflow | PARTIAL؛ پذیرش مهلت/استثنا لازم | 4 |
| INS-01 | قرارداد و الحاقیه نسخه‌دار و تأییدشده باشند | Contract و ContractRevision | STATIC_PRESENT؛ آزمون چرخه عمر لازم | 4 |
| INS-02 | تغییر/فسخ قرارداد در تاریخ اثر اعمال و تاریخچه حفظ شود | مدل lifecycle و دستورات زمان‌بندی | PARTIAL؛ staging لازم | 4/7 |
| IMP-01 | ورود Excel دارای preview، validation، تأیید و reconciliation باشد | imports.ImportBatch و اپ imports | PARTIAL؛ تست داده واقعی‌نما لازم | 4 |
| IMP-02 | تعارض import بدون حذف یا overwrite سابقه متوقف شود | مدل batch و مستندات؛ runtime proof لازم | UNVERIFIED | 4 |
| DOC-01 | اسناد نسخه‌دار و تاریخچه آن‌ها حفظ شود | DocumentRecord، DocumentVersion و constraint نسخه جاری | STATIC_PRESENT؛ runtime لازم | 5 |
| DOC-02 | فایل محرمانه فقط از مسیر مجاز مشاهده/دانلود شود | DocumentAccessEvent و کنترل‌های view | PARTIAL؛ آزمون مستقیم URL و وب‌سرور لازم | 5/7 |
| DOC-03 | فایل قبل از ذخیره با ClamAV اسکن شود و failure fail-closed باشد | config الزام CLAMD_HOST در production | PARTIAL؛ آزمون ClamAV واقعی لازم | 5/7 |
| DOC-04 | محرمانگی پزشکی در همه payloadها و خروجی‌ها رعایت شود | ServiceRequest constraint و تست workflow برای عدم افشای شرح پزشکی | STATIC_PRESENT؛ آزمون جامع لازم | 2/5 |
| COR-01 | دفتر ثبت مکاتبات وارده/صادره/داخلی موجود باشد | Correspondence و Direction | STATIC_PRESENT | 5 |
| COR-02 | شماره داخلی روزانه با قفل تراکنشی تولید شود | CorrespondenceSequence و next_internal_number/select_for_update | STATIC_PRESENT؛ concurrency test لازم | 5/7 |
| COR-03 | مکاتبه به پرونده/شرکت/بیمه‌گر لینک و پیگیری شود | CorrespondenceLink، CorrespondenceEvent، follow-up tests | STATIC_PRESENT؛ UAT لازم | 5 |
| COR-04 | تولید نامه رسمی، سربرگ، امضا، PDF رسمی و گردش تأیید حقوقی | در سورس فعلی اثبات نشده؛ در roadmap خارج از دامنه | OUT_OF_SCOPE | Backlog |
| AUD-01 | رخدادهای ممیزی append-only و قابل ردیابی باشند | auditlog.AuditEvent و queryset محافظت‌شده | STATIC_PRESENT؛ آزمون امنیت لازم | 5 |
| REP-01 | KPIهای مدیریتی تعریف و قابل تطبیق باشند | reports و dashboard apps | PARTIAL؛ تعریف KPI و مالک نیازمند تصمیم | 6 |
| OPS-01 | PostgreSQL در production اجباری باشد | config/settings.py | STATIC_PRESENT؛ اجرای staging لازم | 7 |
| OPS-02 | throttle ورود بین چند worker مشترک باشد | Redis cache در تنظیمات production | STATIC_PRESENT؛ آزمون چندپردازه لازم | 7 |
| OPS-03 | backup رمزگذاری‌شده و restore عملیاتی باشد | مستندات و deployment runbook | UNVERIFIED؛ RPO/RTO نیازمند تصمیم | 7 |
| OPS-04 | هدف 1000 کاربر هم‌زمان با SLO قابل سنجش باشد | هدف کسب‌وکار ثبت شده؛ workload/SLO تعریف نشده | NEEDS_DECISION | 7 |
| OPS-05 | مانیتورینگ، هشدار و incident response عملیاتی باشد | مستندات deployment؛ محیط واقعی بررسی نشده | UNVERIFIED | 7 |
| REL-01 | پذیرش نقش‌محور end-to-end و Go/No-Go رسمی انجام شود | کاتالوگ workflow و roadmap | UNVERIFIED | 8 |

## تصمیم‌های باز مالک کسب‌وکار/امنیت/زیرساخت

| شناسه | تصمیم لازم | پیشنهاد برای تهیه تصمیم | مالک تصمیم |
|---|---|---|---|
| DEC-01 | تعریف 1000 کاربر هم‌زمان | تعیین نرخ درخواست، الگوی عملیات، پیک و SLO پاسخ/خطا | مالک محصول + زیرساخت |
| DEC-02 | RPO/RTO و retention پشتیبان | تعیین حداکثر از دست‌رفتن داده و زمان بازیابی مجاز | زیرساخت + اداره بیمه |
| DEC-03 | MFA | تعیین نقش‌های اجباری، روش عامل دوم و بازیابی امن | امنیت + مالک محصول |
| DEC-04 | SLA و تقویم | تعیین مهلت هر گردش، تعطیلات و escalation | رئیس اداره بیمه |
| DEC-05 | شماره‌گذاری مکاتبات | تفکیک یا اشتراک سری وارده/صادره/داخلی و نقطه تخصیص شماره رسمی | اداره بیمه |
| DEC-06 | KPI | فهرست شاخص، فرمول، فیلتر و مالک تأیید عدد | رئیس اداره بیمه |
| DEC-07 | نگهداری سوابق | مدت نگهداری و آرشیو اشخاص، درمان، خسارت و فایل | حقوقی/حاکمیت داده سازمان؛ بدون ایجاد نقش کاربری حقوقی |
| DEC-08 | مرجع پذیرش | نام سمت‌های تأییدکننده کسب‌وکار، امنیت و زیرساخت | مدیریت سازمان |
| DEC-09 | اختیارات سمت‌های میانی | ماتریس عملیات مجاز برای معاون/مدیر/سرپرست/مسئول | رئیس اداره بیمه |
| DEC-10 | نمایش داده مالی و پیوست غیرپزشکی | ماتریس سطح داده به تفکیک نقش/رشته/عملیات | رئیس اداره بیمه + امنیت |

## قاعده نگهداری ماتریس

هر تغییر کد در فازهای بعد باید شناسه نیازمندی مرتبط، فایل/مدل/سرویس، تست مثبت، تست منفی و نتیجه اجرا را به‌روزرسانی کند. هیچ نیازمندی صرفاً با تغییر مستندات به `PASS` تبدیل نمی‌شود. وضعیت `STATIC_PRESENT` تا زمان اجرای تست مرتبط، به `RUNTIME_VERIFIED` ارتقا نمی‌یابد.
