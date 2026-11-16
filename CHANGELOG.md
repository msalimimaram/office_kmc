# گزارش تغییرات

این فایل تغییرات مهم نسخه‌ها را ثبت می‌کند. تا زمانی که نسخه انتشار رسمی تعریف نشده، موارد زیر به‌عنوان وضعیت مستندات مخزن ثبت می‌شوند؛ این فهرست جایگزین release noteهای خودکار نیست.

## Unreleased

### Safety and Operations
- Historical presentation leadership appointments now attach to the prior employer whose employment interval covers the appointment; the seed regression test verifies company, person, date-range and declaring-representative consistency.
- Demo seeding now refuses to run unless all application data tables are empty (Django framework tables excluded).
- The local preflight reports the workflow audit as not applicable only for a genuinely empty, unseeded baseline; populated and production databases still require the audit.
- Base/support/presentation seed layers now verify overlapping scoped RoleAssignment records before reuse and preserve the original reason and grant history.
- Demo seed reuse fails closed when an existing fixture has no explicit non-empty verification allow-list.
- Existing demo accounts without usable passwords are rejected instead of having credentials changed.
- Demo document reuse is rejected; existing dependent-person links and task assignments are never repaired by the seed process.
- The local preflight no longer runs `seed_demo` implicitly; demo seeding requires explicit `-SeedDemo` on a fresh disposable database.
- Added `-NoMigrate` to run Phase 0 checks against an existing local database without applying migrations.
- Demo dependent persons are now created with their primary-insured link on first insert; regression assertions verify both Person and PersonRelationship rows.
- The demo seed guard permits only the exact singleton `iran-default` calendar installed by `workflow.0001_initial`; altered or additional calendars remain a collision, with regression tests for both cases.
- Operational report transitions normalize all role and position routing JSON fields to lists before validation.
- The demo `DEMO-OTHER-01` contract now includes the parent company that owns the seeded employee-owned asset; asset ownership/contract validation remains intact.
- `Claim.line_code` centralizes contract-derived scope and the existing health fallback for legacy claims without a contract, keeping workflow recipient validation consistent with initial routing.
- Objection regression tests now assert the generic workflow detail route and the actual initial `in_review` state, including specialist answer authority and restricted final closure.
- Correspondence creation now applies the model's timezone-aware timestamp default when `occurred_at` is omitted from the form.
- Added regression coverage for bootstrap calendar preservation, workflow routing JSON types, and supervisor correspondence creation without a supplied timestamp.
- The presentation seed rejects existing demo accounts without usable passwords and verifies shared calendar defaults before reuse.

### Documentation
- Added the prioritized Phase 0 baseline stabilization and acceptance checklist.

### Security
- افزودن محدودسازی تلاش ناموفق ورود (۵ تلاش برای ترکیب نام کاربری/IP و قفل ۱۵ دقیقه‌ای) همراه با تست رگرسیون؛ استقرار چندپردازه به cache مشترک اتمیک نیاز دارد.
- گسترش تست‌های اعتبارسنجی فایل برای پسوند غیرمجاز، بازگرداندن cursor فایل و فایل Office جعلی.

### Documentation
- بازنویسی README ریشه با معرفی اپ‌ها، راه‌اندازی، محدودیت‌ها و وضعیت آمادگی.
- تکمیل سیاست امنیت و روش گزارش خصوصی آسیب‌پذیری.
- افزودن راهنمای مستقل برای هر اپ Django.
- افزودن مستندات معماری، استقرار، آزمون، توسعه و مدل تهدید.
- شفاف‌سازی اینکه migrationهای تولیدشده در CI باید جداگانه در Git نسخه‌بندی شوند.
