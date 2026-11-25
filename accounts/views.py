from django.contrib.auth import views as auth_views
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, models, transaction
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import UserNotification, RoleAssignment
from .access import active_internal_position_assignments, company_ids_for, has_role, is_insurance_staff


def _can_access_notifications(user):
    has_active_position = active_internal_position_assignments(user).exists()
    return (
        is_insurance_staff(user)
        or has_role(user, RoleAssignment.Role.INSURED_PERSON)
        or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP)
        or has_role(user, RoleAssignment.Role.INSURER_REP)
        or has_active_position
    )


class RequiredPasswordChangeView(auth_views.PasswordChangeView):
    """Clear the forced-change flag only after a successful password change."""

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.must_change_password = False
        self.request.user.save(update_fields=["must_change_password"])
        return response



@login_required
def notification_list(request):
    if not _can_access_notifications(request.user):
        raise PermissionDenied("شما مجاز به مشاهده اعلان‌ها نیستید.")
    notifications = UserNotification.objects.filter(
        recipient=request.user
    ).order_by("-created_at", "-pk")
    page_obj = Paginator(notifications, 30).get_page(request.GET.get("page"))
    return render(request, "accounts/notification_list.html", {
        "notifications": page_obj.object_list,
        "page_obj": page_obj,
    })


@login_required
@require_POST
def notification_mark_read(request, pk):
    if not _can_access_notifications(request.user):
        raise PermissionDenied("شما مجاز به مدیریت اعلان‌ها نیستید.")
    notification = get_object_or_404(
        UserNotification,
        pk=pk,
        recipient=request.user,
    )
    notification.mark_read(user=request.user)
    target = notification.target_url
    if (
        target.startswith("/")
        and not target.startswith("//")
        and url_has_allowed_host_and_scheme(
            target,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
    ):
        return redirect(target)
    return redirect("notification_list")



@login_required
@require_POST
def select_active_company(request):
    """Change the active subsidiary context without expanding authorization."""
    allowed_company_ids = company_ids_for(
        request.user, role=RoleAssignment.Role.SUBSIDIARY_REP
    )
    if not allowed_company_ids:
        raise PermissionDenied("برای این حساب محدوده نمایندگی شرکت فعالی تعریف نشده است.")
    try:
        selected_company_id = int(request.POST.get("company_id", ""))
    except (TypeError, ValueError):
        raise PermissionDenied("شرکت انتخاب‌شده معتبر نیست.")
    if selected_company_id not in allowed_company_ids:
        raise PermissionDenied("انتخاب شرکت خارج از محدوده انتصاب معتبر شماست.")

    request.session["active_company_id"] = selected_company_id
    request.session.modified = True
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        target = reverse("dashboard")
    return redirect(target)


@login_required
def personnel_assignments(request):
    """System Admin assigns positions to existing people in the insured roster."""
    if not has_role(request.user, RoleAssignment.Role.SYSTEM_ADMIN):
        raise PermissionDenied("تغییر سمت و دسترسی سازمانی فقط برای مدیر سامانه مجاز است.")

    from organizations.models import Person, PersonEmployment, normalize_national_id
    from .forms import PersonnelPositionAssignmentForm
    from .models import OrganizationalPosition, PositionAssignment
    from .provisioning import provision_insured_person_account
    from auditlog.services import record_event

    raw_national_id = (
        request.POST.get("national_id") if request.method == "POST"
        else request.GET.get("national_id")
    )
    national_id = normalize_national_id(raw_national_id)
    person = None
    search_error = ""
    if raw_national_id:
        if len(national_id) != 10:
            search_error = "کد ملی باید دقیقاً ده رقم باشد."
        else:
            person = Person.objects.select_related("user", "company", "employee").filter(
                national_id=national_id
            ).first()
            if person is None:
                search_error = "شخصی با این کد ملی در فهرست بیمه‌شدگان پیدا نشد."

    form = PersonnelPositionAssignmentForm(request.POST or None)
    if request.method == "POST" and request.POST.get("action") == "assign" and person:
        if form.is_valid():
            try:
                with transaction.atomic():
                    person = Person.objects.select_for_update().select_related(
                        "user", "company", "employee"
                    ).get(pk=person.pk)
                    if (
                        not person.is_active
                        or not person.is_insured
                        or person.relationship != Person.Relationship.EMPLOYEE
                        or person.employee_id
                    ):
                        raise ValidationError(
                            "انتصاب سمت‌های داخلی فقط برای بیمه‌شده اصلیِ فعال و شاغل مجاز است."
                        )

                    today = timezone.localdate()
                    employments = list(
                        PersonEmployment.objects.filter(
                            person=person,
                            status=PersonEmployment.Status.ACTIVE,
                        ).filter(
                            models.Q(valid_from__isnull=True)
                            | models.Q(valid_from__lte=today)
                        ).filter(
                            models.Q(valid_until__isnull=True)
                            | models.Q(valid_until__gte=today)
                        ).select_related("company")
                    )
                    if len(employments) != 1 or not employments[0].company.is_active:
                        raise ValidationError(
                            "برای این شخص باید دقیقاً یک سابقه اشتغال فعال در شرکت فعال وجود داشته باشد."
                        )
                    employment = employments[0]

                    position = form.cleaned_data["position"]
                    line_code = form.cleaned_data["line_code"] or ""
                    role = (
                        RoleAssignment.Role.DEPARTMENT_HEAD
                        if position.code == "department-head"
                        else RoleAssignment.Role.INSURANCE_SPECIALIST
                    )
                    user = provision_insured_person_account(
                        person,
                        company=employment.company,
                        actor=request.user,
                        source_reference="system-admin-personnel-assignment",
                    )
                    position_assignment = PositionAssignment.objects.create(
                        user=user,
                        unit=position.unit,
                        position=position,
                        line_code=line_code,
                        valid_from=form.cleaned_data["valid_from"],
                        valid_until=form.cleaned_data["valid_until"],
                        is_active=True,
                        reason=form.cleaned_data["reason"],
                        granted_by=request.user,
                    )
                    role_assignment = RoleAssignment.objects.create(
                        user=user,
                        role=role,
                        organizational_unit=position.unit,
                        position=position,
                        line_code=line_code,
                        valid_from=form.cleaned_data["valid_from"],
                        valid_until=form.cleaned_data["valid_until"],
                        is_active=True,
                        reason=form.cleaned_data["reason"],
                        granted_by=request.user,
                    )
                    assignment_data = {
                        "person_id": person.pk,
                        "user_id": user.pk,
                        "position_id": position.pk,
                        "role": role,
                        "line_code": line_code,
                        "valid_from": position_assignment.valid_from.isoformat(),
                        "valid_until": (
                            position_assignment.valid_until.isoformat()
                            if position_assignment.valid_until else None
                        ),
                    }
                    record_event(
                        actor=request.user,
                        action="personnel_position_assigned",
                        obj=position_assignment,
                        summary="انتصاب سمت سازمانی از سوی مدیر سامانه",
                        after_data=assignment_data,
                        request=request,
                    )
                    record_event(
                        actor=request.user,
                        action="personnel_access_granted",
                        obj=role_assignment,
                        summary="اعطای دسترسی متناظر با سمت سازمانی",
                        after_data=assignment_data,
                        request=request,
                    )
            except (ValidationError, IntegrityError) as exc:
                messages.error(request, f"انتصاب ثبت نشد: {exc}")
            else:
                messages.success(
                    request,
                    "سمت و دسترسی متناظر با موفقیت ثبت شد. رمز اولیه حساب تازه‌ساخته‌شده، شماره همراه ثبت‌شده همان شخص است و در نخستین ورود باید تغییر کند.",
                )
                return redirect(f"{request.path}?national_id={national_id}")
    elif request.method == "POST" and request.POST.get("action") == "assign" and not person:
        messages.error(request, search_error or "ابتدا شخص معتبر را با کد ملی جست‌وجو کنید.")

    current_assignments = []
    if person and person.user_id:
        today = timezone.localdate()
        current_assignments = PositionAssignment.objects.filter(
            user_id=person.user_id,
            is_active=True,
        ).filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=today)
        ).select_related("unit", "position").order_by("position__level", "position__title")

    return render(request, "accounts/personnel_assignments.html", {
        "national_id": national_id,
        "person": person,
        "search_error": search_error,
        "form": form,
        "current_assignments": current_assignments,
    })


