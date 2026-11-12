from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render, redirect
from django.http import FileResponse, Http404
from django.utils.text import get_valid_filename

from accounts.access import (
    company_ids_for,
    has_global_access,
    has_role,
    insurer_ids_for,
    line_codes_for,
)
from accounts.models import RoleAssignment
from auditlog.services import record_event
from workflow.models import WorkflowDefinition
from workflow.services import resolve_initial_assignee, start_workflow
from claims.models import Claim
from insurance.models import InsuranceLine
from organizations.models import Person, PersonEmployment
from core.uploads import validate_uploaded_file
from .forms import (
    AssetPolicyEndorsementForm, AssetPolicyPeriodForm, AssetValuationForm,
    InsuredAssetForm,
)
from .models import (
    AssetPolicyEndorsement, AssetPolicyPeriod, AssetValuation, InsuredAsset, Vehicle,
)


def _asset_scope(user):
    qs = InsuredAsset.objects.select_related(
        "company", "person", "insurer", "contract", "created_by"
    ).prefetch_related("vehicle_details")
    if has_global_access(user):
        return qs

    allowed = models.Q(pk__in=[])

    if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
        if "*" in lines:
            allowed |= models.Q(pk__gt=0)
        else:
            if lines.intersection({"third_party", "body", "vehicle"}):
                allowed |= models.Q(asset_type=InsuredAsset.Type.VEHICLE)
            if lines.intersection({"fire", "property", "liability", "equipment"}):
                allowed |= ~models.Q(asset_type=InsuredAsset.Type.VEHICLE)

    company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
    if company_ids:
        today = timezone.localdate()
        employed_person_ids = PersonEmployment.objects.filter(
            company_id__in=company_ids,
            status=PersonEmployment.Status.ACTIVE,
        ).filter(
            models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=today)
        ).filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=today)
        ).values_list("person_id", flat=True)
        rep_lines = line_codes_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
        if "*" in rep_lines:
            rep_asset_scope = models.Q(pk__gt=0)
        else:
            rep_asset_scope = models.Q(pk__in=[])
            if rep_lines.intersection({"third_party", "body", "vehicle"}):
                rep_asset_scope |= models.Q(asset_type=InsuredAsset.Type.VEHICLE)
            if rep_lines.intersection({"fire", "property", "liability", "equipment"}):
                rep_asset_scope |= ~models.Q(asset_type=InsuredAsset.Type.VEHICLE)
        allowed |= (
            models.Q(company_id__in=company_ids)
            | models.Q(person_id__in=employed_person_ids)
        ) & rep_asset_scope

    insurer_ids = insurer_ids_for(user)
    if insurer_ids:
        allowed |= models.Q(insurer_id__in=insurer_ids) | models.Q(insurer__isnull=True, contract__insurer_id__in=insurer_ids)

    if has_role(user, RoleAssignment.Role.INSURED_PERSON):
        person_ids = Person.objects.filter(
            models.Q(user_id=user.pk) | models.Q(employee__user_id=user.pk)
        ).values_list("pk", flat=True)
        allowed |= models.Q(person_id__in=person_ids)

    return qs.filter(allowed).distinct()


def _can_manage_asset(user, asset):
    """Check specialist authority against the asset's actual insurance domain."""
    if has_global_access(user):
        return True
    if not has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        return False
    lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
    if "*" in lines:
        return True
    required = (
        {"third_party", "body", "vehicle"}
        if asset.asset_type == InsuredAsset.Type.VEHICLE
        else {"fire", "property", "liability", "equipment"}
        if asset.asset_type in {InsuredAsset.Type.PROPERTY, InsuredAsset.Type.EQUIPMENT}
        else {"other"}
    )
    return bool(lines.intersection(required))


