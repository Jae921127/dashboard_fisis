# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('_local', '_local'),
        ('assets', 'assets')],
    hiddenimports = [
    "dash",
    "dash.dependencies",
    "dash.exceptions",
    "diskcache",
    "pandas",
    "plotly.colors",
    "plotly.express",
    "plotly.graph_objects",
    "plotly.subplots",
    "requests",
    "openpyxl"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FisisAnalytics',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FisisAnalytics',
)
