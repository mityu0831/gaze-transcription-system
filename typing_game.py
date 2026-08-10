import time
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from PIL import Image, ImageTk

DWELL_MS = 800# 滞留時間（ms）
DWELL_MS_DELETE = 800
DWELL_MS_BACK = 800
DWELL_MS_DECISION = 800

BUTTON_SIZE = (200, 200)

BASE_DIR = Path(__file__).resolve().parent

IMG_DELETE = BASE_DIR / "img" /"delete.png" 
WORDS_FILE = BASE_DIR / "text" / "typing_words2.txt"
IMG_KEYBOARD = BASE_DIR / "img" / "keyboard.png"
IMG_KEYBOARD_SELECTED = BASE_DIR / "img" / "keyboard_selected.png"
IMG_BACK = BASE_DIR / "img" / "back.png"
IMG_KEYBOARD_CANCEL = BASE_DIR / "img" / "keyboard_cancel.png"
IMG_KEYBOARD_CANCEL_SELECTED = BASE_DIR / "img" / "keyboard_cancel_selected.png"
IMG_DECISION = BASE_DIR / "img" / "decision.png"
IMG_NEXT = BASE_DIR / "img" / "next.png"
LOG_FILE = BASE_DIR / "text" / "typing_log.txt"

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
        self._enabled = True

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
        if not self._enabled:
            return
        
        self.itemconfigure(self._image_item, image=self._selected_image)
        self._start_tracking()

    def _on_leave(self, event=None):
        """カーソルが出た：通常画像に戻してキャンセル"""
        self.itemconfigure(self._image_item, image=self._image)
        self._stop_tracking(reset=True)
    
    def set_enabled(self, enabled):
        """ボタンの有効・無効"""

        self._enabled = enabled

        if not enabled:
            self._stop_tracking(reset=True)
            self.itemconfigure(self._image_item, image=self._image)

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

class TypingGameApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("かな入力ゲーム")
        self.attributes("-fullscreen", True)
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        self.words_by_level = {
            1: [],
            2: [],
            3: [],
        }

        self.current_level = 1
        self.current_words = []
        self.current_index = 0
        self.current_word = ""

        # ログ記録用
        self.task_start_time = None
        self.selected_chars_log = ""

        self.setup_kana_data()
        self.load_words_from_file()
        self.create_widgets()

    # ===== 画像読み込み関連 =====
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

        # 文字選択ボタン画像
        for row_data in self.kana_rows.values():
            for image_key, char in row_data["chars"]:
                self.kana_images[image_key] = self.load_button_image_pair(image_key)
        
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
    

    # ===== かなキーボードデータ =====
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


    # ===== ゲーム制御関連 =====
    def load_words_from_file(self):
        """1つのtxtファイルからレベル別の単語を読み込む"""
        if not WORDS_FILE.exists():
            messagebox.showerror(
                "エラー",
                f"単語ファイルが見つかりません\n{WORDS_FILE}"
            )
            return

        text = WORDS_FILE.read_text(encoding="utf-8")

        for line in text.splitlines():
            line = line.strip()

            if not line:
                continue

            try:
                level_text, word = line.split(",", 1)
                level = int(level_text)
            except ValueError:
                continue

            if level in self.words_by_level:
                self.words_by_level[level].append(word)
    

    def create_widgets(self):
        """画面部品を作成する"""
        self.label_title = tk.Label(
            self,
            text="かな入力ゲーム",
            font=("Meiryo", 50)
        )
        self.label_title.pack(pady=30)

        self.label_target = tk.Label(
            self,
            text="ゲームを開始してください",
            font=("Meiryo", 60)
        )
        self.label_target.pack(pady=40)

        self.text = tk.Text(
            self,
            font=("Meiryo", 50),
            width=20,
            height=2
        )
        self.text.pack(pady=20)

        self.label_status = tk.Label(
            self,
            text="",
            font=("Meiryo", 30)
        )
        self.label_status.pack(pady=20)

        self.button_start = tk.Button(
            self,
            text="ゲーム開始",
            font=("Meiryo", 40),
            command=self.start_game
        )
        self.button_start.place(
            relx=0.0,
            rely=0.0,
            x=20,
            y=20,
            anchor="nw"
        )

        self.img_keyboard = self.load_img(IMG_KEYBOARD)
        self.img_keyboard_selected = self.load_img(IMG_KEYBOARD_SELECTED)
        self.img_delete = self.load_img(IMG_DELETE)
        self.img_back = self.load_img(IMG_BACK)
        self.img_keyboard_cancel = self.load_img(IMG_KEYBOARD_CANCEL)
        self.img_keyboard_cancel_selected = self.load_img(IMG_KEYBOARD_CANCEL_SELECTED)
        self.img_decision = self.load_img(IMG_DECISION,size=(400, 160))
        self.img_next = self.load_img(IMG_NEXT,size=(400,160))

        self.load_kana_images()

        self.keyboard_frame = tk.Frame(self, bg=self.cget("bg"))
        self.keyboard_frame.place(relx=0.5, rely=0.75, anchor="center")
        self.keyboard_frame.place_forget()

        #self.btn_keyboard = DwellImageButton(
            #self,
            #self.img_keyboard,
            #selected_image=self.img_keyboard_selected,
            #dwell_ms=DWELL_MS,
            #command=self.show_row_keyboard,
            #bd=0
        #)
        #self.btn_keyboard.place(relx=0.0, rely=0.0, x=10, y=500, anchor="nw")

        self.delete_button = DwellImageButton(self, self.img_delete, dwell_ms=DWELL_MS_DELETE, command=self.delete_backspace, bd=0)

        self.back_button = DwellImageButton(
            self,
            self.img_back,
            selected_image=self.img_back,
            dwell_ms=DWELL_MS_BACK,
            command=self.show_row_keyboard,
            bd=0
        )
        self.back_button.place_forget()

        #self.close_button = DwellImageButton(
            #self,
            #self.img_keyboard_cancel,
            #selected_image=self.img_keyboard_cancel_selected,
            #dwell_ms=DWELL_MS,
            #command=self.hide_keyboard,
            #bd=0
        #)
        #self.close_button.place_forget()
        # 初期状態で行選択画面を表示
        self.decision_button = DwellImageButton(
            self,
            self.img_decision,
            selected_image=self.img_decision,
            dwell_ms=DWELL_MS_DECISION,
            command=self.check_answer,
            size=(400, 160),
            bd=0
        )

        self.decision_button.place(
            relx=0.85,
            rely=0.43,
            anchor="center"
        )
        self.show_row_keyboard()

        self.next_button = DwellImageButton(
            self,
            self.img_next,
            selected_image=self.img_next,
            dwell_ms=DWELL_MS,
            command=self.go_next_level,
            size=(400, 160),
            bd=0
        )

        self.next_button.place_forget()
    

    def start_game(self):
        """ゲーム開始"""
        self.current_level = 1
        self.current_words = self.words_by_level[self.current_level]
        self.current_index = 0

        self.show_current_word()


    def start_level(self, level):
        """選択されたレベルの課題を開始する"""
        if not self.words_by_level[level]:
            messagebox.showwarning(
                "警告",
                f"レベル{level}の単語がありません"
            )
            return

        self.current_level = level
        self.current_words = self.words_by_level[level]
        self.current_index = 0

        self.show_current_word()
    
    def go_next_level(self):
        """休憩画面から次の難易度へ進む"""
        
        self.next_button.place_forget()

        self.current_level += 1
        self.current_words = self.words_by_level[self.current_level]
        self.current_index = 0

        self.show_current_word()

    def show_current_word(self):

        if self.current_index >= len(self.current_words):

            if self.current_level < 3:
                self.label_target.config(
                    text=f"レベル{self.current_level}終了\n休憩してください"
                )

                self.label_status.config(
                    text=f"次はレベル{self.current_level + 1}です"
                )

                self.text.delete("1.0", "end")
                self.text.pack_forget()
                self.keyboard_frame.place_forget()
                self.delete_button.place_forget()
                self.back_button.place_forget()
                self.decision_button.place_forget()

                self.next_button.place(
                    relx=0.5,
                    rely=0.65,
                    anchor="center"
                )

                return

            else:
                self.label_target.config(text="ゲームクリア")
                self.label_status.config(text="全レベル終了")

                self.text.delete("1.0", "end")
                self.keyboard_frame.place_forget()
                self.delete_button.place_forget()
                self.back_button.place_forget()
                self.decision_button.place_forget()
                self.next_button.place_forget()

                return
            
        self.current_word = self.current_words[self.current_index]

        self.label_target.config(
            text=f"レベル{self.current_level}：{self.current_word}"
        )

        self.label_status.config(
            text=f"{self.current_index + 1}/{len(self.current_words)}"
        )

        self.text.delete("1.0", "end")
        self.task_start_time = time.perf_counter()
        self.selected_chars_log = ""

        self.text.pack(pady=20)
        self.show_delete_button()
        self.show_row_keyboard()


    def check_answer(self):
        """入力内容を判定する"""
        input_text = self.text.get("1.0", "end-1c")

        if input_text == self.current_word:
            elapsed_time = time.perf_counter() - self.task_start_time
            self.save_task_log(input_text, elapsed_time)
            
            self.current_index += 1
            self.show_current_word()
        else:
            
            self.label_status.config(text="入力が違います")
    
    def save_task_log(self, input_text, elapsed_time):
        """課題ごとの入力時間と選択文字を記録する"""

        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(
                f"レベル: {self.current_level}\n"
                f"課題番号: {self.current_index + 1}\n"
                f"課題文字: {self.current_word}\n"
                f"最終入力文字: {input_text}\n"
                f"選択した文字: {self.selected_chars_log}\n"
                f"入力時間: {elapsed_time:.2f} 秒\n"
                f"{'-' * 30}\n"
            )
    
    def _refocus(self):
        self.text.see("insert")
        self.text.focus_set()
    
    def clear_keyboard_frame(self):
        """キーボード表示領域を空にする"""
        for widget in self.keyboard_frame.winfo_children():
            widget.destroy()
    
    def hide_keyboard(self):
        self.clear_keyboard_frame()
        self.keyboard_frame.place_forget()
        self.back_button.place_forget()
        self.close_button.place_forget()
        self._refocus()
    
    def show_delete_button(self):
        """deleteボタンを表示する"""
        self.delete_button.place(relx=0.0, rely=0.0, x=10, y=170, anchor="nw")

    def delete_backspace(self):
        if self.text.index("insert") == "1.0":
            self._refocus()
            return

        try:
            self.text.delete("insert -1c", "insert")
        except tk.TclError:
            pass

        self._refocus()

    def add_keyboard_back_button(self, relx, rely):
        """戻るボタンを表示する"""
        self.back_button.place(relx=relx, rely=rely, anchor="center")
        #self.back_button.lift()
    
    def add_keyboard_close_button(self,relx,rely):
        """閉じるボタンを表示する"""
        self.close_button.place(relx=relx,rely=rely,anchor="center")
        self.close_button.lift()

    def add_decision_button(self, relx, rely):
        self.decision_button.place(relx=relx,rely=rely,anchor="center")

    def show_row_keyboard(self):
        """行選択画面を表示する"""
        #self.hide_background_buttons()
        self.clear_keyboard_frame()
        self.keyboard_frame.place(relx=0.5, rely=0.75, anchor="center")

        self.back_button.place_forget()

        row_keys = list(self.kana_rows.keys())

        for index, row_key in enumerate(row_keys):
            button = DwellImageButton(
                self.keyboard_frame,
                self.kana_images[row_key]["normal"],
                selected_image=self.kana_images[row_key]["selected"],
                dwell_ms=DWELL_MS,
                command=lambda key=row_key: self.show_char_keyboard(key),
                bd=0
            )
            button.grid(
                row=index // 5,
                column=index % 5,
                padx=8,
                pady=8
            )

        self.add_decision_button(relx=0.87, rely=0.46)
        #self.add_keyboard_close_button(relx=0.87, rely=0.46)
        self._refocus()


    def show_char_keyboard(self, row_key):
        """選択された行の文字選択画面を表示する"""
        self.clear_keyboard_frame()
        self.keyboard_frame.place(relx=0.5, rely=0.75, anchor="center")

        #self.close_button.place_forget()
        self.decision_button.place_forget()

        char_screen_buttons = []

        chars = self.kana_rows[row_key]["chars"]

        for index, (image_key, char) in enumerate(chars):
            button = DwellImageButton(
                self.keyboard_frame,
                self.kana_images[image_key]["normal"],
                selected_image=self.kana_images[image_key]["selected"],
                dwell_ms=DWELL_MS,
                command=lambda c=char: self.insert_char(c),
                bd=0
            )
            button.set_enabled(False)
            char_screen_buttons.append(button)

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
                command=lambda: self.convert_previous_char(self.DAKUTEN_MAP, "゛"),
                bd=0
            )
            button.set_enabled(False)
            char_screen_buttons.append(button)
            button.grid(row=1, column=option_col, padx=10, pady=10)
            option_col += 1

        # 半濁点：は行のみ
        if row_key == "row_ha":
            button = DwellImageButton(
                self.keyboard_frame,
                self.kana_images["handakuten"]["normal"],
                selected_image=self.kana_images["handakuten"]["selected"],
                dwell_ms=DWELL_MS,
                command=lambda: self.convert_previous_char(self.HANDAKUTEN_MAP, "゜"),
                bd=0
            )
            button.set_enabled(False)
            char_screen_buttons.append(button)
            button.grid(row=1, column=option_col, padx=10, pady=10)
            option_col += 1

        # 小文字変換：あ行，や行，た行
        if row_key in ["row_a", "row_ya", "row_ta"]:
            button = DwellImageButton(
                self.keyboard_frame,
                self.kana_images["small"]["normal"],
                selected_image=self.kana_images["small"]["selected"],
                dwell_ms=DWELL_MS,
                command=lambda: self.convert_previous_char(self.SMALL_MAP, "小"),
                bd=0
            )
            button.set_enabled(False)
            char_screen_buttons.append(button)
            button.grid(row=1, column=option_col, padx=10, pady=10)

        self.add_keyboard_back_button(relx=0.87, rely=0.45)
        self._refocus()

        self.after(500, lambda buttons=char_screen_buttons:self.enable_buttons(buttons))

    def enable_buttons(self, buttons):
        for button in buttons:
            if not button.winfo_exists():
                continue

            button.set_enabled(True)

            cursor_x = button.winfo_pointerx()
            cursor_y = button.winfo_pointery()

            button_x = button.winfo_rootx()
            button_y = button.winfo_rooty()
            button_width = button.winfo_width()
            button_height = button.winfo_height()

            if (
                button_x <= cursor_x < button_x + button_width
                and button_y <= cursor_y < button_y + button_height
            ):
                button._on_enter()
    

    def convert_previous_char(self, convert_map, log_label):
        """直前の文字が変換後もお題と一致する場合だけ変換する"""
        self.selected_chars_log += log_label

        if self.text.index("insert") == "1.0":
            self._refocus()
            return

        prev_char = self.text.get("insert -1c", "insert")

        if prev_char not in convert_map:
            self._refocus()
            return

        converted_char = convert_map[prev_char]

        self.text.delete("insert -1c", "insert")
        self.text.insert("insert", converted_char)
        self._refocus()
    

    def can_be_converted_to_target(self, char, target_char):
        """char が濁点・半濁点・小文字変換で target_char になれるか判定する"""

        maps = [
            self.DAKUTEN_MAP,
            self.HANDAKUTEN_MAP,
            self.SMALL_MAP,
        ]

        for convert_map in maps:
            if char in convert_map and convert_map[char] == target_char:
                return True

        return False


    def insert_char(self, char):
        """正しい文字だけ入力する"""
        # 実際に選択した文字は、正誤に関係なく記録する
        self.selected_chars_log += char

        self.text.insert("insert", char)

        self._refocus()


if __name__ == "__main__":
    app = TypingGameApp()
    app.mainloop()