@login_required
def asset_list(request):
    assets = _asset_scope(request.user)
    query = request.GET.get("q", "").strip()[:100]
    asset_type = request.GET.get("type", "").strip()
    if query:
        assets = assets.filter(
            models.Q(asset_code__icontains=query)
            | models.Q(name__icontains=query)
            | models.Q(policy_number__icontains=query)
            | models.Q(company__name__icontains=query)
            | models.Q(person__first_name__icontains=query)
            | models.Q(person__last_name__icontains=query)
            | models.Q(vehicle_details__plate_number__icontains=query)
        ).distinct()
    if asset_type in dict(InsuredAsset.Type.choices):
        assets = assets.filter(asset_type=asset_type)
    page_obj = Paginator(assets.order_by("name", "pk"), 25).get_page(request.GET.get("page"))
    can_create = has_role(request.user, RoleAssignment.Role.INSURANCE_SPECIALIST) and (
        has_global_access(request.user) or bool(line_codes_for(request.user, role=RoleAssignment.Role.INSURANCE_SPECIALIST))
    )
    return render(request, "assets/asset_list.html", {
        "assets": page_obj.object_list,
        "page_obj": page_obj,
        "search_query": query,
        "selected_type": asset_type,
        "asset_types": InsuredAsset.Type.choices,
        "can_create": can_create,
        "can_update": can_create,
    })


