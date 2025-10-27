import tkinter as tk
from tkinter import ttk, font
from PIL import Image, ImageTk
import os, json, re, requests, threading, time, psutil
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from tqdm import tqdm
from requests.auth import HTTPBasicAuth
import sys

# ----------------------------------------------------
# ⭐️ 全局变量初始化
# ----------------------------------------------------
DEFAULT_CHAMPION_ID = 157
DEFAULT_CHAMPION_NAME = "" 

lcu = None 
auto_pick_champion_id = None 
has_picked = False

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
avatar_label = None 
dropdown = None

# ----------------------------------------------------
# 辅助函数
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
            port = re.search(r'--app-port=(\d+)', cmdline).group(1)
            token = re.search(r'--remoting-auth-token=([\w-]+)', cmdline).group(1)
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

def create_blank_avatar(size=(120, 120), color=(255, 255, 255)):
    img = Image.new("RGB", size, color)
    return ImageTk.PhotoImage(img)

def ensure_assets_ready():
    global DEFAULT_CHAMPION_NAME 
    print("🚀 正在初始化资源...")
    versions = requests.get("https://ddragon.leagueoflegends.com/api/versions.json").json()
    version = next(v for v in versions if re.match(r"^\d+\.\d+\.\d+$", v))
    print(f"📦 最新版本号：{version}")
    json_read_path = resource_path("champion.json")
    json_write_path = os.path.join(os.getcwd(), "champion.json")
    need_download_json = True
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
        r = requests.get(url)
        with open(json_write_path, "w", encoding="utf-8") as f:
            f.write(r.text)
        print("✅ champion.json 下载完成")
    with open(resource_path("champion.json"), encoding="utf-8") as f:
        champ_data = json.load(f)["data"]
    
    temp_champion_map = {info["name"]: int(info["key"]) for info in champ_data.values()}
    default_name_found = None
    for name, champ_id in temp_champion_map.items():
        if champ_id == DEFAULT_CHAMPION_ID:
            default_name_found = name
            break
    
    DEFAULT_CHAMPION_NAME = default_name_found if default_name_found else (
        list(temp_champion_map.keys())[0] if temp_champion_map else ""
    )
    
    if is_frozen():
        avatar_dir = resource_path("avatars")
        print("🧊 已打包环境，跳过头像下载")
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
    global lcu, auto_pick_champion_id, has_picked, auto_pick_var, status_var
    if lcu is None or auto_pick_var is None or status_var is None: return 
    while True:
        try:
            state = lcu.get("lol-gameflow/v1/session")
            phase = state.get("phase", "None")
            
            if phase != "ChampSelect":
                if has_picked:
                    pass
                has_picked = False

            status_text = {
                "None": "未在房间",
                "Lobby": "正在房间 - 未排队",
                "Matchmaking": "正在房间 - 排队中",
                "ReadyCheck": "正在房间 - 接受中",
                "ChampSelect": "正在房间 - 选英雄",
                "InProgress": "游戏中",
            }.get(phase, phase)
            status_var.set(f"当前状态：{status_text}")
            
            if phase == "ChampSelect" and auto_pick_var.get() and auto_pick_champion_id and not has_picked:
                try:
                    session = lcu.get("lol-champ-select/v1/session")
                    cell_id = session["localPlayerCellId"]
                    
                    action_done = False
                    
                    for group in session["actions"]:
                        for action in group:
                            if action["type"] == "pick" and action["actorCellId"] == cell_id:
                                action_id = action["id"]
                                current_id = action["championId"]
                                completed = action["completed"]
                                
                                if current_id == 0:
                                    lcu.session.patch(
                                        f"{lcu.base_url}/lol-champ-select/v1/session/actions/{action_id}",
                                        json={"championId": auto_pick_champion_id, "completed": True},
                                        auth=lcu.auth
                                    )
                                    print(f"✅ PATCH 设置并锁定英雄 ID：{auto_pick_champion_id}")
                                    has_picked = True
                                    action_done = True
                                    break 
                                
                                elif current_id == auto_pick_champion_id and not completed:
                                    lcu.session.post(
                                        f"{lcu.base_url}/lol-champ-select/v1/session/actions/{action_id}/complete",
                                        auth=lcu.auth
                                    )
                                    print(f"✅ POST 兜底锁定英雄 ID：{auto_pick_champion_id}")
                                    has_picked = True
                                    action_done = True
                                    break 
                        
                        if action_done:
                            break 
                                
                except Exception as e:
                    print(f"❌ 自动秒选异常：{e}")
                    
        except:
            if status_var:
                 status_var.set("状态获取失败")
            
        time.sleep(0.5)

def monitor_accept_state():
    global lcu, auto_accept_var
    if lcu is None or auto_accept_var is None: return 
    while True:
        try:
            if auto_accept_var.get():
                match_state = lcu.get("lol-matchmaking/v1/ready-check")
                if match_state.get("state") == "InProgress":
                    print("🎮 检测到匹配成功，正在接受对局...")
                    lcu.post("lol-matchmaking/v1/ready-check/accept", {})
                    time.sleep(2)
        except:
            pass
        time.sleep(0.5)

