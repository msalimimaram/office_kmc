"""Canonical account provisioning from the insured-person register."""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import RoleAssignment, User
from auditlog.services import record_event
from organizations.models import Person, normalize_national_id

DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


def normalize_mobile(value: object) -> str:
    """Normalize Persian/Arabic digits without guessing omitted digits."""
    raw = str(value or "").strip().translate(DIGIT_TRANSLATION)
    return "".join(character for character in raw if character in "0123456789")


def provision_insured_person_account(person, *, company, actor, source_reference=""):
    """Create/link the person's canonical account and baseline insured role.

    Existing credentials are never reset when a mobile number changes. A new
    account receives the person's mobile as its initial credential.
    """
    with transaction.atomic():
        person = Person.objects.select_for_update().select_related("user").get(pk=person.pk)
        national_id = normalize_national_id(person.national_id)
        mobile = normalize_mobile(person.mobile)

        if len(national_id) != 10:
            raise ValidationError("کد ملی شخص برای ایجاد حساب باید دقیقاً ده رقم باشد.")
        if len(mobile) != 11 or not mobile.startswith("09"):
            raise ValidationError("شماره همراه معتبر شخص با قالب 09xxxxxxxxx الزامی است.")
        if not person.is_active or not person.is_insured:
            raise ValidationError("برای شخص غیرفعال یا خارج از پوشش بیمه، حساب ایجاد نمی‌شود.")
        if company is None or not company.is_active:
            raise ValidationError("شرکت بیمه‌شده باید فعال باشد.")

        legacy_matches = User.objects.select_for_update().filter(
            national_id=national_id
        ).exclude(username=national_id)
        if legacy_matches.exists():
            raise ValidationError(
                "برای این کد ملی حساب قدیمی با نام کاربری غیر از کد ملی وجود دارد؛ "
                "ابتدا مغایرت هویت آن حساب باید کنترل و اصلاح شود."
            )

        created = False
        linked_now = False
        base_role_created = False
        if person.user_id:
            user = User.objects.select_for_update().get(pk=person.user_id)
            if user.username != national_id:
                raise ValidationError("حساب متصل به شخص با کد ملی او هم‌خوانی ندارد.")
        else:
            user = User.objects.select_for_update().filter(username=national_id).first()

        if user is not None:
            if not user.national_id or normalize_national_id(user.national_id) != national_id:
                raise ValidationError(
                    "حسابی با این نام کاربری وجود دارد اما کد ملی ثبت‌شده آن تأییدشده و منطبق نیست؛ "
                    "اتصال خودکار متوقف شد."
                )
            if not user.is_active:
                raise ValidationError("برای این کد ملی حساب غیرفعال موجود است؛ فعال‌سازی جداگانه لازم است.")
            other_person = Person.objects.filter(user_id=user.pk).exclude(pk=person.pk).first()
            if other_person:
                raise ValidationError("این حساب قبلاً به پرونده بیمه‌شده دیگری متصل شده است.")
            changed = []
            for field, value in (
                ("national_id", national_id),
                ("mobile", mobile),
                ("first_name", person.first_name),
                ("last_name", person.last_name),
            ):
                if getattr(user, field) != value:
                    setattr(user, field, value)
                    changed.append(field)
            if changed:
                # Never call set_password here: changing mobile does not reset a password.
                user.save(update_fields=changed)
        else:
            user = User(
                username=national_id,
                national_id=national_id,
                mobile=mobile,
                first_name=person.first_name,
                last_name=person.last_name,
                is_active=True,
                is_staff=False,
                is_superuser=False,
                must_change_password=True,
            )
            user.set_password(mobile)
            user.save()
            created = True

        if person.user_id != user.pk:
            Person.objects.filter(pk=person.pk).update(user=user)
            person.user = user
            linked_now = True

        today = timezone.localdate()
        has_base_access = RoleAssignment.objects.filter(
            user=user,
            role=RoleAssignment.Role.INSURED_PERSON,
            company=company,
            is_active=True,
            valid_from__lte=today,
        ).filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=today)
        ).exists()
        if not has_base_access:
            RoleAssignment.objects.create(
                user=user,
                role=RoleAssignment.Role.INSURED_PERSON,
                company=company,
                valid_from=today,
                is_active=True,
                reason=(
                    "دسترسی پایه بیمه‌شده از طریق فهرست تأییدشده افراد؛ "
                    f"مرجع ورود: {source_reference or 'ثبت سامانه'}"
                ),
                granted_by=actor,
            )
            base_role_created = True

        if created or linked_now or base_role_created:
            record_event(
                actor=actor,
                action="insured_person_account_provisioned",
                obj=user,
                summary="ایجاد یا اتصال حساب انسانی از روی فهرست بیمه‌شدگان",
                after_data={
                    "person_id": person.pk,
                    "national_id_masked": f"***{national_id[-3:]}",
                    "username_is_national_id": True,
                    "initial_credential_source": "person_mobile",
                    "must_change_password": user.must_change_password,
                    "account_created": created,
                    "baseline_access_created": base_role_created,
                },
                metadata={"source_reference": source_reference},
            )
        return user
