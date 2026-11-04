from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from accounts.models import User
from .models import AuditEvent


class AuditEventImmutabilityTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(
            username="audit-actor",
            password="StrongPass!2026",
            is_staff=True,
            must_change_password=False,
        )
        self.event = AuditEvent.objects.create(
            actor=self.actor,
            action="test_created",
            object_type="TestRecord",
            object_id="1",
            summary="رویداد آزمایشی",
            after_data={"status": "created"},
        )

    def test_model_instance_cannot_be_updated(self):
        self.event.summary = "تغییر غیرمجاز"
        with self.assertRaises(ValidationError):
            self.event.save()

    def test_queryset_update_is_rejected(self):
        with self.assertRaises(ValidationError):
            AuditEvent.objects.filter(pk=self.event.pk).update(summary="تغییر غیرمجاز")

    def test_model_instance_cannot_be_deleted(self):
        with self.assertRaises(PermissionDenied):
            self.event.delete()
        self.assertTrue(AuditEvent.objects.filter(pk=self.event.pk).exists())

    def test_actor_cannot_be_deleted_while_audit_events_reference_them(self):
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.actor.delete()
        self.assertTrue(AuditEvent.objects.filter(pk=self.event.pk).exists())
