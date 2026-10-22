from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction

from .models import InternalTask
from .forms import InternalTaskForm
from auditlog.models import AuditEvent

MANAGERS = {"system_admin", "department_head", "insurance_specialist"}
TASK_TRANSITIONS = {
    InternalTask.Status.OPEN: {InternalTask.Status.IN_PROGRESS, InternalTask.Status.CANCELLED},
    InternalTask.Status.IN_PROGRESS: {InternalTask.Status.WAITING, InternalTask.Status.DONE, InternalTask.Status.CANCELLED},
    InternalTask.Status.WAITING: {InternalTask.Status.IN_PROGRESS, InternalTask.Status.CANCELLED},
    InternalTask.Status.DONE: set(),
    InternalTask.Status.CANCELLED: set(),
}


@login_required
def task_list(request):
    if request.user.is_superuser or request.user.role in {"system_admin", "department_head"}:
        tasks = InternalTask.objects.all()
    else:
        tasks = InternalTask.objects.filter(assignees=request.user) | InternalTask.objects.filter(created_by=request.user)
    tasks = tasks.distinct().select_related("created_by", "related_request").prefetch_related("assignees").order_by("-due_at", "-pk")
    page_obj = Paginator(tasks, 25).get_page(request.GET.get("page"))
    return render(request, "tasks/task_list.html", {"tasks": page_obj.object_list, "page_obj": page_obj})


@login_required
def task_create(request):
    if request.user.role not in MANAGERS and not request.user.is_superuser:
        raise PermissionDenied
    if request.method == "POST":
        form = InternalTaskForm(request.POST, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                task = form.save(commit=False)
                task.created_by = request.user
                task.save()
                form.save_m2m()
                AuditEvent.objects.create(
                    actor=request.user, action="internal_task_created", object_type="InternalTask",
                    object_id=str(task.pk), summary=task.title,
                )
            messages.success(request, "وظیفه ثبت شد.")
            return redirect("task_list")
    else:
        form = InternalTaskForm(user=request.user)
    return render(request, "tasks/task_form.html", {"form": form})


@login_required
def task_update(request, pk):
    task = get_object_or_404(InternalTask.objects.select_related("created_by"), pk=pk)
    is_manager = request.user.is_superuser or request.user.role in {"system_admin", "department_head"}
    if not is_manager and not task.assignees.filter(pk=request.user.pk).exists():
        raise PermissionDenied
    if request.method == "POST":
        status = request.POST.get("status")
        if status not in dict(InternalTask.Status.choices):
            raise PermissionDenied
        if status != task.status and status not in TASK_TRANSITIONS.get(task.status, set()):
            messages.error(request, "این تغییر وضعیت با گردش کار وظیفه سازگار نیست.")
            return redirect("task_update", pk=task.pk)
        with transaction.atomic():
            previous = task.status
            task.status = status
            task.save(update_fields=["status", "updated_at"])
            AuditEvent.objects.create(
                actor=request.user, action="internal_task_status_updated", object_type="InternalTask",
                object_id=str(task.pk), summary=f"وضعیت از {previous} به {status} تغییر کرد",
            )
        messages.success(request, "وضعیت وظیفه تغییر کرد.")
        return redirect("task_list")
    return render(request, "tasks/task_update.html", {"task": task})
