import flet as ft
import pandas as pd
import random
import math
import threading
import time
import traceback

# --- Uploaded asset path (local) ---
# (your environment will transform this path to a usable URL when needed)
UPLOADED_IMAGE = "/mnt/data/422e83ba-3ed2-456a-acca-440d9fe66dbd.png"

# --- CONFIGURATION ---
SET_SIZE = 120  # Words per set

# Theme map (kept general; choose-sets page enforces full-black/white and blue boxes)
THEME_COLORS = {
    "light": {
        "bg_main": "#F3F4F6", "card_bg": "#ffffff", "text": "#1F2937",
        "accent": "#3B82F6", "success": "#059669", "error": "#DC2626",
        "warning": "#D97706", "neutral": "#E5E7EB", "text_btn": "#374151",
        "text_dim": "#9CA3AF", "scroll": "#9CA3AF", "purple": "#8B5CF6"
    },
    "dark": {
        "bg_main": "#1a1a1a", "card_bg": "#2b2b2b", "text": "#E5E7EB",
        "accent": "#3B82F6", "success": "#10B981", "error": "#EF4444",
        "warning": "#F59E0B", "neutral": "#404040", "text_btn": "#ffffff",
        "text_dim": "#6B7280", "scroll": "#4B5563", "purple": "#8B5CF6"
    }
}


class QuizApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "Vocab Master Pro 🎓"
        self.page.padding = 0
        self.page.theme_mode = ft.ThemeMode.SYSTEM

        # Apply choose-sets-only override flag
        self.on_sets_page = False

        # Data / state
        self.original_df = None
        self.working_df = None
        self.active_slice_df = None
        self.quiz_df = None

        self.n = 0
        self.current = 0
        self.selected_set_index = 0
        self.selected_answers = []
        self.review_flags = []
        self.temp_selection = None

        # Timer
        self.timer_seconds = 0
        self.time_limit_val = 0
        self.timer_running = False
        self.submitted = False
        self.timer_thread = None
        self.timer_mode = "overall"

        # UI
        self.file_picker = ft.FilePicker(on_result=self.on_file_picked)
        self.page.overlay.append(self.file_picker)

        self._build_ui_components()
        self.show_upload_screen()

    def _get_color(self, key):
        mode = "dark" if self.page.theme_mode == ft.ThemeMode.DARK else "light"
        return THEME_COLORS[mode].get(key, ft.Colors.BLACK)

    def _build_ui_components(self):
        # Shared text controls
        self.lbl_timer = ft.Text("00:00", color=ft.Colors.RED, size=24, weight=ft.FontWeight.BOLD, font_family="Roboto Mono")
        self.lbl_qnum = ft.Text("Question 1", weight=ft.FontWeight.BOLD, color=ft.Colors.GREY)
        self.lbl_question = ft.Text(size=22, weight=ft.FontWeight.W_500)
        self.lbl_feedback = ft.Column(spacing=8)
        self.lbl_stats = ft.Text("", size=14, color=ft.Colors.GREY)

        # grids
        self.nav_grid = ft.GridView(expand=True, runs_count=5, max_extent=60, child_aspect_ratio=1.2, spacing=8, run_spacing=8)
        self.sets_grid = ft.GridView(expand=True, max_extent=200, child_aspect_ratio=1.5, spacing=10, run_spacing=10, padding=20)

        # options
        self.opts_column = ft.Column(spacing=10)
        self.option_buttons = {}

        # Buttons - DEFER callbacks via lambdas to avoid attribute lookup issues at construction time
        self.btn_prev = self._make_btn("Previous", ft.Icons.ARROW_BACK, lambda e: getattr(self, "prev_q")(e), outline=False)
        self.btn_next = self._make_btn("Next", ft.Icons.ARROW_FORWARD, lambda e: getattr(self, "next_q")(e), outline=False)
        self.btn_mark = self._make_btn("Review", ft.Icons.FLAG_OUTLINED, lambda e: getattr(self, "toggle_flag")(e), outline=False, color_key="warning")
        self.btn_check = self._make_btn("Check", ft.Icons.CHECK_CIRCLE_OUTLINE, lambda e: getattr(self, "submit_current")(e), outline=False, color_key="success")
        # Finish and Exit now filled
        self.btn_finish = self._make_btn("Finish", ft.Icons.DONE_ALL, lambda e: getattr(self, "submit_all")(e), outline=False, color_key="error")

        # Navigation buttons
        self.btn_retry = self._make_btn("Retry Set", ft.Icons.REFRESH, lambda e: getattr(self, "handle_retry")(e))
        self.btn_change_set = self._make_btn("Change Set", ft.Icons.GRID_VIEW, lambda e: getattr(self, "handle_back_to_sets")(e), color_key="warning")
        # New File is purple
        self.btn_new_file = self._make_btn("New File", ft.Icons.UPLOAD_FILE, lambda e: getattr(self, "handle_new_file")(e), color_key="purple")
        self.btn_exit = self._make_btn("Exit", ft.Icons.EXIT_TO_APP, lambda e: self.page.window.close(), outline=False)

        # containers
        self.header_container = ft.Container(padding=ft.padding.symmetric(horizontal=20, vertical=10))
        self.q_card_container = ft.Container(padding=30, border_radius=15)
        self.bottom_bar_container = ft.Container(padding=15)

    def _make_btn(self, text, icon, cmd, outline=False, color_key="accent"):
        return ft.ElevatedButton(
            text=text, icon=icon, on_click=cmd, height=45,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=22), padding=15),
            data={"outline": outline, "key": color_key}
        )

    # ------------------- SCREENS -------------------

    def show_upload_screen(self):
        self.on_sets_page = False
        self.page.controls.clear()

        top_bar = ft.Container(
            padding=10,
            content=ft.Row(
                [
                    ft.Text("Vocab Master", weight=ft.FontWeight.BOLD),
                    ft.Row([
                        ft.Text("Dark Mode"),
                        # defer toggle_theme lookup
                        ft.Switch(value=(self.page.theme_mode == ft.ThemeMode.DARK), on_change=lambda e: getattr(self, "toggle_theme")(e))
                    ])
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN
            )
        )

        # Show the uploaded image as a preview (optional)
        image_preview = ft.Container(content=ft.Image(src=UPLOADED_IMAGE, fit=ft.ImageFit.CONTAIN), height=160) if UPLOADED_IMAGE else ft.Container()

        content = ft.Container(
            alignment=ft.alignment.center, expand=True,
            content=ft.Column(
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.SCHOOL, size=80, color=ft.Colors.BLUE),
                    ft.Text("Vocab Master Pro 🎓", size=32, weight=ft.FontWeight.BOLD),
                    ft.Container(height=12),
                    image_preview,
                    ft.Container(height=12),
                    ft.ElevatedButton("Upload Word List (Excel/CSV)", icon=ft.Icons.UPLOAD_FILE,
                                      on_click=lambda e: self.file_picker.pick_files(allowed_extensions=["csv", "xlsx", "xls"]),
                                      height=50, style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE))
                ]
            )
        )

        self.page.add(ft.Column([top_bar, content], expand=True))
        self.apply_theme_colors()

    def show_set_selection(self):
        # SPECIAL STYLING ONLY FOR THIS PAGE
        self.on_sets_page = True
        self.page.controls.clear()

        is_dark = (self.page.theme_mode == ft.ThemeMode.DARK)
        page_bg = "#000000" if is_dark else "#FFFFFF"
        header_bg = page_bg
        text_color = "#FFFFFF" if is_dark else "#000000"
        divider_color = "#1f2937" if is_dark else "#d1d5db"
        border_color = "#0f172a" if is_dark else "#bfdbfe"

        self.page.bgcolor = page_bg

        self.main_seed_input = ft.TextField(label="Main Seed", width=100, text_align=ft.TextAlign.CENTER, hint_text="Ex: 123")

        self.header_container.content = ft.Column([
            ft.Row([
                ft.Text(f"File Loaded: {len(self.original_df) if self.original_df is not None else 0} Words",
                        size=24, weight=ft.FontWeight.BOLD, color=text_color),
                ft.Row([
                    ft.Text("Dark Mode", color=text_color),
                    # defer toggle_theme lookup
                    ft.Switch(value=(self.page.theme_mode == ft.ThemeMode.DARK), on_change=lambda e: getattr(self, "toggle_theme")(e))
                ])
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),

            ft.Container(height=10),

            ft.Row([
                ft.Text("Shuffle All Words:", weight=ft.FontWeight.BOLD, color=text_color),
                self.main_seed_input,
                ft.ElevatedButton("Shuffle & Reset", on_click=lambda e: getattr(self, "apply_main_seed")(e))
            ], alignment=ft.MainAxisAlignment.CENTER),

            ft.Divider(color=divider_color),
            ft.Text(f"Select a Set (Size: {SET_SIZE} words)", size=16, color=text_color)
        ])
        self.header_container.bgcolor = header_bg

        # Build blue set buttons with white text (rounded)
        self.sets_grid.controls.clear()
        total_sets = math.ceil(len(self.working_df) / SET_SIZE) if self.working_df is not None else 0

        for i in range(total_sets):
            start = i * SET_SIZE
            end = min((i + 1) * SET_SIZE, len(self.working_df))
            num_qs = (end - start) // 4

            content_col = ft.Column([
                ft.Text(f"Set {i+1}", weight=ft.FontWeight.BOLD, size=18, color="#FFFFFF"),
                ft.Text(f"{num_qs} Questions", color="#FFFFFF")
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

            btn = ft.Container(
                bgcolor="#3B82F6",
                border=ft.border.all(2, border_color),
                border_radius=12, padding=18, ink=True,
                on_click=lambda e, idx=i: getattr(self, "on_set_selected")(idx),
                content=content_col
            )
            self.sets_grid.controls.append(btn)

        self.page.add(ft.Column([self.header_container, ft.Container(expand=True, content=self.sets_grid)], expand=True))
        # keep blue boxes intact; apply_theme_colors will not override them when on_sets_page=True
        self.apply_theme_colors()

    def show_config_screen(self):
        self.on_sets_page = False
        self.page.controls.clear()

        set_num = self.selected_set_index + 1
        q_count = len(self.active_slice_df) // 4 if self.active_slice_df is not None else 0

        self.seed_entry = ft.TextField(label="Option Mix Seed (Optional)", width=200)
        self.timer_entry = ft.TextField(label="Seconds", value="30", width=100, keyboard_type=ft.KeyboardType.NUMBER)
        self.mode_switch = ft.Switch(label="Per Question Mode", value=False, on_change=lambda e: None)

        self.q_card_container.content = ft.Column([
            ft.Row([ft.Text("Dark Mode"), ft.Switch(value=(self.page.theme_mode == ft.ThemeMode.DARK), on_change=lambda e: getattr(self, "toggle_theme")(e))], alignment=ft.MainAxisAlignment.END),
            ft.Text(f"Set {set_num} Selected", size=28, weight=ft.FontWeight.BOLD),
            ft.Text(f"({q_count} Questions available)", color=self._get_color("text_dim")),
            ft.Container(height=20),
            self.seed_entry,
            ft.Row([ft.Text("Timer Mode:"), self.mode_switch], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([ft.Text("Time Limit:"), self.timer_entry], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(height=20),
            ft.ElevatedButton("Start Quiz 🚀", on_click=lambda e: getattr(self, "start_quiz_from_timer")(e), height=50, width=200,
                              style=ft.ButtonStyle(bgcolor=self._get_color("success"), color=ft.Colors.WHITE)),
            ft.TextButton("Choose Different Set", on_click=lambda e: getattr(self, "show_set_selection")())
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=15)

        self.page.add(ft.Container(content=self.q_card_container, alignment=ft.alignment.center, expand=True))
        self.apply_theme_colors()

    def build_quiz_ui(self):
        self.on_sets_page = False
        self.page.controls.clear()

        self.header_container.content = ft.Row([
            ft.Text("Vocab Master", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([
                ft.Text("Dark Mode"),
                ft.Switch(value=(self.page.theme_mode == ft.ThemeMode.DARK), on_change=lambda e: getattr(self, "toggle_theme")(e)),
                ft.Container(width=20),
                self.lbl_timer
            ])
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        self.q_card_container.content = self.lbl_question
        self.q_card_container.border = ft.border.all(1, self._get_color("neutral"))

        # build option buttons (defer click handlers)
        self.option_buttons = {}
        self.opts_column.controls.clear()
        for char in ["A", "B", "C", "D"]:
            btn = ft.OutlinedButton(
                text=f"{char}.",
                on_click=lambda e, c=char: getattr(self, "on_option_click")(c),
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10), padding=20, alignment=ft.alignment.center_left)
            )
            self.option_buttons[char] = btn
            self.opts_column.controls.append(btn)

        self.feedback_container = ft.Container(visible=False, padding=15, border=ft.border.all(1, ft.Colors.GREY_400), border_radius=10, content=self.lbl_feedback)

        left_panel = ft.Column(expand=2, scroll=ft.ScrollMode.AUTO, controls=[self.lbl_qnum, self.q_card_container, ft.Container(height=20), self.opts_column, ft.Container(height=20), self.feedback_container])
        right_panel = ft.Container(expand=1, padding=10, content=ft.Column([ft.Text(f"Set {self.selected_set_index+1} Navigator", weight=ft.FontWeight.BOLD), ft.Divider(), self.nav_grid, ft.Divider(), self.lbl_stats]))

        self.bottom_bar_container.content = ft.Row([
            ft.Row([self.btn_mark, self.btn_prev, self.btn_check, self.btn_next, self.btn_retry, self.btn_change_set, self.btn_new_file]),
            ft.Container(expand=True),
            ft.Row([self.btn_finish, self.btn_exit])
        ])

        self.page.add(ft.Column([self.header_container, ft.Container(expand=True, padding=20, content=ft.Row([left_panel, ft.VerticalDivider(), right_panel], vertical_alignment=ft.CrossAxisAlignment.START)), self.bottom_bar_container], expand=True, spacing=0))
        self.apply_theme_colors()
        self.toggle_controls(finished=False)

    # ----------------- LOGIC -----------------

    def on_file_picked(self, e: ft.FilePickerResultEvent):
        if not e.files:
            return
        file_path = e.files[0].path
        try:
            df = pd.read_csv(file_path) if file_path.lower().endswith(".csv") else pd.read_excel(file_path)
            syn_col = next((c for c in df.columns if "synonym" in c.lower()), None)
            if syn_col:
                syn_idx = df.columns.get_loc(syn_col)
                df[syn_col] = df.iloc[:, syn_idx:].apply(lambda row: ", ".join([str(x) for x in row if pd.notna(x) and str(x).lower() != 'nan']), axis=1)

            self.original_df = df
            self.working_df = df.copy()
            self.show_set_selection()
        except Exception as ex:
            traceback.print_exc()
            self.page.open(ft.SnackBar(ft.Text(f"Error: {ex}"), bgcolor=ft.Colors.RED))

    def apply_main_seed(self, e):
        s_txt = self.main_seed_input.value.strip()
        if s_txt:
            try:
                val = int(s_txt)
                self.working_df = self.original_df.sample(frac=1, random_state=val).reset_index(drop=True)
                self.page.open(ft.SnackBar(ft.Text(f"Shuffled with seed {val}")))
            except:
                self.page.open(ft.SnackBar(ft.Text("Seed must be a number")))
                return
        else:
            self.working_df = self.original_df.copy()
            self.page.open(ft.SnackBar(ft.Text("Reset to original order")))
        self.show_set_selection()

    def on_set_selected(self, index):
        self.selected_set_index = index
        start = index * SET_SIZE
        end = min((index + 1) * SET_SIZE, len(self.working_df))
        self.active_slice_df = self.working_df.iloc[start:end].reset_index(drop=True)
        self.show_config_screen()

    def start_quiz_from_timer(self, e):
        try:
            val = int(self.timer_entry.value)
            if val <= 0:
                raise ValueError
            self.time_limit_val = val
            self.timer_seconds = val
            self.timer_mode = "per_question" if self.mode_switch.value else "overall"

            s_txt = self.seed_entry.value.strip()
            seed_val = int(s_txt) if s_txt else None

            self.quiz_df = self._generate_quiz_from_slice(self.active_slice_df, seed=seed_val)
            self.n = len(self.quiz_df)
            self.selected_answers = [None] * self.n
            self.review_flags = [False] * self.n

            # navigator
            self.nav_grid.controls.clear()
            for i in range(self.n):
                self.nav_grid.controls.append(
                    ft.Container(
                        content=ft.Text(str(i+1), weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                        alignment=ft.alignment.center, border_radius=5,
                        on_click=lambda e, x=i: getattr(self, "jump_to")(x), data=i
                    )
                )

            self.current = 0
            self.submitted = False
            self.temp_selection = None
            self.build_quiz_ui()
            self.start_timer_thread()
            self.load_question(0)

        except Exception as ex:
            traceback.print_exc()
            self.page.open(ft.SnackBar(ft.Text(f"Error: {ex}"), bgcolor=ft.Colors.RED))

    def _generate_quiz_from_slice(self, df_slice, seed=None):
        word_col = next((c for c in df_slice.columns if "word" in c.lower()), None)
        meaning_col = next((c for c in df_slice.columns if "meaning" in c.lower()), None)
        syn_col = next((c for c in df_slice.columns if "synonym" in c.lower()), None)

        if not word_col or not meaning_col:
            raise ValueError("File must contain 'Word' and 'Meaning' columns.")

        if seed is not None:
            shuffled = df_slice.sample(frac=1, random_state=seed).reset_index(drop=True)
            rng = random.Random(seed)
        else:
            shuffled = df_slice.sample(frac=1).reset_index(drop=True)
            rng = random.Random()

        if 0 < len(shuffled) < 4:
            while len(shuffled) < 4:
                shuffled = pd.concat([shuffled, shuffled])
            shuffled = shuffled.reset_index(drop=True)

        quiz_data = []
        for i in range(0, len(shuffled), 4):
            chunk = shuffled.iloc[i: i + 4]
            if len(chunk) < 4:
                chunk = pd.concat([chunk, shuffled.iloc[0:4 - len(chunk)]])
            target = chunk.iloc[0]

            def clean(v):
                return str(v).strip().replace("[", "").replace("]", "").replace("'", "").replace('"', "")

            opts = [{
                "txt": str(target[word_col]).strip(),
                "mean": str(target[meaning_col]).strip(),
                "syn": clean(target[syn_col]) if syn_col else "",
                "correct": True
            }]
            for _, row in chunk.iloc[1:].iterrows():
                opts.append({
                    "txt": str(row[word_col]).strip(),
                    "mean": str(row[meaning_col]).strip(),
                    "syn": clean(row[syn_col]) if syn_col else "",
                    "correct": False
                })

            rng.shuffle(opts)
            entry = {"Question": f"\"{target[meaning_col]}\""}
            mapping = ["A", "B", "C", "D"]
            for idx, d in enumerate(opts):
                L = mapping[idx]
                entry[f"Option {L}"] = d["txt"]
                entry[f"Meaning {L}"] = d["mean"]
                entry[f"Synonyms {L}"] = d["syn"]
                if d["correct"]:
                    entry["Correct Answer"] = L
            quiz_data.append(entry)
        return pd.DataFrame(quiz_data)

    def load_question(self, idx):
        if not (0 <= idx < self.n):
            return

        self.current = idx
        row = self.quiz_df.iloc[idx]

        self.lbl_qnum.value = f"Question {idx+1} of {self.n}"
        # Use theme text color so readable in both themes
        self.lbl_question.value = row["Question"]
        self.lbl_question.color = self._get_color("text")

        saved = self.selected_answers[idx]
        correct_L = row["Correct Answer"]
        show = self.submitted or (saved is not None)

        for char, btn in self.option_buttons.items():
            btn.text = f"{char}. {row[f'Option {char}']}"
            btn.disabled = False

            bg_color = None
            text_color = self._get_color("text_btn")
            side_border = ft.BorderSide(1, self._get_color("neutral"))

            if show:
                btn.disabled = True
                if char == correct_L:
                    bg_color = self._get_color("success")
                    text_color = ft.Colors.WHITE
                    btn.text += "  ✅"
                    side_border = None
                elif char == saved and char != correct_L:
                    bg_color = self._get_color("error")
                    text_color = ft.Colors.WHITE
                    btn.text += "  ❌"
                    side_border = None
                else:
                    text_color = self._get_color("text_dim")
                    side_border = ft.BorderSide(1, ft.Colors.GREY_400)
            else:
                if (self.selected_answers[idx] is None) and (char == self.temp_selection):
                    bg_color = self._get_color("accent")
                    text_color = ft.Colors.WHITE
                    side_border = None

            btn.style = ft.ButtonStyle(
                bgcolor=bg_color,
                color=text_color,
                side=side_border,
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=20,
                alignment=ft.alignment.center_left
            )

        if show:
            self.lbl_feedback.controls.clear()

            is_correct = (saved == correct_L)
            status_txt = "Correct! 🎉" if is_correct else "Incorrect."
            status_col = self._get_color("success") if is_correct else self._get_color("error")
            if not saved:
                status_txt, status_col = "Not Answered.", self._get_color("warning")

            # status
            self.lbl_feedback.controls.append(ft.Text(status_txt, color=status_col, weight=ft.FontWeight.BOLD))
            self.lbl_feedback.controls.append(ft.Container(height=6))

            # detailed definitions with improved readability (larger weight/size for meaning)
            for opt in ["A", "B", "C", "D"]:
                marker = "✅" if opt == correct_L else ("❌" if opt == saved else "➡")
                option_row = ft.Row([
                    ft.Text(f"{opt}:", width=26),
                    ft.Text(row[f'Option {opt}'], weight=ft.FontWeight.BOLD),
                    ft.Container(width=8),
                    ft.Text(marker)
                ], vertical_alignment=ft.CrossAxisAlignment.START)
                self.lbl_feedback.controls.append(option_row)

                # Meaning: larger + heavier for readability
                self.lbl_feedback.controls.append(ft.Text(f"   📖 {row[f'Meaning {opt}']}", color=self._get_color("text"), weight=ft.FontWeight.W_600, size=16))

                syn_txt = row[f"Synonyms {opt}"]
                if syn_txt and str(syn_txt).strip():
                    # label not bold, synonyms bold (and use theme text color)
                    self.lbl_feedback.controls.append(ft.Row([ft.Text("   🔗"), ft.Text(str(syn_txt), weight=ft.FontWeight.BOLD, color=self._get_color("text"))]))

                self.lbl_feedback.controls.append(ft.Container(height=6))

            self.feedback_container.visible = True
        else:
            self.feedback_container.visible = False

        self.update_nav_colors()
        self.page.update()

    def on_option_click(self, char):
        if self.submitted:
            return
        if self.selected_answers[self.current]:
            return
        # register a temporary selection, but don't accept it as final until Check is pressed
        self.temp_selection = char
        self.load_question(self.current)

    def submit_current(self, e):
        """
        If called with e is None -> automatic timer-triggered call.
        We treat that as a skip (do not accept temp_selection).
        If called with e (button click), accept temp_selection as answer.
        """
        if self.submitted or self.selected_answers[self.current]:
            return

        manual_submit = (e is not None)

        # Automatic timeout case: skip and move to next question without accepting temp selection
        if not manual_submit:
            if self.timer_mode == "per_question":
                self.timer_running = False
            # Clear temp selection (do not accept)
            self.temp_selection = None

            # Advance to next question shortly after to allow UI refresh
            def _delayed_next():
                time.sleep(0.05)
                self.next_q(None)
            threading.Thread(target=_delayed_next, daemon=True).start()
            return

        # -- Manual submit (user pressed Check) --
        if not self.temp_selection:
            # user clicked Check without selection
            if e:
                self.page.open(ft.SnackBar(ft.Text("Select an option first")))
            return

        # Accept the temp selection
        self.selected_answers[self.current] = self.temp_selection
        self.temp_selection = None
        if self.timer_mode == "per_question":
            self.timer_running = False

        self.load_question(self.current)

        # In per-question mode, auto-advance after a short pause so user sees feedback
        if self.timer_mode == "per_question":
            def auto_next():
                time.sleep(1.5)
                self.next_q(None)
            threading.Thread(target=auto_next, daemon=True).start()

    def next_q(self, e):
        if self.current < self.n - 1:
            self.temp_selection = None
            self.current += 1
            if self.timer_mode == "per_question" and not self.submitted:
                self.timer_seconds = self.time_limit_val
                self.timer_running = True
                self._update_timer_label()
                if not self.timer_thread or not self.timer_thread.is_alive():
                    self.start_timer_thread()
            self.load_question(self.current)
        elif self.timer_mode == "per_question" and not self.submitted:
            self.submit_all()

    def prev_q(self, e):
        if self.timer_mode == "per_question" and not self.submitted:
            return
        if self.current > 0:
            self.temp_selection = None
            self.current -= 1
            self.load_question(self.current)

    def jump_to(self, idx):
        if self.timer_mode == "per_question" and not self.submitted:
            return
        self.temp_selection = None
        self.load_question(idx)

    def toggle_flag(self, e):
        if self.submitted:
            return
        self.review_flags[self.current] = not self.review_flags[self.current]
        self.update_nav_colors()
        self.page.update()

    def update_nav_colors(self):
        for i, box in enumerate(self.nav_grid.controls):
            bg = self._get_color("neutral")
            border = ft.border.all(2, "transparent")

            answered = (self.selected_answers[i] is not None)
            is_current = (i == self.current)

            if answered:
                correct = self.quiz_df.iloc[i]["Correct Answer"]
                user_ans = self.selected_answers[i]
                bg = self._get_color("success") if user_ans == correct else self._get_color("error")
            elif self.review_flags[i]:
                bg = self._get_color("warning")

            if is_current:
                if not answered:
                    bg = self._get_color("accent")
                else:
                    border = ft.border.all(3, self._get_color("accent"))

            box.bgcolor = bg
            box.border = border

        if self.nav_grid.page:
            self.nav_grid.update()

    def submit_all(self, e=None):
        self.submitted = True
        self.timer_running = False

        total = self.n
        answered = sum(1 for a in self.selected_answers if a is not None)
        correct = sum(1 for i in range(self.n) if self.selected_answers[i] == self.quiz_df.iloc[i]["Correct Answer"])
        wrong = answered - correct
        skipped = total - answered
        marked = sum(self.review_flags)

        self.lbl_stats.value = f"Score: {correct} / {total}"

        content = ft.Column([
            ft.Row([ft.Icon(ft.Icons.LIST_ALT), ft.Text(f"Total: {total}", size=16)]),
            ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN), ft.Text(f"Correct: {correct}", size=16, color=ft.Colors.GREEN)]),
            ft.Row([ft.Icon(ft.Icons.CANCEL, color=ft.Colors.RED), ft.Text(f"Wrong: {wrong}", size=16, color=ft.Colors.RED)]),
            ft.Row([ft.Icon(ft.Icons.DO_NOT_DISTURB_ON, color=ft.Colors.GREY), ft.Text(f"Skipped: {skipped}", size=16)]),
            ft.Row([ft.Icon(ft.Icons.FLAG, color=ft.Colors.ORANGE), ft.Text(f"Marked: {marked}", size=16, color=ft.Colors.ORANGE)])
        ], tight=True, spacing=10)

        dlg = ft.AlertDialog(title=ft.Text("Quiz Results 📊"), content=content)
        dlg.actions = [ft.TextButton("Review Answers", on_click=lambda e: self.page.close(dlg))]
        self.page.open(dlg)

        self.toggle_controls(finished=True)
        self.load_question(self.current)

    def toggle_controls(self, finished):
        self.btn_mark.visible = not finished
        self.btn_check.visible = not finished
        self.btn_finish.visible = not finished
        self.btn_retry.visible = finished
        self.btn_change_set.visible = finished
        self.btn_new_file.visible = finished
        self.page.update()

    def handle_retry(self, e):
        self.selected_answers = [None] * self.n
        self.review_flags = [False] * self.n
        self.submitted = False
        self.show_config_screen()

    def handle_back_to_sets(self, e):
        self.show_set_selection()

    def handle_new_file(self, e):
        self.show_upload_screen()

    def toggle_theme(self, e):
        # toggle and re-render the current page (apply choose-sets override if on that page)
        self.page.theme_mode = ft.ThemeMode.DARK if e.control.value else ft.ThemeMode.LIGHT
        if self.on_sets_page:
            self.show_set_selection()
        else:
            self.apply_theme_colors()
            self.page.update()

    def apply_theme_colors(self):
        """
        Apply theme colors for all pages except choose-sets customizations which are preserved
        when self.on_sets_page == True.
        """
        if not self.on_sets_page:
            self.page.bgcolor = self._get_color("bg_main")
            self.header_container.bgcolor = self._get_color("card_bg")

        self.bottom_bar_container.bgcolor = self._get_color("card_bg")
        self.q_card_container.bgcolor = self._get_color("card_bg")

        # question and feedback follow theme text color (avoids unreadable white on light background)
        self.lbl_question.color = self._get_color("text")
        self.lbl_feedback.color = self._get_color("text")

        # Buttons: if outline flag set at creation keep outline style else filled
        for btn in [self.btn_prev, self.btn_next, self.btn_mark, self.btn_check, self.btn_finish, self.btn_retry, self.btn_change_set, self.btn_new_file, self.btn_exit]:
            if btn.data:
                col = self._get_color(btn.data["key"])
                if btn.data.get("outline", False):
                    btn.style.side = ft.BorderSide(2, col)
                    btn.style.color = col
                    btn.style.bgcolor = "transparent"
                else:
                    btn.style.bgcolor = col
                    btn.style.color = ft.Colors.WHITE

        # Only reset sets grid visuals if NOT on sets page (so blue boxes remain)
        if not self.on_sets_page and self.sets_grid.controls:
            for btn in self.sets_grid.controls:
                btn.bgcolor = self._get_color("card_bg")
                btn.border = ft.border.all(2, self._get_color("neutral"))
                if len(btn.content.controls) >= 2:
                    btn.content.controls[0].color = self._get_color("text")
                    btn.content.controls[1].color = self._get_color("text_dim")

        if self.quiz_df is not None:
            self.update_nav_colors()
            self.load_question(self.current)

    def _update_timer_label(self):
        m, s = divmod(self.timer_seconds, 60)
        self.lbl_timer.value = f"{m:02d}:{s:02d}"
        self.lbl_timer.update()

    def start_timer_thread(self):
        # starts a background thread that ticks down timer_seconds and triggers behavior on expiry
        self.timer_running = True

        def run():
            while self.timer_running:
                if self.timer_seconds > 0:
                    time.sleep(1)
                    self.timer_seconds -= 1
                    self._update_timer_label()
                else:
                    # when time runs out decide action depending on mode
                    if self.timer_mode == "overall":
                        self.timer_running = False

                        async def finish():
                            self.submit_all()

                        # schedule in main loop
                        self.page.run_task(finish)
                        break
                    elif self.timer_mode == "per_question":
                        self.timer_running = False

                        # call submit_current(None) — our submit_current treats None as automatic skip
                        async def sub():
                            self.submit_current(None)

                        self.page.run_task(sub)
                        break

        self.timer_thread = threading.Thread(target=run, daemon=True)
        self.timer_thread.start()

def main(page: ft.Page):
    QuizApp(page)


if __name__ == "__main__":
    ft.app(target=main)
