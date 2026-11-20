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
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import PositionAssignment, RoleAssignment, User
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

            framework_apps = {"admin", "auth", "contenttypes", "sessions"}
            for model in apps.get_models(include_auto_created=False):
                if (
                    not model._meta.managed
                    or model._meta.proxy
                    or model._meta.swapped
                    or model._meta.app_label in framework_apps
                    or model is BusinessCalendar
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

            username = input("National ID / username (10 digits): ").strip()
            if not re.fullmatch(r"\d{10}", username):
                raise CommandError("National ID / username must contain exactly 10 digits.")

            first_name = input("First name: ").strip()
            last_name = input("Last name: ").strip()
            mobile = input("Mobile number (09xxxxxxxxx): ").strip()
            if not first_name or not last_name:
                raise CommandError("First name and last name are required.")
            if not re.fullmatch(r"09\d{9}", mobile):
                raise CommandError("Mobile number must use the 11-digit 09xxxxxxxxx format.")

            password = getpass.getpass("Initial password (input hidden): ")
            password_confirmation = getpass.getpass("Repeat initial password: ")
            if not password or password != password_confirmation:
                raise CommandError("Passwords are empty or do not match.")
            
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
            try:
                validate_password(password, user=candidate)
            except ValidationError as exc:
                raise CommandError(
                    "Initial password does not meet the configured password policy: "
                    + "; ".join(exc.messages)
                ) from exc
            candidate.set_password(password)
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