@login_required
def asset_create(request):
    if not has_role(request.user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        raise PermissionDenied("ثبت و تغییر دارایی فقط برای کارشناس رشته مربوط مجاز است.")
    if request.method == "POST":
        form = InsuredAssetForm(request.POST, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                asset = form.save(commit=False)
                asset.created_by = request.user
                asset.save()
                if asset.asset_type == InsuredAsset.Type.VEHICLE:
                    Vehicle.objects.create(
                        asset=asset,
                        plate_number=form.cleaned_data["plate_number"],
                        vin=form.cleaned_data.get("vin", ""),
                        engine_number=form.cleaned_data.get("engine_number", ""),
                        make=form.cleaned_data.get("make", ""),
                        model_name=form.cleaned_data.get("model_name", ""),
                        model_year=form.cleaned_data.get("model_year"),
                    )
                record_event(
                    actor=request.user,
                    action="insured_asset_created",
                    obj=asset,
                    summary=f"دارایی ثبت شد: {asset.asset_code}",
                    after_data={
                        "asset_type": asset.asset_type,
                        "company_id": asset.company_id,
                        "person_id": asset.person_id,
                        "insurer_id": asset.insurer_id,
                        "contract_id": asset.contract_id,
                    },
                    request=request,
                )
            messages.success(request, "دارایی بیمه‌شده با موفقیت ثبت شد.")
            return redirect("asset_list")
    else:
        form = InsuredAssetForm(user=request.user)
    return render(request, "assets/asset_form.html", {"form": form})



def _start_asset_approval(*, obj, asset, actor, code, note=""):
    definition = WorkflowDefinition.objects.filter(
        code=code,
        is_active=True,
    ).order_by("-version").first()
    if not definition:
        raise ValidationError(
            f"گردش‌کار فعال {code} برای تأیید این عملیات دارایی پیکربندی نشده است."
        )
    contract = asset.contract if asset.contract_id else None
    company_id = asset.company_id or (
        asset.person.company_id if asset.person_id else None
    )
    insurer_id = asset.insurer_id or (
        contract.insurer_id if contract else None
    )
    line_code = contract.line if contract else None
    assignee, delegation = resolve_initial_assignee(
        definition=definition,
        obj=obj,
        return_delegation=True,
        company_id=company_id,
        insurer_id=insurer_id,
        line_code=line_code,
    )
    return start_workflow(
        obj=obj,
        code=code,
        actor=actor,
        assignee=assignee,
        delegation=delegation,
        note=note,
    )


@login_required
def asset_detail(request, pk):
    asset = get_object_or_404(_asset_scope(request.user), pk=pk)
    can_manage = _can_manage_asset(request.user, asset)
    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied("ثبت سوابق دارایی فقط برای کارشناس رشته مربوط مجاز است.")
        action = request.POST.get("action", "").strip()
        if action == "add_valuation":
            form = AssetValuationForm(request.POST)
            if form.is_valid():
                try:
                    with transaction.atomic():
                        item = form.save(commit=False)
                        item.asset = asset
                        item.created_by = request.user
                        item.status = AssetValuation.Status.PENDING_APPROVAL
                        item.save()
                        case = _start_asset_approval(
                            obj=item,
                            asset=asset,
                            actor=request.user,
                            code="asset_valuation_approval",
                            note=item.note,
                        )
                        record_event(
                            actor=request.user,
                            action="asset_valuation_created",
                            obj=asset,
                            summary=f"سابقه ارزیابی دارایی {asset.asset_code} برای تأیید ثبت شد.",
                            after_data={
                                "valuation_id": item.pk,
                                "workflow_case_id": case.pk,
                                "status": item.status,
                                "valuation_date": item.valuation_date.isoformat() if item.valuation_date else None,
                                "market_value": str(item.market_value),
                                "insured_value": str(item.insured_value),
                                "method": item.method,
                            },
                            request=request,
                        )
                except (ValidationError, PermissionDenied) as exc:
                    form.add_error(None, str(exc))
                else:
                    messages.success(request, "ارزیابی ثبت و برای تأیید ارجاع شد؛ ارزش جاری دارایی تا تأیید تغییر نمی‌کند.")
                    return redirect("asset_detail", pk=asset.pk)
        elif action == "add_policy_period":
            form = AssetPolicyPeriodForm(
                request.POST,
                asset=asset,
                instance=AssetPolicyPeriod(asset=asset),
            )
            if form.is_valid():
                try:
                    with transaction.atomic():
                        item = form.save(commit=False)
                        item.asset = asset
                        item.created_by = request.user
                        item.status = AssetPolicyPeriod.Status.PENDING_APPROVAL
                        item.save()
                        case = _start_asset_approval(
                            obj=item,
                            asset=asset,
                            actor=request.user,
                            code="asset_policy_approval",
                            note=item.note,
                        )
                        record_event(
                            actor=request.user,
                            action="asset_policy_period_created",
                            obj=asset,
                            summary=f"دوره بیمه‌نامه {item.policy_number} برای تأیید ثبت شد.",
                            after_data={
                                "policy_period_id": item.pk,
                                "workflow_case_id": case.pk,
                                "insurer_id": item.insurer_id,
                                "contract_id": item.contract_id,
                                "policy_number": item.policy_number,
                                "status": item.status,
                            },
                            request=request,
                        )
                except (ValidationError, PermissionDenied) as exc:
                    form.add_error(None, str(exc))
                else:
                    messages.success(request, "دوره بیمه‌نامه ثبت و برای تأیید ارجاع شد؛ تا تأیید نهایی، بیمه‌نامه جاری تغییر نمی‌کند.")
                    return redirect("asset_detail", pk=asset.pk)
        elif action == "add_endorsement":
            form = AssetPolicyEndorsementForm(request.POST, request.FILES, asset=asset)
            if form.is_valid():
                upload = form.cleaned_data["document"]
                file_error = validate_uploaded_file(upload, max_size=20 * 1024 * 1024)
                if file_error:
                    form.add_error("document", file_error)
                else:
                    try:
                        with transaction.atomic():
                            item = form.save(commit=False)
                            item.created_by = request.user
                            item.status = AssetPolicyEndorsement.Status.PENDING_APPROVAL
                            item.save()
                            case = _start_asset_approval(
                                obj=item,
                                asset=asset,
                                actor=request.user,
                                code="asset_endorsement_approval",
                                note=item.description,
                            )
                            record_event(
                                actor=request.user,
                                action="asset_policy_endorsement_created",
                                obj=asset,
                                summary=f"الحاقیه {item.endorsement_number} برای تأیید ثبت شد.",
                                after_data={
                                    "endorsement_id": item.pk,
                                    "policy_period_id": item.policy_period_id,
                                    "endorsement_number": item.endorsement_number,
                                    "workflow_case_id": case.pk,
                                    "status": item.status,
                                },
                                request=request,
                            )
                    except (ValidationError, PermissionDenied) as exc:
                        form.add_error(None, str(exc))
                    else:
                        messages.success(request, "الحاقیه ثبت و برای تأیید ارجاع شد.")
                        return redirect("asset_detail", pk=asset.pk)
        else:
            raise PermissionDenied("عملیات درخواستی برای دارایی معتبر نیست.")
    else:
        form = None

    valuation_form = form if request.method == "POST" and request.POST.get("action") == "add_valuation" else AssetValuationForm()
    policy_period_form = form if request.method == "POST" and request.POST.get("action") == "add_policy_period" else AssetPolicyPeriodForm(asset=asset, instance=AssetPolicyPeriod(asset=asset))
    endorsement_form = form if request.method == "POST" and request.POST.get("action") == "add_endorsement" else AssetPolicyEndorsementForm(asset=asset)

    return render(request, "assets/asset_detail.html", {
        "asset": asset,
        "valuations": asset.valuations.select_related("created_by", "approved_by").all(),
        "policy_periods": asset.policy_periods.select_related("insurer", "contract", "created_by", "approved_by").prefetch_related("endorsements").all(),
        "can_manage": can_manage,
        "valuation_form": valuation_form,
        "policy_period_form": policy_period_form,
        "endorsement_form": endorsement_form,
    })


@login_required
def asset_update(request, pk):
    asset = get_object_or_404(_asset_scope(request.user), pk=pk)
    if not _can_manage_asset(request.user, asset):
        raise PermissionDenied("ویرایش دارایی فقط برای کارشناس دارای انتصاب در رشته مرتبط مجاز است.")
    if request.method == "POST":
        form = InsuredAssetForm(request.POST, user=request.user, instance=asset)
        if form.is_valid():
            with transaction.atomic():
                before = {
                    "name": asset.name,
                    "insured_value": str(asset.insured_value),
                    "insurer_id": asset.insurer_id,
                    "contract_id": asset.contract_id,
                    "is_active": asset.is_active,
                }
                updated = form.save()
                if updated.asset_type == InsuredAsset.Type.VEHICLE:
                    try:
                        vehicle = Vehicle.objects.get(asset=updated)
                    except Vehicle.DoesNotExist:
                        vehicle = Vehicle(asset=updated)
                    vehicle.plate_number = form.cleaned_data["plate_number"]
                    vehicle.vin = form.cleaned_data.get("vin", "")
                    vehicle.engine_number = form.cleaned_data.get("engine_number", "")
                    vehicle.make = form.cleaned_data.get("make", "")
                    vehicle.model_name = form.cleaned_data.get("model_name", "")
                    vehicle.model_year = form.cleaned_data.get("model_year")
                    vehicle.save()
                record_event(
                    actor=request.user,
                    action="insured_asset_updated",
                    obj=updated,
                    summary=f"دارایی بروزرسانی شد: {updated.asset_code}",
                    before_data=before,
                    after_data={
                        "name": updated.name,
                        "insured_value": str(updated.insured_value),
                        "insurer_id": updated.insurer_id,
                        "contract_id": updated.contract_id,
                        "is_active": updated.is_active,
                    },
                    request=request,
                )
            messages.success(request, "اطلاعات دارایی به‌روزرسانی شد.")
            return redirect("asset_detail", pk=asset.pk)
    else:
        form = InsuredAssetForm(user=request.user, instance=asset)
    return render(request, "assets/asset_form.html", {
        "form": form,
        "asset": asset,
        "is_update": True,
    })



@login_required
def asset_endorsement_download(request, pk):
    endorsement = get_object_or_404(
        AssetPolicyEndorsement.objects.select_related("policy_period__asset"),
        pk=pk,
    )
    asset = get_object_or_404(_asset_scope(request.user), pk=endorsement.policy_period.asset_id)
    if not endorsement.document:
        raise Http404("فایل الحاقیه در دسترس نیست.")
    try:
        handle = endorsement.document.open("rb")
    except (OSError, ValueError):
        raise Http404("فایل الحاقیه در دسترس نیست.")
    filename = get_valid_filename(Path(endorsement.document.name).name) or f"asset-endorsement-{endorsement.pk}"
    record_event(
        actor=request.user,
        action="asset_policy_endorsement_downloaded",
        obj=asset,
        summary=f"دریافت فایل الحاقیه {endorsement.endorsement_number} دارایی {asset.asset_code}",
        after_data={"endorsement_id": endorsement.pk, "policy_period_id": endorsement.policy_period_id},
        request=request,
    )
    return FileResponse(handle, as_attachment=True, filename=filename)
