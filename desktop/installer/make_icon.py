import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PySide6.QtGui import QGuiApplication
from PIL import Image
from desktop.app.ui.common.logo import create_logo_pixmap


def generate_ico(output_path: str):
    app = QGuiApplication.instance() or QGuiApplication([])
    pixmap = create_logo_pixmap(256)
    tmp_png = str(Path(output_path).with_suffix(".png"))
    pixmap.save(tmp_png, "PNG")

    img = Image.open(tmp_png)
    img.save(
        output_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    try:
        os.remove(tmp_png)
    except OSError:
        pass
    print(f"Generated icon: {output_path}")


if __name__ == "__main__":
    out = project_root / "desktop" / "app" / "ui" / "resources" / "pharmacare.ico"
    generate_ico(str(out))
