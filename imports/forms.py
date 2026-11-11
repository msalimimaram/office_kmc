from zipfile import BadZipFile, ZipFile
import os
import re

from django import forms


class ClaimImportForm(forms.Form):
    file = forms.FileField(label="فایل اکسل خسارت")

    def clean_file(self):
        upload = self.cleaned_data["file"]
        extension = os.path.splitext(upload.name)[1].lower()
        if extension not in {".xlsx", ".xlsm"}:
            raise forms.ValidationError("فعلاً فقط فایل اکسل xlsx یا xlsm پشتیبانی می‌شود.")
        if upload.size > 25 * 1024 * 1024:
            raise forms.ValidationError("حداکثر حجم فایل ۲۵ مگابایت است.")
        try:
            upload.seek(0)
            with ZipFile(upload) as archive:
                entries = archive.infolist()
                if len(entries) > 5000 or sum(item.file_size for item in entries) > 150 * 1024 * 1024:
                    raise forms.ValidationError("ساختار فایل اکسل بیش از حد بزرگ یا پیچیده است.")
                names = {item.filename for item in entries}
                if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                    raise forms.ValidationError("محتوای فایل با قالب معتبر Excel مطابقت ندارد.")
                if archive.testzip() is not None:
                    raise forms.ValidationError("فایل اکسل خراب است و قابل پردازش نیست.")
        except BadZipFile:
            raise forms.ValidationError("فایل انتخاب‌شده یک فایل Excel معتبر نیست.")
        finally:
            upload.seek(0)
        return upload


class FlexibleExcelImportForm(forms.Form):
    file = forms.FileField(label="فایل Excel")
    header_row = forms.IntegerField(
        label="شماره ردیف عنوان ستون‌ها",
        min_value=1,
        max_value=200,
        initial=1,
        help_text="نگاشت بر اساس حروف ستون‌های Excel انجام می‌شود؛ داده‌ها از ردیف بعد از این مقدار خوانده می‌شوند.",
    )

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        self.mapping_fields = {}
        for key, label, default_column, required in profile["fields"]:
            field_name = f"column_{key}"
            self.mapping_fields[key] = field_name
            self.fields[field_name] = forms.CharField(
                label=f"{label} — ستون Excel",
                required=required,
                initial=default_column,
                max_length=3,
                strip=True,
                help_text="مثال: D یا Y؛ برای فیلد اختیاری می‌توانید خالی بگذارید.",
            )

    @staticmethod
    def _validate_excel_file(upload):
        extension = os.path.splitext(upload.name)[1].lower()
        if extension not in {".xlsx", ".xlsm"}:
            raise forms.ValidationError("فقط فایل Excel با پسوند xlsx یا xlsm مجاز است.")
        if upload.size > 25 * 1024 * 1024:
            raise forms.ValidationError("حداکثر حجم فایل ۲۵ مگابایت است.")
        try:
            upload.seek(0)
            with ZipFile(upload) as archive:
                entries = archive.infolist()
                if len(entries) > 5000 or sum(item.file_size for item in entries) > 150 * 1024 * 1024:
                    raise forms.ValidationError("ساختار فایل بیش از حد بزرگ یا پیچیده است.")
                names = {item.filename for item in entries}
                if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                    raise forms.ValidationError("فایل، ساختار معتبر Excel ندارد.")
                if archive.testzip() is not None:
                    raise forms.ValidationError("فایل Excel خراب است.")
        except BadZipFile:
            raise forms.ValidationError("فایل انتخاب‌شده یک فایل Excel معتبر نیست.")
        finally:
            upload.seek(0)
        return upload

    def clean_file(self):
        return self._validate_excel_file(self.cleaned_data["file"])

    def clean(self):
        cleaned = super().clean()
        seen = {}
        required = self.profile.get("required", set())
        for key, field_name in self.mapping_fields.items():
            raw = (cleaned.get(field_name) or "").strip().upper()
            if not raw:
                if key in required:
                    self.add_error(field_name, "نگاشت این فیلد الزامی است.")
                continue
            if not re.fullmatch(r"[A-Z]{1,3}", raw):
                self.add_error(field_name, "حرف ستون معتبر وارد کنید؛ مانند D یا Y.")
                continue
            column_number = 0
            for character in raw:
                column_number = column_number * 26 + ord(character) - 64
            if column_number > 16384:
                self.add_error(field_name, "ستون انتخاب‌شده خارج از محدوده Excel است؛ آخرین ستون مجاز XFD است.")
                continue
            if raw in seen:
                self.add_error(field_name, f"این ستون قبلاً برای «{seen[raw]}» انتخاب شده است.")
                continue
            seen[raw] = key
            cleaned[field_name] = raw
        return cleaned

    @property
    def column_mapping(self):
        return {
            key: self.cleaned_data.get(field_name, "").strip().upper()
            for key, field_name in self.mapping_fields.items()
            if self.cleaned_data.get(field_name)
        }
