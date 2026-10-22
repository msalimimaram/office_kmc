from django.core.files.uploadedfile import SimpleUploadedFile
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
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


    def test_rejects_disallowed_extension(self):
        upload = SimpleUploadedFile("payload.exe", b"MZ\x00\x01")
        self.assertIn("نوع فایل مجاز", validate_uploaded_file(upload, max_size=1024))

    def test_upload_stream_is_rewound_after_validation(self):
        upload = SimpleUploadedFile("bad.pdf", b"not a pdf")
        upload.read(3)
        validate_uploaded_file(upload, max_size=1024)
        self.assertEqual(upload.tell(), 0)

    def test_rejects_office_zip_without_expected_document_part(self):
        stream = BytesIO()
        with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("random.txt", "not a workbook")
        upload = SimpleUploadedFile("fake.xlsx", stream.getvalue())
        self.assertIn("مطابقت ندارد", validate_uploaded_file(upload, max_size=1024 * 1024))
