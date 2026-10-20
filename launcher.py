"""Windowed app entry point and offline package acceptance check."""
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "--verify-file":
        import hashlib
        from converter import convert_file
        source, destination, report_path = map(Path, sys.argv[2:])
        def fingerprint():
            with source.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest()
        before = fingerprint()
        result = convert_file(source, destination)
        result["source_unchanged"] = fingerprint() == before
        result["source_sha256"] = before
        result["frozen"] = bool(getattr(sys, "frozen", False))
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if not result["source_unchanged"]:
            raise RuntimeError("Input changed during verification")
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from verify_app import run_verification
        result = run_verification(Path(sys.argv[2]))
        if sys.stdout is not None:
            print(json.dumps(result, ensure_ascii=False))
        return
    from gui import main as gui_main
    gui_main()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        error = traceback.format_exc()
        log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AudioBatchConverter"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "error.log").write_text(error, encoding="utf-8")
        except OSError:
            pass
        if len(sys.argv) > 1 and sys.argv[1] in {"--self-test", "--verify-file"}:
            if sys.stderr is not None:
                sys.stderr.write(error)
            raise SystemExit(1)
        import tkinter as tk
        from tkinter import messagebox
        window = tk.Tk()
        window.withdraw()
        messagebox.showerror("启动失败", f"工具未能正常启动。错误日志：\n{log_dir / 'error.log'}", parent=window)
        window.destroy()
        raise SystemExit(1)
