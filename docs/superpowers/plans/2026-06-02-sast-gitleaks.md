# SAST & Secret Scanning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Semgrep SAST and Gitleaks secret-scanning to the CI/CD pipeline so security issues and hardcoded credentials are caught before images are published.

**Architecture:** New reusable workflow `.github/workflows/sast.yml` encapsulates both scanning jobs (semgrep + gitleaks). The `ci-cd-pipeline.yml` calls it in parallel with existing unit-test jobs. Failures notify Teams and block the pipeline on PRs/pushes. SARIF results upload to GitHub Security → Code scanning.

**Tech Stack:** GitHub Actions, `semgrep/semgrep-action@v1`, `gitleaks/gitleaks-action@v2`, SARIF upload via `github/codeql-action/upload-sarif`, Microsoft Teams webhook (existing action).

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `.github/workflows/sast.yml` | Reusable workflow: semgrep + gitleaks jobs |
| Create | `.semgrepignore` | Exclude `tests/`, `data/`, migration scripts from semgrep |
| Create | `.gitleaks.toml` | Allowlist test credential fixtures to suppress false positives |
| Modify | `.github/workflows/ci-cd-pipeline.yml` | Add `sast` job (parallel with unit-test-* jobs) |

---

## Task 1: Create `.semgrepignore`

**Files:**
- Create: `.semgrepignore`

- [ ] **Step 1: Create the file**

```
# Semgrep ignore — test fixtures, data files, migration scripts contain intentional
# patterns (fake tokens, SQL strings) that would produce false positives.
byoeb-v1/byoeb/tests/
byoeb-v1/byoeb-integrations/byoeb_integrations/*/tests/
byoeb-v1/byoeb-core/tests/
data/
migrations/
*.migration.py
```

- [ ] **Step 2: Commit**

```bash
git add .semgrepignore
git commit -m "ci: add .semgrepignore to exclude test fixtures and data dirs from SAST"
```

---

## Task 2: Create `.gitleaks.toml`

**Files:**
- Create: `.gitleaks.toml`

Gitleaks scans the full git history as well as the working tree. Test files intentionally use fake credentials as fixtures — these need allowlisting.

- [ ] **Step 1: Create the file**

```toml
title = "Gitleaks config for byoeb"

[allowlist]
  description = "Allow test-fixture credential patterns and known-safe constants"
  # Paths: everything under any tests/ directory or data/
  paths = [
    '''byoeb-v1/.+/tests/.+''',
    '''data/.+''',
    '''migrations/.+''',
  ]
  # Regexes: fake phone numbers, placeholder API keys used in unit test factories
  regexes = [
    # Phone numbers used in test User fixtures (e.g. "918765432109")
    '''9187654321\d{2}''',
    # Generic placeholder keys like "fake-api-key", "test-secret", "dummy-token"
    '''(fake|test|dummy|placeholder)[-_]?(api[-_]?key|secret|token)''',
  ]
```

- [ ] **Step 2: Commit**

```bash
git add .gitleaks.toml
git commit -m "ci: add .gitleaks.toml allowlist for test-fixture credentials"
```

---

## Task 3: Create `.github/workflows/sast.yml` (reusable workflow)

**Files:**
- Create: `.github/workflows/sast.yml`

This is the reusable workflow called by `ci-cd-pipeline.yml`. It exposes one optional secret (`SEMGREP_APP_TOKEN`) so the OSS ruleset is used when the token is absent.

- [ ] **Step 1: Create the workflow file**

```yaml
name: SAST

on:
  workflow_call:
    secrets:
      SEMGREP_APP_TOKEN:
        description: "Optional Semgrep Cloud token — enables managed rules and dashboard upload"
        required: false
      TEAMS_WEBHOOK_URL:
        required: false

jobs:
  semgrep:
    name: Semgrep (SAST)
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write   # required to upload SARIF

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Run Semgrep
        uses: semgrep/semgrep-action@v1
        with:
          config: >-
            p/python
            p/fastapi
            p/secrets
            p/owasp-top-ten
          generateSarif: "1"
          publishToken: ${{ secrets.SEMGREP_APP_TOKEN }}
        env:
          SEMGREP_APP_TOKEN: ${{ secrets.SEMGREP_APP_TOKEN }}

      - name: Upload SARIF to GitHub Security
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: semgrep.sarif
          category: semgrep

      - name: Notify Teams of Semgrep failure
        if: failure()
        uses: ./.github/actions/dispatch-teams-webhook
        with:
          summary: "❌ SAST (Semgrep) Failed"
          activity-title: "❌ SAST (Semgrep) Failed"
          theme-color: "FF0000"
          facts: |
            [
              {"name": "Stage", "value": "SAST — Semgrep"},
              {"name": "Actor", "value": "${{ github.actor }}"}
            ]
          teams-webhook-url: ${{ secrets.TEAMS_WEBHOOK_URL }}

  gitleaks:
    name: Gitleaks (secret scanning)
    runs-on: ubuntu-latest
    permissions:
      contents: read

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0   # full history — gitleaks scans all commits

      - name: Run Gitleaks
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITLEAKS_CONFIG: .gitleaks.toml

      - name: Notify Teams of Gitleaks failure
        if: failure()
        uses: ./.github/actions/dispatch-teams-webhook
        with:
          summary: "❌ Secret Scanning (Gitleaks) Failed"
          activity-title: "❌ Secret Scanning (Gitleaks) Failed"
          theme-color: "FF0000"
          facts: |
            [
              {"name": "Stage", "value": "Secret Scanning — Gitleaks"},
              {"name": "Actor", "value": "${{ github.actor }}"}
            ]
          teams-webhook-url: ${{ secrets.TEAMS_WEBHOOK_URL }}
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/sast.yml
git commit -m "ci: add reusable SAST workflow (Semgrep + Gitleaks)"
```

