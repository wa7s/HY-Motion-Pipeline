"""Entry point for HY Motion Studio (windowed - no console)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Qt's WebEngine needs a software-GL fallback path on some laptop GPUs and
# must not try to use a sandbox it cannot create from a portable install.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu-sandbox")

from hymstudio.main import main

if __name__ == "__main__":
    main()
