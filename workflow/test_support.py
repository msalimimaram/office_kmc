"""Test helpers for exercising the production workflow proposal lifecycle.

These helpers create provisional definitions through the production seed command,
then model the Department Head's explicit SLA confirmation before approval.
"""
from django.utils import timezone

from workflow.models import WorkflowDefinition
from workflow.governance import approve_workflow_definition
from core.management.commands.seed_operational_workflows import Command as WorkflowSeedCommand


def seed_and_approve_workflows(*, admin, head, codes):
    WorkflowSeedCommand().handle(created_by=admin.pk, commit_proposals=True)
    for code in codes:
        proposal = WorkflowDefinition.objects.get(
            code=code,
            is_active=False,
            approved_by__isnull=True,
            published_at__isnull=True,
        )
        for step in proposal.steps.filter(is_terminal=False):
            step.sla_minutes = max(step.sla_minutes, 480)
            step.sla_confirmed_by = head
            step.sla_confirmed_at = timezone.now()
            step.save(update_fields=[
                "sla_minutes", "sla_confirmed_by", "sla_confirmed_at",
            ])
        approve_workflow_definition(definition_id=proposal.pk, approver=head)
