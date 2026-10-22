from django import forms
from django.contrib.auth import get_user_model

from requests_portal.models import ServiceRequest
from .models import InternalTask


User = get_user_model()
MANAGER_ROLES = {"system_admin", "department_head", "insurance_specialist"}
PRIVILEGED_ROLES = {"system_admin", "department_head"}


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
        self.fields["related_request"].queryset = ServiceRequest.objects.none()
        if not user:
            return

        # Tasks are internal workflow tools. Only active internal staff can be assigned.
        self.fields["assignees"].queryset = User.objects.filter(
            is_active=True,
            role__in=MANAGER_ROLES,
        ).order_by("last_name", "first_name", "username")

        requests = ServiceRequest.objects.select_related("company", "submitted_by")
        if user.is_superuser or user.role in PRIVILEGED_ROLES:
            pass
        elif user.role == "insurance_specialist":
            requests = requests.filter(is_confidential=False)
        else:
            requests = ServiceRequest.objects.none()
        self.fields["related_request"].queryset = requests.order_by("-created_at", "-pk")

        # A specialist can create tasks, but cannot assign them to another role
        # or attach confidential request metadata.
        if user.role not in MANAGER_ROLES and not user.is_superuser:
            self.fields["assignees"].queryset = User.objects.none()
            self.fields["related_request"].queryset = ServiceRequest.objects.none()

    def clean(self):
        cleaned = super().clean()
        related_request = cleaned.get("related_request")
        assignees = cleaned.get("assignees")
        if related_request and related_request.is_confidential:
            allowed = PRIVILEGED_ROLES
            if assignees and any(
                not (assignee.is_superuser or assignee.role in allowed)
                for assignee in assignees
            ):
                self.add_error(
                    "assignees",
                    "وظیفه مرتبط با درخواست محرمانه فقط می‌تواند به مدیر سامانه یا رئیس اداره بیمه تخصیص داده شود.",
                )
        return cleaned
