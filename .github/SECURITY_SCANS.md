# Security scans on this repo

Semgrep runs on every pull request into `a4i/main` and `a4i/staging` (`.github/workflows/semgrep.yml`). Gitleaks secret scanning stays in `.github/workflows/sast.yml`, called from the CI/CD pipeline.

| Tool | Role | Blocks merge? | Where results show |
|------|------|---------------|--------------------|
| Semgrep | Primary SAST gate. Fast pattern + light dataflow, OSS engine. Rulesets `p/security-audit`, `p/owasp-top-ten`. | **Yes**, once the ruleset requires it (see below). A new `ERROR`-severity finding fails the check. | PR **Checks** + Security > Code scanning |
| Gitleaks | Secret scanning over the full history. | Yes | PR **Checks** + Security > Code scanning |

## Why the gate stays low-noise

- **Diff-aware.** Only lines a PR actually touches are evaluated (`--baseline-commit`). A pre-existing finding on a line the PR does not touch is not evaluated. The org-wide rollout is tracked in issue [A4i-tech/.github#645](https://github.com/A4i-tech/.github/issues/645).
- **Severity gate.** Only an `ERROR`-level rule (Semgrep's own label, there is no separate "critical" level) can block, and only if the PR's own diff introduces or touches a matching line.
- **Registry drift.** `p/security-audit` and `p/owasp-top-ten` are fetched live from the Semgrep registry on every run. A rule added or re-graded upstream can turn the gate red with no code change here.

## Suppressing a false positive

1. **One line**, add on the flagged line:

   ```python
   subprocess.run(cmd, shell=True)  # nosemgrep: dangerous-subprocess-use  cmd is a fixed constant
   ```

   Always name the rule id and say why it is safe.

2. **A whole path** (generated code, vendored deps, test fixtures), add it to `.semgrepignore` with a one-line reason.

3. **A rule wrong for this codebase every time**, add `--exclude-rule <rule-id>` to the scan step in `.github/workflows/semgrep.yml`, with a comment, after agreeing it with the security owner.

## Local full-repo scan

Not the gate itself, the gate only evaluates a PR's own diff. This runs the same rulesets against the whole repo, fully sandboxed (no host install):

```bash
docker run --rm -v "$PWD":/src:ro -w /src semgrep/semgrep:1.179.0 \
  semgrep scan --config p/security-audit --config p/owasp-top-ten \
  --oss-only --metrics off
```

Add `--severity ERROR --baseline-commit <base-sha>` to reproduce exactly what the gate evaluates on a given PR.
