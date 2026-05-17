# CI/CD & Release Automation — Design

**Status:** Approved · **Date:** 2026-05-16 · **Owner:** HaoChen

## 1. Goal

Automate Mac (arm64) + Windows (x64) builds and GitHub Releases for
SpireSight, triggered by SemVer git tags. Protect `main` with PR-time
lint/type/test gates. No code signing in this iteration.

## 2. Locked decisions

| Dimension | Choice | Reason |
|---|---|---|
| Release trigger | Push of `v*.*.*` tag only | Keeps release list clean; no nightly noise |
| Code signing | None | Avoids Apple Developer ($) + Win cert ($$$) for MVP; doc Gatekeeper / SmartScreen workarounds in README |
| macOS architecture | arm64 only, `macos-14` runner | Native build; covers all 2020+ Macs; matches dev hardware |
| Windows architecture | x64 only, `windows-latest` runner | GitHub default; arm64 Windows demand negligible |
| Artifact format | Mac `.dmg` + Win `.zip` | DMG is conventional Mac UX; unsigned Win installer is worse than zip under SmartScreen |
| Version source | Git tag → injected at build time | Single source of truth; no "forgot to bump pyproject" footgun |
| Test gating | PR + main push + tag; tag failure blocks release | Quality gate at every entry point |
| Python (CI matrix) | 3.11 + 3.12 | Guards against 3.12-only syntax; release pins 3.11 |
| Python (release build) | 3.11 only | Matches `requires-python = ">=3.11"` floor |

## 3. Workflow architecture

Two workflow files; one reusable concept (test job logic duplicated, ~6
lines, acceptable for MVP — promote to reusable workflow if it grows).

### 3.1 `.github/workflows/ci.yml`

- **Triggers:** `pull_request` (any branch → `main`), `push` to `main`
- **Job `test`** (matrix on `python-version: [3.11, 3.12]`, `runs-on: ubuntu-latest`):
  - `actions/checkout@v4`
  - `actions/setup-python@v5` with `cache: pip`
  - `pip install -e ".[dev]"` (ruff + mypy now part of `[dev]` — see §5)
  - `ruff check src tests`
  - `mypy src`
  - `pytest -q`
- **Concurrency:** `group: ci-${{ github.ref }}`, `cancel-in-progress: true`
- **Permissions:** default read-only

### 3.2 `.github/workflows/release.yml`

- **Trigger:** `push: tags: ['v*.*.*']`
- **Top-level:** `permissions: contents: read`; `concurrency: { group: release-${{ github.ref }}, cancel-in-progress: false }`

**Job graph:**

```
test ──┬─→ build-macos ──┐
       └─→ build-windows ─┴─→ release
```

#### Job `test`
Identical to `ci.yml`'s test job (matrix 3.11 + 3.12). Blocks all
downstream jobs on failure.

#### Job `build-macos`
- `runs-on: macos-14`
- `needs: test`
- Steps:
  1. checkout, setup-python 3.11
  2. Extract version: `VERSION="${GITHUB_REF_NAME#v}"`, export as
     `SPIRESIGHT_VERSION`, also `sed -i ''` into `pyproject.toml`
  3. `pip install -e ".[dev]" pyinstaller`
  4. `pyinstaller --noconfirm packaging/spiresight.spec`
  5. `brew install create-dmg`
  6. `create-dmg --volname "SpireSight $VERSION" \
       "SpireSight-${VERSION}-macos-arm64.dmg" "dist/SpireSight.app"`
     (default window layout — no custom icon positions, no background)
  7. `actions/upload-artifact@v4` name=`macos-dmg`, path=`*.dmg`

#### Job `build-windows`
- `runs-on: windows-latest`
- `needs: test`
- Steps mirror macOS:
  1. checkout, setup-python 3.11
  2. Extract version via PowerShell:
     `$env:SPIRESIGHT_VERSION = $env:GITHUB_REF_NAME -replace '^v',''`,
     then `(Get-Content pyproject.toml) -replace '^version = .*', "version = `"$env:SPIRESIGHT_VERSION`"" | Set-Content pyproject.toml`
  3. `pip install -e ".[dev]" pyinstaller`
  4. `pyinstaller --noconfirm packaging\spiresight.spec`
  5. `Compress-Archive -Path dist\SpireSight\* -DestinationPath "SpireSight-$env:SPIRESIGHT_VERSION-windows-x64.zip"`
  6. upload-artifact name=`windows-zip`, path=`*.zip`

#### Job `release`
- `runs-on: ubuntu-latest`
- `needs: [build-macos, build-windows]`
- `permissions: { contents: write }` (job-scoped, minimal)
- Steps:
  1. `actions/download-artifact@v4` (no name = pulls all)
  2. `softprops/action-gh-release@v2` with:
     - `tag_name: ${{ github.ref_name }}`
     - `name: SpireSight ${{ github.ref_name }}`
     - `generate_release_notes: true`
     - `prerelease: ${{ contains(github.ref_name, '-') }}`
     - `files: |
         **/*.dmg
         **/*.zip`
     - `fail_on_unmatched_files: true`

