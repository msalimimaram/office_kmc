"""One-time, host-operated bootstrap for the first business administrator.

This command deliberately accepts no credentials through command-line arguments.
It is intended to be run only by an authorized operator on the trusted application
host after independently verifying the administrator's identity.
"""
from __future__ import annotations

import getpass
import re
from datetime import time

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import (
    OrganizationalPosition,
    OrganizationalUnit,
    PositionAssignment,
    RoleAssignment,
    User,
)
from auditlog.services import record_event
from workflow.models import BusinessCalendar


class Command(BaseCommand):
    help = "Create the first System Admin on a pristine identity database (interactive, one-shot)."

    CONFIRMATION = "BOOTSTRAP FIRST SYSTEM ADMIN"

    def handle(self, *args, **options):
        with transaction.atomic():
            # The migrated singleton calendar row is the serialization point:
            # concurrent bootstrap attempts must contend on the same locked row.
            try:
                calendar = BusinessCalendar.objects.select_for_update().get(code="iran-default")
            except BusinessCalendar.DoesNotExist as exc:
                raise CommandError(
                    "The baseline BusinessCalendar is missing; run migrations before bootstrap."
                ) from exc

            pristine_calendar = (
                calendar.title == "تقویم کاری مجموعه"
                and calendar.timezone_name == "Asia/Tehran"
                and calendar.working_weekdays == [5, 6, 0, 1, 2, 3]
                and calendar.start_time == time(8, 0)
                and calendar.end_time == time(16, 0)
                and calendar.is_active is True
            )
            if not pristine_calendar:
                raise CommandError(
                    "Bootstrap refused: the baseline BusinessCalendar was modified."
                )

            if User.objects.exists():
                raise CommandError(
                    "Bootstrap refused: at least one account already exists. "
                    "Use the authenticated account/role administration process."
                )
            if RoleAssignment.objects.exists() or PositionAssignment.objects.exists():
                raise CommandError(
                    "Bootstrap refused: authorization history already exists."
                )
            if BusinessCalendar.objects.count() != 1:
                raise CommandError(
                    "Bootstrap refused: the database is not the expected pristine baseline."
                )

            # Migration 0007 creates a fixed, empty department/position catalog.
            # Permit only that exact baseline while rejecting any other organizational data.
            try:
                baseline_unit = OrganizationalUnit.objects.get(
                    code="insurance-department",
                    company__isnull=True,
                    is_active=True,
                )
            except OrganizationalUnit.DoesNotExist as exc:
                raise CommandError(
                    "Bootstrap refused: the baseline insurance-department unit is missing."
                ) from exc

            line_codes = ("health", "life", "liability", "fire", "third_party", "body")
            expected_position_codes = {"department-head"}
            for line_code in line_codes:
                expected_position_codes.update({
                    f"{line_code}-head",
                    f"{line_code}-supervisor",
                    f"{line_code}-responsible",
                    f"{line_code}-specialist",
                })
            baseline_positions = OrganizationalPosition.objects.filter(unit=baseline_unit)
            if (
                set(baseline_positions.values_list("code", flat=True)) != expected_position_codes
                or OrganizationalUnit.objects.exclude(pk=baseline_unit.pk).exists()
                or OrganizationalPosition.objects.exclude(unit=baseline_unit).exists()
            ):
                raise CommandError(
                    "Bootstrap refused: organizational data differs from the empty baseline catalog."
                )

            framework_apps = {"admin", "auth", "contenttypes", "sessions"}
            baseline_models = {OrganizationalUnit, OrganizationalPosition}
            for model in apps.get_models(include_auto_created=False):
                if (
                    not model._meta.managed
                    or model._meta.proxy
                    or model._meta.swapped
                    or model._meta.app_label in framework_apps
                    or model is BusinessCalendar
                    or model in baseline_models
                ):
                    continue
                if model._default_manager.exists():
                    raise CommandError(
                        "Bootstrap refused: business data already exists in "
                        f"{model._meta.label}; use the controlled account provisioning process."
                    )

            self.stdout.write(
                self.style.WARNING(
                    "This one-time command creates the first System Admin. "
                    "Run it only on the trusted application host after verifying "
                    "the person's identity and authority through the organization's "
                    "approved offline process."
                )
            )
            if input(f'Type "{self.CONFIRMATION}" to continue: ').strip() != self.CONFIRMATION:
                raise CommandError("Bootstrap confirmation did not match; no account was created.")

            from organizations.models import normalize_national_id
            from accounts.provisioning import normalize_mobile

            username = normalize_national_id(input("National ID / username (10 digits): "))
            if not re.fullmatch(r"\d{10}", username):
                raise CommandError("National ID / username must contain exactly 10 digits.")

            first_name = input("First name: ").strip()
            last_name = input("Last name: ").strip()
            mobile = normalize_mobile(input("Mobile number (09xxxxxxxxx): "))
            if not first_name or not last_name:
                raise CommandError("First name and last name are required.")
            if not re.fullmatch(r"09\d{9}", mobile):
                raise CommandError("Mobile number must use the 11-digit 09xxxxxxxxx format.")

            candidate = User(
                username=username,
                first_name=first_name,
                last_name=last_name,
                mobile=mobile,
                national_id=username,
                is_active=True,
                is_staff=False,
                is_superuser=False,
                must_change_password=True,
            )
            # The person's verified mobile is the agreed initial credential.
            # It is stored only as a Django password hash and must be changed at first login.
            candidate.set_password(mobile)
            candidate.save()

            assignment = RoleAssignment(
                user=candidate,
                role=RoleAssignment.Role.SYSTEM_ADMIN,
                valid_from=timezone.localdate(),
                is_active=True,
                reason=(
                    "انتصاب اولیه مدیر سامانه از مسیر bootstrap یک‌باره؛ "
                    "هویت و اختیار فرد پیش از اجرا توسط اپراتور مجاز و خارج از سامانه بررسی شده است."
                ),
            )
            assignment.save()

            # No authenticated actor exists at first bootstrap. Keep actor null
            # rather than falsely attributing the action to the account being created.
            record_event(
                actor=None,
                action="accounts.initial_system_admin_bootstrap",
                obj=candidate,
                summary="ایجاد نخستین مدیر سامانه از مسیر bootstrap کنترل‌شده",
                after_data={
                    "role": RoleAssignment.Role.SYSTEM_ADMIN,
                    "valid_from": timezone.localdate().isoformat(),
                    "must_change_password": True,
                    "is_superuser": False,
                },
                metadata={
                    "bootstrap_operator_os_user": getpass.getuser(),
                    "bootstrap_method": "trusted-host-interactive-management-command",
                    "identity_verification": "operator_attested_out_of_band",
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Created first System Admin account #{candidate.pk}. "
                "The user must change the initial password at first login."
            )
        )

