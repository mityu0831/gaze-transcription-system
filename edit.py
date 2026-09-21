import time
import tkinter as tk
import ctypes
from tkinter import filedialog, messagebox
from pathlib import Path
from PIL import Image, ImageTk


DWELL_MS = 600# 滞留時間（ms）
DWELL_MS_DELETE = 800# 滞留時間（ms）
BUTTON_SIZE = (200, 200)
# ===== Windows 仮想キーコード =====
VK_CONVERT = 0x1C       # 変換キー
VK_RETURN = 0x0D        # Enter
VK_SPACE = 0x20         # Space
VK_DOWN = 0x28          #下矢印
VK_UP = 0x26            #上矢印
VK_BACK = 0x08          #Backspace

KEYEVENTF_KEYUP = 0x0002

BASE_DIR = Path(__file__).resolve().parent

IMG_UP    = BASE_DIR / "img" / "up.png"
IMG_DOWN  = BASE_DIR / "img" / "down.png"
IMG_LEFT  = BASE_DIR / "img" / "left.png"
IMG_RIGHT = BASE_DIR / "img" / "right.png"
IMG_DELETE = BASE_DIR / "img" /"delete.png" 

IMG_KEYBOARD = BASE_DIR / "img" / "keyboard.png"
IMG_KEYBOARD_SELECTED = BASE_DIR / "img" / "keyboard_selected.png"
IMG_BACK = BASE_DIR / "img" / "back.png"
IMG_KEYBOARD_CANCEL = BASE_DIR / "img" / "keyboard_cancel.png"
IMG_KEYBOARD_CANCEL_SELECTED = BASE_DIR / "img" / "keyboard_cancel_selected.png"

class DwellImageButton(tk.Canvas):

    def __init__(
        self,
        master,
        image,
        selected_image=None,
        dwell_ms=500,
        command=None,
        *,
        before_fire=None,
        size=(200, 200),
        ring_width=10,
        ring_margin=10,
        ring_color="black",
        show_ring_only_hover=True,
        bg=None,
        update_interval_ms=20,
        **kwargs
    ):
        w, h = size
        super().__init__(
            master,
            width=w,
            height=h,
            highlightthickness=0,
            bg=(bg if bg is not None else master.cget("bg")),
            **kwargs
        )

        # ---------- 設定値 ----------
        self._image = image                 # PhotoImage参照保持
        self._selected_image = selected_image if selected_image is not None else image
        self._dwell_ms = int(dwell_ms)
        self._command = command
        self._before_fire = before_fire
        self._show_ring_only_hover = show_ring_only_hover
        self._update_interval_ms = int(update_interval_ms)

        # ---------- 内部状態 ----------
        self._after_id = None
        self._t0 = None
        self._is_tracking = False

        # ---------- 描画 ----------
        # 画像（中央）
        self._image_item = self.create_image(w // 2, h // 2, image=self._image)

        # リング（進捗円弧）
        x1 = ring_margin
        y1 = ring_margin
        x2 = w - ring_margin
        y2 = h - ring_margin

        self._ring_arc = self.create_arc(
            x1, y1, x2, y2,
            start=90,         # 上から開始
            extent=0,         # 0 → -360 に伸ばす（時計回り）
            style="arc",
            outline=ring_color,
            width=ring_width
        )

        if self._show_ring_only_hover:
            self.itemconfigure(self._ring_arc, state="hidden")

        # ---------- イベント ----------
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, event=None):
        """カーソルが入った：selected画像に変更して計測開始"""
        self.itemconfigure(self._image_item, image=self._selected_image)
        self._start_tracking()

    def _on_leave(self, event=None):
        """カーソルが出た：通常画像に戻してキャンセル"""
        self.itemconfigure(self._image_item, image=self._image)
        self._stop_tracking(reset=True)

    def _start_tracking(self):
        self._stop_tracking(reset=False)  # 念のため二重起動防止
        self._is_tracking = True
        self._t0 = time.perf_counter()

        if self._show_ring_only_hover:
            self.itemconfigure(self._ring_arc, state="normal")

        self._tick()

    def _stop_tracking(self, *, reset: bool):
        self._is_tracking = False

        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

        if reset:
            self._reset_ring()
            if self._show_ring_only_hover:
                self.itemconfigure(self._ring_arc, state="hidden")

    def _reset_ring(self):
        """リング進捗を0に戻す"""
        self.itemconfigure(self._ring_arc, extent=0)

    def _tick(self):
        """一定周期で進捗更新。完了したら command 実行。"""
        if not self._is_tracking:
            return

        elapsed_ms = (time.perf_counter() - self._t0) * 1000.0
        ratio = max(0.0, min(1.0, elapsed_ms / self._dwell_ms))

        # 0 → -360 度へ（時計回りに伸びる）
        self.itemconfigure(self._ring_arc, extent=-360 * ratio)

        if ratio >= 1.0:
            # 完了
            self.itemconfigure(self._image_item, image=self._image)
            self._stop_tracking(reset=True)

            # 確定直前に呼ぶ（Textへフォーカス戻し等）
            if callable(self._before_fire):
                self._before_fire()

            if callable(self._command):
                self._command()
            return

        self._after_id = self.after(self._update_interval_ms, self._tick)

