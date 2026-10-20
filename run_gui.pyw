"""Double-click launcher, or run `python run_gui.pyw` from this directory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if len(sys.argv) == 3 and sys.argv[1] == "--check-runtime":
    from openbroadcast.runtime_check import run
    raise SystemExit(run(sys.argv[2]))

from openbroadcast.i18n import tr

try:
    from openbroadcast.gui import main
    main()
except Exception as exc:
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "OpenBroadcast",
        tr('启动失败：{exc}\n\n请使用安装了 requirements.txt 的 Python。\n推荐：.venv\\Scripts\\pythonw.exe run_gui.pyw', exc=exc),
    )
    root.destroy()
    raise
