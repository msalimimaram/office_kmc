from django.db import models

class Insurer(models.Model):
    name = models.CharField("نام بیمه‌گر", max_length=200, unique=True)
    contact_name = models.CharField("شخص تماس", max_length=150, blank=True)
    contact_email = models.EmailField("ایمیل", blank=True)
    contact_phone = models.CharField("تلفن", max_length=40, blank=True)
    is_active = models.BooleanField("فعال", default=True)
    def __str__(self): return self.name

class InsuranceLine(models.TextChoices):
    HEALTH = "health", "درمان تکمیلی"
    LIFE = "life", "عمر و حوادث"
    LIABILITY = "liability", "مسئولیت"
    FIRE = "fire", "آتش‌سوزی و اموال"
    THIRD_PARTY = "third_party", "شخص ثالث"
    BODY = "body", "بدنه خودرو"
    OTHER = "other", "سایر"

class Contract(models.Model):
    code = models.CharField("شماره قرارداد", max_length=80, unique=True)
    title = models.CharField("عنوان قرارداد", max_length=250)
    insurer = models.ForeignKey(Insurer, on_delete=models.PROTECT, related_name="contracts")
    line = models.CharField("رشته بیمه", max_length=30, choices=InsuranceLine.choices)
    start_date = models.DateField("شروع قرارداد")
    end_date = models.DateField("پایان قرارداد")
    companies = models.ManyToManyField("organizations.Company", related_name="insurance_contracts", blank=True)
    coverage_summary = models.TextField("خلاصه پوشش‌ها", blank=True)
    terms = models.TextField("شرایط و استثناها", blank=True)
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)
    def __str__(self): return f"{self.code} — {self.title}"

class ContractRevision(models.Model):
    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name="revisions")
    revision_number = models.PositiveIntegerField("شماره نسخه")
    description = models.TextField("شرح تغییر")
    document = models.FileField("فایل سند غیرپزشکی", upload_to="contract_docs/", blank=True)
    created_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["contract", "revision_number"], name="uniq_contract_revision")]
