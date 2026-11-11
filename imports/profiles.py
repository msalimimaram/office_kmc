"""Role-aware Excel import profiles with explicit, user-configurable column maps."""

PROFILES = {
    "people_roster": {
        "title": "فهرست کارکنان و افراد تحت پوشش",
        "audience": "نمایندگان شرکت؛ اداره بیمه برای بررسی و تأیید",
        "description": "افزایش یا خاتمه همکاری افراد. حذف فیزیکی سابقه ممنوع است؛ پایان همکاری به‌صورت سابقه اشتغال ثبت می‌شود.",
        "roles": {"company", "staff"},
        "template_name": "office_kmc_people_roster.xlsx",
        "fields": [
            ("action", "عملیات: add_employee / add_dependent / end_employment", "A", True),
            ("national_id", "کد ملی شخص", "B", True),
            ("first_name", "نام", "C", False),
            ("last_name", "نام خانوادگی", "D", False),
            ("birth_date", "تاریخ تولد", "E", False),
            ("personnel_code", "کد پرسنلی", "F", False),
            ("mobile", "شماره همراه", "G", False),
            ("iban", "شماره شبا", "H", False),
            ("relationship", "نسبت: spouse / child / father / mother / other", "I", False),
            ("employee_national_id", "کد ملی بیمه‌شده اصلی برای فرد تحت تکفل", "J", False),
            ("company_code", "کد شرکت؛ برای مدیران و فقط جهت کنترل محدوده", "K", False),
        ],
        "sample": [
            ["add_employee", "0012345690", "علی", "نمونه", "1988-05-12", "D-9001", "09120000001", "IR000000000000000000000000", "employee", "", "DEMO-A"],
            ["add_dependent", "0012345691", "سارا", "نمونه", "1990-08-04", "D-9001-01", "09120000002", "", "spouse", "0012345690", "DEMO-A"],
        ],
        "required": {"action", "national_id"},
    },
    "claims": {
        "title": "خسارت‌ها و پرداخت‌های اعلامی",
        "audience": "نماینده بیمه‌گر؛ کارشناسان مجاز اداره بیمه",
        "description": "ثبت خسارت و مبالغ اعلامی بیمه‌گر. پرداخت واردشده صرفاً سابقه اطلاعاتی است و انتقال وجه انجام نمی‌دهد؛ تأیید مستقل لازم است.",
        "roles": {"insurer", "staff"},
        "template_name": "office_kmc_claims.xlsx",
        "fields": [
            ("claim_number", "شناسه پرونده در سامانه بیمه‌گر", "A", True),
            ("national_id", "کد ملی بیمه‌شده یا فرد تحت تکفل", "B", True),
            ("service_type", "نوع خدمت / شرح غیرپزشکی", "C", True),
            ("contract_number", "شماره قرارداد", "D", True),
            ("service_date", "تاریخ خدمت", "E", True),
            ("registered_date", "تاریخ ثبت در سامانه اداره", "F", False),
            ("source_registered_date", "تاریخ ثبت در بیمه‌گر", "G", False),
            ("requested_amount", "مبلغ درخواستی", "H", False),
            ("assessed_amount", "مبلغ ارزیابی‌شده", "I", False),
            ("payable_amount", "مبلغ قابل پرداخت", "J", False),
            ("paid_amount", "مبلغ پرداخت‌شده اعلامی", "K", False),
            ("payment_date", "تاریخ پرداخت اعلامی", "L", False),
            ("source_duplicate_status", "اعلام تکراری بودن: yes / no", "M", False),
            ("source_duplicate_reference", "شماره پرونده اصلی در صورت اعلام تکراری", "N", False),
            ("source_duplicate_note", "توضیح اعلام تکراری بودن", "O", False),
            ("line_code", "رشته بیمه: health / life / liability / fire / third_party / body", "P", False),
        ],
        "sample": [
            ["INS-CLM-1001", "0012345678", "ویزیت پزشک", "DEMO-1405", "2026-10-20", "2026-10-22", "2026-10-22", 1250000, 1000000, 900000, 450000, "2026-11-01", "no", "", "", "health"],
            ["INS-CLM-1002", "0012345679", "دارو", "DEMO-1405", "2026-10-21", "2026-10-23", "2026-10-23", 850000, 800000, 750000, 0, "", "no", "", "", "health"],
        ],
        "required": {"claim_number", "national_id", "service_type", "contract_number", "service_date"},
    },
    "contracts": {
        "title": "قراردادهای جدید برای بررسی و تصویب",
        "audience": "کارشناسان مجاز اداره بیمه؛ تأیید نهایی فقط رئیس اداره یا مدیر سامانه",
        "description": "قراردادها به‌صورت پیش‌نویس و نسخه در انتظار تصویب ساخته می‌شوند؛ فایل اکسل هرگز قرارداد را فعال یا تأیید نهایی نمی‌کند.",
        "roles": {"staff"},
        "template_name": "office_kmc_contracts.xlsx",
        "fields": [
            ("code", "شماره قرارداد", "A", True),
            ("title", "عنوان قرارداد", "B", True),
            ("insurer_name", "نام دقیق بیمه‌گر", "C", True),
            ("line", "رشته بیمه: health / life / liability / fire / third_party / body / other", "D", True),
            ("company_codes", "کد شرکت‌ها؛ با ; جدا شوند", "E", True),
            ("start_date", "شروع قرارداد", "F", True),
            ("end_date", "پایان قرارداد", "G", True),
            ("effective_date", "تاریخ اثر نسخه", "H", True),
            ("revision_description", "شرح نسخه / دلیل ثبت", "I", True),
            ("coverage_summary", "خلاصه پوشش‌ها", "J", False),
            ("terms", "شرایط و استثناها", "K", False),
        ],
        "sample": [
            ["DEMO-CONTRACT-FIRE-01", "قرارداد نمونه آتش‌سوزی", "بیمه‌گر نمونه", "fire", "DEMO-A;DEMO-B", "2026-01-01", "2027-12-29", "2026-11-15", "ثبت نسخه اولیه برای بررسی", "پوشش ساختمان و تجهیزات", "طبق شرایط پیوست"],
        ],
        "required": {"code", "title", "insurer_name", "line", "company_codes", "start_date", "end_date", "effective_date", "revision_description"},
    },
}


def get_profile(code):
    return PROFILES.get(code)
