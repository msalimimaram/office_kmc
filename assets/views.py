from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
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
        employed_person_ids = PersonEmployment.objects.filter(
            company_id__in=company_ids
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



@login_required
def asset_detail(request, pk):
    asset = get_object_or_404(_asset_scope(request.user), pk=pk)
    can_manage = has_role(request.user, RoleAssignment.Role.INSURANCE_SPECIALIST)
    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied("ثبت سوابق دارایی فقط برای کارشناس رشته مربوط مجاز است.")
        action = request.POST.get("action", "").strip()
        if action == "add_valuation":
            form = AssetValuationForm(request.POST)
            if form.is_valid():
                with transaction.atomic():
                    item = form.save(commit=False)
                    item.asset = asset
                    item.created_by = request.user
                    item.save()
                    record_event(
                        actor=request.user,
                        action="asset_valuation_created",
                        obj=asset,
                        summary=f"سابقه ارزیابی دارایی {asset.asset_code} ثبت شد.",
                        after_data={
                            "valuation_id": item.pk,
                            "valuation_date": item.valuation_date.isoformat() if item.valuation_date else None,
                            "market_value": str(item.market_value),
                            "insured_value": str(item.insured_value),
                            "method": item.method,
                        },
                        request=request,
                    )
                messages.success(request, "سابقه ارزیابی ثبت شد.")
                return redirect("asset_detail", pk=asset.pk)
        elif action == "add_policy_period":
            form = AssetPolicyPeriodForm(
                request.POST,
                asset=asset,
                instance=AssetPolicyPeriod(asset=asset),
            )
            if form.is_valid():
                with transaction.atomic():
                    item = form.save(commit=False)
                    item.asset = asset
                    item.created_by = request.user
                    item.status = AssetPolicyPeriod.Status.DRAFT
                    item.save()
                    record_event(
                        actor=request.user,
                        action="asset_policy_period_created",
                        obj=asset,
                        summary=f"دوره بیمه‌نامه {item.policy_number} به‌صورت پیش‌نویس ثبت شد.",
                        after_data={
                            "policy_period_id": item.pk,
                            "insurer_id": item.insurer_id,
                            "contract_id": item.contract_id,
                            "policy_number": item.policy_number,
                            "status": item.status,
                        },
                        request=request,
                    )
                messages.success(request, "دوره بیمه‌نامه در وضعیت پیش‌نویس ثبت شد.")
                return redirect("asset_detail", pk=asset.pk)
        elif action == "add_endorsement":
            form = AssetPolicyEndorsementForm(request.POST, request.FILES, asset=asset)
            if form.is_valid():
                upload = form.cleaned_data["document"]
                file_error = validate_uploaded_file(upload, max_size=20 * 1024 * 1024)
                if file_error:
                    form.add_error("document", file_error)
                else:
                    with transaction.atomic():
                        item = form.save(commit=False)
                        item.created_by = request.user
                        item.save()
                        record_event(
                            actor=request.user,
                            action="asset_policy_endorsement_created",
                            obj=asset,
                            summary=f"الحاقیه {item.endorsement_number} ثبت شد.",
                            after_data={
                                "endorsement_id": item.pk,
                                "policy_period_id": item.policy_period_id,
                                "endorsement_number": item.endorsement_number,
                                "approved_by_id": item.approved_by_id,
                            },
                            request=request,
                        )
                    messages.success(request, "الحاقیه ثبت شد؛ تا تأیید مرجع مجاز، تأییدنشده باقی می‌ماند.")
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
    if not has_role(request.user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        raise PermissionDenied("ویرایش دارایی فقط برای کارشناس رشته مربوط مجاز است.")
    asset = get_object_or_404(_asset_scope(request.user), pk=pk)
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
