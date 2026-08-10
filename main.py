# filename: gaze_transcribe_gui_persistent_worker.py
# -*- coding: utf-8 -*-
import os
import time
import threading
import tkinter as tk
import json
import multiprocessing as mp
import queue
from tkinter import messagebox, ttk
from pathlib import Path
from PIL import Image, ImageTk
from datetime import datetime

from silence_remove import silence_remove  # 無音除去だけはGUI側import OK（モデルロードしないため）

# ============================================
# 設定
# ============================================
DWELL_MS = 700
DWELL_MS_2 = 1000
BUTTON_SIZE = (250, 250)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = Path(BASE_DIR) / "audio"
OUTPUT_DIR = Path(BASE_DIR) / "text"
SAMPLING_RATE = 16000
RTF_JSON = Path(BASE_DIR) / "rtf_est.json"
WORKER_LOG = Path(BASE_DIR) / "worker_log.txt"

# 固まり検知（必要に応じて調整）
TIMEOUT_SEC = None  


def load_image(path, size=BUTTON_SIZE):
    full_path = os.path.join(BASE_DIR, path)
    img = Image.open(full_path).resize(size, Image.LANCZOS)
    return ImageTk.PhotoImage(img)


def get_audio_duration_sec(audio_path: str) -> float:
    try:
        import librosa
        y, sr = librosa.load(audio_path, sr=None, mono=True)
        if not sr:
            return 0.0
        return float(len(y) / sr)
    except Exception:
        return 0.0


