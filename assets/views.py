from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Q

from auditlog.models import AuditEvent
from core.permissions import PRIVILEGED
from .forms import InsuredAssetForm
from .models import InsuredAsset, Vehicle

STAFF_ROLES = PRIVILEGED | {"insurance_specialist", "auditor"}
EDIT_ROLES = PRIVILEGED | {"insurance_specialist"}


def _asset_scope(user):
    qs = InsuredAsset.objects.select_related("company", "insurer", "contract", "created_by").prefetch_related("vehicle_details")
    if user.is_superuser or user.role in STAFF_ROLES:
        return qs
    if user.role == "insurer":
        return qs.filter(insurer_id=user.insurer_id) if user.insurer_id else qs.none()
    if user.role in {"subsidiary_rep", "finance", "legal"} and user.company_id:
        return qs.filter(company_id=user.company_id)
    return qs.none()


@login_required
def asset_list(request):
    assets = _asset_scope(request.user)
    query = request.GET.get("q", "").strip()[:100]
    asset_type = request.GET.get("type", "").strip()
    if query:
        assets = assets.filter(
            Q(asset_code__icontains=query) | Q(name__icontains=query) |
            Q(policy_number__icontains=query) | Q(company__name__icontains=query) |
            Q(vehicle_details__plate_number__icontains=query)
        ).distinct()
    if asset_type in dict(InsuredAsset.Type.choices):
        assets = assets.filter(asset_type=asset_type)
    page_obj = Paginator(assets.order_by("name", "pk"), 25).get_page(request.GET.get("page"))
    return render(request, "assets/asset_list.html", {
        "assets": page_obj.object_list, "page_obj": page_obj, "search_query": query, "selected_type": asset_type,
        "asset_types": InsuredAsset.Type.choices,
        "can_create": request.user.is_superuser or request.user.role in EDIT_ROLES | {"subsidiary_rep"},
    })


@login_required
def asset_create(request):
    if not (request.user.is_superuser or request.user.role in EDIT_ROLES | {"subsidiary_rep"}):
        raise PermissionDenied
    if request.user.role == "subsidiary_rep" and not request.user.company_id:
        raise PermissionDenied
    if request.method == "POST":
        form = InsuredAssetForm(request.POST, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                asset = form.save(commit=False)
                asset.created_by = request.user
                if request.user.role == "subsidiary_rep":
                    asset.company = request.user.company
                asset.save()
                if asset.asset_type == InsuredAsset.Type.VEHICLE:
                    Vehicle.objects.create(
                        asset=asset, plate_number=form.cleaned_data["plate_number"],
                        vin=form.cleaned_data.get("vin", ""), engine_number=form.cleaned_data.get("engine_number", ""),
                        make=form.cleaned_data.get("make", ""), model_name=form.cleaned_data.get("model_name", ""),
                        model_year=form.cleaned_data.get("model_year"),
                    )
                AuditEvent.objects.create(
                    actor=request.user, action="insured_asset_created", object_type="InsuredAsset",
                    object_id=str(asset.pk), summary=f"دارایی ثبت شد: {asset.asset_code}",
                )
            messages.success(request, "دارایی بیمه‌شده با موفقیت ثبت شد.")
            return redirect("asset_list")
    else:
        form = InsuredAssetForm(user=request.user)
    return render(request, "assets/asset_form.html", {"form": form})
