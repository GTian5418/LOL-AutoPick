import tkinter as tk
from tkinter import ttk, font
from PIL import Image, ImageTk
import os, json, re, requests, threading, time, psutil
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from requests.auth import HTTPBasicAuth
import sys
from tqdm import tqdm

# ----------------------------------------------------
# ⭐️ 全局变量初始化
# ----------------------------------------------------
# 英雄 ID 常量
DEFAULT_CHAMPION_ID = 157 # 默认英雄 (亚索)
DEFAULT_BAN_CHAMPION_ID = 484 # 默认禁用英雄 (俄洛伊)
DEFAULT_CHAMPION_NAME = "" # 动态确定 (锁定/预选默认名)
DEFAULT_BAN_NAME = "" # 动态确定 (禁用默认名)

# 动态 LCU 状态和 ID
lcu = None
AUTO_INTENT_ID = None # 预选ID (将与AUTO_PICK_ID同步)
AUTO_PICK_ID = None
AUTO_BAN_ID = None # 禁用ID
has_picked = False # 用于判断是否已完成 PICK 动作（防止重复锁定）

# UI 相关的全局变量 (将在 UI 初始化时赋值)
avatar_cache = {}
champion_map = {}
champion_keys = {}
champion_map_search = {}
champion_data_info = {}
blank_avatar = None
status_var = None
auto_pick_var = None
auto_accept_var = None
auto_ban_var = None
avatar_label = None
ban_avatar_label = None 

# ----------------------------------------------------
# 辅助函数
# ----------------------------------------------------

def update_selection_id(hero_name, selection_type):
    """
    更新全局英雄ID变量的回调函数。
    :param hero_name: 被选中的英雄名 (中文称号)
    :param selection_type: "pick" 或 "ban"
    """
    global AUTO_PICK_ID, AUTO_BAN_ID, AUTO_INTENT_ID, has_picked

    # 如果 hero_name 为空字符串或不在列表中，则设置为 None ID
    if not hero_name or hero_name not in champion_map:
        champ_id = None
    else:
        champ_id = champion_map.get(hero_name)

    if selection_type == "pick":
        AUTO_PICK_ID = champ_id
        AUTO_INTENT_ID = champ_id # 核心修改：预选ID与锁定ID同步
        # 仅在更新 PICK 英雄时才更新主头像
        update_avatar_for_selection(hero_name, selection_type) 
    elif selection_type == "ban":
        AUTO_BAN_ID = champ_id
        # 禁用英雄更新禁用头像
        update_avatar_for_selection(hero_name, selection_type) 

    # 只要更改了英雄，就重置锁定状态，允许重新尝试
    has_picked = False


def update_avatar_for_selection(name, selection_type):
    """
    更新主界面的大头像或禁用小头像。
    """
    global avatar_cache, blank_avatar, avatar_label, ban_avatar_label 

    # 传入 None 或找不到名字时显示空白头像
    if name is None or name not in avatar_cache:
        # 如果是禁用，使用小一点的空白头像
        photo = create_blank_avatar(size=(60, 60)) if selection_type == "ban" else blank_avatar
    else:
        if selection_type == "ban":
            # 裁剪头像，并创建新的 PhotoImage
            img_key = champion_keys.get(name)
            try:
                img_path = resource_path(os.path.join("avatars", f"{img_key}.png"))
                pil_img = Image.open(img_path).resize((60, 60))
                # 必须将 PhotoImage 存储在一个引用中
                if ban_avatar_label:
                    ban_avatar_label._photo_ref = ImageTk.PhotoImage(pil_img)
                    photo = ban_avatar_label._photo_ref
                else:
                    photo = create_blank_avatar(size=(60, 60))
            except:
                photo = create_blank_avatar(size=(60, 60))
        else:
            photo = avatar_cache.get(name, blank_avatar)

    if selection_type == "pick" and avatar_label:
        avatar_label.config(image=photo)
        avatar_label.image = photo
    elif selection_type == "ban" and ban_avatar_label: 
        ban_avatar_label.config(image=photo)
        ban_avatar_label.image = photo

