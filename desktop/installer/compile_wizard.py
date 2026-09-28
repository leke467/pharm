import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def build_installer_exe():
    desktop_dir = Path(__file__).resolve().parent.parent
    dist_app_dir = desktop_dir / "dist" / "PharmaCarePro"
    build_dir = desktop_dir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    icon_path = desktop_dir / "app" / "ui" / "resources" / "pharmacare.ico"
    if icon_path.exists() and dist_app_dir.exists():
        shutil.copy2(icon_path, dist_app_dir / "pharmacare.ico")

    payload_zip = build_dir / "payload.zip"
    if payload_zip.exists():
        payload_zip.unlink()

    print(f"[Wizard Builder] Compressing application payload from {dist_app_dir} ...")
    with zipfile.ZipFile(payload_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, _, files in os.walk(dist_app_dir):
            for file in files:
                if file.lower() == "install_pharmacarepro.bat":
                    continue
                full_path = Path(root) / file
                rel_path = full_path.relative_to(dist_app_dir).as_posix()
                zf.write(full_path, rel_path)

    csc_path = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    if not csc_path.exists():
        csc_path = Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")

    wizard_cs = desktop_dir / "installer" / "SetupWizard.cs"
    output_exe = desktop_dir / "dist" / "PharmaCarePro_Setup.exe"

    # Close any open Setup Wizard window so the file can be overwritten cleanly
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "PharmaCarePro_Setup.exe"],
            capture_output=True,
            text=True,
        )
    except Exception:
        pass

    cmd = [
        str(csc_path),
        "/target:winexe",
        f"/out:{output_exe}",
        f"/win32icon:{icon_path}",
        f"/resource:{payload_zip},payload.zip",
        "/reference:System.dll",
        "/reference:System.Drawing.dll",
        "/reference:System.Windows.Forms.dll",
        "/reference:System.IO.Compression.dll",
        "/reference:System.IO.Compression.FileSystem.dll",
        "/reference:Microsoft.CSharp.dll",
        "/optimize+",
        str(wizard_cs),
    ]

    print("[Wizard Builder] Compiling single-file Windows Setup Wizard (PharmaCarePro_Setup.exe)...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("CSC STDOUT:", result.stdout)
        print("CSC STDERR:", result.stderr)
        sys.exit(result.returncode)

    size_mb = output_exe.stat().st_size / (1024 * 1024)
    print(f"[Wizard Builder] SUCCESS! Created Setup Wizard: {output_exe} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    build_installer_exe()
