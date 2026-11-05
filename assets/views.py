from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import models, transaction
from django.core.paginator import Paginator
from django.shortcuts import render, redirect

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
from .forms import InsuredAssetForm
from .models import InsuredAsset, Vehicle


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
