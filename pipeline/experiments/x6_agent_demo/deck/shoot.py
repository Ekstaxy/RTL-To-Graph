"""Screenshots of demo sessions with headless Edge: python shoot.py name=session[&scroll=top] ..."""
import subprocess
import sys
from pathlib import Path

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
OUT = Path(__file__).resolve().parent / "shots"
OUT.mkdir(exist_ok=True)
for arg in sys.argv[1:]:
    name, q = arg.split("=", 1)
    f = OUT / f"{name}.png"
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2", "--window-size=1440,900",
                    "--virtual-time-budget=6000", f"--screenshot={f}", f"http://localhost:8765/?session={q}"], capture_output=True, timeout=120)
    print(name, f.exists() and f.stat().st_size)