# ----------------------------------------------------
# 其它辅助函数 (保持不变)
# ----------------------------------------------------
def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def is_frozen():
    return hasattr(sys, '_MEIPASS')

def get_lcu_credentials():
    for proc in psutil.process_iter(['name', 'cmdline']):
        if proc.info['name'] == 'LeagueClientUx.exe':
            cmdline = ' '.join(proc.info['cmdline'])
            port_match = re.search(r'--app-port=(\d+)', cmdline)
            token_match = re.search(r'--remoting-auth-token=([\w-]+)', cmdline)
            if port_match and token_match:
                port = port_match.group(1)
                token = token_match.group(1)
                return port, token
    return None, None

class LoLHelper:
    def __init__(self, port, token):
        self.base_url = f"https://127.0.0.1:{port}"
        self.auth = HTTPBasicAuth("riot", token)
        self.session = requests.Session()
        self.session.verify = False

    def get(self, endpoint):
        url = f"{self.base_url}/{endpoint}"
        response = self.session.get(url, auth=self.auth)
        return response.json()

    def post(self, endpoint, data):
        url = f"{self.base_url}/{endpoint}"
        response = self.session.post(url, json=data, auth=self.auth)
        return response.json()

def create_blank_avatar(size=(120, 120), color="#e8e8e8"): # 浅灰色背景
    img = Image.new("RGB", size, color)
    return ImageTk.PhotoImage(img)

def ensure_assets_ready():
    global DEFAULT_CHAMPION_NAME, DEFAULT_BAN_NAME, champion_map, champion_keys, champion_map_search, champion_data_info
    print("🚀 正在初始化资源...")
    try:
        versions = requests.get("https://ddragon.leagueoflegends.com/api/versions.json").json()
        version = next(v for v in versions if re.match(r"^\d+\.\d+\.\d+$", v))
    except Exception as e:
        print(f"❌ 无法获取最新版本号，使用默认版本 15.21.1: {e}")
        version = "15.21.1" # Fallback version
    
    print(f"📦 版本号：{version}")
    
    json_read_path = resource_path("champion.json")
    json_write_path = os.path.join(os.getcwd(), "champion.json")
    need_download_json = True
    
    # 检查本地文件是否有效
    if os.path.exists(json_read_path):
        try:
            with open(json_read_path, encoding="utf-8") as f:
                data = json.load(f)
                if "type" in data and data["type"] == "champion":
                    need_download_json = False
        except:
            pass
            
    if need_download_json:
        print("📥 下载中文英雄数据...")
        url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/zh_CN/champion.json"
        try:
            r = requests.get(url)
            r.raise_for_status()
            with open(json_write_path, "w", encoding="utf-8") as f:
                f.write(r.text)
            print("✅ champion.json 下载完成")
        except requests.exceptions.RequestException as e:
            print(f"❌ 下载失败：{e}。尝试从本地读取...")
            if not os.path.exists(json_read_path):
                print("❌ 本地也无数据，初始化失败。")
                return {} # 返回空字典
    
    try:
        with open(resource_path("champion.json"), encoding="utf-8") as f:
            champ_data = json.load(f)["data"]
    except Exception as e:
        print(f"❌ 读取英雄数据失败：{e}")
        return {}

    # 填充 champion_map (所有英雄名: ID)
    for key, info in champ_data.items():
        name = info["name"]
        champ_id = int(info["key"])
        champion_map[name] = champ_id
        champion_keys[name] = key
        champion_data_info[name] = info
        champion_map_search[name] = name # 中文名
        champion_map_search[info["title"]] = name # 称号
        champion_map_search[info["id"]] = name # 英文名

    # 查找默认英雄名
    default_names = {}
    for name, champ_id in champion_map.items():
        if champ_id == DEFAULT_CHAMPION_ID:
            default_names[DEFAULT_CHAMPION_ID] = name
        if champ_id == DEFAULT_BAN_CHAMPION_ID:
            default_names[DEFAULT_BAN_CHAMPION_ID] = name

    # 赋值给全局变量
    all_names = list(champion_map.keys())
    first_name = all_names[0] if all_names else ""
    DEFAULT_CHAMPION_NAME = default_names.get(DEFAULT_CHAMPION_ID, first_name)
    DEFAULT_BAN_NAME = default_names.get(DEFAULT_BAN_CHAMPION_ID, first_name)

    if is_frozen():
        avatar_dir = resource_path("avatars")
        print("🧊 已打包环境，跳过头像下载检查")
    else:
        avatar_dir = os.path.join(os.getcwd(), "avatars")
        os.makedirs(avatar_dir, exist_ok=True)
        missing = []
        for key in champ_data.keys():
            path = os.path.join(avatar_dir, f"{key}.png")
            if not os.path.exists(path):
                missing.append(key)
        
        if missing:
            print(f"🖼️ 缺失头像 {len(missing)} 个，正在下载...")
            for key in tqdm(missing, desc="下载头像"):
                url = f"https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{key}.png"
                try:
                    img_data = requests.get(url).content
                    with open(os.path.join(avatar_dir, f"{key}.png"), "wb") as f:
                        f.write(img_data)
                except Exception as e:
                    print(f"❌ 下载失败：{key} → {e}")
            print("✅ 所有头像资源已就绪")
        else:
            print("✅ 所有头像资源已完整")
            
    return champ_data

