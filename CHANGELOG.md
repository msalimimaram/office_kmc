# گزارش تغییرات

این فایل تغییرات مهم نسخه‌ها را ثبت می‌کند. تا زمانی که نسخه انتشار رسمی تعریف نشده، موارد زیر به‌عنوان وضعیت مستندات مخزن ثبت می‌شوند؛ این فهرست جایگزین release noteهای خودکار نیست.

## Unreleased

### Safety and Operations
- Demo seeding now refuses to run unless all application data tables are empty (Django framework tables excluded).
- The local preflight reports the workflow audit as not applicable only for a genuinely empty, unseeded baseline; populated and production databases still require the audit.
- Base/support/presentation seed layers now verify overlapping scoped RoleAssignment records before reuse and preserve the original reason and grant history.
- Demo seed reuse fails closed when an existing fixture has no explicit non-empty verification allow-list.
- Existing demo accounts without usable passwords are rejected instead of having credentials changed.
- Demo document reuse is rejected; existing dependent-person links and task assignments are never repaired by the seed process.
- The local preflight no longer runs `seed_demo` implicitly; demo seeding requires explicit `-SeedDemo` on a fresh disposable database.

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
