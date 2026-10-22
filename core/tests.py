from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from core.uploads import validate_uploaded_file


class UploadedFileValidationTests(SimpleTestCase):
    def test_accepts_pdf_signature(self):
        upload = SimpleUploadedFile("sample.pdf", b"%PDF-1.7\ncontent")
        self.assertIsNone(validate_uploaded_file(upload, max_size=1024))

    def test_rejects_mislabeled_text_file(self):
        upload = SimpleUploadedFile("not-really.pdf", b"this is plain text")
        self.assertIn("مطابقت ندارد", validate_uploaded_file(upload, max_size=1024))

    def test_rejects_oversized_file_before_content_parsing(self):
        upload = SimpleUploadedFile("large.pdf", b"%PDF-1.7\n")
        self.assertIn("حداکثر حجم", validate_uploaded_file(upload, max_size=4))
