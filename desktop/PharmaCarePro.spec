# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['shared.enums', 'bcrypt', 'sqlalchemy.dialects.sqlite']
hiddenimports += collect_submodules('desktop.app.db.migrations.versions')


a = Analysis(
    ['C:/Users/Leke/Desktop/pharm/desktop/app/main.py'],
    pathex=['C:/Users/Leke/Desktop/pharm', 'C:/Users/Leke/Desktop/pharm/desktop'],
    binaries=[],
    datas=[('C:/Users/Leke/Desktop/pharm/desktop/app/ui/resources', 'desktop/app/ui/resources'), ('C:/Users/Leke/Desktop/pharm/desktop/app/db/migrations/versions', 'desktop/app/db/migrations/versions'), ('C:/Users/Leke/Desktop/pharm/shared', 'shared')],
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
    [],
    exclude_binaries=True,
    name='PharmaCarePro',
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
    icon=['C:/Users/Leke/Desktop/pharm/desktop/app/ui/resources/pharmacare.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PharmaCarePro',
)
