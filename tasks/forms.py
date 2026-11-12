from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from accounts.access import has_global_access, is_unit_manager
from accounts.models import PositionAssignment, RoleAssignment
from core.permissions import scoped_requests_for
from requests_portal.models import ServiceRequest
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
        is_active=True,
        valid_from__lte=today,
        position__is_active=True,
        unit__is_active=True,
        unit__company__isnull=True,
        line_code__gt="",
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today)).values("user_id")
    return User.objects.filter(is_active=True).filter(Q(pk__in=roles) | Q(pk__in=positions)).distinct()


def _manager_scope(user):
    """Build the assignable-user scope for each active supervisor/responsible.

    Responsibles manage lower positions in their own unit. Supervisors also
    cover every descendant unit, matching the organizational tree rather than
    assuming that all subordinates share one unit_id.
    """
    if has_global_access(user):
        return None

    today = timezone.localdate()
    level_model = PositionAssignment.position.field.related_model.Level
    assignments = list(PositionAssignment.objects.filter(
        user=user,
        is_active=True,
        valid_from__lte=today,
        position__level__in=[level_model.SUPERVISOR, level_model.RESPONSIBLE],
        position__is_active=True,
        unit__is_active=True,
        unit__company__isnull=True,
        line_code__gt="",
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=today)
    ).select_related("position", "unit"))

    allowed = Q(pk__in=[])
    for assignment in assignments:
        unit_ids = {assignment.unit_id}
        if assignment.position.level == level_model.SUPERVISOR:
            frontier = {assignment.unit_id}
            while frontier:
                children = set(
                    PositionAssignment.unit.field.related_model.objects.filter(
                        parent_id__in=frontier,
                        is_active=True,
                        company__isnull=True,
                    ).values_list("pk", flat=True)
                )
                children -= unit_ids
                if not children:
                    break
                unit_ids.update(children)
                frontier = children

        subordinate_scope = PositionAssignment.objects.filter(
            unit_id__in=unit_ids,
            unit__is_active=True,
            unit__company__isnull=True,
            is_active=True,
            valid_from__lte=today,
            position__is_active=True,
            position__level__gt=assignment.position.level,
            line_code__gt="",
        ).filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=today)
        )
        if assignment.line_code != "*":
            subordinate_scope = subordinate_scope.filter(
                Q(line_code=assignment.line_code) | Q(line_code="*")
            )
        subordinate_ids = subordinate_scope.exclude(
            user_id=user.pk
        ).values("user_id")
        allowed |= Q(pk__in=subordinate_ids)
    return allowed


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
        self.fields["related_request"].queryset = scoped_requests_for(user).order_by("-created_at", "-pk") if user and user.is_authenticated else ServiceRequest.objects.none()
        if not user or not user.is_authenticated:
            return
        staff = _active_staff_ids()
        scope = _manager_scope(user)
        if scope is not None:
            staff = staff.filter(scope).distinct()
        self.fields["assignees"].queryset = staff.order_by("last_name", "first_name", "username")

    def clean(self):
        cleaned = super().clean()
        if not has_global_access(self.user) and not is_unit_manager(self.user):
            self.add_error(
                None,
                "فقط رئیس اداره، مدیر سامانه یا سرپرست/مسئول دارای انتصاب معتبر در اداره بیمه مجاز است وظیفه تعریف کند.",
            )

        related_request = cleaned.get("related_request")
        assignees = cleaned.get("assignees")
        if related_request and related_request.is_confidential:
            if not has_global_access(self.user):
                self.add_error(
                    "related_request",
                    "اتصال وظیفه به پرونده محرمانه فقط برای رئیس اداره یا مدیر سامانه مجاز است.",
                )
            unauthorized_assignees = [
                assignee for assignee in (assignees or [])
                if not has_global_access(assignee)
            ]
            if unauthorized_assignees:
                self.add_error(
                    "assignees",
                    "وظیفه مرتبط با پرونده محرمانه فقط می‌تواند به رئیس اداره یا مدیر سامانه تخصیص داده شود.",
                )
        return cleaned
