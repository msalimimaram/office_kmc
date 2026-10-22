"""Shared validation for user-uploaded files.

Extension and client-provided MIME types are not trusted. Validate a small
signature/structure check and always rewind the upload before saving it.
"""
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from PIL import Image, UnidentifiedImageError


ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg"}


def validate_uploaded_file(upload, *, max_size, allowed_extensions=ALLOWED_EXTENSIONS):
    if not upload:
        return "فایل انتخاب‌شده معتبر نیست."
    if upload.size > max_size:
        return f"حداکثر حجم فایل {max_size // (1024 * 1024)} مگابایت است."

    extension = Path(upload.name).suffix.lower()
    if extension not in allowed_extensions:
        return "نوع فایل مجاز نیست."

    try:
        upload.seek(0)
        header = upload.read(16)
        upload.seek(0)

        if extension == ".pdf":
            if not header.startswith(b"%PDF-"):
                return "محتوای فایل با قالب PDF مطابقت ندارد."
        elif extension == ".png":
            if not header.startswith(b"\x89PNG\r\n\x1a\n"):
                return "محتوای فایل با قالب PNG مطابقت ندارد."
            with Image.open(upload) as image:
                image.verify()
        elif extension in {".jpg", ".jpeg"}:
            if not header.startswith(b"\xff\xd8\xff"):
                return "محتوای فایل با قالب JPEG مطابقت ندارد."
            with Image.open(upload) as image:
                image.verify()
        elif extension in {".docx", ".xlsx"}:
            try:
                with ZipFile(upload) as archive:
                    names = set(archive.namelist())
                    if archive.testzip() is not None or "[Content_Types].xml" not in names:
                        return "ساختار فایل Office معتبر نیست."
                    required = "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
                    if required not in names:
                        return "محتوای فایل با قالب انتخاب‌شده مطابقت ندارد."
            except (BadZipFile, OSError):
                return "فایل Office معتبر نیست."
        return None
    except (UnidentifiedImageError, OSError, ValueError):
        return "محتوای فایل معتبر یا قابل خواندن نیست."
    finally:
        try:
            upload.seek(0)
        except (AttributeError, OSError, ValueError):
            pass
