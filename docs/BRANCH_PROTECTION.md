# Branch Protection Setup — `main`

Status: **Option A applied** (see command below). Direct pushes to `main`
still work; the `test` and `web` CI jobs must pass, force-pushes and branch
deletion are blocked. Applied via `gh api`, logged in as `Apolloat2022`.

## Recommended rule for `main`

| Setting | Value | Why |
|---|---|---|
| Require a pull request before merging | **Decision needed** — see below | Blocks direct pushes to `main`; changes the workflow used to build this repo so far |
| Require approvals | 0 if solo, 1+ if others will push | Only relevant if PRs are required |
| Require status checks to pass | `test`, `web` (from `.github/workflows/ci.yml`) | Blocks merging if pytest/ruff/mypy or the Next.js build fails |
| Require branches to be up to date before merging | Yes | Avoids merging a stale branch that hasn't run CI against latest `main` |
| Require conversation resolution before merging | Yes (only if PRs required) | Standard hygiene once PRs are in use |
| Do not allow force pushes | Yes | Protects the compliance-ledger and migration history from rewrite |
| Do not allow deletions | Yes | Prevents accidental deletion of `main` |
| Include administrators | Recommended, but optional | Applies the rules to the repo owner too, not just other contributors |

**Decision needed before applying:** requiring a pull request before merging
means direct `git push origin main` (the workflow used for every phase
commit so far) will start being rejected — future work would need to land
via a PR (even a self-merged one). If solo development with direct pushes
should continue, skip "require PR" and only enable the status-check +
force-push + deletion protections below.

## Option A — status checks only (keeps direct pushes to `main` working)

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

> Note: `strict` must go through `-F` (typed boolean), not `-f` (string) —
> `-f "required_status_checks[strict]=true"` 422s with "true" is not a
> boolean". `contexts[]` entries stay on `-f` since they're real strings.

**Applied 2026-07-21.** Verified via
`gh api repos/Apolloat2022/observability-agent/branches/main/protection`:
`strict: true`, `contexts: ["test", "web"]`, `enforce_admins: false`,
`allow_force_pushes: false`, `allow_deletions: false`.

## Option B — require PRs (the fuller GitHub-recommended setup, NOT applied)

```bash
gh api -X PUT repos/Apolloat2022/observability-agent/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  -f "required_status_checks[strict]=true" \
  -f "required_status_checks[contexts][]=test" \
  -f "required_status_checks[contexts][]=web" \
  -F "enforce_admins=true" \
  -f "required_pull_request_reviews[required_approving_review_count]=0" \
  -f "required_pull_request_reviews[require_code_owner_reviews]=false" \
  -F "restrictions=null" \
  -F "allow_force_pushes=false" \
  -F "allow_deletions=false" \
  -F "required_conversation_resolution=true"
```

(`required_approving_review_count=0` still forces a PR to exist and CI to
pass, without requiring a second person's approval — appropriate for a
solo repo. Raise it once collaborators are added.)

## GitHub UI equivalent

Repo → **Settings → Branches → Add branch ruleset / Add rule** → branch name
pattern `main` → check the boxes matching the table above → **Create**.

## Verify after applying

```bash
gh api repos/Apolloat2022/observability-agent/branches/main/protection
```

Should return the applied rule instead of a 404.