def load_rtf_est(default: float = 0.8) -> float:
    try:
        if RTF_JSON.exists():
            with open(RTF_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            v = float(data.get("rtf_est", default))
            return max(0.05, min(10.0, v))
    except Exception:
        pass
    return default


def save_rtf_est(rtf_est: float) -> None:
    try:
        with open(RTF_JSON, "w", encoding="utf-8") as f:
            json.dump({"rtf_est": float(rtf_est)}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ============================================
# ★ 常駐ワーカー：起動時に1回だけモデルをロードし、命令を待つ
# ============================================

def persistent_worker(cmd_q, out_q):
    """
    cmd_q:  {"type":"job", "audio_path": "..."} / {"type":"shutdown"}
    out_q:  status / done / error を返す

    ★重要：whisper_transcribe は「このworker内」でimportする
    → GUIプロセス側でモデルがロードされるのを防ぐ（VRAM二重使用を防止）
    """
    log_path = WORKER_LOG

    def log(msg: str):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except Exception:
            pass

    try:
        log("worker boot")
        out_q.put({"type": "status", "phase": "boot"})

        log("model warmup start")
        out_q.put({"type": "status", "phase": "model_warmup"})

        # ★ここで1回だけ import させる（この時点でモデルロードが走る）
        from whisper_transcribe import whisper_transcribe  # ←ここが最重要

        log("model warmup done")
        out_q.put({"type": "status", "phase": "ready"})

        while True:
            cmd = cmd_q.get()  # ブロック
            if not isinstance(cmd, dict):
                continue

            if cmd.get("type") == "shutdown":
                log("shutdown received")
                out_q.put({"type": "status", "phase": "shutdown"})
                return

            if cmd.get("type") != "job":
                continue

            audio_path = cmd.get("audio_path", "")
            if not audio_path:
                out_q.put({"type": "error", "error": "audio_path is empty"})
                continue

            try:
                log(f"job start: {audio_path}")
                out_q.put({"type": "status", "phase": "vad_start"})

                speech_path = silence_remove(audio_path, SAMPLING_RATE)
                if not speech_path or not Path(speech_path).exists():
                    out_q.put({"type": "error", "error": "無音区間除去後の音声ファイルが見つかりません。"})
                    log("speech_path missing -> error")
                    continue

                out_q.put({"type": "status", "phase": "whisper_start"})
                log("whisper_transcribe start")

                t0 = time.time()
                result = whisper_transcribe(speech_path)
                proc_sec = time.time() - t0

                # ★ textだけ返す
                text = ""
                if isinstance(result, dict):
                    text = result.get("text", "") or ""
                elif isinstance(result, str):
                    text = result

                log(f"text_len={len(text)}")
                out_q.put({"type": "done", "text": text, "proc_sec": float(proc_sec)})
                log(f"done: {proc_sec:.2f}s")

            except Exception as e:
                out_q.put({"type": "error", "error": str(e)})
                log(f"exception: {e}")

    except Exception as e:
        out_q.put({"type": "error", "error": f"worker crashed: {e}"})
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] worker crashed: {e}\n")
        except Exception:
            pass


# ============================================
# 画像付き視線ボタン
# ============================================

class GazeImageButton(tk.Canvas):
    def __init__(self, master, images, dwell_ms=1000, command=None, initial_enabled=True,
                 size=BUTTON_SIZE, gauge_width=10, gauge_color="black", **kwargs):

        if "disabled" not in images:
            images["disabled"] = images["enabled"]

        self.images = images
        self.dwell_ms = dwell_ms
        self.command = command

        self.width, self.height = size
        self.gauge_width = gauge_width
        self.gauge_color = gauge_color

        self._confirm_after_id = None
        self._progress_after_id = None
        self._enter_time = None
        self._arc_id = None

        self.state = "enabled" if initial_enabled else "disabled"

        kwargs.setdefault("highlightthickness", 0)
        super().__init__(master, width=self.width, height=self.height, **kwargs)

        self._tk_images = self.images
        self._image_item = self.create_image(
            self.width // 2, self.height // 2, image=self._tk_images[self.state]
        )

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, event=None):
        if self.state in ("disabled", "confirmed"):
            return
        self.state = "selected"
        self._set_image_by_state()

        self._enter_time = time.time()
        self._cancel_timers()
        self._confirm_after_id = self.after(self.dwell_ms, self._confirm)
        self._progress_after_id = self.after(30, self._update_progress)

    def _on_leave(self, event=None):
        if self.state in ("disabled", "confirmed"):
            return
        self._cancel_timers()
        self._clear_progress()
        self.state = "enabled"
        self._set_image_by_state()

    def _confirm(self):
        if self.state != "selected":
            return
        self.state = "confirmed"
        self._set_image_by_state()
        self._clear_progress()
        self._cancel_timers()
        if self.command:
            self.command()

    def set_enabled(self, enabled: bool):
        self._cancel_timers()
        self._clear_progress()
        self.state = "enabled" if enabled else "disabled"
        self._set_image_by_state()

    def _set_image_by_state(self):
        self.itemconfig(self._image_item, image=self._tk_images[self.state])

    def _cancel_timers(self):
        if self._confirm_after_id is not None:
            self.after_cancel(self._confirm_after_id)
            self._confirm_after_id = None
        if self._progress_after_id is not None:
            self.after_cancel(self._progress_after_id)
            self._progress_after_id = None

    def _update_progress(self):
        if self.state != "selected" or self._enter_time is None:
            self._clear_progress()
            return

        elapsed_ms = (time.time() - self._enter_time) * 1000.0
        ratio = max(0.0, min(1.0, elapsed_ms / self.dwell_ms))
        extent = -360 * ratio

        margin = self.gauge_width // 2 + 4
        x0, y0 = margin, margin
        x1, y1 = self.width - margin, self.height - margin

        if self._arc_id is None:
            self._arc_id = self.create_arc(
                x0, y0, x1, y1,
                start=90, extent=extent, style="arc",
                outline=self.gauge_color, width=self.gauge_width
            )
        else:
            self.itemconfig(self._arc_id, extent=extent)

        if ratio < 1.0 and self.state == "selected":
            self._progress_after_id = self.after(30, self._update_progress)
        else:
            self._progress_after_id = None

    def _clear_progress(self):
        if self._arc_id is not None:
            self.delete(self._arc_id)
            self._arc_id = None
        self._enter_time = None

    def config(self, **kwargs):
        if "image" in kwargs:
            img = kwargs.pop("image")
            self.itemconfig(self._image_item, image=img)
        return super().config(**kwargs)

    configure = config


# ============================================
# メイン
# ============================================