def load_local_avatars(champion_keys, folder="avatars"):
    cache = {}
    for name, key in champion_keys.items():
        path = os.path.join(folder, f"{key}.png")
        full_path = resource_path(path)
        if os.path.exists(full_path):
            try:
                img = Image.open(full_path).resize((120, 120))
                cache[name] = ImageTk.PhotoImage(img)
            except Exception as e:
                print(f"头像读取失败：{name} → {e}")
    return cache

def monitor_game_state():
    global lcu, AUTO_PICK_ID, AUTO_INTENT_ID, AUTO_BAN_ID, has_picked, auto_pick_var, auto_ban_var, status_var, auto_accept_var

    if lcu is None or auto_pick_var is None or auto_ban_var is None or status_var is None: 
        time.sleep(1)
        return

    while True:
        try:
            # 自动接受匹配 Check 
            if auto_accept_var.get():
                match_state = lcu.get("lol-matchmaking/v1/ready-check")
                if match_state.get("state") == "InProgress":
                    print("🎮 检测到匹配成功，正在接受对局...")
                    lcu.post("lol-matchmaking/v1/ready-check/accept", {})
                    time.sleep(0.1)
        except Exception:
            pass 

        try:
            state = lcu.get("lol-gameflow/v1/session")
            phase = state.get("phase", "None")

            # 非选人阶段，重置状态
            if phase != "ChampSelect":
                has_picked = False

            status_text_base = {
                "None": "未在房间",
                "Lobby": "正在房间 - 未排队",
                "Matchmaking": "正在房间 - 排队中",
                "ReadyCheck": "正在房间 - 接受中",
                "ChampSelect": "正在房间 - 选英雄",
                "InProgress": "游戏中",
            }.get(phase, phase)

            status_var.set(f"当前状态：{status_text_base}")

            # --------------------------------------------------
            # 核心：处理 ChampSelect 阶段的 Ban, Intent, Pick
            # --------------------------------------------------
            if phase == "ChampSelect":
                try:
                    session = lcu.get("lol-champ-select/v1/session")
                    cell_id = session["localPlayerCellId"]

                    current_champ_select_phase = session["timer"]["phase"]

                    sub_phase_text = {
                        "PLANNING": "预选/预禁选 (Intent)",
                        "BAN_PICK": "禁用/选择",
                        "PRE_BAN": "预禁选 (Intent)",
                        "BAN": "禁用中 (Ban)",
                        "PRE_PICK": "预选 (Intent)",
                        "PICK": "选择中 (Pick)",
                        "FINAL_BANS": "最终禁用",
                        "FINALIZATION": "选人结束/等待中",
                        "CLOSING": "选人结束"
                    }.get(current_champ_select_phase, "选英雄中...")

                    status_var.set(f"当前状态：{status_text_base} ({sub_phase_text})")
                    print(f"--- 实时阶段: {current_champ_select_phase} | 状态栏: {sub_phase_text} ---")

                    
                    should_exit_outer_loop = False
                    
                    # 1. 预选英雄 (Intent) 逻辑 - 持续发送 (低优先级，不退出循环)
                    if auto_pick_var.get() and AUTO_PICK_ID and current_champ_select_phase in ("PLANNING", "PRE_BAN", "PRE_PICK"):
                        for group in session["actions"]:
                            for action in group:
                                action_type = action["type"]
                                actor_cell_id = action["actorCellId"]
                                completed = action["completed"]
                                is_active = action.get("isInProgress", False) 

                                # 找到自己的预选 Action (Type: pick, Active: False)
                                if action_type == "pick" and actor_cell_id == cell_id and not completed and not is_active:
                                    action_id = action["id"]
                                    lcu.session.patch(
                                        f"{lcu.base_url}/lol-champ-select/v1/session/actions/{action_id}",
                                        json={"championId": AUTO_PICK_ID, "completed": False}, 
                                        auth=lcu.auth
                                    )
                                    print(f"🔄 Intent PATCH 预选英雄 ID: {AUTO_PICK_ID} | Action ID: {action_id} | 阶段: {current_champ_select_phase}")
                                    # Intent 不退出循环
                                    break # 找到预选 action 后，跳出内层动作循环，进入下一个 group 检查

                    # 2. 遍历动作组，执行 Ban 和 Lock (高优先级，完成后立即退出循环)
                    for group_index, group in enumerate(session["actions"]):
                        if should_exit_outer_loop:
                            break # 如果完成了 Ban 或 Lock，跳出外部 group 循环

                        for action in group:
                            action_id = action["id"]
                            action_type = action["type"]
                            actor_cell_id = action["actorCellId"]
                            completed = action["completed"]
                            is_active = action.get("isInProgress", False) 

                            # 增加 Action 详情打印 (用于调试)
                            print(f"  [Action {action_id} | Group {group_index}] Type: {action_type}, Active: {is_active}, Completed: {completed}, Actor: {actor_cell_id}")

                            # 仅处理自己的活动且未完成动作
                            if actor_cell_id != cell_id or completed:
                                continue

                            # ----------------------------------------------------------------------
                            # 优先级 A: Pick/Lock (锁定英雄) - Active 且 Pick 阶段
                            # ----------------------------------------------------------------------
                            if action_type == "pick" and is_active and not completed and auto_pick_var.get() and AUTO_PICK_ID and not has_picked:
                                if current_champ_select_phase in ("PICK", "BAN_PICK"): 
                                    lcu.session.patch(
                                        f"{lcu.base_url}/lol-champ-select/v1/session/actions/{action_id}",
                                        json={"championId": AUTO_PICK_ID, "completed": True},
                                        auth=lcu.auth
                                    )
                                    print(f"✅ LOCK PATCH 自动锁定英雄 ID: {AUTO_PICK_ID} | Action ID: {action_id} | 阶段: {current_champ_select_phase}")
                                    has_picked = True
                                    should_exit_outer_loop = True
                                    break # 锁定后退出当前动作循环

                            # ----------------------------------------------------------------------
                            # 优先级 B: Ban (禁用英雄) - Active 且 Ban 阶段
                            # ----------------------------------------------------------------------
                            elif action_type == "ban" and is_active and not completed and auto_ban_var.get() and AUTO_BAN_ID:
                                lcu.session.patch(
                                    f"{lcu.base_url}/lol-champ-select/v1/session/actions/{action_id}",
                                    json={"championId": AUTO_BAN_ID, "completed": True},
                                    auth=lcu.auth
                                )
                                print(f"✅ BAN PATCH 自动禁用英雄 ID: {AUTO_BAN_ID} | Action ID: {action_id}")
                                should_exit_outer_loop = True
                                break # 禁用完成，退出当前动作循环


                except Exception as e:
                    print(f"❌ 自动操作异常：{e}")

        except Exception as e:
            # LCU 连接失败或 session 错误
            if status_var:
                status_var.set("状态获取失败或 LCU 未运行")

        time.sleep(0.1)