---

## Task 4: Wire `sast` job into `ci-cd-pipeline.yml`

**Files:**
- Modify: `.github/workflows/ci-cd-pipeline.yml`

The `sast` job runs in parallel with `unit-test-*` jobs. The `publish-image` job must also wait for `sast` to pass.

- [ ] **Step 1: Add the `sast` job after the three `unit-test-*` jobs (before the `build` job)**

In `.github/workflows/ci-cd-pipeline.yml`, after the `unit-test-byoeb-integrations` block (around line 47), add:

```yaml
  # Step 1d: SAST — Semgrep + Gitleaks (parallel with unit tests)
  sast:
    name: SAST & Secret Scanning
    uses: ./.github/workflows/sast.yml
    secrets:
      SEMGREP_APP_TOKEN: ${{ secrets.SEMGREP_APP_TOKEN }}
      TEAMS_WEBHOOK_URL: ${{ secrets.TEAMS_WEBHOOK_URL }}
```

- [ ] **Step 2: Update `publish-image` needs to include `sast`**

Change:
```yaml
  publish-image:
    name: Publish image
    needs: [build, unit-test-byoeb-core, unit-test-byoeb, unit-test-byoeb-integrations]
```
To:
```yaml
  publish-image:
    name: Publish image
    needs: [build, unit-test-byoeb-core, unit-test-byoeb, unit-test-byoeb-integrations, sast]
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci-cd-pipeline.yml
git commit -m "ci: wire SAST job into pipeline parallel with unit tests, block publish on sast"
```

---

## Task 5: Tune `.gitleaks.toml` and `.semgrepignore` for any false positives

This task is done after the first pipeline run — real false positives discovered at that point must be suppressed.

- [ ] **Step 1: Trigger a pipeline run** by pushing the branch or opening a draft PR to `a4i/staging`.

- [ ] **Step 2: Check Semgrep results** in GitHub Security → Code scanning. If any finding is a false positive from a test file path not already covered, add it to `.semgrepignore`:

```
# example: add a specific file
byoeb-v1/byoeb/tests/conftest.py
```

- [ ] **Step 3: Check Gitleaks output** in the Actions log. If a test fixture triggers a detection not covered by `.gitleaks.toml`, add a new `regexes` entry:

```toml
# example: suppress a specific fake key pattern
'''sk-test-[A-Za-z0-9]{32}''',
```

- [ ] **Step 4: Commit tuning if any changes made**

```bash
git add .semgrepignore .gitleaks.toml
git commit -m "ci: tune SAST ignore/allowlist to remove false positives from test fixtures"
```

---

## Self-Review

**Spec coverage:**
- [x] `.github/workflows/sast.yml` with semgrep job → Task 3
- [x] `.github/workflows/sast.yml` with gitleaks job → Task 3
- [x] Rulesets `p/python`, `p/fastapi`, `p/secrets`, `p/owasp-top-ten` → Task 3 Step 1
- [x] SARIF uploaded to GitHub Security tab → Task 3 Step 1 (`upload-sarif` step)
- [x] `SEMGREP_APP_TOKEN` optional → Task 3 (`required: false`)
- [x] `.semgrepignore` excludes `tests/`, `data/`, migrations → Task 1
- [x] `.gitleaks.toml` allowlist for test fixtures → Task 2
- [x] `sast` job added to `ci-cd-pipeline.yml` parallel with unit tests → Task 4
- [x] Teams webhook on failure → Task 3 (both jobs)
- [x] `publish-image` blocked until `sast` passes → Task 4 Step 2

**No placeholders found.**

**Type consistency:** No shared types across tasks — all YAML/TOML, no cross-task function references.
