# سند جامع پروژه Office KMC
> وضعیت سند: **ممیزی زنده — فاز شناخت و ممیزی ایستا در حال تکمیل؛ پذیرش اجرایی هنوز تأیید نشده است.**  
> آخرین HEAD کدِ به‌روزشده در این ممیزی: `e3a394ce3ac79d6ea0b95a5630dff93ecd7d264f` (بر پایهٔ ممیزی ایستای `091495...` و اصلاحات فاز ۴) روی شاخه `implementation/insurance-platform-core-2026-11-04` (2026-11-07).  
> این سند باید در همان commit/شاخهٔ پیاده‌سازی به‌روزرسانی شود؛ تغییرات آن به‌تنهایی جای تست runtime یا بازبینی مالک کسب‌وکار را نمی‌گیرد.

## 1. معرفی پروژه

Office KMC یک پورتال وب داخلی برای عملیات اداره بیمه در یک گروه چندشرکتی است. کاربران هدف عبارت‌اند از مدیر سامانه، رئیس و کارکنان اداره بیمه، کارکنان/بیمه‌شدگان و افراد وابسته از طریق حساب بیمه‌شده اصلی، نمایندگان شرکت‌های تابعه و نمایندگان شرکت‌های بیمه‌گر. سامانه برای ثبت و پیگیری قرارداد، خسارت، درخواست، وظیفه، سند، مکاتبه، دارایی، ورود گروهی اطلاعات و گردش کار طراحی شده است.

**سامانه انتقال وجه یا عملیات بانکی انجام نمی‌دهد.** پرداخت‌ها فقط به‌عنوان اطلاعات اعلام‌شده از منبع معتبر ثبت می‌شوند.

## 2. Snapshot مخزن و معماری

| مورد | مقدار مشاهده‌شده |
|---|---|
| نوع | Django monolith ماژولار، server-rendered templates |
| نسخه Django | وابستگی `Django>=5.2,<5.3`؛ نسخهٔ نصب‌شده در محیط محلی در این snapshot قابل مشاهده نیست |
| رابط | HTML و CSS، فارسی/RTL؛ نه SPA |
| DRF / serializer | فایل/الگوی DRF یا `serializers.py` در درخت شاخه مشاهده نشد |
| Flutter / client مستقل | `pubspec.yaml` یا پروژهٔ Flutter در درخت شاخه وجود ندارد |
| DB توسعه | SQLite وقتی `DEBUG=True` و `DATABASE_URL` خالی است |
| DB غیرتوسعه | PostgreSQL؛ در تنظیمات غیرتوسعه‌ای نبود `DATABASE_URL` خطای startup است |
| cache throttling | LocMem برای DEBUG؛ Redis مشترک در محیط غیرتوسعه‌ای اجباری |
| زبان/منطقه زمانی | `fa` / `Asia/Tehran` |
| مدل User | `accounts.User` |
| static/media | `static/`، `staticfiles/`، `private_media/`؛ قرار داشتن media در private_media به‌تنهایی کنترل دسترسی وب‌سرور را ثابت نمی‌کند |
| تعداد اپ‌ها | ۱۵ اپ Django در `INSTALLED_APPS` |
| فایل‌های template | ۳۰ فایل شامل base، صفحات، partial و دو template داخلی workflow |
| فایل‌های migration | ۳۸ فایل migration شماره‌دار در snapshot |
| فایل‌های تست | ۱۸ فایل؛ ۱۳۶ متد `test_*` از روی سورس |
| CI | GitHub Actions عمداً در پروژه تعریف نشده است |

### 2.1 ساختار سطح اول

- `config/`: تنظیمات، URL ریشه، WSGI/ASGI.
- `accounts/`, `organizations/`, `insurance/`, `claims/`, `requests_portal/`, `tasks/`, `documents/`, `imports/`, `auditlog/`, `assets/`, `announcements/`, `correspondence/`, `dashboard/`, `core/`, `workflow/`: اپ‌های دامنه/زیرساخت.
- `templates/`: قالب‌های مشترک server-rendered؛ همهٔ اپ‌ها به جز workflow از این ریشه استفاده می‌کنند.
- `workflow/templates/workflow/`: قالب‌های فهرست و جزئیات پرونده گردش کار.
- `static/css/`: CSS مشترک.
- `docs/`: مشخصات محصول، قواعد کسب‌وکار، ماتریس دسترسی، کاتالوگ گردش‌کار، معماری، استقرار، تست، امنیت و وضعیت پیاده‌سازی.
- `private_media/`: محل تنظیم‌شده برای رسانه خصوصی؛ پوشه runtime است و در فهرست Git ثبت‌شده وجود ندارد.
- `manage.py`, `requirements.txt`, `Dockerfile`, `docker-compose.local.yml`, `.env.example`, `.env.local.example`.

### 2.2 فایل‌های مرجع موجود

| فایل | نقش |
|---|---|
| `README.md` | معرفی، راه‌اندازی محلی و هشدار عدم استفاده از داده واقعی تا تکمیل پذیرش |
| `PRODUCT_SPEC.md` | مشخصات سطح محصول و قواعد قطعی مورد تأیید مالک |
| `docs/BUSINESS_RULES_AND_WORKFLOWS.md` | مرجع اصلی قواعد کسب‌وکار |
| `docs/ACCESS_CONTROL_MATRIX.md` | ماتریس نقش، دامنه و مجوز |
| `docs/WORKFLOW_CATALOG.md` | چرخه‌های مورد انتظار کاربران |
| `docs/ARCHITECTURE.md` | معماری و مرزبندی اپ‌ها |
| `docs/WORKFLOW_ENGINE.md` | مدل و رفتار موتور گردش‌کار |
| `docs/IMPLEMENTATION_STATUS.md` | تغییرات/موارد باز شاخه |
| `docs/TESTING.md`, `LOCAL_TESTING.md` | دستورهای تست و سناریوهای پذیرش |
| `SECURITY.md`, `SECURITY_TEST_MATRIX.md`, `docs/SECURITY_REVIEW.md` | سیاست و بررسی امنیت |

**سند جامع قبلی:** در snapshot مورد بررسی، فایلی که کاتالوگ یکپارچه و هم‌زمان models/views/forms/templates/urls/admin/tests را پوشش دهد وجود نداشت. این فایل برای پر کردن همین خلأ ایجاد شده است. اسناد مرجع محصول همچنان منبع قواعد کسب‌وکار هستند؛ این سند، منبع نمایه‌سازی وضعیت واقعی کد و پیوند به آن قواعد است.

## 3. تنظیمات و احراز هویت

- `config/settings.py`: `INSTALLED_APPS` شامل اپ‌های Django و ۱۵ اپ پروژه است؛ `ROOT_URLCONF=config.urls`؛ `AUTH_USER_MODEL=accounts.User`.
- Middleware: Security، Session، Locale، Common، CSRF، Authentication، `RestrictAdminAccessMiddleware`، `RequirePasswordChangeMiddleware`، Messages و Clickjacking protection.
- حسابی که `must_change_password=True` دارد، به جز password-change/logout/static به صفحه تغییر رمز هدایت می‌شود.
- ورود از `accounts/login/` با `ThrottledAuthenticationForm` انجام می‌شود؛ ۵ خطای ورود در بازهٔ ۱۵ دقیقه‌ای باعث قفل موقت بر اساس username نرمال‌شده و IP می‌شود.
- پنل Django Admin برای کاربر غیر-superuser فقط با دسترسی سراسری تعریف‌شده در `accounts.access` مجاز است.
- دو سطح نقش در مدل باقی است: `User.Role` قدیمی برای سازگاری و `RoleAssignment.Role` جدید برای انتصاب عملیاتی. منطق `accounts.access.py` نقش، شرکت، بیمه‌گر، رشته و اعتبار زمانی را ارزیابی می‌کند.
- نقش‌های جاری در RoleAssignment: `system_admin`, `department_head`, `insurance_specialist`, `subsidiary_rep`, `insurer_representative`, `insured_person`.
- MFA در مدل فعلاً فقط `mfa_enabled` است؛ این فیلد به‌تنهایی پیاده‌سازی عامل دوم نیست.

## 4. نقش‌ها و تصمیمات قفل‌شده

### 4.1 نقش‌های مجاز در مدل عملیاتی
مدیر سامانه؛ رئیس اداره بیمه؛ کارشناس اداره بیمه؛ نماینده شرکت تابعه؛ نماینده شرکت بیمه‌گر؛ بیمه‌شده اصلی.

### 4.2 تصمیمات غیرقابل‌تغییر بدون تأیید مالک
1. نقش‌های مالی، حقوقی و حسابرس از محصول حذف شده‌اند و نباید دوباره به role، منو، workflow یا permission وارد شوند.
2. سامانه پول جابه‌جا نمی‌کند؛ دفترکل پرداخت، سابقهٔ اطلاعاتی است.
3. تکراری بودن خسارت صرفاً با اعلام بیمه‌گر منبع ثبت می‌شود؛ تشخیص خودکار قطعی از شباهت داده ممنوع است.
4. SLA در انتظار کاربر/بیمه‌گر/مدرک متوقف نمی‌شود.
5. اسناد پزشکی محرمانه فقط برای رئیس اداره و مدیر سامانه قابل مشاهده‌اند؛ گیرنده ارجاع صرفاً داده حداقلی لازم را دریافت می‌کند.
6. ممیزی، رویدادهای گردش کار، پرداخت‌ها و نسخه‌های سند append-only/immutable هستند؛ اصلاح با رویداد/نسخه جدید انجام می‌شود.
7. نماینده بیمه‌گر نمی‌تواند پرونده را نهایی ببندد.
8. قفل نهایی پرونده فقط به‌وسیله مدیر سامانه و با دلیل انجام می‌شود.
9. انتقال شخص بین شرکت‌ها باید با تاریخچه اشتغال انجام شود؛ شرکت قبلی فقط بازه اشتغال سابق را می‌بیند.
10. افراد تحت تکفل حساب مستقل ندارند و زیر حساب بیمه‌شده اصلی دیده می‌شوند.

### 4.3 ناسازگاری مستندات قدیمی
در `SECURITY_TEST_MATRIX.md` هنوز ردیف‌های مالی/حقوقی/حسابرس وجود دارد و در بخش‌هایی از `ACCESS_CONTROL_MATRIX.md` متن قدیمی درباره «نیازمند تصمیم بودن» این نقش‌ها باقی مانده است؛ این موارد با `PRODUCT_SPEC.md` و بخش 17.1 سند قواعد کسب‌وکار تعارض دارد. برای توسعه، حذف نقش‌ها حکم بالادستی است؛ ماتریس قدیمی باید در بازبینی مستندات اصلاح شود.

## 5. نقشهٔ اپ‌ها

| App | مسیر | مدل‌های پایگاه‌داده | urls.py | views.py | فرم | template اختصاصی | tests |
|---|---|---|---|---|---|---|---|
| accounts | `accounts/` | User, OrganizationalUnit, OrganizationalPosition, RoleAssignment, PositionAssignment | ندارد؛ auth و password در root | دارد | دارد | از `templates/registration` | دارد (۲ فایل) |
| announcements | `announcements/` | Announcement | دارد | دارد | دارد | در `templates/announcements` | دارد |
| assets | `assets/` | InsuredAsset, Vehicle, AssetValuation, AssetPolicyPeriod, AssetPolicyEndorsement | دارد | دارد | دارد | در `templates/assets` | دارد |
| auditlog | `auditlog/` | AuditEvent | ندارد | ندارد | ندارد | ندارد | دارد |
| claims | `claims/` | Claim, ClaimPayment, ClaimObjection | دارد | دارد | دارد | در `templates/claims` | دارد (۲ فایل) |
| core | `core/` | ندارد | ندارد | ندارد | ندارد | ندارد | دارد (۲ فایل) |
| correspondence | `correspondence/` | CorrespondenceSequence, Correspondence, CorrespondenceLink, CorrespondenceEvent | دارد | دارد | دارد | در `templates/correspondence` | دارد |
| dashboard | `dashboard/` | ندارد | ندارد؛ از root | دارد | ندارد | `templates/dashboard` | دارد |
| documents | `documents/` | DocumentRecord, DocumentVersion, DocumentLink, DocumentAccessEvent | دارد | دارد | ندارد | در `templates/documents` | دارد |
| imports | `imports/` | ImportBatch | دارد | دارد | دارد | `templates/imports` | دارد |
| insurance | `insurance/` | Insurer, Contract, ContractRevision | دارد | دارد | ندارد | `templates/insurance` | دارد |
| organizations | `organizations/` | Company, Person, PersonEmployment, CompanyLeadershipTitle | دارد | دارد | دارد | `templates/organizations` | دارد |
| requests_portal | `requests_portal/` | ServiceRequest | دارد | دارد | دارد | `templates/requests_portal` | دارد |
| tasks | `tasks/` | InternalTask, TaskEvent | دارد | دارد | دارد | `templates/tasks` | دارد |
| workflow | `workflow/` | WorkflowDefinition, WorkflowStep, WorkflowTransition, WorkflowCase, WorkflowEvent, BusinessCalendar, CalendarHoliday | دارد | دارد | ندارد | در `workflow/templates/workflow` | دارد |

**یادداشت:** core و dashboard عمداً اپ‌های زیرساختی/نمایشی بدون مدل‌اند. auditlog عمداً سرویس ثبت و مدل immutable است و UI عملیاتی مستقلی ندارد؛ نمایش آن از Admin فقط‌خواندنی انجام می‌شود.

## 6. کاتالوگ مدل داده

در این بخش مدل‌های persistence از کلاس‌های کمکی مانند QuerySet و TextChoices جدا شده‌اند. فهرست فیلدها، فیلدهای مهم و روابط را خلاصه می‌کند؛ تعریف دقیق و قیدها در `models.py` و migration متناظر مرجع است.

