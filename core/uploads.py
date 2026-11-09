"""Shared validation for user-uploaded files.

Extension and client-provided MIME types are not trusted. Validate a small
signature/structure check, scan with ClamAV when configured, and always rewind
the upload before saving it.
"""
from pathlib import Path
import socket
import struct
from zipfile import BadZipFile, ZipFile

from django.conf import settings
from PIL import Image, UnidentifiedImageError


ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xlsm", ".png", ".jpg", ".jpeg"}


def scan_uploaded_file(upload):
    """Scan a validated upload with ClamAV INSTREAM; fail closed outside DEBUG."""
    host = str(getattr(settings, "CLAMD_HOST", "") or "").strip()
    if not host:
        if settings.DEBUG:
            return None
        return "اسکنر بدافزار در محیط عملیاتی پیکربندی نشده است؛ بارگذاری فایل متوقف شد."

    try:
        port = int(getattr(settings, "CLAMD_PORT", 3310))
        timeout = float(getattr(settings, "CLAMD_TIMEOUT", 10))
        if not 1 <= port <= 65535 or timeout <= 0:
            raise ValueError("Invalid ClamAV connection settings")
        upload.seek(0)
        with socket.create_connection((host, port), timeout=timeout) as client:
            client.settimeout(timeout)
            client.sendall(b"zINSTREAM\0")
            while True:
                chunk = upload.read(64 * 1024)
                if not chunk:
                    break
                client.sendall(struct.pack("!I", len(chunk)))
                client.sendall(chunk)
            client.sendall(struct.pack("!I", 0))
            response = client.recv(4096)
    except (OSError, ValueError, TypeError):
        return "ارتباط با اسکنر بدافزار برقرار نشد؛ بارگذاری فایل متوقف شد."
    finally:
        try:
            upload.seek(0)
        except (AttributeError, OSError, ValueError):
            pass

    if b"FOUND" in response:
        return "فایل بارگذاری‌شده توسط اسکنر بدافزار آلوده تشخیص داده شد."
    if b"OK" in response:
        return None
    return "پاسخ اسکنر بدافزار معتبر نیست؛ بارگذاری فایل متوقف شد."


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
        elif extension in {".docx", ".xlsx", ".xlsm"}:
            try:
                with ZipFile(upload) as archive:
                    entries = archive.infolist()
                    if len(entries) > 5000 or sum(entry.file_size for entry in entries) > 100 * 1024 * 1024:
                        return "ساختار فایل Office بیش از حد بزرگ یا پیچیده است."
                    names = {entry.filename for entry in entries}
                    if archive.testzip() is not None or "[Content_Types].xml" not in names:
                        return "ساختار فایل Office معتبر نیست."
                    required = "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
                    if required not in names:
                        return "محتوای فایل با قالب انتخاب‌شده مطابقت ندارد."
            except (BadZipFile, OSError):
                return "فایل Office معتبر نیست."
        scan_error = scan_uploaded_file(upload)
        if scan_error:
            return scan_error
        return None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return "محتوای فایل معتبر یا قابل خواندن نیست."
    finally:
        try:
            upload.seek(0)
        except (AttributeError, OSError, ValueError):
            pass