class App(tk.Tk):
    def load_img(self, path, size=BUTTON_SIZE):
        img = Image.open(path)
        img = img.resize(size, Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    
    def load_kana_images(self):
        """行選択・文字選択用の画像をまとめて読み込む"""

        self.kana_images = {}

        # 行選択ボタン画像
        for row_key in self.kana_rows.keys():
            self.kana_images[row_key] = self.load_button_image_pair(row_key)
        
        # 「A」ボタン画像
        self.kana_images["alphabet"] = self.load_alphabet_image_pair("alphabet")

        # ABC, DEF などのグループボタン画像
        for group_key, group_data in self.alphabet_groups.items():
            self.kana_images[group_key] = self.load_alphabet_image_pair(group_key)
            for image_key, char in group_data["chars"]:
                self.kana_images[image_key] = self.load_alphabet_image_pair(image_key)
    
        # 「数」ボタン画像
        self.kana_images["number"] = self.load_number_image_pair("number")
        # 数字ボタン(0~9)画像
        for image_key, char in self.number_chars:
            self.kana_images[image_key] = self.load_number_image_pair(image_key)

        # 文字選択ボタン画像
        for row_data in self.kana_rows.values():
            for image_key, char in row_data["chars"]:
                self.kana_images[image_key] = self.load_button_image_pair(image_key)
        
        # 濁点，半濁点，小文字ボタン画像
        self.kana_images["dakuten"] = self.load_button_image_pair("dakuten")
        self.kana_images["handakuten"] = self.load_button_image_pair("handakuten")
        self.kana_images["small"] = self.load_button_image_pair("small")


    

    def load_button_image_pair(self, image_key):
        """通常画像とselected画像をセットで読み込む"""

        normal_path = BASE_DIR / "img" / "kana" / f"{image_key}.png"
        selected_path = BASE_DIR / "img" / "kana" / f"{image_key}_selected.png"

        return {
            "normal": self.load_img(normal_path),
            "selected": self.load_img(selected_path),
        }
    
    def load_number_image_pair(self, image_key):
        """数字ボタンを通常画像とselected画像をセットで読み込む"""

        normal_path = BASE_DIR / "img" / "number" / f"{image_key}.png"
        selected_path = BASE_DIR / "img" / "number" / f"{image_key}_selected.png"

        return {
            "normal": self.load_img(normal_path),
            "selected": self.load_img(selected_path),
        }
    
    def load_alphabet_image_pair(self, image_key):
        """アルファベットボタン画像を読み込む"""

        normal_path = BASE_DIR / "img" / "alphabet" / f"{image_key}.png"
        selected_path = BASE_DIR / "img" / "alphabet" / f"{image_key}_selected.png"

        return {
            "normal": self.load_img(normal_path),
            "selected": self.load_img(selected_path),
        }
    
    def setup_kana_data(self):
        """行選択・文字選択で使用するデータを定義する"""

        self.kana_rows = {
            "row_a": {
                "label": "あ行",
                "chars": [("a", "あ"), ("i", "い"), ("u", "う"), ("e", "え"), ("o", "お")]
            },
            "row_ka": {
                "label": "か行",
                "chars": [("ka", "か"), ("ki", "き"), ("ku", "く"), ("ke", "け"), ("ko", "こ")]
            },
            "row_sa": {
                "label": "さ行",
                "chars": [("sa", "さ"), ("shi", "し"), ("su", "す"), ("se", "せ"), ("so", "そ")]
            },
            "row_ta": {
                "label": "た行",
                "chars": [("ta", "た"), ("chi", "ち"), ("tsu", "つ"), ("te", "て"), ("to", "と")]
            },
            "row_na": {
                "label": "な行",
                "chars": [("na", "な"), ("ni", "に"), ("nu", "ぬ"), ("ne", "ね"), ("no", "の")]
            },
            "row_ha": {
                "label": "は行",
                "chars": [("ha", "は"), ("hi", "ひ"), ("fu", "ふ"), ("he", "へ"), ("ho", "ほ")]
            },
            "row_ma": {
                "label": "ま行",
                "chars": [("ma", "ま"), ("mi", "み"), ("mu", "む"), ("me", "め"), ("mo", "も")]
            },
            "row_ya": {
                "label": "や行",
                "chars": [("ya", "や"), ("yu", "ゆ"), ("yo", "よ")]
            },
            "row_ra": {
                "label": "ら行",
                "chars": [("ra", "ら"), ("ri", "り"), ("ru", "る"), ("re", "れ"), ("ro", "ろ")]
            },
            "row_wa": {
                "label": "わ行",
                "chars": [("wa", "わ"), ("wo", "を"), ("n", "ん")]
            },
        
        }

        self.number_chars = [
            ("0", "0"),
            ("1", "1"),
            ("2", "2"),
            ("3", "3"),
            ("4", "4"),
            ("5", "5"),
            ("6", "6"),
            ("7", "7"),
            ("8", "8"),
            ("9", "9"),
        ]

        self.DAKUTEN_MAP = {
            "か": "が", "き": "ぎ", "く": "ぐ", "け": "げ", "こ": "ご",
            "さ": "ざ", "し": "じ", "す": "ず", "せ": "ぜ", "そ": "ぞ",
            "た": "だ", "ち": "ぢ", "つ": "づ", "て": "で", "と": "ど",
            "は": "ば", "ひ": "び", "ふ": "ぶ", "へ": "べ", "ほ": "ぼ",
        }

        self.HANDAKUTEN_MAP = {
            "は": "ぱ", "ひ": "ぴ", "ふ": "ぷ", "へ": "ぺ", "ほ": "ぽ",
        }

        self.SMALL_MAP = {
            "あ": "ぁ", "い": "ぃ", "う": "ぅ", "え": "ぇ", "お": "ぉ",
            "や": "ゃ", "ゆ": "ゅ", "よ": "ょ",
            "つ": "っ",
        }

        self.KANA_ROMAJI = {
            "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
            "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
            "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
            "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
            "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
            "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
            "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
            "や": "ya", "ゆ": "yu","よ": "yo",
            "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
            "わ": "wa", "を": "wo", "ん": "nn",
            # 濁音
            "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
            "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
            "だ": "da", "ぢ": "di", "づ": "du", "で": "de", "ど": "do",
            "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
            # 半濁音
            "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
            # 小文字
            "ぁ": "xa", "ぃ": "xi", "ぅ": "xu", "ぇ": "xe", "ぉ": "xo", "ゃ": "xya", "ゅ": "xyu", "ょ": "xyo","っ": "xtsu",
        }

        self.alphabet_groups = {
            "alphabet_abc": {
                "label": "ABC",
                "chars": [
                    ("alphabet_upper_A", "A"),
                    ("alphabet_upper_B", "B"),
                    ("alphabet_upper_C", "C"),
                    ("alphabet_lower_a", "a"),
                    ("alphabet_lower_b", "b"),
                    ("alphabet_lower_c", "c"),
                ]
            },

            "alphabet_def": {
                "label": "DEF",
                "chars": [
                    ("alphabet_upper_D", "D"),
                    ("alphabet_upper_E", "E"),
                    ("alphabet_upper_F", "F"),
                    ("alphabet_lower_d", "d"),
                    ("alphabet_lower_e", "e"),
                    ("alphabet_lower_f", "f"),
                ]
            },

            "alphabet_ghi": {
                "label": "GHI",
                "chars": [
                    ("alphabet_upper_G", "G"),
                    ("alphabet_upper_H", "H"),
                    ("alphabet_upper_I", "I"),
                    ("alphabet_lower_g", "g"),
                    ("alphabet_lower_h", "h"),
                    ("alphabet_lower_i", "i"),
                ]
            },

            "alphabet_jkl": {
                "label": "JKL",
                "chars": [
                    ("alphabet_upper_J", "J"),
                    ("alphabet_upper_K", "K"),
                    ("alphabet_upper_L", "L"),
                    ("alphabet_lower_j", "j"),
                    ("alphabet_lower_k", "k"),
                    ("alphabet_lower_l", "l"),
                ]
            },

            "alphabet_mno": {
                "label": "MNO",
                "chars": [
                    ("alphabet_upper_M", "M"),
                    ("alphabet_upper_N", "N"),
                    ("alphabet_upper_O", "O"),
                    ("alphabet_lower_m", "m"),
                    ("alphabet_lower_n", "n"),
                    ("alphabet_lower_o", "o"),
                ]
            },

            "alphabet_pqrs": {
                "label": "PQRS",
                "chars": [
                    ("alphabet_upper_P", "P"),
                    ("alphabet_upper_Q", "Q"),
                    ("alphabet_upper_R", "R"),
                    ("alphabet_upper_S", "S"),
                    ("alphabet_lower_p", "p"),
                    ("alphabet_lower_q", "q"),
                    ("alphabet_lower_r", "r"),
                    ("alphabet_lower_s", "s"),
                ]
            },

            "alphabet_tuv": {
                "label": "TUV",
                "chars": [
                    ("alphabet_upper_T", "T"),
                    ("alphabet_upper_U", "U"),
                    ("alphabet_upper_V", "V"),
                    ("alphabet_lower_t", "t"),
                    ("alphabet_lower_u", "u"),
                    ("alphabet_lower_v", "v"),
                ]
            },

            "alphabet_wxyz": {
                "label": "WXYZ",
                "chars": [
                    ("alphabet_upper_W", "W"),
                    ("alphabet_upper_X", "X"),
                    ("alphabet_upper_Y", "Y"),
                    ("alphabet_upper_Z", "Z"),
                    ("alphabet_lower_w", "w"),
                    ("alphabet_lower_x", "x"),
                    ("alphabet_lower_y", "y"),
                    ("alphabet_lower_z", "z"),
                ]
            },
        }

    
    def __init__(self):
        super().__init__()
        self.attributes("-fullscreen", True)
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))
        self.bind("<F2>", lambda event: self.ime_convert())
        self.bind("<F3>", lambda event: self.ime_next_candidate())
        self.bind("<F4>", lambda event: self.ime_previous_candidate())
        self.bind("<F5>", lambda event: self.ime_confirm())
        self.bind("<F6>", lambda event: self.test_ime_input())


        self.setup_kana_data()
        self.last_kana = None

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)  # 右列は固定


        # ===== 上部：操作バー =====
        top = tk.Frame(self)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=10)

        btn_load = tk.Button(top, text="TXTを読み込む", command=self.load_txt, height=2)
        btn_load.pack(side="left")  # top の中は pack のままでOK
        
        # ===== 本文：Text =====
        self.text = tk.Text(self, wrap="word", font=("Meiryo", 100), undo=True)
        self.text.grid(row=1, column=0, sticky="nsew", padx=(220, 0), pady=30)

        # 右側：矢印パネル
        panel = tk.Frame(self)
        panel.grid(row=1, column=1, sticky="se", padx=10, pady=30)

        # ===== キーボード表示領域 =====
        self.keyboard_frame = tk.Frame(self, bg=self.cget("bg"))
        self.keyboard_frame.place(relx=0.5, rely=0.75, anchor="center")
        self.keyboard_frame.place_forget()

        # 画像読み込み
        self.img_up = self.load_img(IMG_UP)
        self.img_down = self.load_img(IMG_DOWN)
        self.img_left = self.load_img(IMG_LEFT)
        self.img_right = self.load_img(IMG_RIGHT)
        self.img_delete = self.load_img(IMG_DELETE)
        self.img_keyboard = self.load_img(IMG_KEYBOARD)
        self.img_keyboard_selected = self.load_img(IMG_KEYBOARD_SELECTED)
        self.load_kana_images()
        self.img_back = self.load_img(IMG_BACK)
        self.img_keyboard_cancel = self.load_img(IMG_KEYBOARD_CANCEL)
        self.img_keyboard_cancel_selected = self.load_img(IMG_KEYBOARD_CANCEL_SELECTED)

        # ===== 矢印,削除,キーボード（滞留）ボタン配置 =====
        self.btn_up = DwellImageButton(panel, self.img_up, dwell_ms=DWELL_MS, command=self.move_up, bd=0)
        self.btn_left = DwellImageButton(panel, self.img_left, dwell_ms=DWELL_MS, command=self.move_left, bd=0)
        self.btn_right = DwellImageButton(panel, self.img_right, dwell_ms=DWELL_MS, command=self.move_right, bd=0)
        self.btn_down = DwellImageButton(panel, self.img_down, dwell_ms=DWELL_MS, command=self.move_down, bd=0)
        self.btn_delete = DwellImageButton(self, self.img_delete, dwell_ms=DWELL_MS_DELETE, command=self.delete_backspace, bd=0)
        self.btn_keyboard = DwellImageButton(self, self.img_keyboard,selected_image=self.img_keyboard_selected,dwell_ms=DWELL_MS,command=self.show_row_keyboard,bd=0)
        self.back_button = DwellImageButton(self, self.img_back, selected_image=self.img_back, dwell_ms=DWELL_MS, command=self.show_row_keyboard,bd=0)
        self.close_button = DwellImageButton(self,self.img_keyboard_cancel,selected_image=self.img_keyboard_cancel_selected,dwell_ms=DWELL_MS,command=self.hide_keyboard,bd=0)

        self.close_button.place_forget()
        self.back_button.place_forget()

        self.btn_up.grid(row=0, column=1, padx=6, pady=(12,0))
        self.btn_left.grid(row=1, column=0, padx=6, pady=6)
        self.btn_right.grid(row=1, column=2, padx=6, pady=6)
        self.btn_down.grid(row=2, column=1, padx=6, pady=(0,12))
        self.btn_delete.place(relx=0.0, rely=0.0, x=10, y=100, anchor="nw")
        self.btn_keyboard.place(relx=0.0, rely=0.0, x=10, y=320, anchor="nw")

        # 見た目調整（必要なら）
        for r in range(3):
            panel.grid_rowconfigure(r, weight=0)
        for c in range(3):
            panel.grid_columnconfigure(c, weight=0)

        # 起動時フォーカス
        self.text.focus_set()

    def _refocus(self):
        """キャレット位置を表示し、Textへフォーカスを戻す。"""
        self.text.see("insert")
        self.text.focus_set()

    def send_windows_key(self, vk_code):
        """Windowsへキー入力を送信する"""

        self.text.focus_force()
        self.update_idletasks()

        ctypes.windll.user32.keybd_event(
            vk_code,
            0,
            0,
            0
        )

        ctypes.windll.user32.keybd_event(
            vk_code,
            0,
            KEYEVENTF_KEYUP,
            0
        )

    def ime_convert(self):
        """Windows IMEの変換キーを送る"""

        self.send_windows_key(VK_SPACE)

    def ime_next_candidate(self):
        """次の変換候補"""
        self.send_windows_key(VK_DOWN)

    def ime_previous_candidate(self):
        """前の変換候補"""
        self.send_windows_key(VK_UP)

    def ime_confirm(self):
        """現在の候補を確定"""
        self.send_windows_key(VK_RETURN)

    def send_ascii_text(self, text):
        """英字をWindowsのキー入力として送信する"""
        self.text.focus_force()
        self.update_idletasks()

        for char in text.lower():

            if "a" <= char <= "z":
                # Windowsの仮想キーコードでは
                # A～Z = 0x41～0x5A
                vk_code = ord(char.upper())

                self.send_windows_key(vk_code)


    def test_ime_input(self):
        """IME入力のテスト"""
        self.send_ascii_text("kyou")

    # ===== txt 読込 =====
    def load_txt(self):
        path = filedialog.askopenfilename(
            title="テキストファイルを選択",
            initialdir=str(BASE_DIR / "text"),
            filetypes=[("Text", "*.txt"), ("All", "*.*")]
        )
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # UTF-8で読めない場合の保険（Shift_JIS等）
            try:
                content = Path(path).read_text(encoding="cp932")
            except Exception as e:
                messagebox.showerror("読込エラー", str(e))
                return
        except Exception as e:
            messagebox.showerror("読込エラー", str(e))
            return

        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.mark_set("insert", "1.0")
        self.text.see("insert")
        self.text.focus_set()

    # ===== キャレット移動 =====
    def move_left(self):
        self.text.mark_set("insert", "insert -1c")  # 1文字左
        self.text.see("insert")
        self.text.focus_set()

    def move_right(self):
        self.text.mark_set("insert", "insert +1c")  # 1文字右
        self.text.see("insert")
        self.text.focus_set()

    def move_up(self):
        before = self.text.index("insert")
        try:
            self.text.mark_set("insert", "insert -1 display lines")
        except tk.TclError:
            self.text.mark_set("insert", before)

        after = self.text.index("insert")
        if after == "1.0" and before != "1.0":
            self.text.mark_set("insert", before)

        self.text.see("insert")
        self.text.focus_set()

    def move_down(self):
        print("before", self.text.index("insert"))
        self.text.mark_set("insert", "insert +1 display lines")  # 1行下
        print("after ", self.text.index("insert"))
        self.text.see("insert")
        self.text.focus_set()

    #キャレットの左1文字を削除（Backspace）, 先頭位置なら何もしない。
    def delete_backspace(self):
        if self.text.index("insert") == "1.0":
            self._refocus()
            return

        try:
            self.text.delete("insert -1c", "insert")
        except tk.TclError:
            pass

        self._refocus()
    def clear_keyboard_frame(self):
        """キーボード表示領域を空にする"""
        for widget in self.keyboard_frame.winfo_children():
            widget.destroy()
    
    def hide_background_buttons(self):
        """キーボード表示中に背景の操作ボタンを隠す"""
        self.btn_delete.place_forget()
        self.btn_keyboard.place_forget()
        self.btn_up.grid_remove()
        self.btn_left.grid_remove()
        self.btn_right.grid_remove()
        self.btn_down.grid_remove()
    
    def show_background_buttons(self):
        """キーボードを閉じた後に背景の操作ボタンを戻す"""
        self.btn_up.grid()
        self.btn_left.grid()
        self.btn_right.grid()
        self.btn_down.grid()
        self.btn_delete.place(relx=0.0, rely=0.0, x=10, y=100, anchor="nw")
        self.btn_keyboard.place(relx=0.0, rely=0.0, x=10, y=320, anchor="nw")
    
    def hide_keyboard(self):
        """キーボード表示領域を閉じる"""
        self.clear_keyboard_frame()
        self.keyboard_frame.place_forget()
        self.back_button.place_forget()
        self.close_button.place_forget()
        self.show_background_buttons()
        self._refocus()
    
    def add_keyboard_back_button(self, relx, rely):
        """戻るボタンを表示する"""
        self.back_button.place(relx=relx, rely=rely, anchor="center")
        self.back_button.lift()
    
    def add_keyboard_close_button(self,relx,rely):
        """閉じるボタンを表示する"""
        self.close_button.place(relx=relx,rely=rely,anchor="center")
        self.close_button.lift()

    def show_row_keyboard(self):
        """行選択画面を表示する"""
        self.hide_background_buttons()
        self.clear_keyboard_frame()
        self.keyboard_frame.place(relx=0.5, rely=0.75, anchor="center")

        self.back_button.place_forget()

        positions = {
            "row_a":  (0, 2),
            "row_ka": (0, 3),
            "row_sa": (0, 4),
            "row_ta": (0, 5),
            "row_na": (0, 6),

            "row_ha": (1, 2),
            "row_ma": (1, 3),
            "row_ya": (1, 4),
            "row_ra": (1, 5),
            "row_wa": (1, 6),
        }

        for row_key, (r, c) in positions.items():

            button = DwellImageButton(
                self.keyboard_frame,
                self.kana_images[row_key]["normal"],
                selected_image=self.kana_images[row_key]["selected"],
                dwell_ms=DWELL_MS,
                command=lambda key=row_key: self.show_char_keyboard(key),
                bd=0
            )

            button.grid(
                row=r,
                column=c,
                padx=8,
                pady=8
            )
        
        # 数ボタン
        number_button = DwellImageButton(
            self.keyboard_frame,
            self.kana_images["number"]["normal"],
            selected_image=self.kana_images["number"]["selected"],
            dwell_ms=DWELL_MS,
            command=self.show_number_keyboard,
            bd=0
        )
        number_button.grid(row=0, column=1, padx=8, pady=8)

        # Aボタン
        alphabet_button = DwellImageButton(
            self.keyboard_frame,
            self.kana_images["alphabet"]["normal"],
            selected_image=self.kana_images["alphabet"]["selected"],
            dwell_ms=DWELL_MS,
            command=self.show_alphabet_group_keyboard,
            bd=0
        )
        alphabet_button.grid(row=0, column=0, padx=8, pady=8)
        
        self.add_keyboard_close_button(relx=0.87, rely=0.46)
        self._refocus()


    def show_char_keyboard(self, row_key):
        """選択された行の文字選択画面を表示する"""
        self.clear_keyboard_frame()
        self.keyboard_frame.place(relx=0.5, rely=0.75, anchor="center")

        self.close_button.place_forget()

        chars = self.kana_rows[row_key]["chars"]

        for index, (image_key, char) in enumerate(chars):
            button = DwellImageButton(
                self.keyboard_frame,
                self.kana_images[image_key]["normal"],
                selected_image=self.kana_images[image_key]["selected"],
                dwell_ms=DWELL_MS,
                command=lambda c=char: self.insert_char_ime(c),
                bd=0
            )
            button.grid(
                row=0,
                column=index,
                padx=10,
                pady=10
            )
        
        option_col = 0

        # 濁点：か行，さ行，た行，は行
        if row_key in ["row_ka", "row_sa", "row_ta", "row_ha"]:
            button = DwellImageButton(
                self.keyboard_frame,
                self.kana_images["dakuten"]["normal"],
                selected_image=self.kana_images["dakuten"]["selected"],
                dwell_ms=DWELL_MS,
                command=lambda: self.convert_previous_char_ime(self.DAKUTEN_MAP),
                bd=0
            )
            button.grid(row=1, column=option_col, padx=10, pady=10)
            option_col += 1

        # 半濁点：は行のみ
        if row_key == "row_ha":
            button = DwellImageButton(
                self.keyboard_frame,
                self.kana_images["handakuten"]["normal"],
                selected_image=self.kana_images["handakuten"]["selected"],
                dwell_ms=DWELL_MS,
                command=lambda: self.convert_previous_char_ime(self.HANDAKUTEN_MAP),
                bd=0
            )
            button.grid(row=1, column=option_col, padx=10, pady=10)
            option_col += 1

        # 小文字変換：あ行，や行，た行
        if row_key in ["row_a", "row_ya", "row_ta"]:
            button = DwellImageButton(
                self.keyboard_frame,
                self.kana_images["small"]["normal"],
                selected_image=self.kana_images["small"]["selected"],
                dwell_ms=DWELL_MS,
                command=lambda: self.convert_previous_char_ime(self.SMALL_MAP),
                bd=0
            )
            button.grid(row=1, column=option_col, padx=10, pady=10)

        self.add_keyboard_back_button(relx=0.87, rely=0.45)
        self._refocus()
    
    def show_number_keyboard(self):
        """数字・記号選択画面を表示する"""
        self.clear_keyboard_frame()
        self.keyboard_frame.place(relx=0.5, rely=0.75, anchor="center")

        self.close_button.place_forget()

        for index, (image_key, char) in enumerate(self.number_chars):
            button = DwellImageButton(
                self.keyboard_frame,
                self.kana_images[image_key]["normal"],
                selected_image=self.kana_images[image_key]["selected"],
                dwell_ms=DWELL_MS,
                command=lambda c=char: self.insert_char(c),
                bd=0
            )
            button.grid(
                row=index // 5,
                column=index % 5,
                padx=10,
                pady=10
            )

        self.add_keyboard_back_button(relx=0.87, rely=0.45)
        self._refocus()
    
    def show_alphabet_group_keyboard(self):
        """ABC, DEF などのアルファベットグループ選択画面を表示する"""
        self.clear_keyboard_frame()
        self.keyboard_frame.place(relx=0.5, rely=0.75, anchor="center")

        self.close_button.place_forget()

        for index, group_key in enumerate(self.alphabet_groups.keys()):
            button = DwellImageButton(
                self.keyboard_frame,
                self.kana_images[group_key]["normal"],
                selected_image=self.kana_images[group_key]["selected"],
                dwell_ms=DWELL_MS,
                command=lambda key=group_key: self.show_alphabet_char_keyboard(key),
                bd=0
            )
            button.grid(
                row=index // 4,
                column=index % 4,
                padx=10,
                pady=10
            )

        self.add_keyboard_back_button(relx=0.87, rely=0.45)
        self._refocus()
    
    def show_alphabet_char_keyboard(self, group_key):
        """選択したアルファベットグループの文字を表示する"""
        self.clear_keyboard_frame()
        self.keyboard_frame.place(relx=0.5, rely=0.75, anchor="center")

        self.close_button.place_forget()

        chars = self.alphabet_groups[group_key]["chars"]

        if group_key in ["alphabet_pqrs", "alphabet_wxyz"]:
            cols = 4
        else:
            cols = 3

        for index, (image_key, char) in enumerate(chars):
            button = DwellImageButton(
                self.keyboard_frame,
                self.kana_images[image_key]["normal"],
                selected_image=self.kana_images[image_key]["selected"],
                dwell_ms=DWELL_MS,
                command=lambda c=char: self.insert_char(c),
                bd=0
            )
            button.grid(
                row=index // cols,
                column=index % cols,
                padx=10,
                pady=10
            )

        self.add_keyboard_back_button(relx=0.87, rely=0.45)
        self._refocus()

    def convert_previous_char(self, convert_map):
        """直前に入力した文字を変換する"""
        if self.text.index("insert") == "1.0":
            self._refocus()
            return

        prev_char = self.text.get("insert -1c", "insert")

        if prev_char not in convert_map:
            self._refocus()
            return

        self.text.delete("insert -1c", "insert")
        self.text.insert("insert", convert_map[prev_char])
        self._refocus()

        # 変換後は行選択画面に戻る
        #self.show_row_keyboard()
    
    def convert_previous_char_ime(self, convert_map):
        """直前にIME入力したかなを別のかなに置き換える"""

        # 最後に入力したかなを取得
        prev_char = self.last_kana

        if prev_char is None:
            return

        # 小文字などに変換できるか確認
        converted_char = convert_map.get(prev_char)

        if converted_char is None:
            return

        # IME上の直前の文字をBackspaceで削除
        self.send_windows_key(VK_BACK)

        # 変換後のかなに対応するローマ字を取得
        romaji = self.KANA_ROMAJI.get(converted_char)

        if romaji is None:
            print(f"ローマ字が登録されていません: {converted_char}")
            return

        # IMEへ入力
        self.send_ascii_text(romaji)

        # 最後に入力したかなを更新
        self.last_kana = converted_char


    def insert_char(self, char):
        """選択した文字をTextのキャレット位置に入力する"""
        self.text.insert("insert", char)
        self._refocus()

        # 入力後は行選択画面に戻る
        #self.show_row_keyboard()
    
    def insert_char_ime(self, char):
        """ひらがなに対応するローマ字をIMEへ送信する"""

        romaji = self.KANA_ROMAJI.get(char)

        if romaji is None:
            print(f"ローマ字が登録されていません: {char}")
            return

        print(f"IME入力: {char} -> {romaji}")

        self.send_ascii_text(romaji)
        # 最後に入力したかなを記録
        self.last_kana = char

if __name__ == "__main__":
    App().mainloop()