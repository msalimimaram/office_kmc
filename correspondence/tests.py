from django.test import TestCase
from accounts.models import User
from organizations.models import Company
from insurance.models import Insurer
from correspondence.models import Correspondence
from correspondence.views import _scope


class CorrespondenceScopeTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(code="COR-A", name="شرکت الف")
        self.company_b = Company.objects.create(code="COR-B", name="شرکت ب")
        self.insurer = Insurer.objects.create(name="بیمه‌گر الف")
        self.rep = User.objects.create_user(username="cor-rep", password="StrongPass!2026", role="subsidiary_rep", company=self.company_a)
        self.insurer_user = User.objects.create_user(username="cor-ins", password="StrongPass!2026", role="insurer", insurer=self.insurer)
        Correspondence.objects.create(subject="مکاتبه الف", channel="email", direction="inbound", company=self.company_a, insurer=self.insurer, summary="شرح", created_by=self.rep)
        Correspondence.objects.create(subject="مکاتبه ب", channel="email", direction="inbound", company=self.company_b, insurer=self.insurer, summary="شرح", created_by=self.rep)
        Correspondence.objects.create(subject="محرمانه", channel="phone", direction="internal", company=self.company_a, summary="شرح", is_confidential=True, created_by=self.rep)

    def test_subsidiary_representative_sees_only_nonconfidential_company_records(self):
        subjects = set(_scope(self.rep).values_list("subject", flat=True))
        self.assertEqual(subjects, {"مکاتبه الف"})

    def test_insurer_sees_only_records_linked_to_their_insurer(self):
        subjects = set(_scope(self.insurer_user).values_list("subject", flat=True))
        self.assertEqual(subjects, {"مکاتبه الف", "مکاتبه ب"})
