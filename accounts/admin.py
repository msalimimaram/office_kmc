from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from auditlog.services import record_event
from .access import has_role
from .models import (
    OrganizationalPosition,
    OrganizationalUnit,
    PositionAssignment,
    RoleAssignment,
    User,
    UserNotification,
)



class SystemAdminUserCreationForm(forms.ModelForm):
    username = forms.CharField(required=False, widget=forms.HiddenInput())
    first_name = forms.CharField(max_length=150, required=True, label="نام")
    last_name = forms.CharField(max_length=150, required=True, label="نام خانوادگی")
    mobile = forms.CharField(max_length=20, required=True, label="شماره همراه")
    national_id = forms.CharField(max_length=10, required=True, label="کد ملی")

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "mobile", "national_id")

    def clean_username(self):
        return (self.cleaned_data.get("username") or "").strip()

    def clean_first_name(self):
        value = self.cleaned_data["first_name"].strip()
        if not value:
            raise forms.ValidationError("نام نمی‌تواند خالی باشد.")
        return value

    def clean_last_name(self):
        value = self.cleaned_data["last_name"].strip()
        if not value:
            raise forms.ValidationError("نام خانوادگی نمی‌تواند خالی باشد.")
        return value

    def clean_national_id(self):
        from organizations.models import normalize_national_id
        national_id = normalize_national_id(self.cleaned_data.get("national_id"))
        if len(national_id) != 10:
            raise forms.ValidationError("کد ملی باید دقیقاً ده رقم باشد.")
        duplicate_national_id = User.objects.filter(
            national_id=national_id
        ).exclude(pk=self.instance.pk).exists()
        duplicate_username = User.objects.filter(
            username=national_id
        ).exclude(pk=self.instance.pk).exists()
        if duplicate_national_id or duplicate_username:
            raise forms.ValidationError("این کد ملی یا نام کاربری متناظر با آن قبلاً ثبت شده است.")
        return national_id

    def clean_mobile(self):
        from .provisioning import normalize_mobile
        mobile = normalize_mobile(self.cleaned_data.get("mobile"))
        if len(mobile) != 11 or not mobile.startswith("09"):
            raise forms.ValidationError("شماره همراه باید با قالب 09xxxxxxxxx وارد شود.")
        return mobile

    def clean(self):
        cleaned = super().clean()
        national_id = cleaned.get("national_id")
        submitted = cleaned.get("username") or ""
        if national_id:
            if submitted and submitted != national_id:
                self.add_error("national_id", "نام کاربری انسانی فقط کد ملی همان شخص است.")
            cleaned["username"] = national_id
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["national_id"]
        user.national_id = self.cleaned_data["national_id"]
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.mobile = self.cleaned_data["mobile"]
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        user.must_change_password = True
        user.set_password(user.mobile)
        if commit:
            user.save()
            self.save_m2m()
        return user


def _user_snapshot(obj):
    return {
        "username": obj.username,
        "first_name": obj.first_name,
        "last_name": obj.last_name,
        "email": obj.email,
        "is_active": obj.is_active,
        "must_change_password": obj.must_change_password,
        "legacy_role": obj.role,
        "legacy_company_id": obj.company_id,
        "legacy_insurer_id": obj.insurer_id,
        "national_id_masked": f"***{(obj.national_id or '')[-3:]}" if obj.national_id else "",
    }


def _role_assignment_snapshot(obj):
    return {
        "user_id": obj.user_id,
        "role": obj.role,
        "company_id": obj.company_id,
        "insurer_id": obj.insurer_id,
        "organizational_unit_id": obj.organizational_unit_id,
        "position_id": obj.position_id,
        "line_code": obj.line_code,
        "valid_from": obj.valid_from.isoformat() if obj.valid_from else None,
        "valid_until": obj.valid_until.isoformat() if obj.valid_until else None,
        "is_active": obj.is_active,
        "reason": obj.reason,
        "approved_by_id": obj.approved_by_id,
        "granted_by_id": obj.granted_by_id,
    }


