from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect
from .models import InternalTask
from .forms import InternalTaskForm
from auditlog.models import AuditEvent

@login_required
def task_list(request):
    tasks = InternalTask.objects.filter(assignees=request.user) | InternalTask.objects.filter(created_by=request.user)
    return render(request, "tasks/task_list.html", {"tasks": tasks.distinct()})

@login_required
def task_create(request):
    if request.user.role not in {"system_admin", "department_head", "insurance_specialist"} and not request.user.is_superuser:
        raise PermissionDenied
    if request.method == "POST":
        form = InternalTaskForm(request.POST)
        if form.is_valid():
            task = form.save(commit=False)
            task.created_by = request.user
            task.save()
            form.save_m2m()
            AuditEvent.objects.create(actor=request.user, action="internal_task_created", object_type="InternalTask", object_id=str(task.pk), summary=task.title)
            messages.success(request, "وظیفه ثبت شد.")
            return redirect("task_list")
    else:
        form = InternalTaskForm()
    return render(request, "tasks/task_form.html", {"form": form})

@login_required
def task_update(request, pk):
    task = InternalTask.objects.filter(pk=pk).filter(assignees=request.user).first()
    if task is None and request.user.role in {"system_admin", "department_head"}:
        task = InternalTask.objects.filter(pk=pk).first()
    if task is None:
        raise PermissionDenied
    if request.method == "POST":
        status = request.POST.get("status")
        if status in dict(InternalTask.Status.choices):
            task.status = status
            task.save(update_fields=["status", "updated_at"])
            AuditEvent.objects.create(actor=request.user, action="internal_task_status_updated", object_type="InternalTask", object_id=str(task.pk), summary=status)
            messages.success(request, "وضعیت وظیفه تغییر کرد.")
            return redirect("task_list")
    return render(request, "tasks/task_update.html", {"task": task})
