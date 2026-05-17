# CI/CD & Release Automation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire SpireSight to GitHub Actions so that pushing a `v*.*.*` git tag automatically builds a Mac arm64 DMG and a Windows x64 zip and publishes them as a GitHub Release. PRs and `main` pushes run lint + type-check + tests on Python 3.11 and 3.12.

**Architecture:** Two workflow files. `ci.yml` runs ruff + mypy + pytest matrix on PR + main push. `release.yml` triggers on `v*.*.*` tag push, runs the same test matrix first, then builds macOS arm64 and Windows x64 in parallel jobs, then a final `release` job uploads both artifacts to a GitHub Release with auto-generated notes. The git tag is the single source of truth for the version string; CI injects it into `pyproject.toml` and the PyInstaller spec's macOS `Info.plist` at build time. No code signing.

**Tech Stack:** GitHub Actions, PyInstaller, `create-dmg` (Homebrew), PowerShell `Compress-Archive`, `softprops/action-gh-release@v2`, ruff, mypy, pytest, PySide6.

**Spec reference:** `docs/superpowers/specs/2026-05-16-cicd-release-design.md`

---

## File map

| Path | Action | Responsibility |
|---|---|---|
| `pyproject.toml` | modify | Version placeholder; add ruff + mypy to `[dev]` |
| `.gitignore` | modify | Add `!packaging/spiresight.spec` exception; ignore `*.dmg` |
| `packaging/spiresight.spec` | modify | Read `SPIRESIGHT_VERSION` env var; inject into mac `BUNDLE` Info.plist |
| `README.md` | modify | Append "Release process" + "Installation (unsigned)" sections |
| `.github/workflows/ci.yml` | create | PR + main push: ruff + mypy + pytest matrix |
| `.github/workflows/release.yml` | create | Tag push: test → build mac + win → release |

---

## Task 1: pyproject.toml — version placeholder + ruff/mypy in dev extras

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Read current `pyproject.toml`**

Confirm current state: `version = "0.1.0"`, `[project.optional-dependencies].dev` lists `pytest`, `pytest-asyncio`, `respx`, `httpx`.

- [ ] **Step 2: Edit `pyproject.toml`**

Change `version = "0.1.0"` to `version = "0.0.0+dev"`.

Change the `dev = [...]` list to include ruff and mypy:

```toml
[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "respx>=0.20",
  "httpx>=0.27",
  "ruff>=0.5",
  "mypy>=1.10",
]
```

- [ ] **Step 3: Reinstall dev extras locally**

Run:
```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: `Successfully installed ... ruff-... mypy-...` (or "already satisfied" if previously installed).

- [ ] **Step 4: Verify ruff + mypy work**

Run:
```bash
ruff check src tests
mypy src
pytest -q
```

Expected: all three exit 0. (If ruff or mypy report pre-existing issues, fix them in this task — CI will block on them otherwise.)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "build(deps): add ruff + mypy to dev extras; placeholder version

CI injects the real version from git tag at build time."
```

---

## Task 2: .gitignore — protect spec file from `*.spec` glob; ignore DMG

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Locate the existing `*.spec` line**

Already in `.gitignore` under the `# PyInstaller` comment. This is a generic Python-template glob and would silently ignore `packaging/spiresight.spec` if it were ever re-added. We add an explicit allow-exception.

- [ ] **Step 2: Edit `.gitignore`**

Find the block:
```
# PyInstaller
#   Usually these files are written by a python script from a template
#   before PyInstaller builds the exe, so as to inject date/other infos into it.
*.manifest
*.spec
```

Replace with:
```
# PyInstaller
#   Usually these files are written by a python script from a template
#   before PyInstaller builds the exe, so as to inject date/other infos into it.
*.manifest
*.spec
!packaging/spiresight.spec

# Release artifacts (built locally for testing)
*.dmg
```

- [ ] **Step 3: Verify the exception works**

Run:
```bash
git check-ignore -v packaging/spiresight.spec
```

Expected: empty output and exit code 1 (meaning: NOT ignored). If it prints a match line, the exception isn't taking effect.

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore(gitignore): un-ignore packaging/spiresight.spec; ignore *.dmg"
```

---

## Task 3: packaging/spiresight.spec — env-driven version + Info.plist

**Files:**
- Modify: `packaging/spiresight.spec`

- [ ] **Step 1: Replace the spec file contents**

Overwrite `packaging/spiresight.spec` with:

```python
# packaging/spiresight.spec
# Run from repo root: pyinstaller packaging/spiresight.spec
# Produces a windowed (no console) bundle that includes prompts/ and resources/.
# Version is sourced from SPIRESIGHT_VERSION env var (CI sets it from the git tag).
# Falls back to "0.0.0+dev" for local builds.