| App | Model | فیلدهای اصلی و ارتباط‌ها | متد/قید مهم |
|---|---|---|---|
| accounts | User | username، role قدیمی، mobile، national_id قدیمی، company، insurer، must_change_password، mfa_enabled، فیلدهای AbstractUser | مدل کاربر سفارشی |
| accounts | OrganizationalUnit | code، name، parent، company، is_active، created_at | clean/save؛ درخت واحد |
| accounts | OrganizationalPosition | unit، code، title، level، is_active | سطح سلسله‌مراتب ۱ تا ۶؛ یکتایی کد در واحد |
| accounts | RoleAssignment | user، role، company، insurer، organizational_unit، position، line_code، valid_from/until، is_active، reason، granted_by، approved_by، timestamps | clean/save/is_valid_on؛ قیدهای scope و بازه اعتبار |
| accounts | PositionAssignment | user، unit، position، line_code، valid_from/until، is_active، reason، granted_by، approved_by، created_at | clean/save؛ بازه اعتبار |
| announcements | Announcement | title، body، audience، company، attachment، is_published، publish_at، expires_at، created_by، timestamps | is_current |
| assets | InsuredAsset | asset_code، name، asset_type، company یا person، identifier، location، insured_value، insurer، contract، policy_number، policy_start/end، is_active، notes، created_by، timestamps | clean/save؛ مالک دقیقاً یک مورد شرکت یا شخص و قید تاریخ/مبلغ |
| assets | Vehicle | asset OneToOne، plate_number، vin، engine_number، make، model_name، model_year | clean/save؛ اعتبارسنجی مشخصات خودرو |
| assets | AssetValuation | asset، valuation_date، market_value، insured_value، method، source_reference، note، created_by، approved_by، created_at | clean/save/delete کنترل‌شده |
| assets | AssetPolicyPeriod | asset، insurer، contract، policy_number، policy_start/end، status، source_reference، note، created_by، approved_by، created_at | clean/save؛ قید بازه |
| assets | AssetPolicyEndorsement | policy_period، endorsement_number، effective_date، description، document، created_by، approved_by، created_at | ارتباط با دوره بیمه‌نامه |
| auditlog | AuditEvent | actor، action، object_type/id، summary، before_data، after_data، metadata، ip_address، user_agent، correlation_id، created_at | save/delete و QuerySet برای append-only |
| claims | Claim | claim_number، source_claim_number، person، primary_insured، company_snapshot، contract، insurer، تاریخ‌های service/registration، contract_number_snapshot، service_type، requested/assessed/payable/paid_amount، status، source_reference، فیلدهای source duplicate، assessment_note، result_sent_at/by، imported_at، timestamps | objection_deadline، clean/save؛ قیود مبلغ/محدوده و جلوگیری از حدس شرکت تاریخی |
| claims | ClaimPayment | claim، entry_type، amount، paid_at، source_reference، source_insurer، reverses_payment، note، recorded_by، confirmed_by، is_legacy_import، created_at | signed_amount، clean/save/delete و QuerySet immutable؛ تأییدکننده مستقل |
| claims | ClaimObjection | claim، submitted_by، description، status، response، deadline_at، timestamps | clean/save؛ مهلت اعتراض و صلاحیت ثبت |
| correspondence | CorrespondenceSequence | solar_date، last_number، updated_at | شمارنده شماره مکاتبه |
| correspondence | Correspondence | internal_number، subject، channel، direction، company، insurer، contract، external_reference، summary، occurred_at، follow_up_due/status، assigned_to، is_confidential، attachment، created_by، timestamps | clean/save؛ شماره‌گذاری از سرویس |
| correspondence | CorrespondenceLink | correspondence، content_type، object_id، created_by، created_at | اتصال generic به رکورد دامنه |
| correspondence | CorrespondenceEvent | correspondence، actor، event_type، summary، metadata، occurred_at | save/delete؛ eventهای append-only |
| documents | DocumentRecord | title، category، file، uploaded_by، company، person، security_level، is_medical، is_confidential قدیمی، is_archived/archived_at/archive_reason، is_void/voided_at/void_reason، created_at | clean/save/current_version/delete؛ immutability |
| documents | DocumentVersion | document، version_number، file، uploaded_by، change_reason، checksum_sha256، is_current، uploaded_at | clean/save/delete و زنجیره نسخه |
| documents | DocumentLink | document، content_type، object_id، created_by، created_at | اتصال generic به رکورد دامنه |
| documents | DocumentAccessEvent | document، version، actor، action، ip_address، occurred_at | save/delete و QuerySet immutable |
| imports | ImportBatch | batch_number، source_type، file، uploaded_by، status، total/valid/invalid_rows، result_report، preview_data، reviewed_by/at، review_note، created_at | داده پیش‌نمایش و تأیید مستقل |
| insurance | Insurer | name، contact_name/email/phone، is_active | اطلاعات بیمه‌گر |
| insurance | Contract | code، title، insurer، line، start/end_date، companies M2M، coverage_summary، terms، is_active، created_at | clean/save؛ قید تاریخ |
| insurance | ContractRevision | contract، revision_number، description، document، created_by، created_at | قید نسخه برای قرارداد |
| organizations | Company | code، name، parent، is_parent، is_active، created_at | clean/save؛ ساختار شرکت مادر/تابعه |
| organizations | Person | company legacy reference، user، personnel_code، national_id unique، first/last_name، birth_date، relationship، employee self-FK، mobile، iban، is_insured، is_active، updated_at | clean/save؛ یکتایی کد ملی و انطباق dependent |
| organizations | PersonEmployment | person، company، personnel_code، job_title، valid_from/until، status، source_reference، created_by، approved_by، timestamps | clean/save؛ حداکثر یک اشتغال فعال سازگار |
| organizations | CompanyLeadershipTitle | company، person، title، valid_from/until، declared_by، timestamps | clean/save؛ عنوان مدیریتی زمان‌دار |
| requests_portal | ServiceRequest | reference، kind، submitted_by، person، company، title، description، status، assigned_to، response، attachment، is_confidential، timestamps | clean/save؛ بعضی انواع پزشکی محرمانه اجباری |
| tasks | InternalTask | title، description، created_by، assignees M2M، priority، status، due_at، related_request، timestamps | وضعیت در view؛ محدودیت وظایف محرمانه در form |
| tasks | TaskEvent | task، actor، event_type، from_value، to_value، note، occurred_at | save/delete؛ append-only |
| workflow | WorkflowDefinition | code، title، version، is_active، description، created_by، approved_by، created_at، published_at | clean/save/delete؛ نسخه منتشرشده محافظت می‌شود |
| workflow | WorkflowStep | definition، code، title، order، allowed_roles، sla_minutes، is_initial، is_terminal، allow_return، requires_acknowledgement | clean/save/delete؛ قید ترتیب/مرحله |
| workflow | WorkflowTransition | definition، source_step، target_step، action_code، title، allowed_roles، recipient_roles، requires_note، is_return، closes_case | clean/save/delete؛ قید انتقال |
| workflow | WorkflowCase | definition، content_type/object_id، current_step، current_assignee، status، opened_at، first_viewed_at، first_action_at، sla_due_at، closed_at، is_locked، locked_by | قید یکتایی موضوع/نمونه و scope |
| workflow | WorkflowEvent | workflow_case، actor، event_type، action_code، from/to_step، from/to_assignee، note، opened/acknowledged/acted/sent_at، metadata | immutable و timeline |
| workflow | BusinessCalendar | code، title، timezone_name، working_weekdays، start/end_time، is_active | clean/save؛ اعتبارسنجی روز/ساعت/منطقه زمانی |
| workflow | CalendarHoliday | calendar، date، title، is_working_override | قید یکتایی تاریخ برای تقویم |

### 6.1 نمودار روابط متنی

```text
accounts.User
 ├─ RoleAssignment ── Company / Insurer / OrganizationalUnit / OrganizationalPosition
 ├─ PositionAssignment ── OrganizationalUnit / OrganizationalPosition
 └─ Person (one-to-one, optional)

organizations.Company ──< PersonEmployment >── Person
organizations.Company ──< Contract >── insurance.Insurer
Person ──< Claim >── Contract / Insurer / historical company snapshot
Claim ├─< ClaimPayment
      └─< ClaimObjection
ServiceRequest ── InternalTask
ServiceRequest / Claim / Correspondence / other objects
       └─ WorkflowCase (GenericForeignKey: content_type + object_id)
WorkflowDefinition ──< WorkflowStep
                   └─< WorkflowTransition
WorkflowCase ──< WorkflowEvent
BusinessCalendar ──< CalendarHoliday
InsuredAsset ── Vehicle (one-to-one)
            ├─< AssetValuation
            └─< AssetPolicyPeriod ──< AssetPolicyEndorsement
Correspondence ──< CorrespondenceEvent
              └─< CorrespondenceLink (Generic target)
DocumentRecord ├─< DocumentVersion
               ├─< DocumentAccessEvent
               └─< DocumentLink (Generic target)
AuditEvent: actor + generic object identity/data snapshots
ImportBatch: uploaded/reviewed by User; preview payload -> Claim / ClaimPayment
```

## 7. نقشه URL و جریان‌های واقعی

### 7.1 Root URL — `config/urls.py`

| Route | Name | View | روش تعامل معمول | جریان/ناوبری |
|---|---|---|---|---|
| `admin/` | Django Admin | admin.site.urls | GET/POST توسط Admin | لینک منوی اصلی ندارد؛ فقط دسترسی مجاز |
| `accounts/login/` | login | Django LoginView + ThrottledAuthenticationForm | GET/POST | صفحه ورود |
| `accounts/logout/` | logout | Django LogoutView | POST در فرم base | دکمه خروج |
| `accounts/password-change/` | password_change | RequiredPasswordChangeView | GET/POST | لینک کاربر و middleware اجباری |
| `/` | home | dashboard.views.home | GET | برند/داشبورد |
| `dashboard/` | dashboard | dashboard.views.home | GET | منوی اصلی |

### 7.2 Routeهای اپ‌ها

پیشوندها از `config/urls.py` هستند. تمام viewهای سفارشی FBV هستند به‌جز `RequiredPasswordChangeView` در accounts. Routeهای list/detail/download معمولاً GET؛ فرم‌های create و عملیات state-change از POST در همان view استفاده می‌کنند.

| App | Prefix + path | Name | View | Form / template |
|---|---|---|---|---|
| organizations | `organizations/` | people_list | people_list | بدون فرم فعال؛ `organizations/people_list.html` |
| insurance | `insurance/contracts/` | contract_list | contract_list | `insurance/contract_list.html` |
| claims | `claims/` | claim_list | claim_list | `claims/claim_list.html` |
| claims | `claims/<int:pk>/` | claim_detail | claim_detail | ClaimObjectionForm؛ `claims/claim_detail.html` |
| requests_portal | `requests/` | request_list | request_list | `requests_portal/request_list.html` |
| requests_portal | `requests/new/` | request_create | request_create | ServiceRequestForm؛ `requests_portal/request_form.html` |
| requests_portal | `requests/<int:pk>/` | request_detail | request_detail | POST برای transition legacy؛ `requests_portal/request_detail.html` و redirect به workflow detail در صورت وجود WorkflowCase |
| tasks | `tasks/` | task_list | task_list | `tasks/task_list.html` |
| tasks | `tasks/new/` | task_create | task_create | InternalTaskForm؛ `tasks/task_form.html` |
| tasks | `tasks/<int:pk>/` | task_update | task_update | POST تغییر status؛ `tasks/task_update.html` |
| imports | `imports/claims/` | claim_import | claim_import | ClaimImportForm؛ `imports/claim_import.html` |
| imports | `imports/claims/<int:batch_id>/confirm/` | claim_import_confirm | claim_import_confirm | POST تأیید batch |
| documents | `documents/` | document_list | document_list | `documents/document_list.html` |
| documents | `documents/upload/` | document_upload | document_upload | فرم HTML در view؛ `documents/document_upload.html` |
| documents | `documents/<int:pk>/download/` | document_download | document_download | FileResponse و ثبت DocumentAccessEvent |
| assets | `assets/` | asset_list | asset_list | `assets/asset_list.html` |
| assets | `assets/new/` | asset_create | asset_create | InsuredAssetForm؛ `assets/asset_form.html` |
| announcements | `announcements/` | announcement_list | announcement_list | `announcements/announcement_list.html` |
| announcements | `announcements/new/` | announcement_create | announcement_create | AnnouncementForm؛ `announcements/announcement_form.html` |
| announcements | `announcements/<int:pk>/attachment/` | announcement_download | announcement_download | FileResponse |
| correspondence | `correspondence/` | correspondence_list | correspondence_list | `correspondence/correspondence_list.html` |
| correspondence | `correspondence/new/` | correspondence_create | correspondence_create | CorrespondenceForm؛ `correspondence/correspondence_form.html` |
| correspondence | `correspondence/<int:pk>/attachment/` | correspondence_download | correspondence_download | FileResponse |
| workflow | `workflow/` | workflow_case_list | workflow_case_list | `workflow/workflow_case_list.html` |
| workflow | `workflow/<int:pk>/` | workflow_case_detail | workflow_case_detail | POST برای acknowledge/transition/final-lock؛ `workflow/workflow_case_detail.html` |

**تعداد routeهای سفارشی ثبت‌شده:** ۳۳ در ۱۱ فایل `urls.py` اپ‌ها، به‌علاوه ۶ مسیر root (شامل Admin، auth و dashboard). شمارش pathهای نهایی با resolve/runtime هنوز اجرا نشده است.

### 7.3 ناوبری base

`templates/base.html` لینک‌های زیر را با access flagهای context processor نشان می‌دهد: داشبورد، خسارت‌ها، قراردادها، دارایی‌ها، اطلاعیه‌ها، ارجاعات من، مکاتبات، اسناد و بخشنامه‌ها، درخواست‌ها، بیمه‌شدگان، وظایف، ورود اکسل، تغییر رمز و خروج. لینک Admin در منوی پایه وجود ندارد.

## 8. کاتالوگ Viewها

| App | View | نوع | URL | Permission / scope اصلی | فرم و template |
|---|---|---|---|---|---|
| accounts | RequiredPasswordChangeView | CBV | `accounts/password-change/` | login required / middleware gate | Django PasswordChangeForm |
| dashboard | home | FBV | `/`, `/dashboard/` | login required؛ داده‌ها با scope نقش فیلتر می‌شوند | dashboard/home |
| organizations | people_list | FBV | organizations/ | login required؛ global/company/insured scope | people_list |
| insurance | contract_list | FBV | insurance/contracts/ | login required؛ `_contract_scope` و مجوز نمایش | contract_list |
| claims | claim_list | FBV | claims/ | login required؛ `scoped_claims_for` | claim_list |
| claims | claim_detail | FBV | claims/<pk>/ | login required؛ scoped object؛ اعتراض فقط برای نقش/پرونده واجد شرایط | ClaimObjectionForm، claim_detail |
| requests_portal | request_list | FBV | requests/ | login required؛ `scoped_requests_for` | request_list |
| requests_portal | request_create | FBV | requests/new/ | login required؛ نقش‌های مجاز، scope فرد/شرکت، workflow autostart در صورت تعریف فعال | ServiceRequestForm، request_form |
| requests_portal | request_detail | FBV | requests/<pk>/ | login required؛ scoped request؛ تصمیم/انتقال تابع policy یا WorkflowCase | request_detail |
| tasks | task_list | FBV | tasks/ | login required؛ `_visible_tasks` | task_list |
| tasks | task_create | FBV | tasks/new/ | login required؛ مدیر/سرپرست/مسئول مجاز؛ فرم scope-aware | InternalTaskForm، task_form |
| tasks | task_update | FBV | tasks/<pk>/ | login required؛ manager یا assignee؛ transition status کنترل‌شده | task_update |
| imports | claim_import | FBV | imports/claims/ | login required؛ insurance staff / insurer rep با insurer scope | ClaimImportForm، claim_import |
| imports | claim_import_confirm | FBV | imports/claims/<batch>/confirm/ | POST، reviewer مجاز و تأیید مستقل؛ مالکیت batch بررسی می‌شود | همان صفحه claim_import |
| documents | document_list | FBV | documents/ | login required؛ `_visible_documents` | document_list |
| documents | document_upload | FBV | documents/upload/ | login required؛ global یا specialist؛ شرکت/رشته و پزشکی محدود | فرم HTML در view، document_upload |
| documents | document_download | FBV | documents/<pk>/download/ | login required؛ visible object؛ archived/void رد می‌شود؛ event ثبت می‌شود | FileResponse |
| assets | asset_list | FBV | assets/ | login required؛ `_asset_scope` | asset_list |
| assets | asset_create | FBV | assets/new/ | login required؛ insurance specialist و form scope/line | InsuredAssetForm، asset_form |
| announcements | announcement_list | FBV | announcements/ | login required؛ audience/company/time filter | announcement_list |
| announcements | announcement_create | FBV | announcements/new/ | login required؛ insurance staff؛ AnnouncementForm | announcement_form |
| announcements | announcement_download | FBV | announcements/<pk>/attachment/ | login required؛ visible announcement | FileResponse |
| correspondence | correspondence_list | FBV | correspondence/ | login required؛ company/insurer/staff scope + confidentiality | correspondence_list |
| correspondence | correspondence_create | FBV | correspondence/new/ | login required؛ نقش/شرکت/بیمه‌گر و رشته؛ CorrespondenceForm | correspondence_form |
| correspondence | correspondence_download | FBV | correspondence/<pk>/attachment/ | login required؛ `_scope`; ثبت event | FileResponse |
| workflow | workflow_case_list | FBV | workflow/ | login required؛ `_visible_cases` و assigned/global scope | workflow_case_list |
| workflow | workflow_case_detail | FBV | workflow/<pk>/ | login required؛ assignee/role/scope؛ service state machine | workflow_case_detail |

