# Access Control & Workflow Verification Matrix

**Status:** Engineering acceptance specification; execution evidence is tracked separately.  
**Repository:** `msalimimaram/office_kmc`  
**Baseline branch:** `main`  
**Created:** 2026-11-20

This document is the acceptance contract for role-based visibility and authorization. A feature is not complete merely because its URL is hidden or a button is absent. The UI must hide unavailable capabilities, and the server must independently deny direct requests and mutations.

## 1. Non-negotiable authorization rules

1. **Deny by default.** A missing, inactive, expired, future-dated, revoked, malformed, or out-of-scope assignment grants no operational capability.
2. **One authorization source.** New authorization decisions use validated `RoleAssignment`, `PositionAssignment`, current workflow ownership, and explicit scope. Legacy `User.role` is compatibility-only and must never override assignment history.
3. **Technical superuser is not a business role.** `is_superuser` / `is_staff` alone grants no insurance business capability.
4. **UI and server are both required.** Hide navigation, dashboard cards, actions, and links for unavailable capabilities. Direct URL, POST, API, object ID, download, and alternate route attempts must still be denied server-side.
5. **Scope is part of permission.** Company, insurer, insurance line, organizational unit, position, validity interval, current assignee, delegation, and workflow stage are independently checked where applicable.
6. **Multiple roles are additive, not substitutive.** A user sees the union of capabilities from all currently valid roles, but every record remains constrained by the scope of the role that provides access. Removing one role must remove only the capabilities that depended on it.
7. **No stale authorization.** Re-evaluate after login, role/position changes, company-context changes, delegation changes, expiry, and account deactivation. Cached UI must not preserve server authority.
8. **Confidentiality is stricter than visibility.** Medical content, internal assessments, private notes, national IDs, bank details, and attachments require separate field-level authorization and safe notification rendering.
9. **No privilege escalation through history.** Former assignees may receive only explicitly approved read-only history access; they cannot act because they once owned a case or appear in legacy `assigned_to`.
10. **Every decision is auditable.** Grants, approvals, changes, expiry/revocation, denied sensitive operations, workflow actions, and administrative overrides record actor, target, scope, reason, timestamp, and correlation/object reference without logging secrets.

## 2. Operational roles

| Role code | Display name | Intended capability boundary |
|---|---|---|
| `system_admin` | مدیر سامانه | Technical/business administration explicitly assigned; not automatic ownership of every business case |
| `department_head` | رئیس اداره بیمه | Department-wide oversight, approvals and final decisions allowed by each workflow |
| `insurance_specialist` | کارشناس اداره بیمه | Operational processing within assigned insurance line/unit and current case assignment |
| `subsidiary_rep` | نماینده شرکت تابعه | Own company and approved insurance-line scope; cannot finally close general insurer-facing requests |
| `insurer_representative` | نماینده شرکت بیمه‌گر | Own insurer scope and referred work; cannot perform department-only final closure |
| `insured_person` | بیمه‌شده | Own profile, own requests/claims and explicitly authorized personal records |

Finance, Legal and Auditor are not operational roles and must not be reintroduced as role choices or hidden aliases.

## 3. UI capability matrix

The following is the intended first-level navigation matrix. It is not a grant of object-level access; each module must apply its own row-level and action-level rules.

| Navigation / capability | System Admin | Department Head | Specialist | Subsidiary Rep | Insurer Rep | Insured |
|---|---:|---:|---:|---:|---:|---:|
| Dashboard | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Notifications | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Workflow inbox | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Delegation inbox | ✓ | ✓ | ✓* | ✓* | ✓* | — |
| Delegation management | ✓ | ✓ | — | — | — | — |
| Tasks | ✓ | ✓ | ✓ | — | — | — |
| People / insured register | ✓ | ✓ | ✓ | ✓ | — | own only |
| Person information correction | ✓ | ✓ | ✓ | ✓ (company stage only) | assigned insurer stage only | own request |
| Service requests | ✓ | ✓ | ✓ | ✓ (company scope) | referred/assigned scope | own only |
| Claims | ✓ | ✓ | ✓ (line/scope) | ✓ (company/line) | ✓ (insurer/assigned) | own only |
| Contracts | ✓ | ✓ | ✓ | ✓ (company scope) | ✓ (insurer scope) | — |
| Assets | ✓ | ✓ | ✓ | ✓ (company/line scope) | ✓ (insurer scope) | own assets only |
| Imports | ✓ | ✓ | ✓ | — | ✓ (insurer scope) | — |
| Management reports | ✓ | ✓ | ✓ (permitted reports) | — | — | — |
| Correspondence | ✓ | ✓ | ✓ | ✓ (company scope) | ✓ (insurer scope) | — |
| Documents / circulars | ✓ | ✓ | ✓ | ✓ (authorized company documents) | ✓ (authorized insurer documents) | ✓ (published/eligible documents) |
| Company leadership titles | ✓ | — | — | ✓ (own company) | — | — |
| Announcements | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

