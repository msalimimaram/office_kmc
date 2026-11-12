from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from accounts.access import has_global_access, is_unit_manager
from accounts.models import PositionAssignment, UserNotification, User
from auditlog.models import AuditEvent
from .forms import InternalTaskForm, _manager_scope
from .models import InternalTask, TaskEvent


TASK_TRANSITIONS = {
    InternalTask.Status.OPEN: {InternalTask.Status.IN_PROGRESS, InternalTask.Status.CANCELLED},
    InternalTask.Status.IN_PROGRESS: {InternalTask.Status.WAITING, InternalTask.Status.DONE, InternalTask.Status.CANCELLED},
    InternalTask.Status.WAITING: {InternalTask.Status.IN_PROGRESS, InternalTask.Status.CANCELLED},
    InternalTask.Status.DONE: set(),
    InternalTask.Status.CANCELLED: set(),
}


def _active_positions(user):
    today = timezone.localdate()
    return PositionAssignment.objects.filter(
        user=user, is_active=True, valid_from__lte=today,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today)).select_related("position", "unit")


def _can_manage_tasks(user):
    return has_global_access(user) or is_unit_manager(user)


def _visible_tasks(user):
    qs = InternalTask.objects.select_related("created_by", "related_request").prefetch_related("assignees")
    if has_global_access(user):
        return qs

    scope = _manager_scope(user)
    if scope is None:
        return qs
    subordinate_ids = User.objects.filter(scope).values("pk")
    return qs.filter(
        Q(assignees=user)
        | Q(created_by=user)
        | Q(assignees__in=subordinate_ids)
        | Q(created_by__in=subordinate_ids)
    ).exclude(
        related_request__is_confidential=True
    ).distinct()


def _notify_task_recipient(task, recipient, actor, *, title, body):
    if (
        not recipient
        or not recipient.is_active
        or recipient.pk == getattr(actor, "pk", None)
        or not _visible_tasks(recipient).filter(pk=task.pk).exists()
    ):
        return
    UserNotification.objects.create(
        recipient=recipient,
        actor=actor,
        title=title,
        body=body,
        target_url=reverse("task_update", args=[task.pk]),
    )


@login_required
def task_list(request):
    page_obj = Paginator(_visible_tasks(request.user).distinct().order_by("-due_at", "-pk"), 25).get_page(request.GET.get("page"))
    return render(request, "tasks/task_list.html", {
        "tasks": page_obj.object_list,
        "page_obj": page_obj,
        "can_create": _can_manage_tasks(request.user),
    })


@login_required
def task_create(request):
    if not _can_manage_tasks(request.user):
        raise PermissionDenied
    if request.method == "POST":
        form = InternalTaskForm(request.POST, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                task = form.save(commit=False)
                task.created_by = request.user
                task.save()
                form.save_m2m()
                TaskEvent.objects.create(
                    task=task, actor=request.user, event_type=TaskEvent.EventType.CREATED,
                    to_value=task.status, note="وظیفه ایجاد شد.",
                )
                TaskEvent.objects.create(
                    task=task, actor=request.user, event_type=TaskEvent.EventType.ASSIGNED,
                    to_value=",".join(str(pk) for pk in task.assignees.values_list("pk", flat=True)),
                    note="مسئولان اولیه وظیفه تعیین شدند.",
                )
                for assignee in task.assignees.select_related():
                    _notify_task_recipient(
                        task,
                        assignee,
                        request.user,
                        title="وظیفه جدید به شما واگذار شد",
                        body=f"وظیفه «{task.title}» برای اقدام به شما تخصیص داده شد.",
                    )
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
    task = get_object_or_404(_visible_tasks(request.user), pk=pk)
    is_manager = _can_manage_tasks(request.user)
    if not is_manager and not task.assignees.filter(pk=request.user.pk).exists():
        raise PermissionDenied

    if request.method == "POST":
        status = request.POST.get("status")
        note = request.POST.get("note", "").strip()[:4000]
        if status not in dict(InternalTask.Status.choices):
            raise PermissionDenied
        with transaction.atomic():
            locked = InternalTask.objects.select_for_update().get(pk=task.pk)
            if not is_manager and not locked.assignees.filter(pk=request.user.pk).exists():
                raise PermissionDenied
            previous = locked.status
            if status != previous and status not in TASK_TRANSITIONS.get(previous, set()):
                messages.error(request, "این تغییر وضعیت با گردش کار وظیفه سازگار نیست.")
                return redirect("task_update", pk=locked.pk)
            action_occurred = status != previous or bool(note)
            if status != previous:
                locked.status = status
                locked.save(update_fields=["status", "updated_at"])
                TaskEvent.objects.create(
                    task=locked, actor=request.user, event_type=TaskEvent.EventType.STATUS,
                    from_value=previous, to_value=status, note=note,
                )
                AuditEvent.objects.create(
                    actor=request.user, action="internal_task_status_updated", object_type="InternalTask",
                    object_id=str(locked.pk), summary=f"وضعیت از {previous} به {status} تغییر کرد",
                )
                _notify_task_recipient(
                    locked,
                    locked.created_by,
                    request.user,
                    title="وضعیت وظیفه به‌روزرسانی شد",
                    body=f"وضعیت وظیفه «{locked.title}» به «{locked.get_status_display()}» تغییر کرد.",
                )
            elif note:
                TaskEvent.objects.create(
                    task=locked, actor=request.user, event_type=TaskEvent.EventType.COMMENT, note=note,
                )
            if action_occurred and not locked.events.filter(
                event_type=TaskEvent.EventType.FIRST_ACTION,
                actor=request.user,
            ).exists():
                TaskEvent.objects.create(
                    task=locked,
                    actor=request.user,
                    event_type=TaskEvent.EventType.FIRST_ACTION,
                    note="اولین اقدام واقعی روی وظیفه ثبت شد.",
                )
        messages.success(request, "اقدام وظیفه ثبت شد.")
        return redirect("task_list")

    with transaction.atomic():
        locked = InternalTask.objects.select_for_update().get(pk=task.pk)
        if not locked.events.filter(
            event_type=TaskEvent.EventType.FIRST_VIEWED,
            actor=request.user,
        ).exists():
            TaskEvent.objects.create(
                task=locked,
                actor=request.user,
                event_type=TaskEvent.EventType.FIRST_VIEWED,
                note="اولین مشاهده صفحه وظیفه ثبت شد.",
            )
    task.refresh_from_db()
    return render(request, "tasks/task_update.html", {
        "task": task,
        "events": task.events.select_related("actor"),
    })
