"""Offline batch audio converter GUI. No Tk calls are made by worker threads."""
from __future__ import annotations

import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from converter import ConversionCancelled, SUPPORTED_EXTENSIONS, convert_file, resource_path


APP_NAME = "MGG 批量转 MP3"
BG = "#f4f7fa"
FG = "#172d40"
MUTED = "#617486"
BLUE = "#087ca7"


class Application:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        if resource_path("icon.ico").is_file():
            self.root.iconbitmap(str(resource_path("icon.ico")))
        self.root.geometry("1080x760")
        self.root.minsize(850, 650)
        self.root.configure(background=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.events: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.mode = "idle"
        self.items: dict[str, dict] = {}
        self.known_paths: set[str] = set()
        self.next_id = 0
        self.output_is_custom = False
        self.output_dir = tk.StringVar()
        self.bitrate = tk.StringVar(value="320k")
        self.summary = tk.StringVar(value="还没有文件，请添加文件或文件夹")
        self.status = tk.StringVar(value="准备就绪")
        self.progress_label = tk.StringVar(value="0 / 0")
        self.current_iid: str | None = None
        self.closing_when_idle = False
        self._set_style()
        self._build_ui()
        self._refresh_controls()
        self.root.after(80, self._drain_events)

    def _set_style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        self.root.option_add("*Font", ("Microsoft YaHei UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 23, "bold"))
        style.configure("Subtitle.TLabel", foreground=MUTED)
        style.configure("Hint.TLabel", foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("TButton", padding=(12, 7))
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Treeview", rowheight=33, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"), padding=(8, 7))
        style.configure("Horizontal.TProgressbar", background=BLUE)
        style.configure("TRadiobutton", background=BG)

    def _build_ui(self) -> None:
        page = ttk.Frame(self.root, padding=(24, 20, 24, 16))
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(4, weight=1)

        ttk.Label(page, text=APP_NAME, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(page, text="添加音乐 → 选择输出目录 → 开始转换", style="Subtitle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(5, 3))
        ttk.Label(page, text="支持自带密钥的 MGG / MFLAC 和普通 OGG / FLAC；需要外部密钥的文件会说明原因。",
                  style="Hint.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 13))

        toolbar = ttk.Frame(page)
        toolbar.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        self.add_button = ttk.Button(toolbar, text="添加文件", command=self._add_files)
        self.add_button.pack(side="left")
        self.folder_button = ttk.Button(toolbar, text="添加文件夹", command=self._add_folder)
        self.folder_button.pack(side="left", padx=(8, 0))
        self.remove_button = ttk.Button(toolbar, text="移除所选", command=self._remove_selected)
        self.remove_button.pack(side="left", padx=(20, 0))
        self.clear_button = ttk.Button(toolbar, text="清空列表", command=self._clear)
        self.clear_button.pack(side="left", padx=(8, 0))
        ttk.Label(toolbar, textvariable=self.summary, style="Hint.TLabel").pack(side="right", padx=(12, 0))

        table = ttk.Frame(page)
        table.grid(row=4, column=0, sticky="nsew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=("name", "status", "output"), show="headings", selectmode="extended")
        self.tree.heading("name", text="源文件")
        self.tree.heading("status", text="状态")
        self.tree.heading("output", text="输出文件")
        self.tree.column("name", width=370, minwidth=240, stretch=True)
        self.tree.column("status", width=110, minwidth=85, stretch=False, anchor="center")
        self.tree.column("output", width=370, minwidth=230, stretch=True)
        self.tree.tag_configure("success", foreground="#16734c")
        self.tree.tag_configure("error", foreground="#bc3838")
        self.tree.tag_configure("working", foreground=BLUE)
        self.tree.tag_configure("waiting", foreground=MUTED)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._show_selected_details)
        self.tree.bind("<Delete>", lambda _event: self._remove_selected())

        details = ttk.Frame(page)
        details.grid(row=5, column=0, sticky="ew", pady=(8, 13))
        ttk.Label(details, text="文件详情", style="Hint.TLabel").pack(anchor="w")
        self.details_text = tk.Text(details, height=3, wrap="word", borderwidth=0, highlightthickness=1,
                                    highlightbackground="#dbe3eb", background="#ffffff", foreground=MUTED,
                                    padx=9, pady=7, font=("Microsoft YaHei UI", 9))
        self.details_text.pack(fill="x", pady=(4, 0))
        self._set_details("选中文件可查看完整路径、转换结果或失败原因。")

        output = ttk.Frame(page)
        output.grid(row=6, column=0, sticky="ew")
        output.columnconfigure(1, weight=1)
        ttk.Label(output, text="输出目录").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.output_entry = ttk.Entry(output, textvariable=self.output_dir, state="readonly")
        self.output_entry.grid(row=0, column=1, sticky="ew", ipady=4)
        self.browse_button = ttk.Button(output, text="选择目录", command=self._choose_output)
        self.browse_button.grid(row=0, column=2, padx=(8, 0))
        self.open_button = ttk.Button(output, text="打开输出", command=self._open_output)
        self.open_button.grid(row=0, column=3, padx=(8, 0))

        quality = ttk.Frame(page)
        quality.grid(row=7, column=0, sticky="ew", pady=(12, 12))
        ttk.Label(quality, text="MP3 码率").pack(side="left", padx=(0, 14))
        self.quality_buttons = []
        for rate in ("320k", "256k", "192k"):
            button = ttk.Radiobutton(quality, text=f"{rate[:-1]} kbps", value=rate, variable=self.bitrate)
            button.pack(side="left", padx=(0, 18))
            self.quality_buttons.append(button)
        ttk.Label(quality, text="保留源文件 · 同名自动另存 · 全程本地处理", style="Hint.TLabel").pack(side="right")

        controls = ttk.Frame(page)
        controls.grid(row=8, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(controls, maximum=1, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        ttk.Label(controls, textvariable=self.progress_label, width=11, anchor="center").grid(row=0, column=1)
        self.cancel_button = ttk.Button(controls, text="取消", command=self._cancel)
        self.cancel_button.grid(row=0, column=2, padx=(10, 8))
        self.start_button = ttk.Button(controls, text="开始转换", style="Accent.TButton", command=self._start)
        self.start_button.grid(row=0, column=3)
        self.status_label = ttk.Label(page, textvariable=self.status, style="Hint.TLabel", wraplength=980)
        self.status_label.grid(row=9, column=0, sticky="w", pady=(10, 0))

    def _set_details(self, text: str) -> None:
        self.details_text.configure(state="normal")
        self.details_text.delete("1.0", "end")
        self.details_text.insert("1.0", text)
        self.details_text.configure(state="disabled")

    def _show_selected_details(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            self._set_details("选中文件可查看完整路径、转换结果或失败原因。")
            return
        item = self.items.get(selection[0])
        if item is None:
            return
        lines = [f"源文件：{item['path']}"]
        if item["output"]:
            lines.append(f"输出：{item['output']}")
        lines.append(item["message"] or f"状态：{item['status']}")
        self._set_details("\n".join(lines))

    def _add_files(self) -> None:
        patterns = " ".join(f"*{extension}" for extension in sorted(SUPPORTED_EXTENSIONS))
        paths = filedialog.askopenfilenames(parent=self.root, title="选择需要转换的音乐文件",
                                            filetypes=[("支持的音乐文件", patterns), ("所有文件", "*.*")])
        if paths:
            self.add_paths(paths)

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self.root, title="选择文件夹（包含子文件夹）")
        if folder:
            self.add_paths([folder])

    def add_paths(self, paths) -> None:
        """Queue file/folder discovery; safe entry point from the Tk thread."""
        if self.mode != "idle":
            return
        paths = [Path(path).expanduser() for path in paths]
        if not paths:
            return
        if not self.output_dir.get():
            first = paths[0]
            self.output_dir.set(str((first if first.is_dir() else first.parent) / "MP3输出"))
        excluded_output = Path(self.output_dir.get()).resolve()
        self.mode = "scanning"
        self.cancel_event.clear()
        self.status.set("正在读取文件列表…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self._refresh_controls()
        self.worker = threading.Thread(target=self._scan_worker, args=(paths, excluded_output), daemon=True, name="audio-file-scan")
        self.worker.start()

    def _scan_worker(self, paths: list[Path], excluded_output: Path) -> None:
        pending: list[Path] = []
        skipped = 0
        errors: list[str] = []

        def add_file(path: Path) -> None:
            nonlocal skipped
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                pending.append(path.resolve())
                if len(pending) >= 100:
                    self.events.put(("files", list(pending)))
                    pending.clear()
            else:
                skipped += 1

        def scan_error(error: OSError) -> None:
            errors.append(str(error))

        def is_output(path: Path) -> bool:
            resolved = path.resolve()
            return resolved == excluded_output or excluded_output in resolved.parents

        try:
            for path in paths:
                if self.cancel_event.is_set():
                    break
                if path.is_file():
                    add_file(path)
                elif path.is_dir():
                    for directory, directories, filenames in os.walk(path, onerror=scan_error, followlinks=False):
                        if self.cancel_event.is_set():
                            break
                        # Do not feed generated MP3 files back into a recursive import.
                        if is_output(Path(directory)):
                            directories.clear()
                            continue
                        directories[:] = sorted(name for name in directories if not is_output(Path(directory) / name))
                        for filename in sorted(filenames):
                            if self.cancel_event.is_set():
                                break
                            add_file(Path(directory) / filename)
                else:
                    errors.append(f"文件不存在：{path}")
        except Exception as error:
            errors.append(str(error))
        finally:
            if pending:
                self.events.put(("files", list(pending)))
            self.events.put(("scan_done", skipped, errors, self.cancel_event.is_set()))

    def _insert_files(self, paths: list[Path]) -> None:
        for path in paths:
            key = os.path.normcase(str(path))
            if key in self.known_paths:
                continue
            self.known_paths.add(key)
            iid = str(self.next_id)
            self.next_id += 1
            self.items[iid] = {"path": path, "key": key, "status": "等待转换", "output": "", "message": ""}
            self.tree.insert("", "end", iid=iid, values=(path.name, "等待转换", ""), tags=("waiting",))
            if not self.output_dir.get():
                self.output_dir.set(str(path.parent / "MP3输出"))
        self._update_summary()

    def _remove_selected(self) -> None:
        if self.mode != "idle":
            return
        for iid in self.tree.selection():
            item = self.items.pop(iid, None)
            if item is not None:
                self.known_paths.discard(item["key"])
            self.tree.delete(iid)
        self._update_summary()
        self._show_selected_details()
        self._refresh_controls()

    def _clear(self) -> None:
        if self.mode != "idle":
            return
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.items.clear()
        self.known_paths.clear()
        if not self.output_is_custom:
            self.output_dir.set("")
        self.progress["value"] = 0
        self.progress_label.set("0 / 0")
        self.status.set("准备就绪")
        self._show_selected_details()
        self._update_summary()
        self._refresh_controls()

    def _choose_output(self) -> None:
        directory = filedialog.askdirectory(parent=self.root, title="选择 MP3 输出目录",
                                            initialdir=self.output_dir.get() or str(Path.home()))
        if directory:
            self.output_dir.set(directory)
            self.output_is_custom = True
            self._refresh_controls()

    def _open_output(self) -> None:
        directory = Path(self.output_dir.get())
        if not self.output_dir.get() or not directory.is_dir():
            messagebox.showinfo(APP_NAME, "输出目录将在首次成功转换时创建。", parent=self.root)
            return
        try:
            os.startfile(str(directory))
        except OSError as error:
            messagebox.showerror("无法打开目录", str(error), parent=self.root)

    def _start(self) -> None:
        if self.mode != "idle":
            return
        jobs = [(iid, item["path"]) for iid, item in self.items.items() if item["status"] != "成功"]
        if not jobs:
            return
        if not self.output_dir.get():
            self.output_dir.set(str(jobs[0][1].parent / "MP3输出"))
        destination = Path(self.output_dir.get())
        bitrate = self.bitrate.get()
        self.cancel_event.clear()
        self.mode = "converting"
        self.progress.configure(mode="determinate", maximum=len(jobs), value=0)
        self.progress_label.set(f"0 / {len(jobs)}")
        for iid, _path in jobs:
            self._set_item(iid, "等待转换", "", "", "waiting")
        self.status.set(f"准备转换 {len(jobs)} 个文件…")
        self._refresh_controls()
        self.worker = threading.Thread(target=self._convert_worker, args=(jobs, destination, bitrate),
                                       daemon=True, name="audio-batch-converter")
        self.worker.start()

    def _convert_worker(self, jobs: list[tuple[str, Path]], destination: Path, bitrate: str) -> None:
        success = failures = completed = 0
        fatal_error = ""
        try:
            for iid, source in jobs:
                if self.cancel_event.is_set():
                    break
                self.events.put(("begin", iid, source.name))
                try:
                    result = convert_file(source, destination, bitrate=bitrate, cancel_event=self.cancel_event,
                                          progress=lambda message, key=iid: self.events.put(("message", key, str(message))))
                except ConversionCancelled:
                    self.events.put(("item", iid, "已取消", "", "转换已取消，源文件未修改。", "waiting"))
                    break
                except Exception as error:
                    failures += 1
                    reason = str(error).strip() or type(error).__name__
                    self.events.put(("item", iid, "失败", "", reason, "error"))
                else:
                    success += 1
                    output = str(result.get("output", ""))
                    self.events.put(("item", iid, "成功", output, "转换完成，源文件已保留。", "success"))
                completed += 1
                self.events.put(("progress", completed, len(jobs)))
        except Exception as error:
            fatal_error = str(error).strip() or type(error).__name__
        finally:
            self.events.put(("batch_done", success, failures, self.cancel_event.is_set(), fatal_error))

    def _cancel(self) -> None:
        if self.mode == "idle":
            return
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.status.set("正在取消，请稍候…")

    def _set_item(self, iid: str, status: str, output: str, message: str, tag: str) -> None:
        item = self.items.get(iid)
        if item is None:
            return
        item.update(status=status, output=output, message=message)
        self.tree.item(iid, values=(item["path"].name, status, Path(output).name if output else ""), tags=(tag,))
        if iid in self.tree.selection():
            self._show_selected_details()
        self._update_summary()

    def _update_summary(self) -> None:
        total = len(self.items)
        success = sum(item["status"] == "成功" for item in self.items.values())
        failures = sum(item["status"] == "失败" for item in self.items.values())
        self.summary.set(f"共 {total} 个 · 成功 {success} · 失败 {failures}" if total else "还没有文件")

    def _refresh_controls(self) -> None:
        idle = self.mode == "idle"
        for widget in (self.add_button, self.folder_button, self.browse_button, *self.quality_buttons):
            widget.configure(state="normal" if idle else "disabled")
        for widget in (self.remove_button, self.clear_button):
            widget.configure(state="normal" if idle and self.items else "disabled")
        pending = any(item["status"] != "成功" for item in self.items.values())
        self.start_button.configure(state="normal" if idle and pending else "disabled")
        self.cancel_button.configure(state="normal" if not idle and not self.cancel_event.is_set() else "disabled")
        self.open_button.configure(state="normal" if self.output_dir.get() else "disabled")

    def _drain_events(self) -> None:
        try:
            # Bound each pass so large batches cannot starve Tk input events.
            for _ in range(150):
                event = self.events.get_nowait()
                kind, *payload = event
                if kind == "files":
                    self._insert_files(payload[0])
                elif kind == "scan_done":
                    skipped, errors, cancelled = payload
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0, maximum=max(1, len(self.items)))
                    self.progress_label.set(f"0 / {len(self.items)}")
                    self.mode = "idle"
                    self.worker = None
                    self.status.set(("已停止读取" if cancelled else "文件列表已更新") +
                                    (f"；跳过 {skipped} 个不支持的文件" if skipped else "") +
                                    (f"；{len(errors)} 个路径无法读取" if errors else ""))
                    if errors:
                        self._set_details("\n".join(errors[:10]))
                    self._refresh_controls()
                elif kind == "begin":
                    iid, name = payload
                    self.current_iid = iid
                    self._set_item(iid, "转换中", "", "正在处理…", "working")
                    self.tree.see(iid)
                    self.status.set(f"正在转换：{name}")
                elif kind == "message":
                    iid, message = payload
                    if iid in self.items:
                        self.items[iid]["message"] = message
                        if iid in self.tree.selection():
                            self._show_selected_details()
                        if not self.cancel_event.is_set():
                            self.status.set(f"{self.items[iid]['path'].name}：{message}")
                elif kind == "item":
                    self._set_item(*payload)
                elif kind == "progress":
                    completed, total = payload
                    self.progress["value"] = completed
                    self.progress_label.set(f"{completed} / {total}")
                elif kind == "batch_done":
                    success, failures, cancelled, fatal_error = payload
                    self.mode = "idle"
                    self.worker = None
                    self.current_iid = None
                    self.status.set(("已取消" if cancelled else "转换结束") +
                                    f"：本次成功 {success} 个，失败 {failures} 个。" +
                                    ("选中失败文件可查看原因。" if failures else ""))
                    if fatal_error:
                        self.status.set(f"转换中断：{fatal_error}")
                        self._set_details(fatal_error)
                    elif failures and not self.tree.selection():
                        failed_iid = next(iid for iid, item in self.items.items() if item["status"] == "失败")
                        self.tree.selection_set(failed_iid)
                        self._show_selected_details()
                    self._refresh_controls()
        except queue.Empty:
            pass
        if self.closing_when_idle and self.mode == "idle":
            self.root.destroy()
            return
        self.root.after(80, self._drain_events)

    def _on_close(self) -> None:
        if self.mode == "idle":
            self.root.destroy()
            return
        if self.closing_when_idle:
            return
        if messagebox.askyesno("取消并关闭", "当前任务尚未结束。要取消任务并关闭工具吗？\n已完成的 MP3 会保留，源文件不会修改。",
                               parent=self.root):
            self.closing_when_idle = True
            self._cancel()


def main() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    application = Application(root)
    paths = [value for value in sys.argv[1:] if not value.startswith("--")]
    if paths:
        root.after(150, lambda: application.add_paths(paths))
    root.mainloop()


if __name__ == "__main__":
    main()
