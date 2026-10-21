from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from claims.models import Claim
from requests_portal.models import ServiceRequest
from tasks.models import InternalTask
from core.permissions import scoped_claims_for, scoped_requests_for

@login_required
def home(request):
    claims = scoped_claims_for(request.user)
    requests = scoped_requests_for(request.user)
    tasks = InternalTask.objects.filter(assignees=request.user) | InternalTask.objects.filter(created_by=request.user)
    context = {
        "claim_count": claims.count(),
        "request_count": requests.count(),
        "open_request_count": requests.exclude(status__in=["closed", "completed", "rejected"]).count(),
        "task_count": tasks.distinct().exclude(status__in=["done", "cancelled"]).count(),
        "recent_claims": claims[:8],
        "recent_requests": requests[:8],
    }
    return render(request, "dashboard/home.html", context)