def _position_assignment_snapshot(obj):
    return {
        "user_id": obj.user_id,
        "unit_id": obj.unit_id,
        "position_id": obj.position_id,
        "line_code": obj.line_code,
        "valid_from": obj.valid_from.isoformat() if obj.valid_from else None,
        "valid_until": obj.valid_until.isoformat() if obj.valid_until else None,
        "is_active": obj.is_active,
        "reason": obj.reason,
        "approved_by_id": obj.approved_by_id,
        "granted_by_id": obj.granted_by_id,
    }


def _unit_snapshot(obj):
    return {
        "code": obj.code, "name": obj.name, "parent_id": obj.parent_id,
        "company_id": obj.company_id, "is_active": obj.is_active,
    }


def _position_snapshot(obj):
    return {
        "title": obj.title, "code": obj.code, "unit_id": obj.unit_id,
        "level": obj.level, "is_active": obj.is_active,
    }


def initial_system_admin_bootstrap_available():
    """The technical bootstrap account may designate exactly the first operational admin."""
    return not RoleAssignment.objects.filter(
        role=RoleAssignment.Role.SYSTEM_ADMIN
    ).exists()


def is_initial_system_admin_bootstrap_user(user):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and user.is_superuser
        and initial_system_admin_bootstrap_available()
    )


def is_system_admin(request):
    return bool(
        request.user
        and request.user.is_authenticated
        and has_role(request.user, RoleAssignment.Role.SYSTEM_ADMIN)
    )


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    # Business access is granted only by RoleAssignment. Do not expose Django's
    # is_staff/is_superuser/groups/permissions switches in this business UI.
    add_form = SystemAdminUserCreationForm
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("اطلاعات شخصی", {"fields": ("first_name", "last_name", "email", "mobile", "national_id")}),
        ("وضعیت حساب", {"fields": ("is_active", "must_change_password", "mfa_enabled")}),
        ("اطلاعات سازگاری قدیمی (فقط مشاهده)", {"fields": ("role", "company", "insurer")}),
        ("تاریخ‌ها", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {
        "classes": ("wide",),
        "fields": ("username", "first_name", "last_name", "national_id", "mobile"),
    }),)
    list_display = ("username", "first_name", "last_name", "role", "company", "insurer", "is_active")
    list_filter = ("role", "company", "insurer", "is_active")
    readonly_fields = (
        "date_joined", "last_login", "username", "role", "mobile", "national_id",
        "company", "insurer", "mfa_enabled",
    )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ("date_joined", "last_login", "role", "company", "insurer", "mfa_enabled")
        return super().get_readonly_fields(request, obj)

    def save_model(self, request, obj, form, change):
        before = _user_snapshot(User.objects.get(pk=obj.pk)) if change else {}
        super().save_model(request, obj, form, change)
        record_event(
            actor=request.user,
            action="user_account_updated" if change else "user_account_created",
            obj=obj,
            summary="ثبت تغییرات حساب کاربری توسط مدیر سامانه",
            before_data=before,
            after_data=_user_snapshot(obj),
            request=request,
        )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if is_initial_system_admin_bootstrap_user(request.user):
            return queryset.filter(is_active=True, is_superuser=False)
        return queryset

    def has_module_permission(self, request):
        return is_system_admin(request)

    def has_view_permission(self, request, obj=None):
        return is_system_admin(request) or (
            obj is None and is_initial_system_admin_bootstrap_user(request.user)
        )

    def has_add_permission(self, request):
        # Human accounts originate from the approved insured-person roster.
        # This admin is for controlled review/updates of already provisioned accounts.
        return False

    def has_change_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_delete_permission(self, request, obj=None):
        return False