## 9. فرم‌ها و اعتبارسنجی‌ها

| Form | اتصال فعلی | فیلدها/اعتبارسنجی‌های مهم | حکم استفاده |
|---|---|---|---|
| ThrottledAuthenticationForm | LoginView در root | username+IP key؛ قفل پس از ۵ خطا/۱۵ دقیقه؛ شمارنده cache | متصل |
| AnnouncementForm | announcement_create | title/body/audience/company/file/publish_at/expires_at؛ پایان پس از انتشار؛ فایل مجاز و حداکثر ۱۵MB | متصل |
| InsuredAssetForm | asset_create | فیلدهای دارایی و خودرو؛ پلاک برای خودرو؛ تاریخ پوشش؛ مالک دقیقاً شرکت یا شخص؛ بیمه‌گر/قرارداد سازگار؛ line scope | متصل |
| ClaimObjectionForm | POST در claim_detail | فقط description؛ پاسخ/وضعیت در فرم فعلی نیست | ثبت اعتراض متصل؛ پاسخ/تصمیم ناقص |
| CorrespondenceForm | correspondence_create | subject/channel/direction/company/insurer/contract/ref/summary/date/follow-up/assignee/confidentiality/attachment؛ scope شرکت/بیمه‌گر/رشته و فایل حداکثر ۱۵MB | متصل |
| ClaimImportForm | claim_import | فقط xlsx/xlsm؛ حداکثر ۲۵MB؛ ZIP/OOXML معتبر، تعداد/حجم entry و CRC کنترل می‌شود | متصل |
| PersonChangeRequestForm | هیچ viewی آن را استفاده نمی‌کند | فیلدهای personnel_code/national_id/name/mobile/iban/is_insured | **فرم یتیم**؛ نام آن change-request است اما مستقیماً Person را هدف می‌گیرد و مسیر درخواست/تأیید ندارد |
| ServiceRequestForm | request_create | kind/person/title/description/attachment؛ person queryset و قواعد self/dependent/company؛ درخواست درمان باید فرد مجاز داشته باشد؛ فایل حداکثر ۱۰MB | متصل |
| InternalTaskForm | task_create | title/description/assignees/priority/due_at/related_request؛ assigneeهای مجاز؛ عدم تخصیص درخواست محرمانه به کارشناس فاقد دسترسی | متصل |

**اپ‌های بدون فرم اختصاصی:** auditlog، core، dashboard، documents (فرم HTML در view)، insurance (فعلاً فقط list)، workflow (اقدامات POST در view). عدم وجود forms.py به‌تنهایی ایراد نیست؛ معیار، جریان واقعی view است.

## 10. فهرست تمپلیت‌ها

| فایل | استفاده | ناوبری/اتصال |
|---|---|---|
| `templates/base.html` | قالب پایه صفحات | منوی اصلی مشترک |
| `templates/registration/login.html` | LoginView | مسیر login |
| `templates/registration/password_change.html` | RequiredPasswordChangeView | لینک userbox و middleware |
| `templates/dashboard/home.html` | dashboard.home | مسیر root/dashboard و quick cards |
| `templates/organizations/people_list.html` | people_list | منو و داشبورد براساس access.people |
| `templates/insurance/contract_list.html` | contract_list | منو و داشبورد براساس access.contracts |
| `templates/claims/claim_list.html` | claim_list | منو و داشبورد |
| `templates/claims/claim_detail.html` | claim_detail | لینک از claim list و recent claims |
| `templates/requests_portal/request_list.html` | request_list | منو/داشبورد |
| `templates/requests_portal/request_form.html` | request_create | دکمه داشبورد/صفحه درخواست |
| `templates/requests_portal/request_detail.html` | request_detail | لیست و داشبورد |
| `templates/tasks/task_list.html` | task_list | منو و داشبورد |
| `templates/tasks/task_form.html` | task_create | دکمه create در task list |
| `templates/tasks/task_update.html` | task_update | لینک از task list |
| `templates/assets/asset_list.html` | asset_list | منو/داشبورد |
| `templates/assets/asset_form.html` | asset_create | دکمه create در asset list |
| `templates/announcements/announcement_list.html` | announcement_list | منو/داشبورد |
| `templates/announcements/announcement_form.html` | announcement_create | دکمه create در announcement list |
| `templates/correspondence/correspondence_list.html` | correspondence_list | منو/داشبورد |
| `templates/correspondence/correspondence_form.html` | correspondence_create | دکمه create در correspondence list |
| `templates/documents/document_list.html` | document_list | منو/داشبورد |
| `templates/documents/document_upload.html` | document_upload | دکمه create در document list |
| `templates/imports/claim_import.html` | claim_import/confirm | منو/داشبورد |
| `workflow/templates/workflow/workflow_case_list.html` | workflow_case_list | منوی «ارجاعات من» و redirect از request detail |
| `workflow/templates/workflow/workflow_case_detail.html` | workflow_case_detail | لینک از workflow list |
| `templates/includes/pagination.html` | include در فهرست صفحه‌بندی‌شده | partial؛ route مستقل ندارد |

در snapshot همهٔ ۲۶ فایل بالا به یک render/include مشخص قابل انتساب‌اند؛ orphan بودن template هنوز با instrumentation/runtime test کامل رد نشده است.

## 11. پنل Django Admin

| App | مدل‌های ثبت‌شده | تنظیمات/کنترل مهم |
|---|---|---|
| accounts | User، RoleAssignment، OrganizationalUnit، OrganizationalPosition، PositionAssignment | list/search؛ کنترل سطح module/view/add/change/delete در ModelAdmin |
| organizations | Company، Person | Company list/search؛ PersonAdmin اجازهٔ مشاهده و ایجاد اولیهٔ مجاز می‌دهد و تغییر/حذف مستقیم را می‌بندد؛ PersonEmployment و CompanyLeadershipTitle ثبت نشده‌اند |
| insurance | Insurer سفارشی؛ Contract و ContractRevision ثبت عمومی | Insurer list/search؛ قراردادها generic admin |
| claims | Claim، ClaimPayment، ClaimObjection | list/filter/search؛ همه فیلدهای مدل readonly و عملیات add/change/delete محدود/غیرفعال |
| announcements | Announcement | list/filter/search؛ فیلدها readonly؛ عملیات مستقیم admin محدود |
| assets | InsuredAsset، Vehicle، AssetValuation، AssetPolicyPeriod، AssetPolicyEndorsement | list/filter/search؛ readonly fields و کنترل permission سفارشی |
| auditlog | AuditEvent | readonly؛ add/change/delete ممنوع؛ view مجاز محدود |
| correspondence | Correspondence، CorrespondenceSequence، CorrespondenceEvent، CorrespondenceLink | list/filter/search؛ فیلدها readonly؛ event/link فقط مشاهده |
| documents | DocumentRecord، DocumentVersion، DocumentAccessEvent | list/filter/search؛ readonly و add/change/delete ممنوع |
| imports | ImportBatch | list/filter/search؛ readonly و CRUD مستقیم محدود |
| tasks | InternalTask، TaskEvent | task inline event؛ فیلدها readonly و permission سفارشی |
| workflow | WorkflowDefinition/Step/Transition، WorkflowCase، WorkflowEvent، BusinessCalendar، CalendarHoliday | step/transition inline؛ published definitions/children محافظت‌شده؛ case/event/calendar با کنترل global |
| core / dashboard | مدل قابل ثبت در admin ندارند | core/dashboard زیرساختی/نمایشی و بدون مدل persistence هستند؛ requests_portal در admin به‌شکل ثبت ساده و بدون محدودیت ثبت شده و در شکاف #8 بررسی می‌شود |

**قاعده:** وجود ثبت در Admin به معنی وجود جریان کاربری کامل در سایت نیست. Admin برای داده‌های پایه و بررسی داخلی استفاده می‌شود؛ مسیر عملیاتی مورد انتظار کاربر از template و view جدا سنجیده می‌شود.

## 12. تست‌ها — فهرست فایل و دامنه

| App / فایل | تعداد test method | دامنهٔ پوشش سورس |
|---|---:|---|
| accounts/test_access.py | ۵ | scope شرکت، انقضای انتصاب، scope رشته، global admin، insurer scope |
| accounts/tests.py | ۶ | تغییر رمز اولیه، محدودیت Admin، login throttling |
| announcements/tests.py | ۱ | فیلتر انتشار و audience |
| assets/tests.py | ۸ | scope شرکت، جلوگیری از ثبت دارایی شرکت دیگر، مبلغ/تاریخ |
| auditlog/tests.py | ۴ | append-only، منع update/delete، نگهداری actor |
| claims/tests.py | ۱۲ | visibility claim، انتقال تاریخی شرکت، شناسه ملی، مبلغ، مجوز اعتراض |
| claims/test_payments.py | ۸ | پرداخت قسطی، سقف payable، تأیید مستقل، برگشت، immutability، پرداخت اعلامی بیمه‌گر |
| core/test_permissions.py | ۱ | عدم نمایش درخواست محرمانه به specialist حتی با assignment |
| core/tests.py | ۶ | امضای فایل، پسوند، حجم، فایل Office |
| correspondence/tests.py | ۹ | scope شرکت و بیمه‌گر |
| dashboard/tests.py | ۴ | dashboard نقش‌ها، جلوگیری از افشای داده دیگران/تعداد task محرمانه |
| documents/tests.py | ۱۰ | scope اتصال سند، مدرک پزشکی، دانلود محرمانه، immutability |
| imports/tests.py | ۱۳ | مبلغ/تاریخ فارسی و میلادی، اعتبارسنجی فایل، تأیید مستقل batch و پرداخت |
| insurance/tests.py | ۲ | بازه تاریخ قرارداد |
| organizations/tests.py | ۹ | scope فهرست اشخاص، dependent-company integrity، اشتغال فعال یکتا |
| requests_portal/tests.py | ۲۱ | create/visibility/confidentiality، status، assignment، تاریخچه پاسخ، medical dependent، transition graph |
| tasks/tests.py | ۵ | فیلتر درخواست محرمانه، assigneeهای مجاز، رد specialist و پذیرش head |
| workflow/tests.py | ۱۲ | start/transition، note، SLA، append-only، immutability، scope، calendar، role/recipient |

تعداد ۱۳۱ تعریف `test_*` در ۱۸ فایل از روی سورس snapshot محاسبه شده است؛ تعداد تست‌های اجراشده، تعداد pass/fail و نتیجهٔ runtime در این محیط هنوز **قابل تأیید نیست**.

## 13. فهرست نهایی شکاف‌ها — دامنهٔ بستهٔ فاز ۳

این فهرست پس از تطبیق `WORKFLOW_CATALOG.md`، قواعد کسب‌وکار و سورس کد snapshot `091495cf35bf2e667a3d00647256ebbe06fc6894` تثبیت شده است. تعداد شکاف‌ها **۲۰ مورد** است. این فهرست دامنهٔ فاز ۴ است و پس از این نقطه شکاف جدیدی به آن افزوده نمی‌شود؛ کشف مورد تازه خارج از این دامنه، بدون بازگشایی رسمی فاز ۳ اجرا نخواهد شد. موارد USED عمداً در جدول نیامده‌اند.