# ----------------------------------------------------
# 核心：自定义图片下拉选择器类 (ImageDropdown) - 修复 Toplevel 图标
# ----------------------------------------------------
class ImageDropdown(tk.Frame):
    _list_photo_refs = {}
    DROPDOWN_HEIGHT = 400

    def __init__(self, master, champion_map, champion_keys, champion_data_info, on_select_callback, default_name):
        super().__init__(master, bd=1, relief="groove")
        self.champion_map = champion_map
        self.champion_keys = champion_keys
        self.champion_data_info = champion_data_info
        self.on_select_callback = on_select_callback
        self.default_name = default_name

        self.selected_champion_name = tk.StringVar(value=default_name)
        self.current_filter_keyword = ""
        self.filtered_champions = list(champion_map.keys())
        self.selected_index = -1

        # 使用 tk.Entry
        self.entry = tk.Entry(self, textvariable=self.selected_champion_name, width=28, font=("Microsoft YaHei", 10), relief="flat")
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<KeyRelease>", self._on_key_release)
        self.entry.bind("<Return>", self._select_current)
        self.entry.bind("<Down>", lambda e: self._navigate(1))
        self.entry.bind("<Up>", lambda e: self._navigate(-1))

        self.arrow_button = tk.Button(self, text="▼", command=self._toggle_list, width=2, bd=0, relief="flat", bg="#f2f2f2")
        self.arrow_button.pack(side="right", fill="y")

        self.listbox_frame = None

        # 确保 ID 在 UI 初始化时即被设置
        self.on_select_callback(default_name)

    def _toggle_list(self):
        if self.listbox_frame:
            self._hide_list_now()
        else:
            keyword = self.entry.get().strip()
            self._filter_champions(keyword)
            self.master.after(10, self._show_list)

    def _on_key_release(self, event):
        current_text = self.selected_champion_name.get()
        keyword = current_text.strip()

        if event.keysym in ("Down", "Up", "Return", "Shift_L", "Shift_R", "Control_L", "Control_R"):
            return

        if keyword != self.current_filter_keyword:
            self.current_filter_keyword = keyword
            self._filter_champions(keyword)

            if keyword and self.filtered_champions:
                self.master.after(10, self._show_list)
            else:
                self.master.after(10, self._hide_list_now)

        # 只有当输入完全匹配一个英雄名时，才触发英雄选择回调，更新ID
        if keyword in self.champion_map:
            self.on_select_callback(keyword)
        elif not keyword:
            # 清空输入框时，回调默认英雄
            self.on_select_callback(self.default_name)
        else:
            # 输入了不匹配的文字，回调 None ID
            self.on_select_callback(None)

        self.selected_champion_name.set(current_text)

    def _hide_list_now(self):
        if self.listbox_frame:
            try:
                # 先解绑 FocusOut，再销毁
                self.listbox_frame.unbind("<FocusOut>")
                self.listbox_frame.grab_release()
                self.listbox_frame.destroy()
            except tk.TclError:
                pass
            self.listbox_frame = None
            self.selected_index = -1
            self._list_photo_refs.clear()

    def _filter_champions(self, keyword):
        global champion_map_search
        if not keyword:
            self.filtered_champions = list(self.champion_map.keys())
        else:
            lower_keyword = keyword.lower()
            filtered = []
            # 只在 champion_map_search 中查找
            for search_term, official_name in champion_map_search.items():
                if lower_keyword in search_term.lower():
                    if official_name not in filtered:
                        filtered.append(official_name)

            # 确保中文名直接搜索有效
            for name in self.champion_map.keys():
                if lower_keyword in name.lower() and name not in filtered:
                    filtered.append(name)

            self.filtered_champions = filtered

    def _on_mousewheel(self, event, canvas):
        if event.num == 4 or event.delta > 0:
            canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:
            canvas.yview_scroll(1, "units")

    def _bind_mousewheel_recursive(self, widget, canvas):
        widget.bind("<MouseWheel>", lambda e: self._on_mousewheel(e, canvas), add=True)
        widget.bind("<Button-4>", lambda e: self._on_mousewheel(e, canvas), add=True)
        widget.bind("<Button-5>", lambda e: self._on_mousewheel(e, canvas), add=True)

        for child in widget.winfo_children():
            self._bind_mousewheel_recursive(child, canvas)


    def _show_list(self):
        self._hide_list_now()
        if not self.filtered_champions:
            return

        self.listbox_frame = tk.Toplevel(self.master)
        self.listbox_frame.wm_transient(self.master)

        # ⭐️ 修复：设置 Toplevel 窗口的图标
        icon_path = resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.listbox_frame.iconbitmap(icon_path)
            except Exception as e:
                # TclError: not a bitmap file (常见于非ICO文件)
                print(f"❌ 警告：无法设置 Toplevel 图标，请确保 'app_icon.ico' 是有效的 ICO 文件。{e}")

        self.update_idletasks()
        x = self.master.winfo_rootx() + self.winfo_x()
        y = self.master.winfo_rooty() + self.winfo_y() + self.winfo_height()

        self.listbox_frame.wm_geometry(f"{self.winfo_width()}x{self.DROPDOWN_HEIGHT}+{x}+{y}")

        self.master.after(50, self.listbox_frame.grab_set)

        # 绑定 FocusOut 事件，只有当 Toplevel 自身失去焦点时才关闭
        self.master.after(150, lambda: self.listbox_frame.bind("<FocusOut>", lambda e: self._hide_list_now() if str(e.widget) == str(self.listbox_frame) else None))

        canvas = tk.Canvas(self.listbox_frame, borderwidth=0, highlightthickness=0)
        vbar = tk.Scrollbar(self.listbox_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)

        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._bind_mousewheel_recursive(canvas, canvas)

        scrollable_frame = tk.Frame(canvas)
        scrollable_frame.update_idletasks()
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        scrollable_frame.bind("<Configure>", on_frame_configure)

        self.list_items = []
        for i, name in enumerate(self.filtered_champions):
            key = self.champion_keys.get(name)

            try:
                img_path = resource_path(os.path.join("avatars", f"{key}.png"))
                pil_img = Image.open(img_path).resize((32, 32))
                list_photo = ImageTk.PhotoImage(pil_img)
                self._list_photo_refs[name] = list_photo
            except:
                list_photo = create_blank_avatar(size=(32, 32))

            item_frame = tk.Frame(scrollable_frame, padx=5, pady=2, bg="#f0f0f0")
            item_frame.pack(fill="x")

            img_label = tk.Label(item_frame, image=list_photo, bg="#f0f0f0")
            img_label.pack(side="left", padx=5)

            # 修复：如果 title 不存在，默认为空字符串
            title = self.champion_data_info.get(name, {}).get('title', '')
            text_label = tk.Label(item_frame, text=f"{name} ({title})", anchor="w", bg="#f0f0f0", font=("Microsoft YaHei", 10))
            text_label.pack(side="left", fill="x", expand=True)

            item_frame.bind("<Button-1>", lambda e, n=name: self.master.after(50, lambda: self._on_list_select(n)))
            img_label.bind("<Button-1>", lambda e, n=name: self.master.after(50, lambda: self._on_list_select(n)))
            text_label.bind("<Button-1>", lambda e, n=name: self.master.after(50, lambda: self._on_list_select(n)))

            self.list_items.append((item_frame, name, canvas))

            self._bind_mousewheel_recursive(item_frame, canvas)

        self._highlight_item(0)
        scrollable_frame.event_generate('<Configure>')

        self.entry.focus_set()

    def _on_list_select(self, name):
        self.selected_champion_name.set(name)
        # 调用回调函数更新 ID
        self.on_select_callback(name)
        self._hide_list_now()
        self.entry.focus_set()

    def _navigate(self, direction):
        if not self.listbox_frame:
            self._filter_champions(self.entry.get().strip())
            if self.filtered_champions:
                self._show_list()
            return

        new_index = (self.selected_index + direction)

        if 0 <= new_index < len(self.list_items):
            self._highlight_item(new_index)

            if self.listbox_frame:
                canvas = self.list_items[new_index][2]
                item_frame = self.list_items[new_index][0]

                y_pos = item_frame.winfo_y()
                item_height = item_frame.winfo_height()

                view_top, view_bottom = canvas.yview()

                if canvas.bbox("all") is None: return
                total_scroll_height = canvas.bbox("all")[3]

                fraction_top = y_pos / total_scroll_height
                fraction_bottom = (y_pos + item_height) / total_scroll_height

                if fraction_top < view_top:
                    canvas.yview_moveto(fraction_top)
                elif fraction_bottom > view_bottom:
                    canvas.yview_moveto(fraction_bottom - (view_bottom - view_top))

    def _highlight_item(self, index):
        if self.selected_index != -1 and self.selected_index < len(self.list_items):
            old_frame = self.list_items[self.selected_index][0]
            old_frame.config(bg="#f0f0f0")
            for widget in old_frame.winfo_children():
                widget.config(bg="#f0f0f0", fg="black")

        self.selected_index = index

        if self.selected_index != -1 and self.selected_index < len(self.list_items):
            new_frame = self.list_items[self.selected_index][0]
            highlight_color = "#0078D7"
            new_frame.config(bg=highlight_color)
            for widget in new_frame.winfo_children():
                widget.config(bg=highlight_color, fg="white")

    def _select_current(self, event):
        if self.listbox_frame and self.selected_index != -1:
            name = self.list_items[self.selected_index][1]
            self.selected_champion_name.set(name)
            self._on_list_select(name)
        else:
            name = self.selected_champion_name.get()
            if name in self.champion_map:
                # 仅当回车时确认英雄，更新 ID
                self.on_select_callback(name)
                self.entry.focus_set()
                self._hide_list_now()

    def set(self, value):
        self.selected_champion_name.set(value)
        # set 时调用回调函数，确保 ID 更新
        self.on_select_callback(value)
        self._hide_list_now()

