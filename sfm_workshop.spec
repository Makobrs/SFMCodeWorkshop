# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)
APP = ROOT / "sfm_workshop"

datas = [
    (str(APP / "resources"), "resources"),
    (str(APP / "NOTICE.md"), "."),
    (str(APP / "README.md"), "."),
    (str(APP / "requirements.txt"), "."),
]
hiddenimports = [
    "SFMLLexer",
    "SFMLParser",
    "SFMLListener",
    "PySide6.QtSvg",
    "sfm_workshop.core.importer",
    "sfm_workshop.core.workspaces",
    "sfm_workshop.ui.face_picker",
    "sfm_workshop.ui.icons",
] + collect_submodules("antlr4") + collect_submodules("pypinyin")
datas += collect_data_files("pypinyin")

a = Analysis(
    ["launcher.py"],
    pathex=[str(ROOT), str(APP / "grammar")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
# This host's antivirus intermittently locks the destination when COLLECT
# copies Microsoft runtime DLLs.  Exclude them here and copy them after
# COLLECT; they are required at runtime and are still present in the build.
a.binaries = [
    b for b in a.binaries
    if Path(b[0]).name.lower() not in {
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "msvcp140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
        "concrt140.dll",
    }
]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SFMCodeWorkshop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(APP / "resources" / "icon.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SFMCodeWorkshop",
)