import os
import sys

from PyInstaller.utils.hooks import collect_data_files  # noqa: F401  (kept for future use)

VERSION = os.environ.get("SPIRESIGHT_VERSION", "0.0.0+dev")

datas = [
    ("prompts", "prompts"),
    ("src/spiresight/resources", "spiresight/resources"),
]

a = Analysis(
    ["src/spiresight/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "spiresight.llm.providers.openai_provider",
        "spiresight.llm.providers.anthropic_provider",
        "spiresight.llm.providers.gemini_provider",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="SpireSight",
    console=False,
    icon=None,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    name="SpireSight",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="SpireSight.app",
        icon=None,
        bundle_identifier="dev.haochen.spiresight",
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
        },
    )
```

- [ ] **Step 2: Sanity-check the env var is read**

Run (on any platform):
```bash
SPIRESIGHT_VERSION=9.9.9 python -c "
import os
ns = {'os': os}
for line in open('packaging/spiresight.spec'):
    if line.startswith('VERSION ='):
        exec(line, ns)
        break
assert ns['VERSION'] == '9.9.9', ns['VERSION']
print('OK:', ns['VERSION'])
"
```

Expected: `OK: 9.9.9`.

Also verify the fallback:
```bash
unset SPIRESIGHT_VERSION
python -c "
import os
ns = {'os': os}
for line in open('packaging/spiresight.spec'):
    if line.startswith('VERSION ='):
        exec(line, ns)
        break
assert ns['VERSION'] == '0.0.0+dev', ns['VERSION']
print('Fallback OK:', ns['VERSION'])
"
```

Expected: `Fallback OK: 0.0.0+dev`.

- [ ] **Step 3: Commit**

```bash
git add packaging/spiresight.spec
git commit -m "build(packaging): read version from SPIRESIGHT_VERSION env

Injects CFBundleShortVersionString / CFBundleVersion into the macOS
app bundle's Info.plist. CI sets the env var from the git tag.
Falls back to 0.0.0+dev for local builds."
```

---

## Task 4: README.md — release process + unsigned install instructions

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append two new sections to `README.md`**

After the existing `## Security note` section, append:

````markdown

## Installation (unsigned builds)

SpireSight builds are **not code-signed** in this MVP. First-launch
warnings are expected.

### macOS