# ----------------------------------------------------
# ⬇️ UI 初始化及变量设置 (修复后版本) ⬇️
# ----------------------------------------------------

# 资源和数据加载
champion_data = ensure_assets_ready()

# LCU 连接和全局变量初始化
port, token = get_lcu_credentials()
if port and token:
    lcu = LoLHelper(port, token)
else:
    # 如果找不到 LCU，可以创建一个假的 lcu 对象或设置状态
    print("❌ 未找到 LeagueClientUx.exe 进程，LCU 连接失败。")
    class MockLCU:
        def get(self, endpoint): return {"phase": "LCU_OFFLINE"}
        def post(self, endpoint, data): return {}
    lcu = MockLCU()

root = tk.Tk()
root.title("AutoPick Created by God") # 修复：设置窗口标题
root.geometry("300x550") 
root.resizable(False, False)
root.configure(bg="#f2f2f2")
default_font = font.nametofont("TkDefaultFont")
default_font.configure(family="Microsoft YaHei", size=10)

# ⭐️ 修复：设置主窗口图标
icon_path = resource_path("app_icon.ico")
if os.path.exists(icon_path):
    try:
        root.iconbitmap(icon_path)
    except Exception as e:
        # TclError: not a bitmap file (常见于非ICO文件)
        print(f"❌ 警告：无法设置主窗口图标，请确保 'app_icon.ico' 是有效的 ICO 文件。{e}")


