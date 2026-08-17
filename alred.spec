from PyInstaller.utils.hooks import collect_data_files, collect_submodules


datas = collect_data_files("alred")
datas += collect_data_files("ntc_templates")
datas += [("pyproject.toml", ".")]
datas += [("THIRD_PARTY_LICENSES.txt", ".")]
hiddenimports = collect_submodules("netmiko")


a = Analysis(
    ["alred.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name="alred",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
