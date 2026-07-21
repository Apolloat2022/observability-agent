# Branch Protection Setup — `main`

Status: **Option B applied** (superseded Option A). `main` now requires a
pull request (0 required approvals — appropriate for a solo repo), the
`test` and `web` CI jobs must pass, force-pushes and branch deletion are
blocked, conversation resolution is required, and **admins are no longer
exempt** (`enforce_admins: true`) — direct `git push origin main` is
rejected for everyone, including the repo owner. All future changes land
via a branch + PR, even self-merged ones.

## Current settings (as applied)

| Setting | Value |
|---|---|
| Require a pull request before merging | Yes |
| Required approving reviews | 0 |
| Require status checks to pass | `test`, `web` (strict — branch must be up to date) |
| Require conversation resolution before merging | Yes |
| Allow force pushes | No |
| Allow deletions | No |
| Include administrators | Yes — no bypass, even for the repo owner |

## Workflow this implies going forward

```bash
git checkout -b some-change
# ... commit ...
git push -u origin some-change
gh pr create --fill
gh pr merge --squash --auto   # or merge manually once checks pass
```

A direct `git push origin main` will now be rejected with a protected-branch
error.

## Commands used

**Option A (applied first, later superseded by B):**

```bash
gh api -X PUT repos/Apolloat2022/observability-agent/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  -F "required_status_checks[strict]=true" \
  -f "required_status_checks[contexts][]=test" \
  -f "required_status_checks[contexts][]=web" \
  -F "enforce_admins=false" \
  -F "required_pull_request_reviews=null" \
  -F "restrictions=null" \
  -F "allow_force_pushes=false" \
  -F "allow_deletions=false"
```

**Option B (current):**

```bash
gh api -X PUT repos/Apolloat2022/observability-agent/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  -F "required_status_checks[strict]=true" \
  -f "required_status_checks[contexts][]=test" \
  -f "required_status_checks[contexts][]=web" \
  -F "enforce_admins=true" \
  -F "required_pull_request_reviews[required_approving_review_count]=0" \
  -F "required_pull_request_reviews[require_code_owner_reviews]=false" \
  -F "restrictions=null" \
  -F "allow_force_pushes=false" \
  -F "allow_deletions=false" \
  -F "required_conversation_resolution=true"
```

> Note: boolean and integer fields (`strict`, `enforce_admins`,
> `required_approving_review_count`, `required_conversation_resolution`,
> `allow_force_pushes`, `allow_deletions`, `restrictions`) must go through
> `-F` (typed), not `-f` (string) — `-f` sends `"true"` as a literal string
> and the API 422s with "is not a boolean". `contexts[]` entries stay on
> `-f` since they're genuinely strings.

**Applied 2026-07-21.** Verified via
`gh api repos/Apolloat2022/observability-agent/branches/main/protection`:
`strict: true`, `contexts: ["test", "web"]`, `enforce_admins: true`,
`required_approving_review_count: 0`, `conversation_resolution: true`,
`allow_force_pushes: false`, `allow_deletions: false`.

## GitHub UI equivalent

Repo → **Settings → Branches → Add branch ruleset / Add rule** → branch name
pattern `main` → check the boxes matching the table above → **Create**.

## Verify current state

```bash
gh api repos/Apolloat2022/observability-agent/branches/main/protection
```