# ⭐️ UI 变量初始化
auto_accept_var = tk.BooleanVar(value=True)
auto_pick_var = tk.BooleanVar(value=True)
auto_ban_var = tk.BooleanVar(value=True)
status_var = tk.StringVar()
status_var.set("状态初始化中...")

# 确保全局变量被赋值
blank_avatar = create_blank_avatar()
avatar_cache = load_local_avatars(champion_keys)


# ------------------------------
# 1. 锁定/预选英雄设置 (合并)
# ------------------------------
tk.Label(root, text="🎯 锁定英雄 (Pick/Intent)：", bg="#f2f2f2", font=("Microsoft YaHei", 10)).pack(pady=(10, 2))
pick_dropdown = ImageDropdown(
    root,
    champion_map,
    champion_keys,
    champion_data_info,
    lambda name: update_selection_id(name, "pick"),
    DEFAULT_CHAMPION_NAME
)
pick_dropdown.pack(pady=5, padx=20, fill="x")

# ------------------------------
# 2. 主头像显示
# ------------------------------
avatar_label = tk.Label(root, image=blank_avatar, bg="#f2f2f2")
avatar_label.image = blank_avatar
avatar_label.pack(pady=5)
pick_dropdown.set(DEFAULT_CHAMPION_NAME)


# ------------------------------
# 3. 禁用英雄设置 (移至头像下方)
# ------------------------------
tk.Label(root, text="🚫 禁用英雄 (Ban)：", bg="#f2f2f2", font=("Microsoft YaHei", 10)).pack(pady=(10, 2))
ban_dropdown = ImageDropdown(
    root,
    champion_map,
    champion_keys,
    champion_data_info,
    lambda name: update_selection_id(name, "ban"),
    DEFAULT_BAN_NAME
)
ban_dropdown.pack(pady=5, padx=20, fill="x")