`*` Delegation inbox appears only when the user has an applicable delegation history or a permitted global role. A visible read-only historical inbox does not imply an actionable assignment.

**Implementation note:** The current `accounts/context_processors.py` exposes an `assets` navigation flag to insured users, and `assets/views.py::_asset_scope` limits those users to assets linked to their own person record. The dashboard's `_capabilities_for` currently does not include `assets` for the insured role, so the sidebar and dashboard capability sets are inconsistent and require a regression fix. Compare this matrix with `accounts/context_processors.py`, `dashboard/views.py::_capabilities_for`, `templates/base.html`, module views, and URL patterns. A single capability registry should eventually drive navigation and dashboard visibility; the server remains the enforcement authority.

## 4. Required tests for every capability

For each capability row above, implement and execute all applicable cases:

- V01: Authorized role sees the navigation link and dashboard card.
- V02: User without the capability does not receive the link, card, action button, or sensitive count.
- V03: User without the capability receives HTTP 403 (or deliberate 404 for object-existence privacy) on direct GET.
- V04: User without the capability receives HTTP 403 on direct POST/PUT/PATCH/DELETE; no database mutation occurs.
- V05: Anonymous user is redirected to login; login does not imply business access.
- V06: Inactive account is denied even if assignments remain in the database.
- V07: Future-dated assignment is denied before its start date.
- V08: Expired assignment is denied after its end date.
- V09: Revoked/inactive assignment is denied immediately.
- V10: Legacy role fallback is denied when any assignment/position history exists but no current valid assignment remains.
- V11: Technical superuser without an explicit business assignment is denied business actions.
- V12: Out-of-company, out-of-insurer, out-of-line and out-of-unit access is denied.
- V13: A multi-role user receives the union of valid capabilities, but cannot use one role to escape another role's scope.
- V14: Removing one role removes only its derived navigation/actions on the next request/session refresh.
- V15: Changing active company context cannot expose another company's records.
- V16: A stale session, bookmark, crafted object ID, or guessed URL does not bypass current server authorization.
- V17: File preview/download and exports enforce the same object and field scope as the parent record.
- V18: Sensitive fields and notification/email content are redacted for unauthorized viewers.
- V19: Denials and administrative grants/revocations produce the expected audit events without secrets.
- V20: Concurrent role expiry/revocation and workflow action cannot allow a stale permission to commit.

For each test, assert both response status and absence of side effects. For denied POSTs, compare database state and audit events. For allowed requests, assert the exact scoped records, not merely HTTP 200.

## 5. Workflow-by-workflow authorization test catalogue

All 19 definitions must have a dedicated test class or parameterized scenario set. For each workflow test: start, each transition, valid actor, invalid role, wrong company/insurer/line, wrong current owner, wrong position/unit, expired grant, missing note/required data, duplicate/replay submission, final closure, audit event, notification redaction, SLA continuity, and transaction rollback on failure.

### 5.1 Service-request workflows (10)

| Code | Workflow | Required authorization assertions |
|---|---|---|
| `medical_assistance` | کمک‌هزینه درمان | Health line; confidential medical payload only to applicant/current authorized handler; no medical detail in general notifications |
| `anonymous_plan` | طرح ناشناس | Health scope; anonymous identity and content not disclosed to unrelated roles |
| `excess_coverage` | پوشش مازاد | Health/company scope; applicant ownership and approval stage enforced |
| `identity_change` | اصلاح مشخصات هویتی | Applicant → company rep → specialist/insurer as defined; identity fields masked outside authorized stage |
| `iban_change` | اصلاح شماره شبا | No direct IBAN edit endpoint; workflow-only update with verification and audit |
| `add_coverage` | افزودن پوشش | Eligible company/insured scope; authorized approver; no self-approval |
| `remove_coverage` | حذف پوشش | Eligibility, effective date, company authority and final approval enforced |
| `document_request` | درخواست سند | Applicant access only to own response/document; download permissions tested |
| `base_insurance_waiver` | معافیت بیمه پایه | Health scope; required evidence; approval and sensitive document restrictions |
| `other` | سایر درخواست‌ها | Explicit routing and role policy; no permissive catch-all transition |