def main():
    AUDIO_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    root = tk.Tk()
    root.title("文字起こし GUI（常駐ワーカー版）")
    root.attributes("-fullscreen", True)
    root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))

    selected_file_path = tk.StringVar(value="（未選択）")
    transcribing = False

    rtf_est = load_rtf_est(default=0.8)
    rtf_lock = threading.Lock()

    # ---- 常駐ワーカー管理 ----
    mp_ctx = mp.get_context("spawn")
    cmd_q = None
    out_q = None
    worker_proc = None

    # 受信スレッド停止用
    recv_stop = threading.Event()

    # ------------------------------
    # UI
    # ------------------------------
    lbl_status = tk.Label(root, text="文字起こし開始ボタンを選択してください。", anchor="w", justify="left")
    lbl_status.grid(row=0, column=0, columnspan=2, sticky="we", padx=10, pady=5)

    lbl_file = tk.Label(root, textvariable=selected_file_path, anchor="w", justify="left")
    lbl_file.grid(row=1, column=0, columnspan=2, sticky="we", padx=10, pady=5)

    left_frame = tk.Frame(root, bd=2, relief="solid")
    left_frame.grid(row=2, column=0, padx=10, pady=10, sticky="nsew")

    right_frame = tk.Frame(root)
    right_frame.grid(row=2, column=1, padx=(10, 20), pady=10, sticky="ns")

    root.grid_rowconfigure(2, weight=1)
    root.grid_columnconfigure(0, weight=1)
    root.grid_columnconfigure(1, weight=0)

    txt_result = tk.Text(left_frame, width=80, height=18, wrap="word", font=("Meiryo", 30))
    txt_result.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

    scroll = tk.Scrollbar(left_frame, command=txt_result.yview)
    scroll.grid(row=0, column=1, sticky="ns", pady=10)
    txt_result.config(yscrollcommand=scroll.set)

    left_frame.grid_rowconfigure(0, weight=1)
    left_frame.grid_columnconfigure(0, weight=1)

    progress_overlay = tk.Frame(left_frame, bg="#FFFFFF", bd=2, relief="ridge")
    lbl_progress = tk.Label(progress_overlay, text="文字起こし 進捗(推定): 0.0%", font=("Arial", 20), bg="#FFFFFF")
    lbl_progress.pack(pady=(20, 10))

    pbar = ttk.Progressbar(progress_overlay, orient="horizontal", mode="determinate", maximum=100, length=500)
    pbar.pack(padx=20, pady=(0, 20))

    def ui_set_progress(percent: float, phase: str = "文字起こし"):
        p = max(0.0, min(100.0, float(percent)))
        lbl_progress.config(text=f"{phase} 進捗(推定): {p:.1f}%")
        pbar["value"] = p

    def show_progress_overlay():
        progress_overlay.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.8, relheight=0.25)
        progress_overlay.lift()

    def hide_progress_overlay():
        progress_overlay.place_forget()

    # ------------------------------
    # 画像
    # ------------------------------
    mojiokosi_images = {
        "disabled":  load_image("img/mojiokosi_disabled.png"),
        "enabled":   load_image("img/mojiokosi_enabled.png"),
        "selected":  load_image("img/mojiokosi_selected.png"),
        "confirmed": load_image("img/mojiokosi_comfirmed.png"),  # ファイル名に合わせる
    }

    save_images = {
        "disabled":  load_image("img/save_disabled.png"),
        "enabled":   load_image("img/save_enabled.png"),
        "selected":  load_image("img/save_selected.png"),
        "confirmed": load_image("img/save_comfirmed.png"),
    }

    # ユーザー指定のcancel画像名に合わせる
    cancel_images = {
        "disabled":  load_image("img/cancel_disabled.png"),
        "enabled":   load_image("img/cancel_enabled.png"),
        "selected":  load_image("img/cancel_selected.png"),
        "confirmed": load_image("img/cancel_selected.png"),  # confirmed用がない場合はselectedで代用
    }

    root._image_refs = (mojiokosi_images, save_images, cancel_images)

    btn_mojiokosi = None
    btn_save = None
    btn_cancel = None

    # ------------------------------
    # 常駐ワーカー起動/停止
    # ------------------------------
    def ensure_worker():
        nonlocal cmd_q, out_q, worker_proc

        if worker_proc is not None and worker_proc.is_alive():
            return True

        # ★SimpleQueueではなく Queue に（timeout付きgetが使える）
        cmd_q = mp_ctx.Queue()
        out_q = mp_ctx.Queue()

        worker_proc = mp_ctx.Process(target=persistent_worker, args=(cmd_q, out_q), daemon=False)
        worker_proc.start()
        return True

    def stop_worker():
        nonlocal cmd_q, out_q, worker_proc

        # 受信スレッド停止
        recv_stop.set()

        try:
            if cmd_q is not None:
                cmd_q.put({"type": "shutdown"})
        except Exception:
            pass

        # 少し待ってダメならterminate
        try:
            if worker_proc is not None:
                worker_proc.join(timeout=1.5)
        except Exception:
            pass

        try:
            if worker_proc is not None and worker_proc.is_alive():
                worker_proc.terminate()
                worker_proc.join(timeout=1.0)
        except Exception:
            pass

        cmd_q = None
        out_q = None
        worker_proc = None

    # ------------------------------
    # Cancel確定：ワーカーterminate（確実に止める）
    # ------------------------------
    def on_cancel_confirmed():
        nonlocal transcribing
        if not transcribing:
            return

        stop_worker()

        transcribing = False
        hide_progress_overlay()
        ui_set_progress(0.0, "文字起こし")
        lbl_status.config(text="文字起こしを中断しました（ワーカーを停止）")

        btn_mojiokosi.set_enabled(True)
        btn_mojiokosi.state = "enabled"
        btn_mojiokosi.config(image=btn_mojiokosi.images["enabled"])

        btn_save.set_enabled(False)
        btn_save.state = "disabled"
        btn_save.config(image=btn_save.images["disabled"])

        btn_cancel.set_enabled(False)
        btn_cancel.state = "disabled"
        btn_cancel.config(image=btn_cancel.images["disabled"])

    # ------------------------------
    # ステータス表示
    # ------------------------------
    def set_phase_status(phase: str):
        if phase == "boot":
            lbl_status.config(text="ワーカー起動中...")
        elif phase == "model_warmup":
            lbl_status.config(text="モデル準備中（初回は時間がかかります）...")
        elif phase == "ready":
            lbl_status.config(text="準備完了：処理開始...")
        elif phase == "vad_start":
            lbl_status.config(text="無音除去中...")
        elif phase == "whisper_start":
            lbl_status.config(text="Whisperで文字起こし中...（重い処理です）")
        elif phase == "shutdown":
            lbl_status.config(text="ワーカー停止中...")

    # ------------------------------
    # UI更新（error/done）
    # ------------------------------
    def handle_error_ui(err: str):
        nonlocal transcribing
        hide_progress_overlay()
        ui_set_progress(0.0, "文字起こし")
        lbl_status.config(text=f"エラー: {err}")
        messagebox.showerror("エラー", f"{err}\nworker_log.txt を確認してください。")

        btn_mojiokosi.set_enabled(True)
        btn_mojiokosi.state = "enabled"
        btn_mojiokosi.config(image=btn_mojiokosi.images["enabled"])

        btn_save.set_enabled(False)
        btn_save.state = "disabled"
        btn_save.config(image=btn_save.images["disabled"])

        btn_cancel.set_enabled(False)
        btn_cancel.state = "disabled"
        btn_cancel.config(image=btn_cancel.images["disabled"])

        transcribing = False

    def handle_done_ui(text: str, proc_sec: float, dur_sec: float):
        nonlocal transcribing, rtf_est
        hide_progress_overlay()
        ui_set_progress(100.0, "文字起こし")

        btn_cancel.set_enabled(False)
        btn_cancel.state = "disabled"
        btn_cancel.config(image=btn_cancel.images["disabled"])

        if text.strip():
            txt_result.delete("1.0", tk.END)
            txt_result.insert(tk.END, text)
            lbl_status.config(text="文字起こし完了（保存ボタンで保存してください）")

            btn_save.set_enabled(True)
            btn_save.state = "enabled"
            btn_save.config(image=btn_save.images["enabled"])
        else:
            lbl_status.config(text="結果が空でした（worker_log.txt を確認）")

        # RTF学習（推定改善）
        if dur_sec and dur_sec > 0 and proc_sec > 0:
            measured_rtf = max(0.05, min(10.0, proc_sec / dur_sec))
            alpha = 0.2
            with rtf_lock:
                rtf_est = (1.0 - alpha) * rtf_est + alpha * measured_rtf
                save_rtf_est(rtf_est)

        transcribing = False

    # ------------------------------
    # 文字起こし開始
    # ------------------------------
    def start_transcription(audio_path: str):
        nonlocal transcribing, rtf_est, cmd_q, out_q

        if transcribing:
            return
        transcribing = True
        recv_stop.clear()  # 受信スレッドを動かす

        if not audio_path or audio_path == "（未選択）":
            messagebox.showwarning("警告", "音声ファイルを選択してください。")
            transcribing = False
            return

        ensure_worker()

        selected_file_path.set(str(audio_path))
        txt_result.delete("1.0", tk.END)

        btn_mojiokosi.state = "confirmed"
        btn_mojiokosi.config(image=btn_mojiokosi.images["confirmed"])

        btn_save.set_enabled(False)
        btn_save.state = "disabled"
        btn_save.config(image=btn_save.images["disabled"])

        btn_cancel.set_enabled(True)
        btn_cancel.state = "enabled"
        btn_cancel.config(image=btn_cancel.images["enabled"])

        lbl_status.config(text="ワーカーにジョブ送信...")
        root.update_idletasks()

        # 推定進捗（95%で止める仕様）
        dur_sec = get_audio_duration_sec(str(audio_path))
        with rtf_lock:
            RTF = float(rtf_est)
        est_total = max(10.0, (dur_sec * RTF) if dur_sec > 0 else 60.0)
        start_t = time.time()

        def progress_pump():
            if not transcribing:
                return
            elapsed = time.time() - start_t
            pct = min(95.0, (elapsed / est_total) * 100.0)
            ui_set_progress(pct, "文字起こし")
            if pct >= 95.0:
                lbl_status.config(text="文字起こし中...（最終処理中 / 応答待ち）")
            root.after(200, progress_pump)

        def ui_update_start():
            ui_set_progress(0.0, "文字起こし")
            show_progress_overlay()
            root.update_idletasks()
            root.after(200, progress_pump)

        root.after(0, ui_update_start)

        # ジョブ送信
        try:
            cmd_q.put({"type": "job", "audio_path": str(audio_path)})
        except Exception as e:
            transcribing = False
            messagebox.showerror("エラー", f"ワーカーへの送信に失敗: {e}")
            return

        # ------------------------------
        # ★ 受信専用スレッド（ブロック受信 + timeoutで監視）
        # ------------------------------
        last_msg_time = {"t": time.time()}

        def receiver_loop():
            nonlocal transcribing
            while (not recv_stop.is_set()) and transcribing:
                # タイムアウト監視（ワーカーが固まった/死んだ等）
                if (TIMEOUT_SEC is not None) and (time.time() - last_msg_time["t"] > TIMEOUT_SEC):
                    # UIで中断
                    root.after(0, lambda: (
                        messagebox.showwarning("タイムアウト",
                            "ワーカーが一定時間応答しません。\nworker_log.txt を確認してください。"),
                        on_cancel_confirmed()
                    ))
                    break

                # ワーカー死亡監視
                if worker_proc is not None and (not worker_proc.is_alive()) and transcribing:
                    root.after(0, lambda: handle_error_ui("ワーカーが停止しました（クラッシュの可能性）"))
                    break

                try:
                    msg = out_q.get(timeout=0.5)  # ★ここが安定の肝
                except queue.Empty:
                    continue
                except Exception:
                    break

                last_msg_time["t"] = time.time()

                mtype = msg.get("type")

                if mtype == "status":
                    phase = msg.get("phase", "")
                    root.after(0, lambda ph=phase: set_phase_status(ph))
                    continue

                if mtype == "error":
                    err = msg.get("error", "不明なエラー")
                    root.after(0, lambda e=err: handle_error_ui(e))
                    break

                if mtype == "done":
                    text = msg.get("text", "") or ""
                    proc_sec = float(msg.get("proc_sec", 0.0))
                    root.after(0, lambda t=text, ps=proc_sec, ds=dur_sec: handle_done_ui(t, ps, ds))
                    break

        threading.Thread(target=receiver_loop, daemon=True).start()

    # ------------------------------
    # ファイル選択ウィンドウ（audioフォルダから選ぶ）
    # ------------------------------
    def open_file_select_window():
        audio_files = []
        for pattern in ("*.wav", "*.mp3", "*.m4a", "*.flac"):
            audio_files.extend(AUDIO_DIR.glob(pattern))

        fs_win = tk.Toplevel(root)
        fs_win.title("音声ファイル選択（視線操作）")
        fs_win.geometry("1200x1000")

        info_label = tk.Label(
            fs_win,
            text=f"audio フォルダ内の音声ファイルを視線で選択してください。\nフォルダ: {AUDIO_DIR}",
            justify="left"
        )
        info_label.grid(row=0, column=0, columnspan=2, pady=10, sticky="we")

        # ===== ここからスクロール付きリスト部分（grid版：確実に横に伸びる）=====
        # fs_win の grid を有効化
        fs_win.grid_rowconfigure(1, weight=1)   # 真ん中（リスト）を伸ばす
        fs_win.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(fs_win, highlightthickness=0)
        scroll_y = tk.Scrollbar(fs_win, orient="vertical", command=canvas.yview)

        # canvas / scrollbar を grid で配置
        canvas.grid(row=1, column=0, sticky="nsew")
        scroll_y.grid(row=1, column=1, sticky="ns")

        canvas.configure(yscrollcommand=scroll_y.set)

        frame = tk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=frame, anchor="nw")

        # 中身(frame)のサイズが変わったらスクロール範囲更新
        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        frame.bind("<Configure>", _on_frame_configure)

        # canvas の幅が変わったら「frameの表示幅」も追従させる（ここが横幅の肝）
        def _on_canvas_configure(event):
            canvas.itemconfigure(window_id, width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)

        

        class GazeGaugeButton(tk.Canvas):
            """
            視線滞留で確定するボタン（左→右ゲージ方式）
            - <Enter> で計測開始、ゲージが伸びる
            - <Leave> でリセット
            - dwell_ms 到達で command 実行
            """
            def __init__(
                self, master, text, dwell_ms=1500, command=None,
                font=("Arial", 40), height=160,
                pad_x=30, pad_y=20,
                bg="#FFFFFF",
                border="#B0B0B0",
                gauge_color="#A7D8FF",   # ゲージ色（好みで）
                hover_border="#3A7BD5",  # ホバー時の枠（好みで）
                text_color="#000000",
                wraplength=850,
                **kwargs
            ):
                super().__init__(master, height=height, bg=bg, highlightthickness=0, **kwargs)
                self._text = text
                self.dwell_ms = dwell_ms
                self.command = command

                self._bg = bg
                self._border = border
                self._hover_border = hover_border
                self._gauge_color = gauge_color
                self._text_color = text_color
                self._font = font
                self._pad_x = pad_x
                self._pad_y = pad_y
                self._wraplength = wraplength

                self._enter_time = None
                self._after_id = None

                # アイテム
                self._rect_border = None
                self._rect_gauge = None
                self._text_id = None

                # 描画＆イベント
                self.bind("<Configure>", self._redraw)  # 幅変更に追従
                self.bind("<Enter>", self._on_enter)
                self.bind("<Leave>", self._on_leave)

            def _redraw(self, event=None):
                self.delete("all")
                w = max(1, self.winfo_width())
                h = max(1, self.winfo_height())

                # ゲージ（背面）
                self._rect_gauge = self.create_rectangle(
                    0, 0, 0, h,
                    fill=self._gauge_color, outline=""
                )

                # 枠
                self._rect_border = self.create_rectangle(
                    2, 2, w-2, h-2,
                    fill="", outline=self._border, width=3
                )

                # テキスト（前面）
                self._text_id = self.create_text(
                    self._pad_x, h//2,
                    text=self._text,
                    anchor="w",
                    fill=self._text_color,
                    font=self._font,
                    width=max(1, w - self._pad_x*2),  # ここで折り返し幅が決まる
                )

                # ホバー中なら枠色維持
                # （Enter直後などで描画が走っても見た目が崩れない）
                if self._enter_time is not None:
                    self.itemconfig(self._rect_border, outline=self._hover_border)

            def _on_enter(self, event=None):
                self._enter_time = time.time()
                self.itemconfig(self._rect_border, outline=self._hover_border)
                self._cancel_timer()
                self._tick()

            def _on_leave(self, event=None):
                self._cancel_timer()
                self._enter_time = None
                self.itemconfig(self._rect_border, outline=self._border)
                self._set_gauge_ratio(0.0)

            def _tick(self):
                if self._enter_time is None:
                    return

                elapsed_ms = (time.time() - self._enter_time) * 1000.0
                ratio = max(0.0, min(1.0, elapsed_ms / self.dwell_ms))
                self._set_gauge_ratio(ratio)

                if ratio >= 1.0:
                    # 確定
                    self._cancel_timer()
                    self._enter_time = None
                    if self.command:
                        self.command()
                    return

                self._after_id = self.after(30, self._tick)

            def _set_gauge_ratio(self, ratio: float):
                w = max(1, self.winfo_width())
                h = max(1, self.winfo_height())
                gw = int(w * ratio)
                # 左→右に伸びる
                self.coords(self._rect_gauge, 0, 0, gw, h)

            def _cancel_timer(self):
                if self._after_id is not None:
                    try:
                        self.after_cancel(self._after_id)
                    except Exception:
                        pass
                    self._after_id = None


        def on_file_selected(path: Path):
            selected_file_path.set(str(path))
            lbl_status.config(text=f"選択: {path.name} / 文字起こし開始...")
            fs_win.destroy()
            start_transcription(str(path))

        def on_back():
            set_buttons_initial()
            lbl_status.config(text="ファイル選択をキャンセルしました。")
            fs_win.destroy()

        fs_win.protocol("WM_DELETE_WINDOW", on_back)

        if not audio_files:
            tk.Label(frame, text="audioフォルダに音声ファイルがありません。", font=("Arial", 16), fg="red").pack(pady=20)
        else:
            for p in sorted(audio_files):
                btn = GazeGaugeButton(frame, text=p.name, dwell_ms=DWELL_MS_2, command=lambda path=p: on_file_selected(path))
                btn.pack(fill="x", padx=30, pady=12)

        back_btn = GazeGaugeButton(fs_win, text="戻る（視線で確定）", dwell_ms=DWELL_MS, command=on_back)
        back_btn.grid(row=2, column=0, columnspan=2, padx=20, pady=10, sticky="we")

    # ------------------------------
    # 保存
    # ------------------------------
    def on_save_confirmed():
        content = txt_result.get("1.0", tk.END).strip()
        if not content:
            messagebox.showwarning("警告", "保存するテキストがありません。")
            return

        audio_path_str = selected_file_path.get()
        if audio_path_str == "（未選択）":
            messagebox.showwarning("警告", "音声ファイルが未選択のため保存名を決められません。")
            return

        audio_path = Path(audio_path_str)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        txt_filename = f"{audio_path.stem}_{ts}.txt"
        save_path = OUTPUT_DIR / txt_filename

        with open(save_path, "w", encoding="utf-8") as f:
            f.write(content + "\n")

        lbl_status.config(text=f"保存しました: {save_path}")
        #messagebox.showinfo("保存完了", f"保存しました:\n{save_path}")

        selected_file_path.set("（未選択）")
        set_buttons_initial()

    def set_buttons_initial():
        btn_mojiokosi.set_enabled(True)
        btn_mojiokosi.state = "enabled"
        btn_mojiokosi.config(image=btn_mojiokosi.images["enabled"])

        btn_save.set_enabled(False)
        btn_save.state = "disabled"
        btn_save.config(image=btn_save.images["disabled"])

        btn_cancel.set_enabled(False)
        btn_cancel.state = "disabled"
        btn_cancel.config(image=btn_cancel.images["disabled"])

        hide_progress_overlay()
        ui_set_progress(0.0, "文字起こし")
        lbl_status.config(text="文字起こし開始ボタンを選択して、音声ファイルを選んでください。")

    # ------------------------------
    # ボタン
    # ------------------------------
    def on_mojiokosi_confirmed():
        if transcribing:
            return
        open_file_select_window()

    btn_mojiokosi = GazeImageButton(right_frame, images=mojiokosi_images, dwell_ms=DWELL_MS,
                                    command=on_mojiokosi_confirmed, initial_enabled=True)
    btn_mojiokosi.grid(row=0, column=0, padx=10, pady=(10, 20))

    btn_save = GazeImageButton(right_frame, images=save_images, dwell_ms=DWELL_MS,
                                command=on_save_confirmed, initial_enabled=False)
    btn_save.grid(row=1, column=0, padx=10, pady=(20, 10))

    btn_cancel = GazeImageButton(right_frame, images=cancel_images, dwell_ms=DWELL_MS,
                                command=on_cancel_confirmed, initial_enabled=False)
    btn_cancel.grid(row=2, column=0, padx=10, pady=(20, 10))

    set_buttons_initial()

    # ウィンドウを閉じるときワーカー停止
    def on_close():
        stop_worker()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    mp.freeze_support()
    main()