# 修复：新增禁用英雄头像 (60x60)
ban_avatar_label = tk.Label(root, image=create_blank_avatar(size=(60, 60)), bg="#f2f2f2")
ban_avatar_label.image = create_blank_avatar(size=(60, 60))
ban_avatar_label.pack(pady=5)
ban_dropdown.set(DEFAULT_BAN_NAME)


# ------------------------------
# 4. 功能设置
# ------------------------------
tk.Label(root, text="⚙ 功能设置：", bg="#f2f2f2", font=("Microsoft YaHei", 10, "bold")).pack(pady=(15, 2))

tk.Checkbutton(root, text=" 开启自动同意", variable=auto_accept_var,
    font=("Microsoft YaHei", 10), bg="#f2f2f2", activebackground="#f2f2f2").pack(pady=2)

tk.Checkbutton(root, text=" 开启自动锁定", variable=auto_pick_var,
    font=("Microsoft YaHei", 10), bg="#f2f2f2", activebackground="#f2f2f2").pack(pady=2)

tk.Checkbutton(root, text=" 开启自动禁用", variable=auto_ban_var,
    font=("Microsoft YaHei", 10), bg="#f2f2f2", activebackground="#f2f2f2").pack(pady=2)


status_label = tk.Label(root, textvariable=status_var,
    font=("Microsoft YaHei", 10, "bold"), bg="#f2f2f2", fg="#333")
status_label.pack(pady=10)

# 线程启动
threading.Thread(target=monitor_game_state, daemon=True).start()

root.mainloop()