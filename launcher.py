"""GUI entry point; internal verification also runs from the frozen executable."""
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--verify":
        from verify_app import run_verification
        result = run_verification(Path(sys.argv[2]), Path(sys.argv[3]))
        if sys.stdout is not None:
            print(json.dumps(result, ensure_ascii=True))
        return
    from gui import main as gui_main
    gui_main()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        error = traceback.format_exc()
        if len(sys.argv) > 1 and sys.argv[1] == "--verify":
            if sys.stderr is not None:
                sys.stderr.write(error)
            raise SystemExit(1)
        log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MGGBatchConverter"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "error.log").write_text(error, encoding="utf-8")
        except OSError:
            pass
        import tkinter as tk
        from tkinter import messagebox
        window = tk.Tk()
        window.withdraw()
        messagebox.showerror("启动失败", f"工具未能正常启动。错误日志：\n{log_dir / 'error.log'}", parent=window)
        window.destroy()
        raise SystemExit(1)
