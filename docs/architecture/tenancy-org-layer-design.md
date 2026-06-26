# Design: Tenancy & Organization Layer

Status: **Draft for review**
Date: 2026-06-25
Related: `docs/vision_audit_062425.md` (Pillar 3 — regulated model lifecycle / PAT), PR #321 (paid Pro)

---

## 1. Problem

The data model has **one** real isolation axis — `user_id` (43 columns across the data
tables) — plus a **half-built, entity-less** `tenant_id` string that exists *only* in the
audit chain (`audit_event.py`). There is no `Organization`, `Team`, `Workspace`,
`Membership`, or `Role` entity anywhere.

"The user **is** the tenant." That is correct and clean for the modes that ship today and
degrades gracefully downward to single-user:

| Mode | Tenancy today | Fit |
|---|---|---|
| OSS local | one implicit `local` user | clean |
| Demo | per-user isolated, ephemeral | clean |
| Pro | per-user isolated, single seat | clean |
| Hybrid | per-user data isolation, per-deployment license | works, conflated |

It **cannot express** any mode where a tenant is more than one user — Team ($200/user),
Site ($1000, RBAC + collaboration), or hybrid multi-seat. The codebase is already reaching
for that world (the entitlements map has a `team` plan with `audit.full`; the audit chain
already carries `tenant_id`) while identity and data have not followed. That split — audit
tenant-aware, identity and data user-only, and nothing defining what a tenant *is* — is the
integrity gap this design closes.

`tenancy_mode` today also **conflates two scopes that genuinely diverge**:

- **data-isolation scope** — what owns a project (always `user_id` today), and
- **licensing/entitlement scope** — what is billed (`user`, or `deployment`, never `org`).

Hybrid is the tell: data is isolated per-user, but the license is per-deployment.

## 2. Goals & non-goals

**Goals**

1. Introduce **one tenancy spine** — `Organization` — that subscription,
   lifecycle, audit, and default data ownership all share.
2. Keep Pro single-seat and OSS local **behaviorally identical** via a personal *org-of-one*.
3. Make Team / Site / hybrid-multi-seat **additive**, not a later migration of 43 tables.
4. Give the orphan audit `tenant_id` a real referent.
5. Make tenant isolation a **single, testable chokepoint**.
6. Preserve a clean path to enterprise hybrid mode where the customer's org/deployment policy
   is authoritative and scientific data may never leave their security boundary.

