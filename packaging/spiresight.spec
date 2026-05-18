# packaging/spiresight.spec
# Run from repo root: pyinstaller packaging/spiresight.spec
# Produces a windowed (no console) bundle that includes prompts/ and resources/.
# Version is sourced from SPIRESIGHT_VERSION env var (CI sets it from the git tag).
# Falls back to "0.0.0+dev" for local builds.

import os
import sys

from PyInstaller.utils.hooks import collect_data_files  # noqa: F401  (kept for future use)

VERSION = os.environ.get("SPIRESIGHT_VERSION", "0.0.0+dev")

# SPECPATH is the directory of this spec file (packaging/).
# All relative source paths must be anchored to the repo root, one level up.
ROOT = os.path.join(SPECPATH, "..")

datas = [
    (os.path.join(ROOT, "prompts"), "prompts"),
    (os.path.join(ROOT, "src", "spiresight", "resources"), "spiresight/resources"),
    (os.path.join(ROOT, "src", "spiresight", "ui", "markdown", "style.css"),
     "spiresight/ui/markdown"),
]

a = Analysis(
    [os.path.join(ROOT, "src", "spiresight", "__main__.py")],
    pathex=[os.path.join(ROOT, "src")],
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
