# SAST & Secret Scanning — Architecture

## What We're Adding

No static security analysis or secret-leak detection exists in the pipeline today.
This change adds two scanners that run **in parallel with unit tests** on every PR and push:

| Scanner | What it catches |
|---------|----------------|
| **Semgrep** | Python/FastAPI vulnerabilities, OWASP Top 10, hardcoded secrets patterns |
| **Gitleaks** | Actual secrets (API keys, tokens) committed anywhere in git history |

Results block the pipeline. SARIF output appears as inline PR annotations in GitHub Security → Code scanning.

---

## Current Pipeline (before)

```mermaid
flowchart LR
    PR([PR / Push]) --> UT1[unit-test\nbyoeb-core]
    PR --> UT2[unit-test\nbyoeb]
    PR --> UT3[unit-test\nbyoeb-integrations]
    PR --> B[Build\nDocker image]

    UT1 --> PUB[publish-image]
    UT2 --> PUB
    UT3 --> PUB
    B   --> PUB

    PUB --> DS[deploy-staging]
    PUB --> DP[deploy-production]

    DS --> IT1[integration-tests\nstaging]
    DP --> IT2[integration-tests\nproduction]
```

---

## New Pipeline (after)

```mermaid
flowchart LR
    PR([PR / Push]) --> UT1[unit-test\nbyoeb-core]
    PR --> UT2[unit-test\nbyoeb]
    PR --> UT3[unit-test\nbyoeb-integrations]
    PR --> SAST[**sast**\nSemgrep + Gitleaks]:::new
    PR --> B[Build\nDocker image]

    UT1  --> PUB[publish-image]
    UT2  --> PUB
    UT3  --> PUB
    SAST --> PUB
    B    --> PUB

    PUB --> DS[deploy-staging]
    PUB --> DP[deploy-production]

    DS --> IT1[integration-tests\nstaging]
    DP --> IT2[integration-tests\nproduction]

    classDef new fill:#2d6a4f,color:#fff,stroke:#1b4332
```

> `publish-image` now waits on **five** jobs instead of four. SAST blocks the image from ever reaching the registry if findings exist.

---

## SAST Workflow Internal Structure

```mermaid
flowchart TD
    subgraph sast.yml [".github/workflows/sast.yml — reusable workflow"]
        direction TB

        subgraph semgrep["Job: semgrep"]
            S1[Checkout code]
            S2["Run semgrep-action@v1\np/python · p/fastapi\np/secrets · p/owasp-top-ten"]
            S3[Upload SARIF\nto GitHub Security]
            S4{Failure?}
            S5[Notify Teams ❌]
            S1 --> S2 --> S3 --> S4
            S4 -- yes --> S5
        end

        subgraph gitleaks["Job: gitleaks"]
            G1[Checkout full history\nfetch-depth: 0]
            G2["Run gitleaks-action@v2\n+ .gitleaks.toml allowlist"]
            G3{Failure?}
            G4[Notify Teams ❌]
            G1 --> G2 --> G3
            G3 -- yes --> G4
        end
    end

    CI[ci-cd-pipeline.yml\nsast job] -->|workflow_call| sast.yml
```

---

## What Each New File Does

```mermaid
graph LR
    subgraph "New files"
        A[".semgrepignore"]
        B[".gitleaks.toml"]
        C[".github/workflows/sast.yml"]
    end

    subgraph "Modified files"
        D[".github/workflows/ci-cd-pipeline.yml"]
    end

    A -->|"Tells semgrep to skip\ntests/ · data/ · migrations/"| C
    B -->|"Allowlists fake credentials\nin test fixtures"| C
    D -->|"Calls sast.yml\n(workflow_call)"| C
    C -->|"Blocks publish-image\non any finding"| D
```

---

## Secret Detection Flow (Gitleaks)

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant GH  as GitHub Actions
    participant GL  as Gitleaks
    participant TM  as Teams

    Dev->>GH: git push / open PR
    GH->>GL: checkout full history (fetch-depth: 0)
    GL->>GL: scan all commits against rules
    alt secret found (not in .gitleaks.toml allowlist)
        GL-->>GH: exit code 1 — job fails
        GH->>TM: ❌ Secret Scanning Failed webhook
        GH-->>Dev: PR blocked — annotation shows offending line
    else clean
        GL-->>GH: exit code 0 — job passes
        GH-->>Dev: ✅ Gitleaks passed
    end
```

---

## SARIF Upload Flow (Semgrep → GitHub Security)

```mermaid
sequenceDiagram
    participant SG  as Semgrep Action
    participant AR  as upload-sarif Action
    participant SEC as GitHub Security tab
    participant PR  as Pull Request

    SG->>SG: run rulesets, emit semgrep.sarif
    SG->>AR: semgrep.sarif (even on failure via `if: always()`)
    AR->>SEC: POST SARIF via Code scanning API
    SEC->>PR: inline annotations on changed lines
    Note over SEC: Findings persist in\nSecurity → Code scanning
```

---

## False-Positive Suppression Strategy

```mermaid
flowchart TD
    FP[Semgrep / Gitleaks\nflags a finding]
    Q1{Is it in a\ntest fixture?}
    Q2{Is it a real\npattern to suppress?}

    FP --> Q1
    Q1 -- yes --> ADD1["Add path to .semgrepignore\nor .gitleaks.toml paths[]"]
    Q1 -- no  --> Q2
    Q2 -- yes --> ADD2["Add regex to\n.gitleaks.toml regexes[]"]
    Q2 -- no  --> FIX[Fix the real\nsecurity issue]

    ADD1 --> COMMIT[git commit & push]
    ADD2 --> COMMIT
    FIX  --> COMMIT
```

---

## Required Secrets / Variables

| Name | Where | Required? | Purpose |
|------|-------|-----------|---------|
| `SEMGREP_APP_TOKEN` | GitHub repo secrets | **Optional** | Enables Semgrep Cloud dashboard; OSS rules work without it |
| `TEAMS_WEBHOOK_URL` | GitHub repo secrets | Optional (already present) | Failure notifications |
| `GITHUB_TOKEN` | Auto-provided | Automatic | Gitleaks auth + SARIF upload |

---

## Acceptance Criteria Checklist

- [ ] Semgrep findings fail the PR; results visible in GitHub Security → Code scanning
- [ ] Gitleaks always blocks on detected secrets
- [ ] No false positives from test fixtures (`.gitleaks.toml` + `.semgrepignore` tuned)
- [ ] SARIF uploaded — findings appear as inline PR annotations
- [ ] `SEMGREP_APP_TOKEN` optional — pipeline works without it (uses OSS rules)