def update_champion_selection(name, update_id=True):
    """
    回调函数，用于更新头像和秒选ID。
    """
    global auto_pick_champion_id, has_picked, avatar_cache, blank_avatar, avatar_label, champion_map
    
    # 1. 更新头像
    if name is None or name not in avatar_cache:
        photo = blank_avatar
    else:
        photo = avatar_cache.get(name, blank_avatar)

    if avatar_label:
        avatar_label.config(image=photo)
        avatar_label.image = photo
    
    # 2. 更新秒选ID
    if update_id:
        champ_id = champion_map.get(name) 
        if champ_id:
            auto_pick_champion_id = champ_id
            has_picked = False 

# ----------------------------------------------------
# ⭐️ 核心：自定义图片下拉选择器类 (ImageDropdown)
# ----------------------------------------------------
class ImageDropdown(tk.Frame):
    _list_photo_refs = {}

    # ⭐️ 候选框固定高度：您可以在这里修改大小 (例如 400)
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
                 self._hide_list_now()

        if keyword in self.champion_map:
             self.on_select_callback(keyword, update_id=True)
        elif not keyword:
             self.on_select_callback(self.default_name, update_id=True)
        else:
             self.on_select_callback(None, update_id=False) 

        self.selected_champion_name.set(current_text)
             
    def _hide_list_now(self):
         if self.listbox_frame:
            try:
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
            for search_term, official_name in champion_map_search.items():
                if lower_keyword in search_term.lower():
                    if official_name not in filtered:
                        filtered.append(official_name)
            self.filtered_champions = filtered
            
    def _on_mousewheel(self, event, canvas):
        # 统一处理滚轮事件
        if event.num == 4 or event.delta > 0:
            canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:
            canvas.yview_scroll(1, "units")

    # ⭐️ 关键修复函数：递归绑定滚轮事件
    def _bind_mousewheel_recursive(self, widget, canvas):
        # 绑定到当前 widget
        widget.bind("<MouseWheel>", lambda e: self._on_mousewheel(e, canvas), add=True)
        widget.bind("<Button-4>", lambda e: self._on_mousewheel(e, canvas), add=True)
        widget.bind("<Button-5>", lambda e: self._on_mousewheel(e, canvas), add=True)
        
        # 递归绑定到所有子 widget
        for child in widget.winfo_children():
            self._bind_mousewheel_recursive(child, canvas)


    def _show_list(self):
        self._hide_list_now()
        if not self.filtered_champions:
            return

        self.listbox_frame = tk.Toplevel(self.master)
        self.listbox_frame.wm_transient(self.master)
        
        # ⭐️ 固定候选框高度
        self.update_idletasks()
        x = self.master.winfo_rootx() + self.winfo_x()
        y = self.master.winfo_rooty() + self.winfo_y() + self.winfo_height()
        
        # 窗口宽度取 Entry 的宽度，高度固定为 DROPDOWN_HEIGHT
        self.listbox_frame.wm_geometry(f"{self.winfo_width()}x{self.DROPDOWN_HEIGHT}+{x}+{y}")
        
        # 延迟 grab_set
        self.master.after(50, self.listbox_frame.grab_set)
        
        # 延迟绑定 FocusOut
        self.master.after(150, lambda: self.listbox_frame.bind("<FocusOut>", lambda e: self._hide_list_now() if str(e.widget) == str(self.listbox_frame) else None))
        
        canvas = tk.Canvas(self.listbox_frame, borderwidth=0, highlightthickness=0)
        vbar = tk.Scrollbar(self.listbox_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        
        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        # ⭐️ 在 Canvas 上绑定滚轮，作为兜底
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
            
            title = self.champion_data_info.get(name, {}).get('title', '')
            text_label = tk.Label(item_frame, text=f"{name} ({title})", anchor="w", bg="#f0f0f0", font=("Microsoft YaHei", 10))
            text_label.pack(side="left", fill="x", expand=True)

            # 绑定点击事件，使用 after(50) 延迟选择
            item_frame.bind("<Button-1>", lambda e, n=name: self.master.after(50, lambda: self._on_list_select(n)))
            img_label.bind("<Button-1>", lambda e, n=name: self.master.after(50, lambda: self._on_list_select(n)))
            text_label.bind("<Button-1>", lambda e, n=name: self.master.after(50, lambda: self._on_list_select(n)))
            
            self.list_items.append((item_frame, name, canvas))

            # ⭐️ 关键修复：递归绑定滚轮事件到每个列表项，确保滚轮工作
            self._bind_mousewheel_recursive(item_frame, canvas)
        
        self._highlight_item(0)
        scrollable_frame.event_generate('<Configure>')
        
        self.entry.focus_set()

    def _on_list_select(self, name):
        self.selected_champion_name.set(name)
        self.on_select_callback(name, update_id=True)
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
            
            # 确保键盘导航时，列表内容也会滚动到选中项
            if self.listbox_frame:
                canvas = self.list_items[new_index][2]
                item_frame = self.list_items[new_index][0]
                
                # 获取选中项在 Canvas 中的 Y 坐标和高度
                y_pos = item_frame.winfo_y()
                item_height = item_frame.winfo_height()
                
                # 计算 Canvas 可视区域（分数形式）
                view_top, view_bottom = canvas.yview()
                total_scroll_height = canvas.bbox("all")[3] 
                
                # 转换像素位置为分数
                fraction_top = y_pos / total_scroll_height
                fraction_bottom = (y_pos + item_height) / total_scroll_height

                # 确保选中项在可视范围内
                if fraction_top < view_top:
                     # 向上滚动，使其顶部可见
                     canvas.yview_moveto(fraction_top)
                elif fraction_bottom > view_bottom:
                     # 向下滚动，使其底部可见
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
                self.on_select_callback(name, update_id=True)
                self.entry.focus_set()
                self._hide_list_now()

    def set(self, value):
        self.selected_champion_name.set(value)
        self._hide_list_now()

# ----------------------------------------------------
# ⬇️ UI 初始化及变量设置
# ----------------------------------------------------

# 资源和数据加载 
champion_data = ensure_assets_ready()

# 赋值给模块全局变量 (无需 global 关键字)
champion_map = {info["name"]: int(info["key"]) for info in champion_data.values()}
champion_keys = {info["name"]: key for key, info in champion_data.items()}
champion_data_info = {info["name"]: info for info in champion_data.values()}

champion_map_search = {}
for info in champion_data.values():
    official_name = info["name"] 
    hero_title = info["title"]  

    champion_map_search[official_name] = official_name
    if hero_title != official_name:
        champion_map_search[hero_title] = official_name
    
# LCU 连接和全局变量初始化
port, token = get_lcu_credentials()
lcu = LoLHelper(port, token)

# 为全局变量赋值 (无需 global 关键字)
auto_pick_champion_id = champion_map.get(DEFAULT_CHAMPION_NAME) 
has_picked = False

root = tk.Tk()
root.title("AutoPick Created by God")
icon_path = resource_path("app_icon.ico")
if os.path.exists(icon_path):
    root.iconbitmap(icon_path)
root.geometry("340x500") 

# 设置窗口大小不可调整
root.resizable(False, False) 

root.configure(bg="#f2f2f2")
default_font = font.nametofont("TkDefaultFont")
default_font.configure(family="Microsoft YaHei", size=10)

# 为全局变量赋值 (无需 global 关键字)
blank_avatar = create_blank_avatar()
avatar_cache = load_local_avatars(champion_keys)

# 选择英雄标签
tk.Label(root, text="🎯 选择英雄：", bg="#f2f2f2", font=("Microsoft YaHei", 10)).pack(pady=(20, 2))

# ⭐️ 必须使用 ImageDropdown 类！
dropdown = ImageDropdown(
    root, 
    champion_map, 
    champion_keys, 
    champion_data_info,
    update_champion_selection,
    DEFAULT_CHAMPION_NAME
)
dropdown.pack(pady=5, padx=20, fill="x")

# 头像显示
avatar_label = tk.Label(root, image=blank_avatar, bg="#f2f2f2")
avatar_label.image = blank_avatar
avatar_label.pack(pady=10)

# 确保启动时默认英雄的头像被加载和 ID 被设置
dropdown.set(DEFAULT_CHAMPION_NAME)
update_champion_selection(DEFAULT_CHAMPION_NAME, update_id=True) 


# 功能设置 (保持不变)
tk.Label(root, text="⚙ 功能设置：", bg="#f2f2f2", font=("Microsoft YaHei", 10, "bold")).pack(pady=(10, 2))

# 为全局变量赋值 (无需 global 关键字)
auto_accept_var = tk.BooleanVar(value=True)
tk.Checkbutton(
    root, text=" 开启自动同意", variable=auto_accept_var,
    font=("Microsoft YaHei", 10), bg="#f2f2f2", activebackground="#f2f2f2"
).pack(pady=2)

auto_pick_var = tk.BooleanVar(value=True)
tk.Checkbutton(
    root, text=" 开启自动秒选", variable=auto_pick_var,
    font=("Microsoft YaHei", 10), bg="#f2f2f2", activebackground="#f2f2f2"
).pack(pady=2)

status_var = tk.StringVar()
status_label = tk.Label(root, textvariable=status_var,
    font=("Microsoft YaHei", 10, "bold"),
    bg="#f2f2f2", fg="#333"
)
status_label.pack(pady=10)

# 线程启动
threading.Thread(target=monitor_game_state, daemon=True).start()
threading.Thread(target=monitor_accept_state, daemon=True).start()

root.mainloop()