1. Download `SpireSight-<version>-macos-arm64.dmg` from the [Releases page](https://github.com/JarrettChen217/SpireSight/releases).
2. Open the DMG and drag `SpireSight.app` into `/Applications`.
3. First launch will be blocked by Gatekeeper. Either:
   - **Right-click** `SpireSight.app` in Finder → **Open** → confirm in the dialog, OR
   - Run once: `xattr -dr com.apple.quarantine /Applications/SpireSight.app`

Apple Silicon (M1/M2/M3/M4) only. Intel Macs are not supported.

### Windows

1. Download `SpireSight-<version>-windows-x64.zip` from the Releases page.
2. Extract anywhere (e.g. `C:\Program Files\SpireSight\`).
3. Run `SpireSight.exe`. SmartScreen will warn "Windows protected your PC".
   Click **More info** → **Run anyway**.

## Release process (maintainer)

Releases are fully automated. Tags drive everything; do not edit
`pyproject.toml` version manually.

```bash
# Make sure main is green
git checkout main && git pull

# Tag and push
git tag v0.1.1
git push origin v0.1.1

# Watch https://github.com/JarrettChen217/SpireSight/actions
# After ~8–12 minutes, the new release appears with DMG + zip attached.
```

Pre-release: include a hyphen in the tag (e.g. `v0.2.0-rc.1`). The
workflow auto-flags it as a GitHub pre-release.

Rollback a bad tag (only works before users download):

```bash
git push --delete origin v0.1.1
git tag -d v0.1.1
# Then delete the release in the GitHub Releases UI (if it was created).
```
````

- [ ] **Step 2: Verify markdown renders sanely**

Run:
```bash
head -100 README.md && echo "..." && tail -60 README.md
```

Expected: new sections visible, no broken code fences.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): unsigned-install + maintainer release process"
```

---

## Task 5: `.github/workflows/ci.yml` — lint/type/test on PR + main push

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the `.github/workflows/` directory and file**

Run:
```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
          cache-dependency-path: pyproject.toml

      - name: Install dev dependencies
        run: pip install -e ".[dev]"

      - name: Ruff lint
        run: ruff check src tests

      - name: Mypy type-check
        run: mypy src

      - name: Pytest
        run: pytest -q
```

- [ ] **Step 3: Verify locally (best-effort)**

Run the same three commands the workflow runs:
```bash
ruff check src tests && mypy src && pytest -q
```

Expected: all three exit 0. If any fail, fix them now — CI will fail on the PR otherwise.

- [ ] **Step 4: Commit and push to a feature branch to exercise CI**

```bash
git checkout -b ci/workflows
git add .github/workflows/ci.yml
git commit -m "ci: lint + type-check + test matrix (3.11, 3.12) on PR and main"
git push -u origin ci/workflows
```

- [ ] **Step 5: Open a PR and watch the workflow**

Run:
```bash
gh pr create --base main --head ci/workflows --title "ci: workflows" --body "Bootstrap CI + release workflows. Will be merged once Task 6 lands."
gh run watch
```

Expected: `test (3.11)` and `test (3.12)` both pass green. Do **not** merge yet — Task 6 adds `release.yml` to the same PR.

---

## Task 6: `.github/workflows/release.yml` — tag-driven Mac DMG + Win zip release

**Files:**
- Create: `.github/workflows/release.yml`

Continue on the `ci/workflows` branch from Task 5.

- [ ] **Step 1: Write `.github/workflows/release.yml`**

```yaml
name: Release

on:
  push:
    tags:
      - "v*.*.*"

concurrency:
  group: release-${{ github.ref }}
  cancel-in-progress: false

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
          cache-dependency-path: pyproject.toml
      - run: pip install -e ".[dev]"
      - run: ruff check src tests
      - run: mypy src
      - run: pytest -q

  build-macos:
    needs: test
    runs-on: macos-14
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: pyproject.toml

      - name: Extract version from tag
        run: |
          VERSION="${GITHUB_REF_NAME#v}"
          echo "SPIRESIGHT_VERSION=$VERSION" >> "$GITHUB_ENV"
          sed -i '' "s/^version = .*/version = \"$VERSION\"/" pyproject.toml
          echo "Built version: $VERSION"
          grep '^version' pyproject.toml

      - name: Install build dependencies
        run: pip install -e ".[dev]" pyinstaller

      - name: PyInstaller build
        run: pyinstaller --noconfirm packaging/spiresight.spec

      - name: Install create-dmg
        run: brew install create-dmg

      - name: Create DMG
        run: |
          create-dmg \
            --volname "SpireSight $SPIRESIGHT_VERSION" \
            "SpireSight-${SPIRESIGHT_VERSION}-macos-arm64.dmg" \
            "dist/SpireSight.app"

      - name: Upload DMG artifact
        uses: actions/upload-artifact@v4
        with:
          name: macos-dmg
          path: "*.dmg"
          if-no-files-found: error

  build-windows:
    needs: test
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: pyproject.toml

      - name: Extract version from tag
        shell: pwsh
        run: |
          $version = $env:GITHUB_REF_NAME -replace '^v', ''
          "SPIRESIGHT_VERSION=$version" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
          (Get-Content pyproject.toml) -replace '^version = .*', "version = ""$version""" | Set-Content pyproject.toml
          Write-Host "Built version: $version"
          Select-String -Path pyproject.toml -Pattern '^version'

      - name: Install build dependencies
        run: pip install -e ".[dev]" pyinstaller

      - name: PyInstaller build
        run: pyinstaller --noconfirm packaging\spiresight.spec

      - name: Create zip
        shell: pwsh
        run: |
          $zipName = "SpireSight-$env:SPIRESIGHT_VERSION-windows-x64.zip"
          Compress-Archive -Path dist\SpireSight\* -DestinationPath $zipName
          Get-ChildItem $zipName

      - name: Upload zip artifact
        uses: actions/upload-artifact@v4
        with:
          name: windows-zip
          path: "*.zip"
          if-no-files-found: error

  release:
    needs: [build-macos, build-windows]
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - name: Download all artifacts
        uses: actions/download-artifact@v4
        with:
          path: artifacts

      - name: List artifacts
        run: ls -laR artifacts

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ github.ref_name }}
          name: SpireSight ${{ github.ref_name }}
          generate_release_notes: true
          prerelease: ${{ contains(github.ref_name, '-') }}
          fail_on_unmatched_files: true
          files: |
            artifacts/macos-dmg/*.dmg
            artifacts/windows-zip/*.zip
```

- [ ] **Step 2: Commit on the same PR branch**

```bash
git add .github/workflows/release.yml
git commit -m "ci(release): tag-driven Mac arm64 DMG + Win x64 zip release"
git push
```

- [ ] **Step 3: Watch the PR's CI run again**

Run:
```bash
gh run watch
```

Expected: `ci.yml` re-runs and passes (release.yml does not trigger on PR — only on tag). If green, merge the PR:

```bash
gh pr merge --squash --delete-branch
```

---

## Task 7: End-to-end smoke test with a throwaway tag

This validates the `release.yml` workflow against the real macOS + Windows runners. We use a clearly-marked prerelease tag, then clean up.

- [ ] **Step 1: Pull merged main**

```bash
git checkout main
git pull
```

- [ ] **Step 2: Push a smoke-test tag**

```bash
git tag v0.0.1-smoke.1
git push origin v0.0.1-smoke.1
```

- [ ] **Step 3: Watch the release workflow**

```bash
gh run watch
```

Expected: `test` matrix (both Python versions) passes, then `build-macos` and `build-windows` run in parallel and succeed, then `release` creates a GitHub Release flagged as prerelease.

If any job fails: read the logs, fix the workflow on a new branch (PR + merge), then delete the tag (Step 6) and retry.

- [ ] **Step 4: Inspect the release**

Run:
```bash
gh release view v0.0.1-smoke.1
```

Expected output includes two assets: `SpireSight-0.0.1-smoke.1-macos-arm64.dmg` and `SpireSight-0.0.1-smoke.1-windows-x64.zip`, with `Prerelease: true`.

- [ ] **Step 5: Manual artifact validation**

Download both assets from the GitHub Releases page:

**macOS:**
1. Open the DMG.
2. Drag `SpireSight.app` to `/Applications`.
3. Run `xattr -dr com.apple.quarantine /Applications/SpireSight.app`.
4. Launch from Applications. Confirm window opens.
5. Check version: in the app, look for the version string in the title bar / About menu (or verify via Finder → Get Info → Version on the .app — should show `0.0.1-smoke.1`).

**Windows** (if you have access — otherwise note this as a known gap and ask a Windows user to verify before any real release):
1. Extract the zip.
2. Run `SpireSight.exe`. Click through SmartScreen "Run anyway".
3. Confirm window opens.

- [ ] **Step 6: Clean up the smoke tag and release**

```bash
gh release delete v0.0.1-smoke.1 --yes
git push --delete origin v0.0.1-smoke.1
git tag -d v0.0.1-smoke.1
```

Expected: tag and release both gone.

---

## Task 8: Enable branch protection (manual GitHub UI)

The branch protection rule cannot be set via workflow file — it must be configured once in the GitHub web UI.

- [ ] **Step 1: Navigate to branch protection settings**

Open: `https://github.com/JarrettChen217/SpireSight/settings/branches`

- [ ] **Step 2: Add a rule for `main`**

Click **Add branch protection rule** (or **Add rule**). Set:

- **Branch name pattern:** `main`
- ☑ **Require a pull request before merging**
  - ☑ Require approvals (1) — optional but recommended for solo work, set to 0 if you want to self-merge without approval friction
- ☑ **Require status checks to pass before merging**
  - ☑ Require branches to be up to date before merging
  - **Status checks that are required:** type `test` in the search box and select both:
    - `test (3.11)`
    - `test (3.12)`
- ☑ **Do not allow bypassing the above settings** — optional but recommended

Click **Create** (or **Save changes**).

- [ ] **Step 3: Verify protection is active**

Run:
```bash
gh api repos/JarrettChen217/SpireSight/branches/main/protection
```

Expected: JSON output describing the rule with `required_status_checks.contexts` containing `test (3.11)` and `test (3.12)`.

- [ ] **Step 4: No commit needed**

This task only changes GitHub-side configuration, not the repo.

---

## Self-review notes

- All spec sections (§2 decisions, §3 workflow architecture, §4 spec change, §5 pyproject changes, §6 repo additions, §7 operator workflow, §10 secrets, §11 branch protection, §13 acceptance criteria) are covered by Tasks 1–8.
- Task 7 acceptance includes verifying both DMG (Mac) and zip (Win) launch — covers spec §13 #3 and #4.
- Tag prerelease behaviour (spec §13 #5) is exercised by Task 7's `v0.0.1-smoke.1` tag.
- Test-fails-blocks-release (spec §13 #6) is not explicitly exercised; it would require intentionally breaking a test before tagging, which is overkill for the smoke. The `needs: test` dependency in `release.yml` is read-and-verified during code review.
- Acceptance #1 (PR blocked on failing test) becomes true only after Task 8.

---

## Hand-off notes for the executor

- Use `superpowers:subagent-driven-development` to walk through tasks one at a time.
- Tasks 1–4 are independent and can be done in any order. Tasks 5 and 6 belong on the same PR branch. Task 7 must follow Task 6's merge. Task 8 follows Task 7.
- The smoke test in Task 7 will create (and then delete) a real GitHub Release. Confirm this is acceptable before running.
- If Apple Silicon hardware is unavailable, you cannot validate the Mac DMG locally — the CI build succeeding is the next-best signal, and the user (HaoChen, on Apple Silicon) can verify post-merge.