@login_required
def personnel_assignment_end(request, assignment_id):
    """End an appointment without deleting its audit/history record."""
    from organizations.models import normalize_national_id
    if request.method != "POST":
        raise PermissionDenied("پایان انتصاب فقط با درخواست ثبت‌شده مجاز است.")
    if not has_role(request.user, RoleAssignment.Role.SYSTEM_ADMIN):
        raise PermissionDenied("تغییر سمت و دسترسی سازمانی فقط برای مدیر سامانه مجاز است.")

    from .models import PositionAssignment
    from auditlog.services import record_event

    today = timezone.localdate()
    try:
        with transaction.atomic():
            assignment = PositionAssignment.objects.select_for_update().select_related(
                "user", "position", "unit"
            ).get(pk=assignment_id)
            if not assignment.is_active:
                raise ValidationError("این انتصاب قبلاً خاتمه یافته است.")
            before = {
                "user_id": assignment.user_id,
                "position_id": assignment.position_id,
                "valid_from": assignment.valid_from.isoformat(),
                "valid_until": assignment.valid_until.isoformat() if assignment.valid_until else None,
                "is_active": assignment.is_active,
            }
            assignment.is_active = False
            if assignment.valid_from <= today and (
                assignment.valid_until is None or assignment.valid_until > today
            ):
                assignment.valid_until = today
            assignment.save()

            role = (
                RoleAssignment.Role.DEPARTMENT_HEAD
                if assignment.position.code == "department-head"
                else RoleAssignment.Role.INSURANCE_SPECIALIST
            )
            role_assignments = RoleAssignment.objects.select_for_update().filter(
                user_id=assignment.user_id,
                position_id=assignment.position_id,
                role=role,
                is_active=True,
            )
            for role_assignment in role_assignments:
                role_assignment.is_active = False
                if role_assignment.valid_from <= today and (
                    role_assignment.valid_until is None or role_assignment.valid_until > today
                ):
                    role_assignment.valid_until = today
                role_assignment.save()

            record_event(
                actor=request.user,
                action="personnel_position_ended",
                obj=assignment,
                summary="خاتمه انتصاب سازمانی بدون حذف سابقه",
                before_data=before,
                after_data={
                    **before,
                    "valid_until": assignment.valid_until.isoformat() if assignment.valid_until else None,
                    "is_active": False,
                },
                request=request,
            )
    except (PositionAssignment.DoesNotExist, ValidationError, IntegrityError) as exc:
        messages.error(request, f"پایان انتصاب انجام نشد: {exc}")
    else:
        messages.success(request, "انتصاب پایان یافت؛ سابقه و رویداد ممیزی حفظ شد.")
    target = normalize_national_id(request.POST.get("national_id", ""))
    return redirect(f"/accounts/personnel-assignments/?national_id={target}")
