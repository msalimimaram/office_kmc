from zipfile import BadZipFile, ZipFile

from django import forms


class ClaimImportForm(forms.Form):
    file = forms.FileField(label="فایل اکسل خسارت")

    def clean_file(self):
        upload = self.cleaned_data["file"]
        import os

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