| # | App | Capability | Verdict | Exact gap | Proposed fix | Severity |
|---:|---|---|---|---|---|---|
| 1 | claims | ثبت دستی/اصلاح/بازبینی اولیه خسارت | PARTIAL | ثبت اولیه از Excel انجام می‌شود؛ ClaimForm و مسیر کاربری برای ثبت دستی و اصلاح دادهٔ منبع/تخصصی وجود ندارد؛ Claim admin فقط‌خواندنی است | فرم و view متناسب با نقش، ثبت before/after و اتصال به گردشِ تأیید بدون حدس خودکار duplicate | BLOCKER |
| 2 | claims | ثبت، تأیید مستقل و برگشت پرداخت | PARTIAL | سرویس‌های `record_payment`، `reverse_payment` و مدل immutable وجود دارند؛ اما view/form/URL کاربری برای ثبت و تأیید مستقل وجود ندارد؛ import فقط پرداخت منبع را وارد می‌کند | اتصال فرم و view به سرویس‌های تراکنشی، کنترل جدایی ثبت‌کننده/تأییدکننده و تست برگشت/سقف/تکرار | BLOCKER |
| 3 | claims | گردش چندمرحله‌ای اعتراض به خسارت | PARTIAL | ثبت اعتراض و تغییر وضعیت/پاسخ ساده پیاده شده؛ ارجاع به بیمه‌گر، پاسخ بیمه‌گر، رفت‌وبرگشت چندمرحله‌ای و نهایی‌سازی اداره به Workflow متصل نیست | تعریف workflow اعتراض با نقش‌های مقصد، تاریخچه و ۶۰ روز تقویمی؛ جلوگیری از بستن توسط بیمه‌گر | IMPORTANT |
| 4 | insurance | چرخه عمر قرارداد/بیمه‌نامه | PARTIAL | فقط فهرست قرارداد در Template UI وجود دارد؛ ایجاد، پیش‌نویس، تأیید، نسخه/الحاقیه، فسخ زمان‌مند، اثر بر پوشش/خسارت باز و هشدار سررسید به view/form متصل نیست | پیاده‌سازی مسیرهای تعریف‌شده در کاتالوگ با تأیید رئیس/مدیر، تاریخ اثر و نسخهٔ immutable | BLOCKER |
| 5 | assets | تأیید valuation، دوره بیمه‌نامه و الحاقیه | PARTIAL | ثبت valuation، policy period و endorsement از detail page انجام می‌شود؛ دوره پیش‌نویس می‌ماند و هیچ عملیات تأیید/رد/فعال‌سازی برای فیلدهای approved_by وجود ندارد | افزودن مرحلهٔ تأیید با مرجع مجاز پس از تثبیت اختیار نقش‌ها؛ حفظ تاریخچه و کنترل دانلود | IMPORTANT |
| 6 | organizations | اصلاح موبایل، شبا و اطلاعات هویتی/وابستگان | MISSING | `PersonChangeRequestForm` مصرف‌کننده ندارد؛ ServiceRequest فقط شرح عمومی دارد؛ old/new، مرحله/عامل/زمان‌های لازم برای گردش تغییر ساخته نشده است | ساخت درخواست تغییر ساخت‌یافته، اتصال به نماینده شرکت/بیمه‌گر/مرجع داخلی و به‌روزرسانی Person فقط پس از تأیید | BLOCKER |
| 7 | organizations | مدیریت چرخه سوابق اشتغال و انتقال شرکت | PARTIAL | `PersonEmployment` در scope و import مصرف می‌شود؛ UI و فرم تأیید/خاتمه/انتقال برای ثبت دستی و مشاهدهٔ گردش اشتغال وجود ندارد | تکمیل فرم/view محدود به شرکت و نقش مجاز، اعتبار زمانی و ثبت عامل/تأییدکننده؛ حفظ اشتغال تاریخی | IMPORTANT |
| 8 | requests_portal | جلوگیری از دور زدن workflow از Django Admin | BROKEN | `ServiceRequest` با admin پیش‌فرض ثبت شده؛ کاربر staff مجاز به Admin می‌تواند status/assignee/response را مستقیم عوض کند و از `transition_case` و ثبت ممیزی دامنه‌ای عبور کند | تبدیل Admin به مشاهدهٔ فقط‌خواندنی و بستن add/change/delete؛ تمام تغییرها از view/workflow عبور کنند؛ تست POST منفی | IMPORTANT |
| 9 | organizations | جلوگیری از ویرایش مستقیم دادهٔ شخص از Admin | BROKEN | `Person` با admin پیش‌فرض ثبت شده و فیلدهای mobile/IBAN/identity بدون گردش مصوب قابل تغییرند | حفظ مشاهده و ایجاد اولیهٔ مجاز، محدودکردن تغییر مستقیم داده‌های هویتی/تماس/مالی تا اتصال گردش اصلاح؛ تست عدم تغییر | IMPORTANT |
| 10 | workflow | اتصال گردش کار به دامنه‌های غیر از درخواست عمومی | PARTIAL | `start_workflow` در جریان ایجاد ServiceRequest متصل است؛ claim، objection، contract، person change، asset و چرخه‌های دیگر تعریف/اتصال دامنه‌ای ندارند | اتصال هر نوع فقط طبق Workflow Catalog، با تعریف نسخه‌دار، نقش/دامنه و تست end-to-end همان جریان | BLOCKER |
| 11 | requests_portal / workflow | مدیریت پیکربندی ناقص گیرندهٔ مرحله آغازین | PARTIAL | اگر تعریف فعال موجود باشد اما گیرندهٔ واجد انتصاب پیدا نشود، `resolve_initial_assignee`، `ValidationError` می‌دهد؛ request_create آن را به خطای قابل‌فهم فرم/پیام تبدیل نمی‌کند | اعتبارسنجی publish/config و مدیریت اتمیک خطا در request_create؛ تست عدم ثبت رکورد نیمه‌کاره و پاسخ کنترل‌شده | IMPORTANT |
| 12 | imports | فیلدهای پویا و قالب Excel نسخه‌دار با تصمیم فیلدبه‌فیلد | MISSING | `ImportBatch` فقط import ثابت خسارت دارد؛ FieldDefinition/ExcelTemplate/نسخه قالب، تولید نمونه، merge/replace/ignore و تاریخچه مقادیر قدیمی وجود ندارد | ساخت تعریف فیلد و قالب با مجوز مدیر سامانه، پیش‌نمایش و تصمیم‌های تراکنشیِ تعریف‌شده در کاتالوگ | BLOCKER |
| 13 | documents | اتصال سند به رکوردهای دامنه | PARTIAL | `DocumentLinkForm` برای claim/request/correspondence/contract/asset/task تعریف شده، اما view آن را import/مصرف نمی‌کند؛ URL و UI اتصال و دامنهٔ visibility برای همه مقصدها کامل نیست | اتصال form→view→template، کنترل مجوز روی target و دانلود، نمایش linkها و تست هر target و tenant | IMPORTANT |
| 14 | dashboard | گزارش‌ساز سفارشی و گردش تأیید/انتشار گزارش | MISSING | فقط KPIهای ثابت وجود دارد؛ تعریف گزارش، فیلترهای مجاز، زنجیره تأیید، نسخه/خروجی و گزارش بیمه‌گر پیاده نشده‌اند | پیاده‌سازی مدل/فرم/report run و approval طبق چرخه ۱۶ کاتالوگ و محدودیت scope | IMPORTANT |
| 15 | dashboard / workflow | گزارش SLA، زمان مشاهده/اقدام/ارجاع و هشدار تأخیر | MISSING | WorkflowCase زمان‌های موردی را دارد، ولی گزارش تجمیعی SLA، زمان انتظار به تفکیک نقش/واحد و job/هشدار تأخیر در UI وجود ندارد | query/service گزارش SLA و اعلان‌های نقش‌محور بدون توقف SLA؛ آزمون با تقویم کاری ایران | IMPORTANT |
| 16 | accounts | احراز هویت چندعاملی واقعی | PARTIAL | فقط `User.mfa_enabled` موجود است؛ enrollment، challenge، factor، recovery code و تست ورود دومرحله‌ای وجود ندارد | انتخاب روش MFA و عامل‌های پشتیبانی‌شده با تأیید مالک/امنیت، سپس پیاده‌سازی و آزمون | IMPORTANT |
| 17 | accounts | بازیابی امن رمز عبور | MISSING | Login و تغییر رمز اجباری وجود دارند؛ route/template/process برای بازیابی امن حساب و احراز هویت مجدد وجود ندارد | تعریف کانال تأیید هویت و انقضای توکن با مالک/امنیت؛ سپس جریان reset و تست سوءاستفاده | IMPORTANT |
| 18 | core / deployment | اسکن بدافزار و قرنطینهٔ فایل بارگذاری‌شده | MISSING | اعتبارسنجی پسوند/امضا/ساختار/حجم وجود دارد؛ اسکن بدافزار و قرنطینه در مستند امنیت صریحاً نیازمند تکمیل است | اتصال به موتور اسکن مورد تأیید زیرساخت، قرنطینهٔ پیش از انتشار و fail-closed؛ نیازمند تصمیم/سرویس زیرساخت | BLOCKER |
| 19 | tasks | رویداد اولین مشاهده و زمان اقدام/تکمیل وظیفه | PARTIAL | TaskEvent ایجاد/تخصیص/تغییر وضعیت را ثبت می‌کند؛ در GET صفحه، first-view/acknowledgement و KPI مدت مشاهده تا اقدام در مدل/گزارش دیده نمی‌شود | افزودن رویدادهای زمانی سازگار با کاتالوگ و ثبت اتمیک زمان اولین مشاهده/اقدام؛ تست تکرار مشاهده و انتقال | IMPORTANT |
| 20 | workflow / feedback | چرخه رضایت‌سنجی پس از پایان پرونده | MISSING | چرخه اختیاری نظرسنجی پس از پایان، ثبت امتیاز/نظر و گزارش نرخ مشارکت در مدل/view/template وجود ندارد | فقط با حفظ اختیاری‌بودن و عدم اثر بر دسترسی/بستن پرونده؛ مدل، فرم و گزارش با scope | MINOR |

### 13.1 موارد EXCLUDED-BY-DECISION

| App | Capability | Verdict | دلیل قفل‌شده |
|---|---|---|---|
| accounts / all | نقش‌های Finance، Legal و Auditor | EXCLUDED-BY-DECISION | در تصمیم‌های محصول حذف شده‌اند و نباید به RoleAssignment، منو یا policy برگردند. |
| claims / all | انتقال وجه یا پرداخت بانکی از داخل سامانه | EXCLUDED-BY-DECISION | سامانه فقط سابقهٔ پرداخت اعلام‌شده را نگه می‌دارد؛ درگاه یا تراکنش بانکی ندارد. |
| claims | تشخیص قطعی duplicate با شباهت‌سنجی خودکار | EXCLUDED-BY-DECISION | duplicate فقط با اعلام بیمه‌گر منبع ثبت می‌شود؛ تطبیق سامانه صرفاً ابزار جست‌وجو است. |
| organizations | حساب مستقل برای فرد تحت تکفل | EXCLUDED-BY-DECISION | فرد وابسته زیر حساب بیمه‌شده اصلی مشاهده می‌شود. |
| repository / CI | افزودن GitHub Actions | EXCLUDED-BY-DECISION | راهنمای تست پروژه تصریح می‌کند CI workflow عمداً وجود ندارد؛ تست محلی توسط توسعه‌دهنده اجرا می‌شود. |

**تثبیت فاز ۳:** ۲۰ شکاف قابل اقدام در جدول بالا؛ ۵ مورد EXCLUDED-BY-DECISION جداگانه ثبت شد؛ هیچ قابلیت USED وارد فهرست نشده است. این دو جدول دامنهٔ بستهٔ کار فاز ۴ هستند.

## 14. وضعیت اعتبارسنجی و محدودیت شواهد

### 14.1 وضعیت branch/repository از GitHub
- مخزن: `msalimimaram/office_kmc`.
- شاخه بررسی: `implementation/insurance-platform-core-2026-11-04`.
- HEAD snapshot: `d0983f92daf2ae0d9298dad00ae0c89e901379af`.
- `main`: `a944760c8d442ee61015ea96cca135ea61fa0dac`.
- PR #1: Draft و open، base=`main`؛ ادغام نشده.
- branches مشاهده‌شده: `main`، `implementation/insurance-platform-core-2026-11-04`، `audit/project-assessment-2026-10-29`.
- GitHub Actions در پروژه عمداً وجود ندارد.

### 14.2 اجرای runtime در این محیط
| دستور/عملیات | وضعیت |
|---|---|
| `python manage.py check` روی HEAD فعلی d0983f9 | اجرا نشد؛ checkout مخزن در محیط فعلی وجود ندارد و DNS به github.com در دسترس نیست |
| `python manage.py showmigrations` روی HEAD فعلی | اجرا نشد؛ داده runtime/DB محلی قابل دسترسی نیست |
| `python manage.py test` روی HEAD فعلی | اجرا نشد؛ نتیجهٔ قبلی برای commit قدیمی‌تر است و قابل تعمیم به HEAD جدید نیست |
| `runserver` | اجرا نشد؛ checkout و محیط Python پروژه در این runtime موجود نیست |
| `makemigrations --check --dry-run` | آخرین گزارش قبلی کاربر در commit قدیمی‌تر clean بود؛ برای HEAD فعلی نیازمند اجرای مجدد است |
| working tree محلی Windows | از GitHub قابل مشاهده نیست؛ پاک بودن آن را نمی‌توان تأیید کرد |
| `flutter analyze/test/build` | موضوعیت ندارد؛ پروژهٔ Flutter در مخزن وجود ندارد |

**آخرین اجرای محلی گزارش‌شده از سوی کاربر:** روی HEAD قبلی `9bc1614`، `manage.py check` و `makemigrations --check --dry-run` موفق گزارش شد؛ suite شامل ۱۰۱ تست بود و یک تست محرمانگی تخصیص task شکست خورد. بعد از آن commits `78b3dbe`, `1302ae0`, `6036e4c`, `d0983f9` برای fix/test و محدودسازی dashboard به شاخه اضافه شده‌اند؛ اما تا اجرای مجدد در محیط کاربر، رفع خطای runtime «تأییدشده» محسوب نمی‌شود.

## 15. معیار پایان

پروژه فقط پس از اجرای مجدد روی HEAD نهایی و تأیید موارد زیر آماده اعلام پایان است:
- check و showmigrations بدون خطا/مهاجرت معلق؛
- کل suite با صفر failure/error؛
- runserver بدون traceback؛
- تمامی viewها route و تمام templateها render/include شده باشند؛
- مدل‌ها در view/form/admin یا مستند به‌عنوان زیرساخت داخلی مصرف شوند؛
- جریان‌های اصلی کاربر از entry point تا persistence تست client داشته باشند؛
- همهٔ شکاف‌های بخش ۱۳ CLOSED یا با دلیل دقیق BLOCKED/EXCLUDED ثبت شوند؛
- سند با آخرین HEAD و رفتار واقعی کد هم‌خوان باشد؛
- main فقط با تأیید صریح مالک تغییر کند؛ PR موجود تا پذیرش runtime ادغام نشود.

---
**قاعده نگهداری:** هر اصلاح یا آزمون جدید باید در بخش مربوط همین سند ثبت شود: commit SHA، فایل‌های تغییرکرده، route/template، نام تست واقعی و نتیجه واقعی اجرای آن.


## 16. الحاقات ممیزی و تکمیل پس از snapshot اولیه (2026-11-07)

این بخش وضعیت اجزایی را ثبت می‌کند که پس از نسخه اولیه این سند به شاخه پیاده‌سازی وصل شده‌اند. این بخش بر ردیف‌های قدیمی و متناقض جدول شکاف بخش ۱۳ مقدم است. HEAD کد بررسی‌شده پیش از commit همین به‌روزرسانی سند: cf283941452d3b3e5ef4cdc0d337bae8ff218605.

### 16.1 routeها و جریان‌های اضافه‌شده

| App | Method | Path | Name | View | Template / نقطه اتصال | وضعیت کد |
|---|---|---|---|---|---|---|
| requests_portal | GET | /requests/<pk>/attachment/ | request_attachment_download | request_attachment_download | لینک در request_detail.html فقط در صورت وجود attachment | پیاده‌سازی شده؛ تست runtime معلق |
| claims | POST | /claims/<pk>/objections/<objection_pk>/review/ | claim_objection_review | claim_objection_review | فرم اقدام در claim_detail.html | پاسخ/وضعیت/بستن برای نقش مجاز؛ ارجاع بیمه‌گر هنوز کامل نیست |
| documents | GET/POST | /documents/<pk>/manage/ | document_manage | document_manage | document_manage.html؛ لینک از document_list.html | نسخه‌بندی، بایگانی، ابطال؛ تست runtime معلق |
| organizations | GET/POST | /organizations/leadership-titles/ | company_leadership_titles | company_leadership_titles | leadership_titles.html؛ منوی base و ستون در people list | پیاده‌سازی شده؛ scope شرکت |
| correspondence | GET/POST | /correspondence/<pk>/ | correspondence_detail | correspondence_detail | correspondence_detail.html؛ subject فهرست به جزئیات لینک است | ثبت پیگیری/وضعیت و history append-only؛ تست runtime معلق |
| assets | GET | /assets/<pk>/ | asset_detail | asset_detail | asset_detail.html؛ لینک از فهرست | جزئیات دارایی و سوابق؛ تست runtime معلق |
| assets | GET/POST | /assets/<pk>/edit/ | asset_update | asset_update | asset_form.html در حالت update | ویرایش دارایی و Vehicle؛ تست runtime معلق |
| assets | GET | /assets/endorsements/<pk>/download/ | asset_endorsement_download | asset_endorsement_download | لینک از asset detail | دانلود امن پس از scope دارایی + ممیزی؛ تست runtime معلق |

### 16.2 فرم‌ها و templateهای اضافه‌شده

| App | فرم | اعتبارسنجی/دامنه | Template |
|---|---|---|---|
| claims | ClaimObjectionReviewForm | وضعیت از choices مدل؛ برای ANSWERED پاسخ غیرخالی لازم است | claim_detail.html |
| documents | DocumentVersionForm | فایل و شرح تغییر؛ signature/type/size در view با validate_uploaded_file | document_manage.html |
| documents | DocumentLifecycleActionForm | دلیل حداقل ۳ حرف و حداکثر ۵۰۰۰ کاراکتر | document_manage.html |
| organizations | CompanyLeadershipTitleForm | شرکت/شخص در محدوده انتصاب شرکت و اشتغال معتبر؛ title و بازه اعتبار مدل validate می‌شوند | leadership_titles.html |
| correspondence | CorrespondenceFollowUpForm | status از choices مدل؛ تاریخ پیگیری اختیاری؛ شرح اقدام ۲ تا ۲۰۰۰ کاراکتر | correspondence_detail.html |
| assets | AssetValuationForm | مقادیر منفی توسط مدل و قید DB رد می‌شوند؛ سابقه ارزیابی immutable است | asset_detail.html |
| assets | AssetPolicyPeriodForm | قرارداد محدود به شرکت مالک؛ بیمه‌گر باید با قرارداد یکسان باشد؛ status در view به draft تنظیم می‌شود | asset_detail.html |
| assets | AssetPolicyEndorsementForm | دوره بیمه‌نامه محدود به همان دارایی؛ فایل با signature/type/size اعتبارسنجی می‌شود | asset_detail.html |

