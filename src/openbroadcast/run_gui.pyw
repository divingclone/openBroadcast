"""Package launcher for login startup and the Windows portable build."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openbroadcast.i18n import tr

try:
    from openbroadcast.launcher import main
    raise SystemExit(main())
except Exception as exc:
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "OpenBroadcast",
        tr('启动失败：{exc}\n\n请在已安装 OpenBroadcast 的 Python 环境中运行：\npython -m openbroadcast', exc=exc),
    )
    root.destroy()
    raise