General request rules: company representative may refer but cannot perform final closure; insurer representative cannot close; Department Head/System Admin closure is limited to transitions explicitly allowed by the workflow. SLA does not pause while waiting for insurer follow-up. First-view and first-action timestamps are tested independently.

### 5.2 Domain workflows (9)

| Code | Workflow | Required authorization assertions |
|---|---|---|
| `claim_review` | بررسی خسارت | Specialist line/insurer/company scope; assessment before decision; final decision authority |
| `claim_objection` | اعتراض خسارت | Specialist response required; Department Head/System Admin final closure |
| `contract_approval` | تأیید قرارداد | Pending approval; Department Head/System Admin only; maker-checker separation |
| `contract_termination` | خاتمه قرارداد | Authorized approval and effective date; no self-approval |
| `person_change` | اصلاح اطلاعات شخص | Company → insurer → company; company rep closes only the final company-review stage for this workflow |
| `asset_valuation_approval` | تأیید ارزیابی دارایی | Department Head/System Admin approval; snapshot immutable after approval |
| `asset_policy_approval` | تأیید بیمه‌نامه دارایی | Department Head/System Admin approval; insurer/company scope |
| `asset_endorsement_approval` | تأیید الحاقیه دارایی | Department Head/System Admin approval; version/snapshot and audit integrity |
| `management_report_approval` | تأیید گزارش مدیریتی | Supervisor/responsible/head routing; only authorized final approver publishes |

## 6. Cross-cutting security and data-integrity scenarios

- IDOR matrix across every detail, edit, delete, action, attachment, export and history endpoint using at least two companies, two insurers, two lines and two organizational units.
- Company representative: same-company employee/dependent validation; no more than three concurrent distinct representatives; line/category scope; cross-company exception requires System Admin approval, reason, permitted companies/lines and bounded validity.
- Insurer representative: insurer-only scope; no access to another insurer's contracts, claims, correspondence or attachments.
- Supervisor: read-only oversight of eligible subordinates; cannot act as the subordinate or acquire ownership.
- Position assignments: valid dates, active unit/position, ancestry/descendant route scope, same-unit and line-wide scope.
- Delegation: valid delegator/delegate authority, no self-delegation, no scope widening, expiry/revocation, immutable event history, and safe reassignment on revoke.
- Confidential medical records: no content leakage in list, dashboard, search, notification, export, logs, error pages or attachment metadata.
- Workflow engine: transition replay/idempotency, race conditions, lock/version handling, immutable published definitions, event history and SLA clock.
- Account lifecycle: forced password change, deactivation, role change, session invalidation/re-evaluation, password reset, MFA and recovery controls.
- Audit integrity: actor and approver independence for privileged operations; no update/delete/bulk bypass of authorization history.

## 7. Test execution layers and evidence

| Layer | Minimum evidence |
|---|---|
| Model/service unit | role validity, scope resolution, policy decisions, transition guards, state changes |
| View integration | GET/POST status, response redaction, exact queryset scope, no side effects on denial |
| Template/UI | rendered navigation, cards, buttons, disabled/hidden controls by role and multiple-role union |
| API contract | authentication, permissions, validation, pagination, object scope, error semantics |
| Workflow integration | every definition, every transition, each actor/negative actor, event, notification, SLA |
| Security regression | IDOR, privilege escalation, stale session, direct URL, file access, sensitive data leakage |
| Database/concurrency | transaction rollback, uniqueness, concurrent transition, stale grant/revocation |
| End-to-end UAT | realistic journeys for all six roles using seeded non-production identities |

Every evidence entry records: exact command, commit SHA, Python/Django/database versions, test count, pass/fail/error/skip counts, duration, and artifact/log location. A test that was merely written is **NOT RUN**, not PASS. A skipped or blocked test is not complete.

## 8. Release gate

The access-control workstream cannot be marked complete until:

- Every row in the UI capability matrix has a verified positive and negative visibility test.
- Every capability has direct-URL and mutation-denial tests.
- All 19 workflow definitions and all transitions have positive and negative authorization tests.
- Cross-company, cross-insurer, cross-line, position, delegation, expiry/revocation and multiple-role cases pass.
- Confidential fields and file endpoints pass leakage/IDOR checks.
- Full Django suite passes on the exact commit SHA containing the changes.
- Staging UAT is signed off by the business owner for all six operational roles.

Until then: **ACCESS CONTROL RELEASE GATE = OPEN; PRODUCTION = NO-GO.**