### 16.3 وضعیت شکاف‌های قبلی پس از تغییرات

| App | Capability | Verdict قبلی | وضعیت کد پس از این دور | آزمون تعریف‌شده (اجرا نشده) |
|---|---|---|---|---|
| requests_portal | دریافت امن پیوست درخواست | PARTIAL | view/route/link و ممیزی دانلود اضافه شد؛ بستهٔ کد کامل، runtime تأیید نشده | ServiceRequestAttachmentDownloadTests (۳ تست) |
| claims | رسیدگی به اعتراض | PARTIAL | فرم/view/route و انتقال‌های محدود وضعیت و پاسخ append به متن قبلی اضافه شد؛ رفت‌وبرگشت به بیمه‌گر و مسئول ارجاع جداگانه هنوز موجود نیست | ClaimObjectionReviewFlowTests (۳ تست) |
| claims | پرداخت دستی/برگشت پرداخت | PARTIAL / BLOCKED | record_payment و reverse_payment سرویس دارند ولی pending approval state یا endpoint workflow ندارند؛ از ساخت فرم یک‌مرحله‌ای که تأییدکننده را صوری کند خودداری شده | آزمون‌های service موجود در claims/test_payments.py؛ endpoint test وجود ندارد |
| documents | نسخه جدید سند | PARTIAL | route مدیریت و add_document_version به فرم/صفحه وصل شد؛ runtime تأیید نشده | DocumentManagementFlowTests.test_specialist_can_add_document_version_and_current_version_is_updated |
| documents | آرشیو/ابطال سند | PARTIAL | route مدیریت و سرویس‌های archive/void با دلیل و دسترسی global وصل شدند؛ runtime تأیید نشده | DocumentManagementFlowTests (۵ تست مرتبط) |
| organizations | اعلام سمت مدیریتی شرکت | ORPHAN-MODEL | form/view/route/template/navigation/people-list وصل شد؛ عنوان هیچ permissionی ایجاد نمی‌کند؛ runtime تأیید نشده | CompanyLeadershipTitleFlowTests (۴ تست) |
| correspondence | پیگیری مکاتبه و مشاهده تاریخچه | PARTIAL | جزئیات و ثبت follow-up/status event اضافه شد؛ explicit assignee می‌تواند مکاتبه را ببیند/اقدام کند؛ runtime تأیید نشده | CorrespondenceFollowUpFlowTests (۴ تست) |
| assets | ثبت و ویرایش دارایی پایه | PARTIAL | جزئیات، edit route و vehicle edit وصل شد؛ runtime تأیید نشده | AssetOperationalWorkflowTests.test_specialist_can_update_asset_and_vehicle_details_through_scoped_route |
| assets | valuation | PARTIAL | ثبت/نمایش سابقه immutable وصل شد؛ تأییدکننده/مرجع تأیید در ACL روشن نیست | AssetOperationalWorkflowTests.test_specialist_can_open_asset_detail_and_add_immutable_valuation_record |
| assets | دوره بیمه‌نامه و الحاقیه | PARTIAL | ثبت پیش‌نویس دوره، الحاقیه و دانلود امن به دارایی وصل شد؛ تأیید/فعال‌سازی همچنان BLOCKED | AssetOperationalWorkflowTests.test_specialist_can_create_draft_policy_period_and_endorsement_with_secure_download و test_user_from_another_company_cannot_download_asset_endorsement |

### 16.4 محدودیت‌ها و تصمیم‌های رعایت‌شده

1. CompanyLeadershipTitle: ثبت سمت مطابق چرخه بخش ۳ کاتالوگ انجام شده است؛ چون سند قواعد تصریح می‌کند سمت مدیریتی به‌تنهایی مجوز داده‌ای ایجاد نمی‌کند، نه view و نه context processor آن را برای authorization استفاده نمی‌کنند.
2. Correspondence: بعد از ارجاع به assignee دیگر، ایجادکننده حق POST ندارد؛ مسئول فعلی یا دسترسی سراسری مجاز است. موقعیت Supervisor/Responsible با PositionAssignment زمان‌دار در منوی مکاتبات نمایش داده می‌شود.
3. Documents: افزودن نسخه برای کارشناس/نقش سراسری؛ archive/void در این پیاده‌سازی محافظه‌کارانه به global scope محدود شده‌اند. این محدودیت تا تعیین مجوز جزئی‌تر در ماتریس حفظ می‌شود.
4. Assets: ثبت/ویرایش پایه، ارزیابی، دوره و الحاقیه برای کارشناس رشته مجاز است. ارزیابی append-only می‌ماند. دوره جدید با وضعیت draft ایجاد می‌شود و approved_by خالی است. هیچ صفحه/دکمه‌ای دوره را فعال یا تأییدشده نشان نمی‌دهد. این عملیات تا تعیین مرجع تأیید و state transition صریح BLOCKED هستند.
5. Claim payment: هر دو سرویس پرداخت دستی و برگشت نیازمند تأییدکننده مستقل‌اند؛ مدل فعلی وضعیت درخواست تأیید/صف reviewer ندارد. افزودن view تک‌مرحله‌ای که یک نام را به‌عنوان تأییدکننده انتخاب کند، تأیید واقعی نیست و مجاز به پیاده‌سازی نیست.
6. Claim objection: وضعیت و response به‌روزرسانی می‌شود و response قبلی در متن حفظ می‌شود؛ اما route/assignee/رویداد دامنه‌ای مستقل برای ارسال به بیمه‌گر و بازگشت به اداره در مدل فعلی موجود نیست.
7. PersonChangeRequestForm: هنوز یتیم است. آن را به عنوان ویرایش مستقیم Person متصل نکرده‌ایم، چون قواعد مصوب تغییر موبایل/شبا/اطلاعات حساس را به گردش تأیید بیمه‌شده ← نماینده شرکت ← بیمه‌گر ← نماینده شرکت محدود کرده‌اند و مدل درخواست اختصاصی با old/new values و timestamps لازم در schema فعلی دیده نشد.
8. Workflow: موتور workflow فعلی در درخواست‌ها استفاده می‌شود؛ اتصال عمومی به claims/contracts/objections/correspondence/assets هنوز کامل نیست. اتصال بدون mapping معتبر ContentType، definition و scope انجام نمی‌شود.

### 16.5 تست‌ها و وضعیت اجرای واقعی

- تعداد متدهای تست از روی سورس فعلی: ۱۳۱ در ۱۸ فایل. این عدد تعداد تعریف‌هاست، نه تعداد اجراشده.
- در این محیط checkout محلی و شبکه دسترسی به GitHub برای دریافت clone وجود نداشت؛ manage.py check، showmigrations، test، runserver روی HEAD جاری اجرا نشدند.
- تست‌های بالا فقط در source اضافه شده‌اند؛ وضعیت همه آنها NOT RUN / نیازمند اجرای واقعی روی سیستم توسعه‌دهنده است.
- هیچ migration جدیدی در این موج اضافه نشده است؛ چون تغییرات فقط view/form/template/url/test بوده‌اند. بااین‌حال، makemigrations --check --dry-run برای HEAD فعلی نیز اجرا نشده و باید در محیط محلی اجرا شود.
- main همچنان دست‌نخورده و PR #1 باز و Draft است.

### 16.6 snapshot و commits این موج

- HEAD کد پیش از این commit سند: cf283941452d3b3e5ef4cdc0d337bae8ff218605.
- commit اصلاح تکمیلی پس از بازبینی مسیر ویرایش خودرو: cf283941452d3b3e5ef4cdc0d337bae8ff218605 (fix(assets): populate vehicle data before initial save).
- پس از ثبت این سند، SHA جدید commit سند باید از نتیجه GitHub ثبت شود.


## 17. بازبینی مجدد snapshot شاخه در 2026-11-08

این بخش به‌روزرسانی‌های پس از آخرین ثبت قبلی در سند را پوشش می‌دهد و در تعارض شمارشی/وضعیتی، مرجع جدیدتر است.

### 17.1 وضعیت GitHub در زمان بازبینی

- مخزن: `msalimimaram/office_kmc`؛ شاخهٔ جاری این ممیزی: `implementation/insurance-platform-core-2026-11-04`.
- HEAD مشاهده‌شده: `091495cf35bf2e667a3d00647256ebbe06fc6894`؛ آخرین پیام: `Expose documents: add scoped generic link form`؛ زمان commit: 2026-11-07 13:37:53 UTC.
- `main`: `a944760c8d442ee61015ea96cca135ea61fa0dac`.
- مقایسهٔ شاخه: implementation به‌اندازهٔ 333 commit جلوتر و صفر commit عقب‌تر از main است؛ PR شمارهٔ 1 باز و Draft و ادغام‌نشده است. 129 فایل در PR تغییر کرده‌اند.
- شاخهٔ `audit/project-assessment-2026-10-29` نیز در فهرست branchها وجود دارد؛ در این مرحله نه ادغام و نه حذف نشده است.
- در snapshot شاخهٔ implementation، 15 اپ در `INSTALLED_APPS`، 38 فایل migration شماره‌دار، 30 فایل HTML، 18 فایل تست و 131 تابع `test_*` مشاهده شد. شمار متدهای تست با خواندن فایل‌های تست در همین snapshot مجدداً محاسبه شد؛ این عدد به‌معنی اجرای تست‌ها نیست.
- فایل workflow مربوط به GitHub Actions در درخت این شاخه وجود ندارد؛ `docs/TESTING.md` در همین snapshot نیز به‌درستی تصریح می‌کند که پروژه عمداً GitHub Actions ندارد.

### 17.2 تغییرهای بعد از snapshot قبلی

- در اپ `correspondence`، فرم اتصال رکورد موجود به مکاتبه در جزئیات مکاتبه اضافه شده است. مسیر موجود `/correspondence/<pk>/` عملیات POST با `action=add_link` را می‌پذیرد؛ نوع‌های مقصد مجاز در فرم شامل company، contract، claim و request هستند. تابع بررسی مقصد، scope کاربر و سازگاری شرکت/بیمه‌گر مکاتبه و رکورد مقصد را کنترل می‌کند. لینک در `CorrespondenceLink` ذخیره و رویداد ممیزی ثبت می‌شود. تمپلیت جزئیات، فهرست ارتباط‌ها و فرم اتصال را نمایش می‌دهد.
- برای این قابلیت سه تست HTTP در `CorrespondenceLinkFlowTests` تعریف شده‌اند: اتصال موفق و persistence، رد شرکت خارج از scope، و رد هدف ناسازگار با شرکت مکاتبه. این تست‌ها در این محیط اجرا نشده‌اند.
- در اپ `documents`، کلاس `DocumentLinkForm` با مقصدهای claim، request، correspondence، contract، asset و task به `documents/forms.py` اضافه شده است. اما در HEAD فعلی، `documents/views.py` این فرم را import یا مصرف نمی‌کند؛ `documents/urls.py` مسیر اتصال ندارد؛ و `templates/documents/document_manage.html` فرم یا فهرست لینک‌ها را نمایش نمی‌دهد. بنابراین صرف وجود فرم، قابلیت اتصال سند به رکورد را کامل نمی‌کند. این مورد برای بررسی فاز ۱/۳ ثبت می‌شود و هنوز به‌عنوان قابلیت متصل‌شده شمرده نمی‌شود.

### 17.3 شمارش فعلی تست‌ها بر اساس سورس

| فایل | تعداد تعریف `test_*` |
|---|---:|
| accounts/tests.py | 6 |
| accounts/test_access.py | 5 |
| announcements/tests.py | 1 |
| assets/tests.py | 8 |
| auditlog/tests.py | 4 |
| claims/tests.py | 12 |
| claims/test_payments.py | 8 |
| core/tests.py | 6 |
| core/test_permissions.py | 1 |
| correspondence/tests.py | 9 |
| dashboard/tests.py | 4 |
| documents/tests.py | 10 |
| imports/tests.py | 13 |
| insurance/tests.py | 2 |
| organizations/tests.py | 7 |
| requests_portal/tests.py | 18 |
| tasks/tests.py | 5 |
| workflow/tests.py | 12 |
| **مجموع** | **131** |

این جدول شمار تعریف‌های آزمون از روی کد است؛ اجرا، pass/fail و پوشش runtime هنوز جداگانه باید تأیید شوند.

### 17.4 محدودیت اجرای محلی در این نشست

- تلاش برای clone مستقیم شاخه با GitHub انجام شد، اما محیط اجرا نتوانست دامنهٔ `github.com` را resolve کند (`Could not resolve host: github.com`). checkout محلی پروژه در این محیط ایجاد نشد.
- در نتیجه در این نشست `python manage.py check`، `showmigrations`، `test`، `runserver`، `makemigrations --check --dry-run` و اجرای migration واقعاً انجام نشده‌اند.
- نتیجهٔ قدیمی `check` روی commit قبلی یا ادعای داخل سند را نمی‌توان به HEAD فعلی تعمیم داد. همهٔ این موارد برای پذیرش فاز ۵ باز هستند.
- وضعیت working tree ویندوز کاربر از GitHub قابل مشاهده نیست؛ فقط commit/branch راه دور قابل بررسی است.

### 17.5 وضعیت سند و قواعد نگهداری

- این سند موجود، `docs/PROJECT_MASTER.md`، سند جامع زندهٔ پروژه است؛ در این ممیزی سند موازی یا جایگزین ساخته نشده است.
- هر حکم CLOSED در فاز تکمیل باید هم نام تست اجراشده، هم نتیجهٔ واقعی اجرای تست و هم commit حاوی تغییر را داشته باشد. تعریف تست در سورس، به‌تنهایی CLOSED نیست.
- شکاف‌های قدیمی جدول بخش ۱۳ و وضعیت‌های بخش ۱۶ باید با نتایج ممیزی جزءبه‌جزء این snapshot همسان شوند؛ مواردی که صرفاً در فاز بعد از نظر UI/flow بررسی شوند نباید زودتر USED اعلام شوند.


### 17.6 نقشهٔ اپ‌ها بر اساس فایل‌های HEAD

در جدول زیر «دارد» به‌معنی وجود فایل و محتوای بررسی‌شده در شاخه است، نه تضمین کامل بودن جریان runtime. فایل‌های template احراز هویت در پوشهٔ سراسری `templates/registration` قرار دارند.

