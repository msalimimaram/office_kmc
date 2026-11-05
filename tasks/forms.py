from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from accounts.access import has_global_access
from accounts.models import PositionAssignment, RoleAssignment
from core.permissions import scoped_requests_for
from .models import InternalTask


User = get_user_model()


def _active_staff_ids():
    today = timezone.localdate()
    roles = RoleAssignment.objects.filter(
        is_active=True, valid_from__lte=today,
        role__in=[
            RoleAssignment.Role.SYSTEM_ADMIN,
            RoleAssignment.Role.DEPARTMENT_HEAD,
            RoleAssignment.Role.INSURANCE_SPECIALIST,
        ],
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today)).values("user_id")
    positions = PositionAssignment.objects.filter(
        is_active=True, valid_from__lte=today,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today)).values("user_id")
    return User.objects.filter(is_active=True).filter(Q(pk__in=roles) | Q(pk__in=positions)).distinct()


def _manager_scope(user):
    if has_global_access(user):
        return None
    today = timezone.localdate()
    assignments = PositionAssignment.objects.filter(
        user=user, is_active=True, valid_from__lte=today,
        position__level__in=[
            PositionAssignment.position.field.related_model.Level.SUPERVISOR,
            PositionAssignment.position.field.related_model.Level.RESPONSIBLE,
        ],
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
    units = assignments.values_list("unit_id", flat=True)
    levels = assignments.values_list("position__level", flat=True)
    return Q(position_assignments__unit_id__in=units) & Q(position_assignments__position__level__gt=min(levels)) if levels else Q(pk__in=[])


class InternalTaskForm(forms.ModelForm):
    class Meta:
        model = InternalTask
        fields = ["title", "description", "assignees", "priority", "due_at", "related_request"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["assignees"].queryset = User.objects.none()
        self.fields["related_request"].queryset = scoped_requests_for(user).order_by("-created_at", "-pk") if user and user.is_authenticated else scoped_requests_for(User.objects.none())
        if not user or not user.is_authenticated:
            return
        staff = _active_staff_ids()
        scope = _manager_scope(user)
        if scope is not None:
            staff = staff.filter(scope).distinct()
        self.fields["assignees"].queryset = staff.order_by("last_name", "first_name", "username")

    def clean(self):
        cleaned = super().clean()
        if not has_global_access(self.user):
            today = timezone.localdate()
            levels = PositionAssignment.objects.filter(
                user=self.user, is_active=True, valid_from__lte=today,
                position__level__in=[
                    PositionAssignment.position.field.related_model.Level.SUPERVISOR,
                    PositionAssignment.position.field.related_model.Level.RESPONSIBLE,
                ],
            ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today)).values_list("position__level", flat=True)
            if not levels:
                self.add_error(None, "فقط رئیس اداره، مدیر سامانه یا سرپرست/مسئول مجاز می‌تواند وظیفه تعریف کند.")
        related_request = cleaned.get("related_request")
        if related_request and related_request.is_confidential and not has_global_access(self.user):
            self.add_error("related_request", "اتصال وظیفه به پرونده محرمانه فقط برای رئیس اداره یا مدیر سامانه مجاز است.")
        return cleaned
