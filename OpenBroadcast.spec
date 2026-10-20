# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)
datas = [(str(root / src), dst) for src, dst in [
    ('audio/models', 'openbroadcast/audio/models'),
    ('audio/data', 'openbroadcast/audio/data'),
    ('README.md', 'openbroadcast'),
]]
binaries = []
hiddenimports = ['pystray._win32']


a = Analysis(
    [str(root / 'run_gui.pyw')],
    pathex=[str(root.parent)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(root / 'packaging' / 'hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['onnxruntime.tools', 'onnxruntime.transformers', 'onnxruntime.quantization',
              'onnxruntime.training', 'onnxruntime.backend', 'onnxruntime.datasets',
              'PIL._imagingft', 'PIL._imagingcms', 'PIL._avif', 'PIL._webp'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OpenBroadcast',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
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
    name='OpenBroadcast',
)
