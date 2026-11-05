# -*- mode: python ; coding: utf-8 -*-

import re
from pathlib import Path

_init = Path("agentbell/__init__.py").read_text(encoding="utf-8")
_version = re.search(r'__version__ = "([^"]+)"', _init).group(1)

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("assets/agentbell.ico", "assets"),
        ("assets/agentbell.svg", "assets"),
    ],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.lifespan.off",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AgentBell",
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
    icon="assets/agentbell.icns",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AgentBell",
)

app = BUNDLE(
    coll,
    name="AgentBell.app",
    icon="assets/agentbell.icns",
    bundle_identifier="com.agentbell.app",
    info_plist={
        "CFBundleDisplayName": "AgentBell",
        "CFBundleShortVersionString": _version,
        "CFBundleVersion": _version,
        "LSMinimumSystemVersion": "14.0",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
)
