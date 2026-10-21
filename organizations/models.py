from django.db import models

class Company(models.Model):
    code = models.CharField("کد شرکت", max_length=30, unique=True)
    name = models.CharField("نام شرکت", max_length=200)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="subsidiaries")
    is_parent = models.BooleanField("شرکت مادر", default=False)
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField("تاریخ ایجاد", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "شرکت"
        verbose_name_plural = "شرکت‌ها"

    def __str__(self):
        return self.name

class Person(models.Model):
    class Relationship(models.TextChoices):
        EMPLOYEE = "employee", "کارمند"
        SPOUSE = "spouse", "همسر"
        CHILD = "child", "فرزند"
        OTHER = "other", "سایر افراد تحت تکفل"

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="people")
    personnel_code = models.CharField("کد پرسنلی", max_length=50, blank=True, db_index=True)
    national_id = models.CharField("کد ملی", max_length=10, db_index=True)
    first_name = models.CharField("نام", max_length=100)
    last_name = models.CharField("نام خانوادگی", max_length=100)
    relationship = models.CharField("نسبت", max_length=20, choices=Relationship.choices, default=Relationship.EMPLOYEE)
    employee = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="dependents")
    mobile = models.CharField("همراه", max_length=20, blank=True)
    iban = models.CharField("شماره شبا", max_length=34, blank=True)
    is_insured = models.BooleanField("تحت پوشش", default=True)
    is_active = models.BooleanField("فعال", default=True)
    updated_at = models.DateTimeField("آخرین بروزرسانی", auto_now=True)

    class Meta:
        ordering = ["company__name", "last_name", "first_name"]
        constraints = [models.UniqueConstraint(fields=["company", "national_id"], name="uniq_person_company_national_id")]
        verbose_name = "شخص بیمه‌شده"
        verbose_name_plural = "اشخاص بیمه‌شده"

    def __str__(self):
        return f"{self.first_name} {self.last_name}"
