import sys
import argparse
import os
import platform

# Set Windows AppUserModelID BEFORE any Qt imports so the taskbar shows
# the PharmaCare icon instead of the default Python interpreter icon.
if platform.system() == "Windows":
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        "pharmacare.enterprise.desktop.1.0"
    )

from PySide6.QtWidgets import QApplication

# Ensure parent directory is in sys.path to import shared.enums
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from desktop.app.application import PharmacyApplication

def main():
    parser = argparse.ArgumentParser(description="Pharmacy Management System")
    parser.add_argument("--server-url", help="Backend API Server URL")
    parser.add_argument("--data-dir", help="Local Data Directory")
    parser.add_argument("--log-level", help="Logging Level", default="INFO")
    parser.add_argument("--apply-wizard-setup", action="store_true", help="Apply Setup Wizard onboarding JSON and exit")
    args = parser.parse_args()

    app = PharmacyApplication(sys.argv, args)
    if getattr(args, "apply_wizard_setup", False):
        sys.exit(0)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