| App | models.py | views.py | forms.py | urls.py | admin.py | Tests | Templateهای اصلی |
|---|---|---|---|---|---|---:|---|
| accounts | دارد | دارد | دارد | ندارد؛ مسیرها در config | دارد | 11 | registration/login، password_change |
| announcements | دارد | دارد | دارد | دارد | دارد | 1 | announcement_list، announcement_form |
| assets | دارد | دارد | دارد | دارد | دارد | 8 | asset_list، asset_form، asset_detail |
| auditlog | دارد | ندارد؛ سرویس/مدل ممیزی | ندارد | ندارد | دارد؛ فقط‌خواندنی | 4 | ندارد |
| claims | دارد | دارد | دارد | دارد | دارد؛ فقط‌خواندنی | 20 | claim_list، claim_detail |
| core | ندارد؛ زیرساخت مجوز/فایل | ندارد | ندارد | ندارد | ندارد | 7 | ندارد |
| correspondence | دارد | دارد | دارد | دارد | دارد؛ فقط‌خواندنی | 9 | correspondence_list، correspondence_form، correspondence_detail |
| dashboard | ندارد | دارد | ندارد | ندارد؛ مسیرها در config | ندارد | 4 | dashboard/home |
| documents | دارد | دارد | دارد | دارد | دارد؛ فقط‌خواندنی | 10 | document_list، document_upload، document_manage |
| imports | دارد | دارد | دارد | دارد | دارد؛ فقط‌خواندنی | 13 | claim_import |
| insurance | دارد | دارد | فایل forms.py ندارد | دارد | دارد | 2 | contract_list |
| organizations | دارد | دارد | دارد | دارد | دارد | 7 | people_list، leadership_titles |
| requests_portal | دارد | دارد | دارد | دارد | دارد؛ ثبت سادهٔ ServiceRequest | 18 | request_list، request_form، request_detail |
| tasks | دارد | دارد | دارد | دارد | دارد؛ فقط‌خواندنی | 5 | task_list، task_form، task_update |
| workflow | دارد | دارد؛ POST action در view | فایل forms.py ندارد | دارد | دارد؛ پیکربندی تعریف‌ها | 12 | workflow_case_list، workflow_case_detail |

- مجموع فایل‌های آزمون: 18؛ مجموع تعریف‌های `test_*`: 136 (پس از افزودن 5 تست HTTP/جریان در فاز ۴).
- 13 اپ دارای `models.py` و 13 اپ دارای `views.py` هستند؛ `core` و `dashboard` عمداً مدل ندارند.
- 10 اپ دارای `forms.py`، 11 اپ دارای `urls.py` و 13 اپ دارای `admin.py` هستند.
- 30 فایل HTML موجود است: 28 فایل در `templates/` و 2 فایل در `workflow/templates/workflow/`. `templates/base.html` و `templates/includes/pagination.html` مشترک‌اند.
- 38 فایل migration شماره‌دار در 13 اپ وجود دارد؛ `core` و `dashboard` migration شماره‌دار ندارند. این شمارش، وضعیت اعمال‌شدن migrationها در دیتابیس را مشخص نمی‌کند.

### 17.7 نقشهٔ URL و نقاط ورود

شش مسیر ریشه در `config/urls.py` تعریف شده‌اند: `/admin/`، `/accounts/login/`، `/accounts/logout/`، `/accounts/password-change/`، `/` و `/dashboard/`. مسیر home و dashboard هر دو به نمای داشبورد می‌رسند.

33 الگوی مسیر در 11 فایل `urls.py` اپ‌ها ثبت شده‌اند:
- organizations: فهرست اشخاص و `leadership-titles/`.
- insurance: فهرست قراردادها.
- claims: فهرست، جزئیات و رسیدگی به اعتراض.
- requests_portal: فهرست، ایجاد، جزئیات و دانلود پیوست.
- tasks: فهرست، ایجاد و به‌روزرسانی.
- imports: ورود خسارت از اکسل و تأیید batch.
- documents: فهرست، بارگذاری، دانلود و مدیریت/نسخه‌بندی.
- assets: فهرست، ایجاد، جزئیات، ویرایش و دانلود الحاقیه.
- announcements: فهرست، ایجاد و دانلود پیوست.
- correspondence: فهرست، ایجاد، جزئیات و دانلود پیوست.
- workflow: فهرست ارجاعات و جزئیات/اقدام گردش کار.

در auth routeها endpoint ثبت‌نام یا بازیابی رمز فراموش‌شده وجود ندارد؛ فقط login، logout و password change متصل‌اند. ایجاد/فعال‌سازی حساب در وضعیت فعلی از پنل مدیریت انجام می‌شود. بازیابی امن رمز در قواعد کسب‌وکار الزام شده و هنوز مسیر کاربرمحور آن در URLهای فعلی دیده نمی‌شود.

### 17.8 مشاهدات تکمیلی فاز ۱ از سورس واقعی

1. `requests_portal/admin.py` فقط `admin.site.register(ServiceRequest)` را فراخوانی می‌کند و ModelAdmin سفارشی ندارد. از آنجا که middleware دسترسی head و system_admin به `/admin/` را می‌پذیرد، این مسیر پیش‌فرض امکان تغییر مستقیم فیلدهای وضعیت/مسئول/پاسخ درخواست را خارج از `workflow.services.transition_case` فراهم می‌کند. مدل فقط محرمانگی درخواست پزشکی را در `save()` تحمیل می‌کند. این یک مسیر بالقوهٔ دور زدن گردش‌کار/ممیزی است و باید در شکاف‌ها با تست HTTP ادمین بررسی و محدود شود.
2. `organizations/admin.py` برای `Person` ثبت عمومی پیش‌فرض دارد؛ در مقابل، `PersonChangeRequestForm` در `organizations/forms.py` هیچ view یا URL مصرف‌کننده ندارد. قواعد کسب‌وکار تغییر مستقیم موبایل را مجاز نمی‌دانند و مسیر بیمه‌شده → نماینده شرکت → بیمه‌گر → بازبینی نماینده → اطلاع‌رسانی را الزام می‌کنند. `ServiceRequest` فعلی فقط عنوان/شرح و status عمومی دارد و فیلد ساختاریافتهٔ old/new و زمان هر مرحله ندارد؛ جریان تغییر موبایل فعلاً کامل پیاده نشده است.
3. `PersonEmployment` در scope، import و فهرست اشخاص مصرف می‌شود، اما view/form مستقل برای مدیریت و تأیید سوابق اشتغال ندارد؛ مدل orphan نیست، ولی چرخهٔ مدیریت آن ناقص است.
4. `insurance.Contract` و `ContractRevision` در admin ثبت شده‌اند، اما رابط Template-based اپ فقط فهرست قرارداد را ارائه می‌کند. قواعد کسب‌وکار ثبت قرارداد توسط کارشناس و تأیید توسط رئیس اداره/مدیر سامانه، نسخه‌ها، الحاقیه و آثار زمانی را الزام می‌کنند؛ چرخهٔ ایجاد/بازبینی/تأیید در UI جاری دیده نمی‌شود.
5. `ClaimPayment`، ثبت پرداخت، برگشت و ثبت ورودی تأییدشده در سرویس‌های تراکنشی وجود دارند؛ اما مسیر view/form/URL برای ثبت و تأیید مستقل پرداخت در اپ claims ارائه نشده است. این قابلیت نباید با یک عملیات تک‌مرحله‌ای یا تأیید توسط همان ثبت‌کننده جایگزین شود.
6. `workflow` موتور عمومی دارد، ولی در view فعلی اتصال خودکار زمان ایجاد فقط در `requests_portal` دیده می‌شود. اتصال claim objection، contract/revision، person change، correspondence و asset به workflow هنوز کامل نیست.
7. `DocumentLinkForm` یتیم/مصرف‌نشده است؛ `DocumentLink` در scope خواندن اسناد برای claim-linkها پرس‌وجو می‌شود، اما UI یا view برای ایجاد لینک سند به رکوردهای مجاز وجود ندارد و مدل در admin نیز ثبت نشده است.
8. داشبورد KPIهای مدیریتی و بیمه‌شده را محاسبه می‌کند؛ ابزار گزارش‌ساز قابل پیکربندی و گزارش تجمیعی SLA در Template UI فعلی مشاهده نشد.
9. `mfa_enabled` فقط فیلد مدل است؛ مسیر challenge، factor enrollment، recovery code یا تنظیمات MFA در view/form/URL فعلی دیده نمی‌شود. قواعد محصول MFA و بازیابی امن رمز را لازم دانسته‌اند.
10. `core.permissions.py` و `core.policies.py` دو لایهٔ helper با توابع هم‌نام برای scope/transition دارند. تا زمان بررسی همهٔ importها نباید یکی حذف یا ادغام شود؛ اختلاف رفتار میان آن‌ها باید در فاز ۱ ثبت و مصرف واقعی هر تابع مشخص شود.

### 17.9 بازبینی قواعد قفل‌شده

- نقش‌های finance، legal و auditor در migration اطلاعیه‌ها حذف شده‌اند و در access helper نیز legacy fallback آن‌ها رد می‌شود؛ این نقش‌ها نباید بازگردند.
- قرارداد/تغییر دادهٔ بیمه‌گر نیازمند تأیید مرجع داخلی است؛ تصمیم نهایی دربارهٔ تکراری بودن خسارت فقط از منبع بیمه‌گر پذیرفته می‌شود.
- نماینده بیمه‌گر نمی‌تواند پرونده را نهایی ببندد؛ قفل مطلق فقط برای مدیر سامانه است.
- SLA در وضعیت انتظار هم متوقف نمی‌شود.
- مسیر تغییر موبایل باید تمام مراحل و مقادیر قبل/بعد را ثبت کند؛ وجود نوع درخواست عمومی یا فرم بدون مصرف، جایگزین آن نیست.
- مدارک پزشکی فقط در محدودهٔ رئیس اداره و مدیر سامانه قرار می‌گیرند و فایل‌ها باید از مسیر دانلود مجاز، نه URL عمومی media، ارائه شوند.
- GitHub Actions عمداً در این پروژه وجود ندارد؛ تست‌ها طبق تصمیم فعلی از محیط توسعه‌دهنده اجرا می‌شوند.

### 17.10 وضعیت branch پس از به‌روزرسانی سند

- commitهای مستنداتی این ممیزی روی شاخهٔ implementation ثبت شده‌اند؛ آخرین commit سند در زمان این الحاق باید از refs شاخه دریافت شود و با HEAD کد بررسی‌شده اشتباه نشود.
- `main` بدون تغییر باقی مانده است. 333 commit اختلاف PR مربوط به snapshot کد اولیه است؛ commitهای مستنداتی این نشست پس از آن به شاخه اضافه شده‌اند.
- در نبود checkout محلی و اجرای تست روی HEAD، هیچ آیتمی صرفاً بر اساس وجود view/template/test به وضعیت CLOSED ارتقا داده نمی‌شود.


### 17.11 اصلاحات فاز ۴ — کد و تست‌های افزوده‌شده (2026-11-08)

این اصلاحات فقط روی شکاف‌های از پیش ثبت‌شدهٔ #8، #9 و #11 انجام شده‌اند؛ هیچ capability جدیدی به دامنه اضافه نشده است.

| Gap # | فایل‌های تغییرکرده | رفتار تغییریافته | تست HTTP افزوده‌شده | وضعیت |
|---:|---|---|---|---|
| 8 | `requests_portal/admin.py`, `requests_portal/tests.py` | ServiceRequest در Admin برای مدیر/رئیس قابل مشاهده است؛ add/change/delete بسته شد تا وضعیت، مسئول یا پاسخ از مسیر خارج از Workflow تغییر نکند | `ServiceRequestAdminIsolationTests.test_global_operator_can_view_requests_but_cannot_add_change_or_delete`; `test_admin_post_cannot_change_request_status_or_assignment` | پیاده‌سازی شد؛ اجرا نشده؛ BLOCKED verification |
| 9 | `organizations/admin.py`, `organizations/tests.py` | Person در Admin قابل مشاهده و ایجاد اولیه توسط اپراتور global است؛ ویرایش و حذف مستقیم ممنوع شد تا تغییر هویت/تماس/شبا از مسیر مصوب انجام شود | `PersonAdminChangeProtectionTests.test_global_operator_can_view_and_create_person_but_cannot_edit_or_delete_existing_person`; `test_admin_post_cannot_bypass_person_change_workflow` | پیاده‌سازی شد؛ اجرا نشده؛ BLOCKED verification |
| 11 | `requests_portal/views.py`, `requests_portal/tests.py` | ایجاد درخواست و شروع workflow در یک تراکنش قرار گرفت؛ ValidationError ناشی از تعریف/گیرنده نامعتبر به خطای فرم تبدیل می‌شود و هیچ درخواست نیمه‌کاره‌ای باقی نمی‌ماند | `RequestWorkflowConfigurationFailureTests.test_missing_initial_recipient_returns_form_error_and_rolls_back_request_creation` | پیاده‌سازی شد؛ اجرا نشده؛ BLOCKED verification |

**Commitهای کد و تست فاز ۴:**
- `a5dd319d02207d9f2fff36e4ff8b666feb751f27` — محدودسازی ServiceRequest Admin به مشاهده.
- `50ad6fc9b36725fa4c7dc5bd758b41d8cf171c67` — حفاظت از Person در Admin.
- `7882ea4166e0209a85e4e3e12faf31b6b2ff6185` — تست دسترسی/عدم تغییر ServiceRequest در Admin.
- `dfe5e0dc417ed5776f804263da1e5ab48dae3fa1` — تست محدودیت ویرایش مستقیم Person.
- `fc75cfaa7e717cb520a9c223cbca50d98f04b742` — مدیریت اتمیک خطای گیرندهٔ workflow در request_create.
- `e3a394ce3ac79d6ea0b95a5630dff93ecd7d264f` — تست rollback برای workflow بدون گیرنده.

### 17.12 وضعیت فعلی اجرای Phase 4 و محدودیت محیط

- تعریف تست‌ها در سورس از 131 به 136 رسیده؛ در requests_portal از 18 به 21 و در organizations از 7 به 9 افزایش یافته است. این شمارش static است، نه اجرای suite.
- تلاش اول برای checkout محلی با `git clone` با خطای DNS `Could not resolve host: github.com` متوقف شد.
- تلاش دوم برای materialize کردن archive مخزن نیز checkout قابل اجرا نساخت؛ محیط همچنان فایل‌های پروژه/دیتابیس را در اختیار نمی‌گذارد.
- به همین دلیل هیچ تست جدید، تست اپ، full suite یا `manage.py check/showmigrations/runserver` اجرا نشده است. دو تلاش دسترسی به checkout شکست خورده و هر دو patch تا آزمون واقعی BLOCKED باقی می‌مانند.
- Gap #8/#9/#11 از نظر سورس اصلاح شده‌اند ولی CLOSED نیستند؛ باید روی checkout واقعی، تست‌های نام‌برده و تست‌های موجود همان اپ اجرا شوند. اگر تست رد شود، حداکثر یک تلاش اصلاحی دیگر مجاز است؛ پس از شکست تلاش دوم، دلیل دقیق BLOCKED حفظ می‌شود.
- آخرین HEAD راه دور پس از اصلاحات: `e3a394ce3ac79d6ea0b95a5630dff93ecd7d264f`.
- PR #1 هنوز Draft و Open و ادغام‌نشده است؛ implementation نسبت به main در این snapshot 345 commit جلوتر و 0 عقب‌تر است؛ 131 فایل در PR تغییر کرده‌اند. `main` تغییر نکرده است.


### 17.13 فهرست تفصیلی مدل‌های پایگاه داده

این فهرست از خواندن مستقیم `models.py` تمام اپ‌ها تهیه شده است. کلاس‌های QuerySet، enum و TextChoices مدل پایگاه داده محسوب نشده‌اند. `core` و `dashboard` عمداً مدل persistence ندارند.