class InitialSystemAdminAssignmentForm(forms.ModelForm):
    """Narrow, one-time form shown only to the technical bootstrap superuser."""

    reason = forms.CharField(
        min_length=5,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="دلیل و مستند انتخاب",
    )

    class Meta:
        model = RoleAssignment
        fields = ("user", "role", "valid_from", "valid_until", "is_active", "reason")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = (
            (RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.SYSTEM_ADMIN.label),
        )
        self.fields["user"].queryset = User.objects.filter(
            is_active=True, is_superuser=False
        ).order_by("last_name", "first_name", "username")
        self.fields["is_active"].initial = True
        self.fields["reason"].help_text = (
            "دلیل انتخاب مدیر سامانه و مرجع/مجوز سازمانی انتصاب را ثبت کنید."
        )

    def clean(self):
        cleaned = super().clean()
        user = cleaned.get("user")
        today = timezone.localdate()
        if cleaned.get("role") != RoleAssignment.Role.SYSTEM_ADMIN:
            self.add_error("role", "در مرحله راه‌اندازی فقط انتخاب مدیر سامانه مجاز است.")
        if user and (not user.is_active or user.is_superuser):
            self.add_error("user", "مدیر سامانه باید یک حساب عملیاتی فعال و غیرسوپریوزر باشد.")
        if not cleaned.get("is_active"):
            self.add_error("is_active", "انتصاب اولیه مدیر سامانه باید در زمان ثبت فعال باشد.")
        if cleaned.get("valid_from") and cleaned["valid_from"] > today:
            self.add_error("valid_from", "برای جلوگیری از قفل‌شدن راه‌اندازی، انتصاب اولیه باید از امروز یا قبل معتبر باشد.")
        if cleaned.get("valid_until") and cleaned["valid_until"] < today:
            self.add_error("valid_until", "انتصاب اولیه نمی‌تواند در زمان ثبت منقضی باشد.")
        if RoleAssignment.objects.filter(role=RoleAssignment.Role.SYSTEM_ADMIN).exists():
            raise forms.ValidationError(
                "برای مدیر سامانه قبلاً سابقه انتصاب ثبت شده است؛ راه‌اندازی اولیه دیگر در دسترس نیست."
            )
        return cleaned


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "company", "insurer", "line_code", "valid_from", "valid_until", "is_active")
    list_filter = ("role", "company", "insurer", "is_active")
    search_fields = ("user__username", "user__first_name", "user__last_name", "reason")
    readonly_fields = ("created_at", "updated_at", "granted_by")
    autocomplete_fields = ("user", "company", "insurer", "organizational_unit", "position", "approved_by")

    bootstrap_fields = ("user", "role", "valid_from", "valid_until", "is_active", "reason")

    def _bootstrap_request(self, request):
        return is_initial_system_admin_bootstrap_user(request.user)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.none() if self._bootstrap_request(request) else queryset

    def get_fields(self, request, obj=None):
        if obj is None and self._bootstrap_request(request):
            return self.bootstrap_fields
        return super().get_fields(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        if obj is None and self._bootstrap_request(request):
            kwargs["form"] = InitialSystemAdminAssignmentForm
        return super().get_form(request, obj, **kwargs)

    def has_module_permission(self, request):
        return is_system_admin(request) or self._bootstrap_request(request)

    def has_view_permission(self, request, obj=None):
        if is_system_admin(request):
            return True
        return obj is None and self._bootstrap_request(request)

    def has_add_permission(self, request):
        return is_system_admin(request) or self._bootstrap_request(request)

    def has_change_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if self._bootstrap_request(request):
            if change or obj.pk:
                raise PermissionDenied("حساب راه‌انداز فقط مجاز به تعیین نخستین مدیر سامانه است.")
            from workflow.models import BusinessCalendar

            with transaction.atomic():
                # Serialize concurrent first-designation attempts against the
                # migrated singleton calendar row, then re-check the one-time gate.
                BusinessCalendar.objects.select_for_update().get(code="iran-default")
                if RoleAssignment.objects.filter(
                    role=RoleAssignment.Role.SYSTEM_ADMIN
                ).exists():
                    raise ValidationError(
                        "سابقه مدیر سامانه وجود دارد؛ انتخاب اولیه فقط یک‌بار مجاز است."
                    )
                if (
                    obj.role != RoleAssignment.Role.SYSTEM_ADMIN
                    or not obj.user_id
                    or not obj.user.is_active
                    or obj.user.is_superuser
                    or not obj.is_active
                    or obj.valid_from > timezone.localdate()
                    or (obj.valid_until and obj.valid_until < timezone.localdate())
                ):
                    raise ValidationError("اطلاعات انتصاب نخستین مدیر سامانه معتبر نیست.")
                obj.company = None
                obj.insurer = None
                obj.organizational_unit = None
                obj.position = None
                obj.line_code = ""
                obj.granted_by = request.user
                obj.approved_by = None
                super().save_model(request, obj, form, change)
                record_event(
                    actor=request.user,
                    action="accounts.initial_system_admin_designated",
                    obj=obj,
                    summary="انتخاب نخستین مدیر سامانه توسط سوپریوزر راه‌انداز",
                    after_data={
                        **_role_assignment_snapshot(obj),
                        "bootstrap_actor_is_superuser": True,
                    },
                    request=request,
                )
            return

        if not is_system_admin(request):
            raise PermissionDenied("مدیریت انتصاب‌ها فقط برای مدیر سامانه مجاز است.")
        before = _role_assignment_snapshot(RoleAssignment.objects.get(pk=obj.pk)) if change else {}
        if not change and not obj.granted_by_id:
            obj.granted_by = request.user
        # Approval is a separate business act; never silently approve by the grantor.
        super().save_model(request, obj, form, change)
        record_event(
            actor=request.user,
            action="role_assignment_updated" if change else "role_assignment_created",
            obj=obj,
            summary="ثبت انتصاب یا تغییر دامنه نقش عملیاتی",
            before_data=before,
            after_data=_role_assignment_snapshot(obj),
            request=request,
        )


@admin.register(OrganizationalUnit)
class OrganizationalUnitAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "parent", "company", "is_active")
    list_filter = ("company", "is_active")
    search_fields = ("code", "name")

    def has_module_permission(self, request):
        return is_system_admin(request)

    def has_view_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_add_permission(self, request):
        return is_system_admin(request)

    def has_change_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        before = _unit_snapshot(OrganizationalUnit.objects.get(pk=obj.pk)) if change else {}
        super().save_model(request, obj, form, change)
        record_event(
            actor=request.user,
            action="organizational_unit_updated" if change else "organizational_unit_created",
            obj=obj, summary="ثبت تغییر در ساختار واحدهای سازمانی",
            before_data=before, after_data=_unit_snapshot(obj), request=request,
        )