**Non-goals (deferred — leave the seam, don't build)**

- Full custom RBAC / arbitrary per-resource ACLs (start with a fixed role enum plus a
  workspace/project sharing primitive).
- SSO / SAML / OIDC (sketch the `ExternalIdentity` seam only).
- Cross-org sharing / data exchange.
- Seat-management / billing UI.

## 3. Core principle

> **Ownership moves from user → org/workspace. `user_id` becomes authorship. Access =
> membership role × workspace/project visibility × org plan/policy.**

- Every user has exactly **one personal org** (`kind=personal`), auto-created with the user.
- Data is **owned** by an org (`org_id`) and usually grouped by a workspace/project; it is
  **authored** by a user (`user_id`, retained as `created_by` for provenance — never dropped).
- `Membership(user, org, role)` governs who may act within an org.
- `WorkspaceMembership` or `ProjectAccess` governs who may see shared internal work when the
  org has more than one user. In v1 this can default to one workspace per org, but the column
  and policy seam must exist before enterprise sharing lands.
- Subscription, lifecycle, seats, data-custody policy, egress policy, and audit all key on **org**.

For Pro single-seat and OSS local this is invisible: one user, one personal org, one owner
membership. Multi-member orgs are then purely additive.

## 4. Entity model

New tables (server-owned; `org_id` columns live on the OSS data tables so ownership is
uniform across distributions).

### Principal (actor) — the one actor-model guarantee to lock now

`Membership.user_id`, every data row's `created_by` (`user_id`), the audit actor, and
`TenancyContext.actor` reference a **principal**, and the implementation must **not** assume a
principal is human or has a `ManagedUserAccount`. This is the only actor-model decision that is
essential *now*, because the Phase-1 backfill stamps `created_by` across all 43 tables: if that
path hard-requires a managed account (the login flow already does — "user without managed
account → 503"), non-human identities become a refactor instead of an addition.

No feature work now. The guarantee alone keeps service / instrument / pipeline identities (PAT
auto-ingestion, folder-watch, LIMS push) a later additive `kind` (`human | service`) on the
existing principal record — not a re-model. Build nothing for them yet; just don't foreclose them.

### Organization
```
id            PK
tenant_key    str  unique, stable      # == audit tenant_id; e.g. "org_<ULID>"
name          str
kind          enum(personal, team, site)
status        enum(active, suspended)
created_at, updated_at
```

### OrgMembership
```
id                PK
org_id            FK -> organization (ondelete CASCADE)
user_id           FK -> user         (ondelete CASCADE)
role              enum(owner, admin, member, viewer)
status            enum(active, invited, suspended)
invited_by_user_id  FK -> user (nullable)
created_at
UNIQUE(org_id, user_id)
```

Roles start as a **fixed enum**, with capabilities derived in code (no `Role` table yet):

| Role | Read | Write/compute | Manage members | Billing | Delete org |
|---|---|---|---|---|---|
| owner | ✓ | ✓ | ✓ | ✓ | ✓ |
| admin | ✓ | ✓ | ✓ | – | – |
| member | ✓ | ✓ | – | – | – |
| viewer | ✓ | – | – | – | – |

### Workspace

Workspace is the minimum collaboration boundary inside an org. It prevents the first
enterprise release from becoming "every org member can see every dataset/model forever."

```
Workspace
  id            PK
  org_id        FK -> organization
  name          str
  kind          enum(default, regulated_area, project_area)
  status        enum(active, archived)
  created_by    FK -> user
  created_at, updated_at

WorkspaceMembership
  id
  workspace_id  FK -> workspace
  user_id       FK -> user
  role          enum(admin, editor, viewer)
  UNIQUE(workspace_id, user_id)
```

Incremental rule:

- Personal Pro / OSS: one implicit personal workspace.
- Team/Site/hybrid enterprise v1: one default org workspace plus optional additional
  workspaces when the customer needs internal separation.
- Project-level sharing may start as `project.workspace_id`; arbitrary per-resource ACLs stay
  deferred until real customer workflows demand them.

### Subscription (generalized)

Today: `UserSubscription(user_id)` (Pro/Stripe) **+** `Subscription` via `DeploymentKey`
(hybrid/OEM). Target: subscription attaches to **org**.

```
OrgSubscription
  id, org_id FK (unique)
  plan            enum(none, pro, team, site, ...)
  status          enum(...)
  seat_limit      int            # active memberships must be <= seat_limit
  lifecycle_state enum(active, expired_visible, dark_retained, crypto_shredded)
  current_period_start/end, expired_at, visible_until, dark_started_at, ...
  stripe_customer_id, stripe_subscription_id
  erasure_*  (as today, now org-scoped)
```

- A **personal-org** `OrgSubscription` == today's per-user Pro (seat_limit = 1).
- `DeploymentKey` stays as an **auth credential**, but a deployment **maps to an org**, so
  entitlement resolution has **one** shape: *resolve active org → org subscription → plan*.
- In dedicated enterprise/hybrid deployments, the org/deployment subscription is authoritative.
  A member's personal Pro subscription must not override org policy, security posture, export
  policy, AI policy, or audit entitlement.
- **Lifecycle moves to the org.** `dark_retained` / `crypto_shredded` apply to org-owned
  data; a member's effective access = `org.lifecycle ∈ {active|readable}` **×**
  `membership.status == active`. A lapsed *site* license now has a place to cascade.

### Data custody and erasure

The paid-Pro artifact custody layer is currently user-shaped. Shared enterprise data requires
custody to be scoped to the owner of the data, not merely the actor who created it.

```
ArtifactKey
  id
  org_id          FK -> organization
  workspace_id    FK -> workspace nullable
  key_scope       enum(org, workspace, personal_user)
  key_version
  provider        enum(local_wrapped, vault_kv_v2, openbao_kv_v2, cloud_kms)
  status          enum(active, retired, destroyed)
```

Rules:

- Personal orgs may continue to use personal-user semantics as a compatibility layer.
- Org-shared datasets, models, reports, and audit evidence are encrypted under org/workspace
  custody keys, not under the individual author's user key.
- User departure or user PII erasure must not crypto-shred org-owned scientific artifacts.
- Org erasure is a separate administrative/legal action and may destroy org/workspace custody
  keys according to the customer's contract and retention obligations.
- Hybrid regulated custody mode should support customer-controlled Vault/OpenBao/cloud-KMS
  providers, with local wrapped keys remaining a development/self-managed fallback.

### Org policy and egress

Hybrid enterprise needs org-admin policy above user preference:

```
OrgSecurityPolicy
  org_id
  allow_llm_context
  allowed_llm_providers
  allow_spectrasherpa_sync
  allow_export
  allow_external_library_queries
  require_byok
  require_local_only_artifacts
  audit_policy_overrides
```

Effective egress = org policy **AND** workspace/project policy **AND** user preference. User
preference can be more restrictive, but it cannot override a stricter org policy. Every override
or attempted blocked egress should be auditable in enterprise/hybrid mode.

### Audit unification
`audit_event.tenant_id := organization.tenant_key`. The hash chain becomes **per-org** for new
events.

Migration caution: existing chained audit rows cannot be rewritten in place without invalidating
their HMAC chain. Backfill must either:

- leave legacy chains under their historical tenant id and create a tenant-alias table that maps
  old tenant ids to the new org; or
- emit a signed chain-transition event, start a new per-org chain head, and keep the old chain
  verifiable as an immutable predecessor.

Do not mutate chained `tenant_id` values unless the chain is intentionally reissued with a
documented auditor-facing migration record.

### Deferred seam (do not build now)
```
ExternalIdentity  # SSO later
  user_id, provider, subject, UNIQUE(provider, subject)
```

## 5. Data ownership: adding `org_id`

Add `org_id` (owner) to every table currently scoped by `user_id`: `project`, `experiment`,
`workflow`, `execution_run`, `model_artifact`, `calibration*`, `cal_model`, `doe_config`,
`factor_definition`, `batch_prediction`, `folder_watch`, `background_job`, `conversation`,
`advisor_memory*`, `project_script`, `workflow_{folder,tag,template,version}`, `sample`,
`mixture`, `doe_config`, …

- `org_id` = **owner** (isolation scope); `user_id` = **author** (retained).
- **Denormalize** `org_id` onto the high-traffic leaf tables that are queried directly
  (`experiment_file`, `execution_run`, `model_artifact`) for index efficiency and
  defense-in-depth; pure children always loaded via a parent (`workflow_node/edge`,
  `exp_version`) can inherit ownership through the parent. *(Decision point — see §10.)*

## 6. Access resolution

```
request → actor (User, via CurrentActor)
        → TenancyContext(deployment, org, workspace, actor, policy)
        → OrgMembership(role)
        → WorkspaceMembership / ProjectAccess
        → capability check
```

- **Single-seat Pro / OSS local:** active org = the user's personal org, implicit (no header).
- **Multi-member:** explicit selection. Recommended incremental path: header `X-Org-Id`
  (default = personal org), membership validated server-side. Path-scoping
  (`/orgs/{id}/...`) is cleaner long-term but a larger route refactor. *(Decision point.)*

New dependency `require_tenancy_context(user) -> TenancyContext` (403 if not an active member).
The existing ownership helpers change from `(id, user_id, session)` to `(id, tenancy_ctx,
session)`, scoping by `org_id` plus workspace/project visibility and checking role/policy for
writes. **This becomes the one chokepoint where tenant isolation is enforced and tested** —
replacing 43 ad-hoc `user_id` filters with a default-deny, org-scoped guard.

`TenancyContext` should be persisted or passed explicitly into non-request work:

- background jobs
- folder watches
- WebSocket workflow execution
- durable artifact writes
- audit events
- Advisor/LLM calls

Do not rely on `X-Org-Id` once work leaves the HTTP request lifecycle.

## 7. Config consolidation (second integrity fix)

Replace the loosely-coupled `APP_MODE × SITE_PROFILE` env axes (which today **fail open** —
unknown profile → `pro`) with **one validated `DeploymentProfile`** resolved at boot:

- An allowlisted descriptor: `(security_mode, product_profile, tenancy_granularity, capabilities)`.
- **Fail closed:** unknown/empty → most restrictive, never `pro`.
- Tenancy granularity (`single_user | per_user | per_org`) is *derived* from the profile,
  not a separate hand-maintained enum.

## 8. Migration plan (phased, reversible)

**Phase 0 — additive schema (no behavior change).**
Create `organization`, `org_membership`, `workspace`, default workspace rows, and the custody /
policy seams; add nullable `org_id` and `workspace_id` where appropriate; add `tenant_key`.

**Phase 1 — backfill (the one-way door; do this early, while user counts are small).**
For each user: create a personal `Organization`, an owner `OrgMembership`, a default personal
workspace, set `org_id = personal_org` and `workspace_id = personal_workspace` on their rows,
map `UserSubscription → OrgSubscription(personal_org)`, and create an audit tenant alias or
transition record. Idempotent (one personal org per user).

**Phase 2 — enforce ownership.**
`org_id` NOT NULL + FK + composite indexes; switch `require_*`/list queries to org/workspace
scoping (+ role/policy for writes); `ProAccessPolicyMiddleware` and entitlement gates resolve
the **org** subscription / plan / lifecycle. `user_id` stays as `created_by`.

**Phase 3 — multi-member features (post-launch, incremental).**
Invitations, seat enforcement, role management, Team/Site plans, org-scoped lifecycle UI,
workspace/project sharing UI, org security/egress policy UI, and enterprise/hybrid custody
provider configuration.

Rollback is clean through Phase 1; Phase 2 (`NOT NULL`) is the commit point.

## 9. Mode behavior after the change

| Mode | Org model | Members | Subscription scope | Isolation |
|---|---|---|---|---|
| OSS local | 1 personal org | 1 (owner) | none | transparent |
| Demo | personal org/user, ephemeral | 1 | none | per-org |
| Pro | personal org/user | 1 | `OrgSubscription` (seat 1) | per-org |
| Hybrid | deployment → org + default workspace | loopback owner + managed members | deployment→org sub | per-org/workspace + org policy |
| Team ($200/user) | team org | N, roles | org sub, seats=N | per-org + role |
| Site ($1000) | site org + workspaces | N, RBAC, `audit.full` | org sub | per-org/workspace + role |

Pro and OSS are byte-for-byte identical in behavior; everything else is additive.

## 10. Safety wins

- **One isolation chokepoint** (`require_tenancy_context` + org/workspace-scoped helpers) → systematic,
  testable; removes the "did this route remember to filter by user_id?" risk class.
- **Workspace/project visibility** → avoids the enterprise anti-pattern where org membership
  silently grants access to all internal customer data and models.
- **Org-scoped custody keys** → lets teams share data while preventing a user's departure or PII
  erasure from destroying org-owned scientific records.
- **Org-admin egress policy** → makes hybrid security enforceable instead of relying on each
  user's local preference.
- **demo-cleanup** keys on `org.kind == personal` + lifecycle, **not an env var** →
  structural protection so it can never touch a paid org even if misconfigured.
- **folder_watch / uploads** scope to the org's data subtree (`org_id`) → closes the
  cross-tenant residual structurally instead of per-handler.

## 11. Open decisions (need your call)

1. **Active-org selection:** header `X-Org-Id` (incremental) vs path `/orgs/{id}/...` (cleaner). *Recommend header first, but persist `TenancyContext` for async work.*
2. **Subscription:** fully unify into `OrgSubscription` and treat `DeploymentKey` purely as a credential that maps to an org? *Recommend yes.*
3. **`org_id` on leaf tables:** denormalize on the hot leaves vs inherit-via-parent only? *Recommend denormalize on `experiment_file`, `execution_run`, `model_artifact`.*
4. **Seat model:** named seats (membership count) vs concurrent? *Recommend named.*
5. **Role set:** confirm `owner / admin / member / viewer`.
6. **OSS carries `org_id`:** confirm OSS data tables carry the column (always the personal org there) for uniformity.
7. **Workspace model:** default workspace only at first vs visible workspace/project sharing UI in the first enterprise release? *Recommend schema now, minimal UI later.*
8. **Custody scope:** org-level key only vs workspace-level keys for regulated separation? *Recommend org key for default workspace, workspace keys where isolation is requested.*
9. **Hybrid policy authority:** confirm org policy always overrides user preference and personal Pro entitlement. *Recommend yes.*

## 12. Explicitly deferred

SSO/OIDC (`ExternalIdentity` seam), SCIM, custom roles, cross-org sharing, arbitrary
per-resource ACLs, and full seat/billing UI.

Considered in the use-mode review and intentionally **not now** — all additive given the
principal, `org_id`/`workspace_id`, and org/workspace-custody seams above: service-account /
instrument identities, approval & segregation-of-duties workflow (reviewer identity +
e-signature, author ≠ approver), time-boxed non-seat auditor grants, cross-org transfer /
sponsor↔CRO handoff, OEM/reseller org hierarchy, and deployment-target (site / instrument)
topology.