| App | Model | Fields اصلی | Methods / رفتار | روابط و قیدهای کلیدی |
|---|---|---|---|---|
| accounts | User | username, role, mobile, national_id, company, insurer, must_change_password, mfa_enabled + فیلدهای AbstractUser | str | کاربر سفارشی؛ company→Company، insurer→Insurer |
| accounts | OrganizationalUnit | code, name, parent, company, is_active, created_at | clean, save, str | درخت واحد؛ parent به خودش؛ جلوگیری از چرخه و ناسازگاری شرکت |
| accounts | OrganizationalPosition | unit, code, title, level, is_active | str | unique(unit,code)، متعلق به OrganizationalUnit |
| accounts | RoleAssignment | user, role, company, insurer, organizational_unit, position, line_code, valid_from/until, is_active, reason, granted_by, approved_by, timestamps | clean, save, is_valid_on, str | انتصاب زمان‌دار؛ قیود company برای subsidiary_rep و insurer برای insurer_representative؛ indexهای scope |
| accounts | PositionAssignment | user, unit, position, line_code, valid_from/until, is_active, reason, granted_by, approved_by, created_at | clean, save, str | انتصاب سازمانی زمان‌دار؛ بازه اعتبار |
| announcements | Announcement | title, body, audience, company, attachment, is_published, publish_at, expires_at, created_by, timestamps | is_current, str | audience و company؛ زمان انتشار/انقضا |
| assets | InsuredAsset | asset_code, name, asset_type, company/person, identifier, location, insured_value, insurer, contract, policy_number, policy_start/end, is_active, notes, created_by, timestamps | clean, save, str | مالکیت XOR شرکت/شخص؛ مبلغ غیرمنفی و تاریخ معتبر |
| assets | Vehicle | asset, plate_number, vin, engine_number, make, model_name, model_year | clean, save, str | OneToOne با InsuredAsset |
| assets | AssetValuation | asset, valuation_date, market_value, insured_value, method, source_reference, note, created_by, approved_by, created_at | clean, save, delete, str | مبالغ غیرمنفی؛ approved_by وجود دارد ولی تأیید در UI پیاده نشده |
| assets | AssetPolicyPeriod | asset, insurer, contract, policy_number, policy_start/end, status, source_reference, note, created_by, approved_by, created_at | clean, save, str | اعتبار بازه؛ وضعیت پیش‌نویس و بدون مسیر تأیید |
| assets | AssetPolicyEndorsement | policy_period, endorsement_number, effective_date, description, document, created_by, approved_by, created_at | — | unique(policy_period,endorsement_number) |
| auditlog | AuditEvent | actor, action, object_type/id, summary, before_data, after_data, metadata, ip_address, user_agent, correlation_id, created_at | save, delete, str | append-only؛ مصرف در تمام جریان‌ها؛ فقط‌خواندنی در Admin |
| claims | Claim | claim_number, source_claim_number, person, primary_insured, company_snapshot, contract, insurer, service/registration dates, contract_number_snapshot, service_type, requested/assessed/payable/paid_amount, status, source_reference, source_duplicate fields, assessment_note, result_sent_at/by, imported_at, timestamps | objection_deadline, clean, save, str | مبالغ نامنفی؛ paid≤payable؛ duplicate اعلامی نیازمند insurer؛ indexهای شرکت/بیمه‌گر/بیمه‌شده |
| claims | ClaimPayment | claim, entry_type, amount, paid_at, source_reference, source_insurer, reverses_payment, note, recorded_by, confirmed_by, is_legacy_import, created_at | signed_amount, clean, save, delete, str | دفترکل immutable؛ برگشت با رکورد مستقل؛ تأییدکننده مستقل |
| claims | ClaimObjection | claim, submitted_by, description, status, response, deadline_at, timestamps | clean, save | مهلت اعتراض ۶۰ روز از ارسال نتیجه؛ عملیات پاسخ/وضعیت در view |
| correspondence | CorrespondenceSequence | solar_date, last_number, updated_at | str | شمارنده مشترک سری روزانه |
| correspondence | Correspondence | internal_number, subject, channel, direction, company, insurer, contract, external_reference, summary, occurred_at, follow_up_due/status, assigned_to, is_confidential, attachment, created_by, timestamps | clean, save, str | شماره‌گذاری از service؛ company/insurer/contract/assignee |
| correspondence | CorrespondenceLink | correspondence, content_type, object_id, created_by, created_at | — | GenericFK؛ unique(correspondence,content_type,object_id) |
| correspondence | CorrespondenceEvent | correspondence, actor, event_type, summary, metadata, occurred_at | save, delete | append-only؛ تاریخچه پیگیری |
| documents | DocumentRecord | title, category, file, uploaded_by, company, person, security_level, is_medical, is_confidential, archive/void flags, archive/void timestamps and reasons, created_at | clean, save, current_version, delete, str | archive/void نیازمند دلیل؛ حفاظت lifecycle و محرمانگی |
| documents | DocumentVersion | document, version_number, file, uploaded_by, change_reason, checksum_sha256, is_current, uploaded_at | clean, save, delete, str | unique(document,version_number)، حداکثر یک نسخه جاری |
| documents | DocumentLink | document, content_type, object_id, created_by, created_at | — | GenericFK؛ unique(document,content_type,object_id)؛ فرم اتصال هنوز view ندارد |
| documents | DocumentAccessEvent | document, version, actor, action, ip_address, occurred_at | save, delete | immutable؛ ثبت مشاهده/دانلود |
| imports | ImportBatch | batch_number, source_type, file, uploaded_by, status, total/valid/invalid_rows, result_report, preview_data, reviewed_by/at, review_note, created_at | — | batch ورود Excel خسارت؛ preview و تأیید مستقل |
| insurance | Insurer | name, contact_name, contact_email, contact_phone, is_active | str | مرجع بیمه‌گر |
| insurance | Contract | code, title, insurer, line, start/end_date, companies(M2M), coverage_summary, terms, is_active, created_at | clean, save, str | end_date≥start_date؛ رابطه چندبه‌چند Companies |
| insurance | ContractRevision | contract, revision_number, description, document, created_by, created_at | — | unique(contract,revision_number)؛ UI چرخه نسخه ندارد |
| organizations | Company | code, name, parent, is_parent, is_active, created_at | clean, save, str | درخت شرکت مادر/تابعه |
| organizations | Person | company, user, personnel_code, national_id, first/last name, birth_date, relationship, employee, mobile, iban, is_insured, is_active, updated_at | clean, save, str | شناسه ملی یکتا؛ employee برای وابسته |
| organizations | PersonEmployment | person, company, personnel_code, job_title, valid_from/until, status, source_reference, created_by, approved_by, timestamps | clean, save, str | یک اشتغال فعال برای هر شخص؛ بازه زمانی معتبر |
| organizations | CompanyLeadershipTitle | company, person, title, valid_from/until, declared_by, timestamps | clean, save, str | اعتبار زمانی؛ در رابط نماینده شرکت مدیریت می‌شود |
| requests_portal | ServiceRequest | reference, kind, submitted_by, person, company, title, description, status, assigned_to, response, attachment, is_confidential, timestamps | clean, save, str | درخواست کمک درمانی همیشه محرمانه؛ در Admin اکنون فقط‌خواندنی |
| tasks | InternalTask | title, description, created_by, assignees(M2M), priority, status, due_at, related_request, timestamps | str | گردش task و محدودیت assignee |
| tasks | TaskEvent | task, actor, event_type, from_value, to_value, note, occurred_at | save, delete | append-only؛ تاریخچه وظیفه |
| workflow | WorkflowDefinition | code, title, version, is_active, description, created_by, approved_by, created_at, published_at | clean, save, delete, str | unique(code,version)، یک نسخه فعال؛ نسخه منتشرشده immutable |
| workflow | WorkflowStep | definition, code, title, order, allowed_roles, sla_minutes, is_initial, is_terminal, allow_return, requires_acknowledgement | clean, save, delete, str | unique(definition,code)، دقیقاً یک مرحله آغازین |
| workflow | WorkflowTransition | definition, source_step, target_step, action_code, title, allowed_roles, recipient_roles, requires_note, is_return, closes_case | clean, save, delete, str | unique(source_step,action_code)؛ source/target باید از یک تعریف باشند |
| workflow | WorkflowCase | definition, content_type, object_id, current_step, current_assignee, status, opened_at, first_viewed_at, first_action_at, sla_due_at, closed_at, is_locked, locked_by | str | GenericFK؛ unique(definition,content_type,object_id)؛ index assignee/status |
| workflow | WorkflowEvent | workflow_case, actor, event_type, action_code, from/to_step, from/to_assignee, note, opened/acknowledged/acted/sent timestamps, metadata | save, delete | append-only؛ index timeline |
| workflow | BusinessCalendar | code, title, timezone_name, working_weekdays, start_time, end_time, is_active | clean, save | اعتبارسنجی timezone/روزها/ساعت؛ پیش‌فرض تقویم ایران |
| workflow | CalendarHoliday | calendar, date, title, is_working_override | — | unique(calendar,date)؛ روز تعطیل یا استثنای کاری |

در جدول بالا انواع دقیق هر ستون در تعریف مدل آمده‌اند؛ فایل‌های مدل و migration مرجع نهایی nullability، default، verbose_name و گزینه‌های کامل Django هستند. کلاس‌های کمکی QuerySet و enumهای `TextChoices` در شمار ۴۱ مدل persistence منظور نشده‌اند.

### 17.14 فهرست کامل URLها

شش مسیر ریشه و ۳۳ مسیر اپی (۳۹ الگوی `path()`) در سورس ثبت شده‌اند. روش HTTP بر اساس decorator و مصرف request در view گزارش شده است؛ این فهرست جایگزین اجرای `resolve()` در محیط Django نیست.

| App | Path | URL name | Method | View |
|---|---|---|---|---|
| root | `/admin/` | admin:index | GET/POST | Django Admin |
| accounts | `/accounts/login/` | login | GET/POST | LoginView + ThrottledAuthenticationForm |
| accounts | `/accounts/logout/` | logout | POST | LogoutView |
| accounts | `/accounts/password-change/` | password_change | GET/POST | RequiredPasswordChangeView |
| dashboard | `/` | home | GET | dashboard.home |
| dashboard | `/dashboard/` | dashboard | GET | dashboard.home |
| organizations | `/organizations/` | people_list | GET | people_list |
| organizations | `/organizations/leadership-titles/` | company_leadership_titles | GET/POST | company_leadership_titles |
| insurance | `/insurance/contracts/` | contract_list | GET | contract_list |
| claims | `/claims/` | claim_list | GET | claim_list |
| claims | `/claims/<int:pk>/` | claim_detail | GET/POST | claim_detail |
| claims | `/claims/<int:pk>/objections/<int:objection_pk>/review/` | claim_objection_review | POST | claim_objection_review |
| requests_portal | `/requests/` | request_list | GET | request_list |
| requests_portal | `/requests/new/` | request_create | GET/POST | request_create |
| requests_portal | `/requests/<int:pk>/` | request_detail | GET/POST | request_detail |
| requests_portal | `/requests/<int:pk>/attachment/` | request_attachment_download | GET | request_attachment_download |
| tasks | `/tasks/` | task_list | GET | task_list |
| tasks | `/tasks/new/` | task_create | GET/POST | task_create |
| tasks | `/tasks/<int:pk>/` | task_update | GET/POST | task_update |
| imports | `/imports/claims/` | claim_import | GET/POST | claim_import |
| imports | `/imports/claims/<int:batch_id>/confirm/` | claim_import_confirm | POST | claim_import_confirm |
| documents | `/documents/` | document_list | GET | document_list |
| documents | `/documents/upload/` | document_upload | GET/POST | document_upload |
| documents | `/documents/<int:pk>/download/` | document_download | GET | document_download |
| documents | `/documents/<int:pk>/manage/` | document_manage | GET/POST | document_manage |
| assets | `/assets/` | asset_list | GET | asset_list |
| assets | `/assets/new/` | asset_create | GET/POST | asset_create |
| assets | `/assets/<int:pk>/` | asset_detail | GET/POST | asset_detail |
| assets | `/assets/<int:pk>/edit/` | asset_update | GET/POST | asset_update |
| assets | `/assets/endorsements/<int:pk>/download/` | asset_endorsement_download | GET | asset_endorsement_download |
| announcements | `/announcements/` | announcement_list | GET | announcement_list |
| announcements | `/announcements/new/` | announcement_create | GET/POST | announcement_create |
| announcements | `/announcements/<int:pk>/attachment/` | announcement_download | GET | announcement_download |
| correspondence | `/correspondence/` | correspondence_list | GET | correspondence_list |
| correspondence | `/correspondence/new/` | correspondence_create | GET/POST | correspondence_create |
| correspondence | `/correspondence/<int:pk>/` | correspondence_detail | GET/POST | correspondence_detail |
| correspondence | `/correspondence/<int:pk>/attachment/` | correspondence_download | GET | correspondence_download |
| workflow | `/workflow/` | workflow_case_list | GET | workflow_case_list |
| workflow | `/workflow/<int:pk>/` | workflow_case_detail | GET/POST | workflow_case_detail |

Logout فقط POST است و در فرم خروج base template مصرف می‌شود. عملیات تغییر وضعیت detailها عموماً POST روی همان URL صفحه انجام می‌شود؛ دو مسیر review اعتراض و confirm واردات فقط POST هستند.

### 17.15 فهرست viewها، مجوز و template

تمام viewهای دامنه به‌جز `RequiredPasswordChangeView`، تابعی (FBV) هستند. موارد زیر از view و URL خوانده شده‌اند.

| App | View | Type | URL | Permission / scope و فرم | Template |
|---|---|---|---|---|---|
| accounts | RequiredPasswordChangeView | CBV | accounts/password-change/ | احراز هویت؛ PasswordChangeForm؛ middleware اجبار رمز | registration/password_change |
| dashboard | home | FBV | / و dashboard/ | login؛ KPI براساس scope نقش | dashboard/home |
| organizations | people_list | FBV | organizations/ | login؛ global/company/insured scope | organizations/people_list |
| organizations | company_leadership_titles | FBV | organizations/leadership-titles/ | نماینده با انتصاب شرکت؛ CompanyLeadershipTitleForm | organizations/leadership_titles |
| insurance | contract_list | FBV | insurance/contracts/ | login؛ _contract_scope | insurance/contract_list |
| claims | claim_list | FBV | claims/ | login؛ scoped_claims_for | claims/claim_list |
| claims | claim_detail | FBV | claims/<pk>/ | login و scope؛ اعتراض فقط نقش/پرونده واجدشرایط؛ ClaimObjectionForm | claims/claim_detail |
| claims | claim_objection_review | FBV | objections/<objection_pk>/review | POST؛ can_decide_claim؛ ClaimObjectionReviewForm | redirect به claim_detail |
| requests_portal | request_list | FBV | requests/ | login؛ scoped_requests_for | requests_portal/request_list |
| requests_portal | request_create | FBV | requests/new/ | insured/company rep/global؛ ServiceRequestForm؛ شروع workflow اختیاری | requests_portal/request_form |
| requests_portal | request_detail | FBV | requests/<pk>/ | login؛ scoped request؛ workflow assignee/global یا legacy policy | requests_portal/request_detail |
| requests_portal | request_attachment_download | FBV | requests/<pk>/attachment | login؛ scoped request؛ FileResponse و AuditEvent | ندارد؛ دانلود امن |
| tasks | task_list | FBV | tasks/ | login؛ _visible_tasks | tasks/task_list |
| tasks | task_create | FBV | tasks/new | مدیر/سرپرست/مسئول مجاز؛ InternalTaskForm | tasks/task_form |
| tasks | task_update | FBV | tasks/<pk> | مدیر یا assignee؛ تغییر وضعیت کنترل‌شده | tasks/task_update |
| imports | claim_import | FBV | imports/claims | insurance staff یا insurer rep در scope بیمه‌گر؛ ClaimImportForm | imports/claim_import |
| imports | claim_import_confirm | FBV | imports/claims/<batch>/confirm | POST؛ reviewer مستقل و مجاز؛ مالکیت batch | imports/claim_import |
| documents | document_list | FBV | documents/ | login؛ _visible_documents؛ محدودیت پزشکی | documents/document_list |
| documents | document_upload | FBV | documents/upload | global/specialist؛ پزشکی فقط global؛ فرم در view | documents/document_upload |
| documents | document_download | FBV | documents/<pk>/download | login؛ scope؛ archive/void رد؛ access event | FileResponse |
| documents | document_manage | FBV | documents/<pk>/manage | نسخه با مجوز بارگذاری؛ archive/void فقط global؛ DocumentVersionForm و LifecycleActionForm | documents/document_manage |
| assets | asset_list | FBV | assets/ | login؛ _asset_scope | assets/asset_list |
| assets | asset_create | FBV | assets/new | specialist و line scope؛ InsuredAssetForm | assets/asset_form |
| assets | asset_detail | FBV | assets/<pk> | login؛ scope؛ POST valuation/policy/endorsement | assets/asset_detail |
| assets | asset_update | FBV | assets/<pk>/edit | specialist و scope؛ InsuredAssetForm | assets/asset_form |
| assets | asset_endorsement_download | FBV | endorsements/<pk>/download | login؛ scope دارایی/بیمه‌نامه | FileResponse |
| announcements | announcement_list | FBV | announcements/ | audience/company/publication scope | announcements/announcement_list |
| announcements | announcement_create | FBV | announcements/new | insurance staff؛ AnnouncementForm | announcements/announcement_form |
| announcements | announcement_download | FBV | announcements/<pk>/attachment | login؛ visible announcement و download audit | FileResponse |
| correspondence | correspondence_list | FBV | correspondence/ | company/insurer/line/assigned/confidential scope | correspondence/correspondence_list |
| correspondence | correspondence_create | FBV | correspondence/new | نقش/شرکت/بیمه‌گر/رشته؛ CorrespondenceForm | correspondence/correspondence_form |
| correspondence | correspondence_detail | FBV | correspondence/<pk> | scope؛ follow-up و add_link؛ FollowUpForm و CorrespondenceLinkForm | correspondence/correspondence_detail |
| correspondence | correspondence_download | FBV | correspondence/<pk>/attachment | scope و ثبت رویداد | FileResponse |
| workflow | workflow_case_list | FBV | workflow/ | login؛ assigned/global scope | workflow/workflow_case_list |
| workflow | workflow_case_detail | FBV | workflow/<pk> | assignee/role/scope؛ acknowledge/transition/final-lock | workflow/workflow_case_detail |