@admin.register(OrganizationalPosition)
class OrganizationalPositionAdmin(admin.ModelAdmin):
    list_display = ("title", "code", "unit", "level", "allow_multiple_holders", "is_active")
    list_filter = ("unit", "level", "allow_multiple_holders", "is_active")
    search_fields = ("title", "code", "unit__name")

    def has_module_permission(self, request):
        return is_system_admin(request)

    def has_view_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_add_permission(self, request):
        return is_system_admin(request)

    def has_change_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        before = _position_snapshot(OrganizationalPosition.objects.get(pk=obj.pk)) if change else {}
        super().save_model(request, obj, form, change)
        record_event(
            actor=request.user,
            action="organizational_position_updated" if change else "organizational_position_created",
            obj=obj, summary="ثبت تغییر در فهرست سمت‌های سازمانی",
            before_data=before, after_data=_position_snapshot(obj), request=request,
        )


@admin.register(PositionAssignment)
class PositionAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "unit", "position", "line_code", "valid_from", "valid_until", "is_active")
    list_filter = ("unit", "position", "is_active")
    search_fields = ("user__username", "user__first_name", "user__last_name", "position__title")
    readonly_fields = ("created_at", "granted_by")
    autocomplete_fields = ("user", "unit", "position", "approved_by")

    def has_module_permission(self, request):
        return is_system_admin(request)

    def has_view_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_add_permission(self, request):
        return is_system_admin(request)

    def has_change_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        before = _position_assignment_snapshot(PositionAssignment.objects.get(pk=obj.pk)) if change else {}
        if not change and not obj.granted_by_id:
            obj.granted_by = request.user
        # Do not manufacture an approval record from the grantor's identity.
        super().save_model(request, obj, form, change)
        record_event(
            actor=request.user,
            action="position_assignment_updated" if change else "position_assignment_created",
            obj=obj, summary="ثبت انتصاب یا تغییر سمت سازمانی",
            before_data=before, after_data=_position_assignment_snapshot(obj), request=request,
        )


@admin.register(UserNotification)
class UserNotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "title", "actor", "created_at", "read_at")
    list_filter = ("created_at", "read_at")
    search_fields = ("recipient__username", "title", "body")
    readonly_fields = tuple(field.name for field in UserNotification._meta.fields)

    def has_module_permission(self, request):
        return is_system_admin(request)

    def has_view_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