### 3.3 Action pinning
All actions pinned to major (`@v4`, `@v5`, `@v2`). Dependabot can later
auto-PR upgrades. SHA-pinning deferred (overkill for MVP).

## 4. PyInstaller spec change

`packaging/spiresight.spec` reads `SPIRESIGHT_VERSION` from env and
passes it into the macOS `BUNDLE(...)` via `info_plist={
"CFBundleShortVersionString": version, "CFBundleVersion": version }`.
Windows EXE metadata is left default (PyInstaller's optional version
resource is not introduced — MVP YAGNI).

If `SPIRESIGHT_VERSION` is unset (local builds), spec falls back to
`"0.0.0+dev"`.

## 5. `pyproject.toml` changes

- `version = "0.0.0+dev"` (placeholder; CI injects real value)
- `[project.optional-dependencies].dev` adds `ruff` and `mypy` so local
  `pip install -e ".[dev]"` matches CI exactly

## 6. Repo additions / edits

| Path | Action |
|---|---|
| `.github/workflows/ci.yml` | new |
| `.github/workflows/release.yml` | new |
| `packaging/spiresight.spec` | edit — env-driven version |
| `pyproject.toml` | edit — `0.0.0+dev` placeholder, ruff/mypy in `[dev]` |
| `README.md` | edit — append "Release process" + "Installation (unsigned)" sections |
| `.gitignore` | edit — ensure `dist/`, `build/`, `*.dmg` are ignored |

`packaging/build.sh` and `build.bat` are kept for local debugging,
unchanged.

## 7. Release operator workflow

```bash
git checkout main && git pull
git tag v0.1.1                      # do NOT edit pyproject first
git push origin v0.1.1
# wait ~8–12 min for Actions
```

Pre-release: tag with a hyphen (e.g. `v0.2.0-rc.1`) — workflow auto-flags
`prerelease: true`.

Rollback: `git push --delete origin <tag>` + `git tag -d <tag>` +
manually delete the release from the GitHub Releases UI.

## 8. Failure modes & recovery

| Failure | Effect | Recovery |
|---|---|---|
| `test` fails on tag | All downstream jobs skip; no release | Fix code, delete + repush tag |
| `build-macos` fails (e.g. missing hiddenimport) | Windows continues; `release` skipped | Fix `spiresight.spec`, delete + repush tag |
| `build-windows` fails | Symmetric | Same |
| `release` fails (e.g. token, file glob) | Artifacts uploaded to workflow run; no release | Fix workflow, re-run failed jobs (no retag) |
| Bad release reaches users | — | Add ⚠️ to release notes; for severe issues, mark prior release as draft and ship a patch version |

No automated "yank" — manual draft-toggle is sufficient for MVP volume.

## 9. Observability

- GitHub Actions UI for run status
- GitHub Releases page for asset download counts
- No external monitoring (Sentry / Slack notify) — defer

## 10. Security & secrets

`release.yml` uses **zero repository secrets**:

- `GITHUB_TOKEN` is auto-injected; elevated to `contents: write` only on
  the `release` job
- No signing → no Apple / Windows cert secrets
- No PyPI publishing → no PyPI token
- Tests don't need LLM provider API keys (project design has users
  supply keys at runtime)

This means **fork PRs can run CI safely** with no secret-leak surface.

## 11. Branch protection (manual GitHub UI setup)

After `ci.yml` runs at least once, in GitHub repo Settings → Branches:

- Protect `main`
- "Require status checks to pass before merging" → select `test (3.11)`
  and `test (3.12)`
- "Require branches to be up to date" — optional, recommended

This is a manual step (cannot be set via workflow file). Mentioned here
so the implementation plan includes a reminder.

## 12. Explicit non-goals

- Code signing / notarization (Mac or Windows)
- Universal2 binary
- Linux build artifact
- Windows installer (NSIS / Inno / MSI)
- PyPI publishing
- Auto-changelog generation beyond GitHub's built-in
- setuptools-scm / release-please / semantic-release
- Reusable workflow extraction (defer until duplication hurts)
- Cross-platform test matrix in `ci.yml` (Linux-only covers logic; mac/win
  validated implicitly by release build)
- SHA-pinned actions
- Coverage reporting

## 13. Acceptance criteria

1. Opening a PR triggers `ci.yml`; failing tests prevent merge once
   branch protection is enabled
2. Pushing `v0.1.1` creates a GitHub Release named `SpireSight v0.1.1`
   with two assets: `SpireSight-0.1.1-macos-arm64.dmg` and
   `SpireSight-0.1.1-windows-x64.zip`
3. The DMG opens, drag-to-Applications works, and `SpireSight.app`
   launches (after manual Gatekeeper bypass)
4. The Windows zip extracts to a folder where `SpireSight.exe` launches
   (after manual SmartScreen bypass)
5. Pushing `v0.1.1-rc.1` produces the same flow but with
   `prerelease: true` on the GitHub Release
6. A failing test on a tag prevents release creation