`auditlog` و `core` view مستقل ندارند؛ سرویس ممیزی و helperهای permission/upload هستند. `dashboard` route خود را در root config دارد و فایل `urls.py` مستقل ندارد. نبود template برای download viewها مورد orphan محسوب نمی‌شود چون نتیجه FileResponse است.

### 17.16 فهرست تمام ۳۰ template و اتصال

| Template | Render/include توسط | نقطه ورود کاربر |
|---|---|---|
| templates/base.html | base مشترک | قاب و منوی اصلی تمام صفحات |
| templates/registration/login.html | LoginView | /accounts/login/ |
| templates/registration/password_change.html | RequiredPasswordChangeView | تغییر رمز اجباری و user menu |
| templates/dashboard/home.html | dashboard.home | / و /dashboard/ |
| templates/organizations/people_list.html | people_list | منوی افراد/داشبورد |
| templates/organizations/leadership_titles.html | company_leadership_titles | پیوند از صفحه افراد برای نماینده مجاز |
| templates/insurance/contract_list.html | contract_list | منوی قرارداد/داشبورد |
| templates/claims/claim_list.html | claim_list | منوی خسارت/داشبورد |
| templates/claims/claim_detail.html | claim_detail | پیوند از فهرست خسارت |
| templates/requests_portal/request_list.html | request_list | منوی درخواست‌ها/داشبورد |
| templates/requests_portal/request_form.html | request_create | دکمه درخواست جدید |
| templates/requests_portal/request_detail.html | request_detail | پیوند از فهرست درخواست‌ها |
| templates/tasks/task_list.html | task_list | منوی وظایف/داشبورد |
| templates/tasks/task_form.html | task_create | دکمه ایجاد وظیفه |
| templates/tasks/task_update.html | task_update | پیوند از فهرست وظایف |
| templates/assets/asset_list.html | asset_list | منوی دارایی/داشبورد |
| templates/assets/asset_form.html | asset_create و asset_update | دکمه ایجاد/ویرایش از فهرست و جزئیات |
| templates/assets/asset_detail.html | asset_detail | پیوند از فهرست دارایی |
| templates/announcements/announcement_list.html | announcement_list | منوی اطلاعیه/داشبورد |
| templates/announcements/announcement_form.html | announcement_create | دکمه ایجاد اطلاعیه |
| templates/correspondence/correspondence_list.html | correspondence_list | منوی مکاتبات/داشبورد |
| templates/correspondence/correspondence_form.html | correspondence_create | دکمه ثبت مکاتبه |
| templates/correspondence/correspondence_detail.html | correspondence_detail | پیوند از موضوع در فهرست |
| templates/documents/document_list.html | document_list | منوی اسناد/بخشنامه‌ها |
| templates/documents/document_upload.html | document_upload | دکمه بارگذاری سند |
| templates/documents/document_manage.html | document_manage | پیوند مدیریت/نسخه از فهرست اسناد |
| templates/imports/claim_import.html | claim_import و claim_import_confirm | منوی ورود اکسل |
| templates/includes/pagination.html | include در فهرست‌های صفحه‌بندی‌شده | partial مشترک؛ مسیر مستقل ندارد |
| workflow/templates/workflow/workflow_case_list.html | workflow_case_list | منوی ارجاعات من |
| workflow/templates/workflow/workflow_case_detail.html | workflow_case_detail | پیوند از فهرست ارجاعات |

تعداد templateها در Git tree برابر ۳۰ است: ۲۸ در پوشه سراسری و ۲ در ریشه template اپ workflow. اتصال render/include در سورس بررسی شده؛ برای رد قطعی orphan runtime لازم است template rendering در test client اجرا شود.



### 17.17 خلاصهٔ ممیزی per اپ و وضعیت شکاف‌ها

شمار مدل/view/form/template/URL از فایل‌های سورس در snapshot و فهرست‌های همین سند استخراج شده است. ستون Forms تعداد کلاس‌های فرم تعریف‌شده در `forms.py` را می‌شمارد؛ فرم‌های درون view (مانند document upload) جداگانه در جدول view ثبت شده‌اند. شمار USED عمداً عددگذاری نشده، چون «استفاده واقعی» نیازمند اجرای جریان و تست client است و در این محیط runtime تأیید نشده است.

| App | Models | Views | Forms | Templates | URLs در app | USED | UNLINKED | ORPHAN model/view/template/URL | PARTIAL | BROKEN | MISSING |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|
| accounts | 5 | 1 | 1 | 2 | 0* | نامشخص تا اجرای جریان | 0 یافت‌شده | 0 یافت‌شده | 1 | 0 | 1 |
| announcements | 1 | 3 | 1 | 2 | 3 | نامشخص تا اجرای جریان | 0 یافت‌شده | 0 یافت‌شده | 0 | 0 | 0 |
| assets | 5 | 5 | 4 | 3 | 5 | نامشخص تا اجرای جریان | 0 یافت‌شده | 0 یافت‌شده | 1 | 0 | 0 |
| auditlog | 1 | 0 | 0 | 0 | 0 | سرویس داخلی؛ runtime نامشخص | 0 | 0 (مدل در Admin readonly) | 0 | 0 | 0 |
| claims | 3 | 3 | 2 | 2 | 3 | نامشخص تا اجرای جریان | 0 یافت‌شده | 0 یافت‌شده | 3 | 0 | 0 |
| core | 0 | 0 | 0 | 0 | 0 | helper زیرساختی؛ runtime نامشخص | 0 | 0 | 0 | 0 | 1 |
| correspondence | 4 | 4 | 3 | 3 | 4 | نامشخص تا اجرای جریان | 0 یافت‌شده | 0 یافت‌شده | 0 | 0 | 0 |
| dashboard | 0 | 1 | 0 | 1 | 0* | نامشخص تا اجرای جریان | 0 یافت‌شده | 0 یافت‌شده | 0 | 0 | 2 |
| documents | 4 | 4 | 3 | 3 | 4 | نامشخص تا اجرای جریان | 0 یافت‌شده | 0 یافت‌شده | 1 | 0 | 0 |
| imports | 1 | 2 | 1 | 1 | 2 | نامشخص تا اجرای جریان | 0 یافت‌شده | 0 یافت‌شده | 0 | 0 | 1 |
| insurance | 3 | 1 | 0 | 1 | 1 | نامشخص تا اجرای جریان | 0 یافت‌شده | 0 یافت‌شده | 1 | 0 | 0 |
| organizations | 4 | 2 | 2 | 2 | 2 | نامشخص تا اجرای جریان | 0 یافت‌شده | 0 یافت‌شده | 1 | 1 | 1 |
| requests_portal | 1 | 4 | 1 | 3 | 4 | نامشخص تا اجرای جریان | 0 یافت‌شده | 0 یافت‌شده | 1 | 1 | 0 |
| tasks | 2 | 3 | 1 | 3 | 3 | نامشخص تا اجرای جریان | 0 یافت‌شده | 0 یافت‌شده | 1 | 0 | 0 |
| workflow | 7 | 2 | 0 | 2 | 2 | نامشخص تا اجرای جریان | 0 یافت‌شده | 0 یافت‌شده | 1 | 0 | 1 |
| **جمع** | **41** | **35** | **19** | **28 app templates** | **29 در اپ‌ها** | **تأیید runtime نشده** | **0 مورد قطعی** | **0 مدل/view/template/URL قطعی** | **10** | **2** | **7** |

* مسیرهای accounts و dashboard در `config/urls.py` ریشه ثبت شده‌اند، نه در `accounts/urls.py` یا `dashboard/urls.py`. ۶ مسیر ریشه شامل Admin، login/logout/password-change و دو مسیر dashboard هستند. مجموع الگوهای URL برابر ۳۹ است: ۳۳ مسیر اپی به‌اضافه ۶ مسیر root؛ عدد ۲۹ در جمع جدول بالا تعداد مسیرهای app-level برای اپ‌های دارای `urls.py` است و ۴ مسیر اختصاصی Admin/auth در root به حساب آن افزوده می‌شود، همراه با دو dashboard route.

مجموع ۲۸ template داخل اپ‌ها/صفحه‌هاست؛ دو فایل مشترک `templates/base.html` و `templates/includes/pagination.html` آن را به ۳۰ فایل واقعی می‌رسانند. صفر بودن UNLINKED و ORPHAN فقط نتیجهٔ بررسی static view/URL/template/model است؛ آزمون runtime برای قطعیت لازم است. دو فرم یتیم از نظر اتصال، در خود Gap #6 (`PersonChangeRequestForm`) و Gap #13 (`DocumentLinkForm`) مستند شده‌اند و به‌عنوان قابلیت USED شمرده نشده‌اند.

### 17.18 پیوندهای ورود به اپ و وضعیت اتصال

- navigation مشترک در `templates/base.html` به‌صورت role/context-aware برای داشبورد، خسارت، قراردادها، دارایی، اطلاعیه، ارجاعات، مکاتبات، اسناد، درخواست، اشخاص، وظایف، واردات Excel و خروج/تغییر رمز بررسی شد.
- نقطه ورود جدیدی به navigation مشترک در این موج اضافه نشد؛ دو مسیر Admin به‌جای افزودن منو، فقط سطح تغییر مستقیم را محدود کردند.
- مسیرهای جدید/تکمیل‌شده‌ای که در snapshot کد وجود دارند و در 17.16 ثبت شده‌اند: مدیریت سمت مدیریتی شرکت، جزئیات/پیگیری/پیوند مکاتبه، جزئیات/ویرایش دارایی و دانلود پیوست درخواست/الحاقیه. پیاده‌سازی و linkهای HTML آن‌ها در سورس دیده شد؛ runtime flow آن‌ها در این نشست اجرا نشد.
- `PersonChangeRequestForm` و `DocumentLinkForm` هنوز صفحه/مسیر کاربری ندارند؛ علت باقی ماندن gapهای #6 و #13 همین است.

### 17.19 صورت‌جلسهٔ پذیرش فاز ۵ (snapshot فعلی)

| # | شرط DoD | نتیجهٔ قابل استناد | حکم |
|---:|---|---|---|
| 1 | `python manage.py check` | اجرا نشد؛ checkout محلی و محیط پروژه در دسترس نیست | FAIL / NOT VERIFIED |
| 2 | `showmigrations` بدون migration معلق | اجرا نشد؛ وضعیت دیتابیس قابل مشاهده نیست | FAIL / NOT VERIFIED |
| 3 | full test suite صفر failure/error | 136 تعریف تست در سورس؛ هیچ‌کدام در این runtime اجرا نشده‌اند | FAIL / NOT VERIFIED |
| 4 | `runserver` بدون خطا | اجرا نشد؛ checkout/runtime در دسترس نیست | FAIL / NOT VERIFIED |
| 5 | هیچ orphan model | در بررسی static هر مدل به view/form/admin یا نقش زیرساختی متصل است؛ `PersonEmployment` و `DocumentLink` flow ناقص دارند و در gaps هستند، نه orphan قطعی | NOT VERIFIED |
| 6 | هیچ orphan view | viewهای 35گانه به route root/app وصل شده‌اند؛ تست URL resolver اجرا نشده | NOT VERIFIED |
| 7 | هیچ orphan template | 30 فایل به render/include یا base/partial متصل‌اند؛ رندر runtime همه صفحات اجرا نشده | NOT VERIFIED |
| 8 | هیچ URL شکسته | 39 الگوی path در سورس موجود؛ `resolve/reverse` و GET/POST همه مسیرها در Django اجرا نشده | NOT VERIFIED |
| 9 | تمام journeyهای اصلی E2E | 20 gap ثبت شده؛ چند چرخه اصلی قرارداد، تغییر هویت، پرداخت و Excel پویا ناقص‌اند؛ تست E2E نهایی اجرا نشده | FAIL |
| 10 | همه قابلیت‌ها از navigation قابل دسترسی | منوی base برای قابلیت‌های پیاده‌شده بررسی شد؛ gapهای فرم/قابلیت بی‌مسیر #6 و #13 و دیگر چرخه‌های MISSING/PARTIAL پابرجا هستند | FAIL |
| 11 | سند جامع کامل و همخوان با کد | `docs/PROJECT_MASTER.md` دارای 19 بخش اصلی/الحاقی با مدل‌ها، viewها، فرم‌ها، URLها و templateهاست؛ sync runtime و شمارش نهایی linkها هنوز نیازمند اجرای محلی است | PARTIAL / NOT VERIFIED |
| 12 | هیچ BLOCKED بدون دلیل | تمام 20 gap و 5 exclusion ثبت شده؛ 3 patch جدید دلیل BLOCKED runtime دارند؛ 17 gap دیگر هنوز کد/test اجراشده ندارند و در ادامهٔ کار باید per-item تعیین تکلیف شوند | PASS در ثبت دلیل، نه در تکمیل محصول |
| 13 | HEAD و commitها روی main/master و working tree پاک | HEAD و commitهای implementation ثبت شده‌اند؛ PR #1 هنوز Draft/Open و 347 commit جلوتر از main است؛ main ادغام نشده و working tree محلی ویندوز قابل مشاهده نیست | FAIL |

