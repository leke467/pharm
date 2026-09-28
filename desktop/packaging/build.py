"""
Desktop Application Build & Packaging Script (Architecture Plan §17).
Validates prerequisites, invokes PyInstaller, and verifies build artifacts.
"""

import os
import subprocess
import sys
from pathlib import Path


def main():
    root_dir = Path(__file__).parent.parent.parent.resolve()
    spec_file = Path(__file__).parent / "pharmacy.spec"
    dist_dir = Path(__file__).parent / "dist"
    build_dir = Path(__file__).parent / "build"

    print(f"[*] Packaging Pharmacy Management Desktop App from {root_dir}")
    print(f"[*] Spec file: {spec_file}")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir),
        str(spec_file),
    ]

    print(f"[*] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(root_dir))
    if result.returncode != 0:
        print("[!] PyInstaller build failed!")
        sys.exit(result.returncode)

    output_exe = dist_dir / "PharmacyManagement" / "PharmacyManagement.exe"
    if output_exe.exists():
        print(f"[+] Build SUCCESS! Executable created at: {output_exe}")
    else:
        print(f"[-] Build finished, but expected executable not found at: {output_exe}")


if __name__ == "__main__":
    main()
