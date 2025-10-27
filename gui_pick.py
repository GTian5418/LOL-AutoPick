import tkinter as tk
from tkinter import ttk, font
from PIL import Image, ImageTk
import os, json, re, requests, threading, time, psutil
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from tqdm import tqdm
from requests.auth import HTTPBasicAuth
import sys

# 设置默认秒选的英雄 ID
DEFAULT_CHAMPION_ID = 157
DEFAULT_CHAMPION_NAME = "" # 将在资源加载后动态确定

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
    global DEFAULT_CHAMPION_NAME # 允许在这里修改全局变量
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
    
    # ⭐️ 动态查找 ID 157 对应的英雄名 (疾风剑豪)
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
    global auto_pick_champion_id, has_picked
    while True:
        try:
            state = lcu.get("lol-gameflow/v1/session")
            phase = state.get("phase", "None")
            
            if phase != "ChampSelect":
                if has_picked:
                    # print("🔄 游戏阶段变更，重置秒选状态为 False。")
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
                    
                    # ⭐️ 修复：使用标志位跳出嵌套循环
                    action_done = False
                    
                    for group in session["actions"]:
                        for action in group:
                            if action["type"] == "pick" and action["actorCellId"] == cell_id:
                                action_id = action["id"]
                                current_id = action["championId"]
                                completed = action["completed"]
                                
                                # 方案 1: 英雄 ID 为 0 (未选择)，直接设置并锁定
                                if current_id == 0:
                                    lcu.session.patch(
                                        f"{lcu.base_url}/lol-champ-select/v1/session/actions/{action_id}",
                                        json={"championId": auto_pick_champion_id, "completed": True},
                                        auth=lcu.auth
                                    )
                                    print(f"✅ PATCH 设置并锁定英雄 ID：{auto_pick_champion_id}")
                                    has_picked = True
                                    action_done = True
                                    break # ⭐️ 修复：从 return 改为 break
                                
                                # 方案 2: 英雄已选但未锁定，执行锁定操作 (兜底)
                                elif current_id == auto_pick_champion_id and not completed:
                                    lcu.session.post(
                                        f"{lcu.base_url}/lol-champ-select/v1/session/actions/{action_id}/complete",
                                        auth=lcu.auth
                                    )
                                    print(f"✅ POST 兜底锁定英雄 ID：{auto_pick_champion_id}")
                                    has_picked = True
                                    action_done = True
                                    break # ⭐️ 修复：从 return 改为 break
                        
                        if action_done:
                            break # ⭐️ 修复：跳出外层循环
                                
                except Exception as e:
                    print(f"❌ 自动秒选异常：{e}")
                    
        except:
            status_var.set("状态获取失败")
            
        time.sleep(0.5)
def monitor_accept_state():
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

def update_avatar(event=None):
    global auto_pick_champion_id, has_picked
    # combo.get() 获取的是英雄的 'name' (称号，如：疾风剑豪)
    # 此函数在用户从下拉菜单**选择**时触发
    name = combo.get() 
    
    # 检查用户输入是否是有效英雄名（防止用户在框内乱输文字）
    if name in champion_map:
        photo = avatar_cache.get(name, blank_avatar)
        avatar_label.config(image=photo)
        avatar_label.image = photo
        
        champ_id = champion_map.get(name) 
        if champ_id:
            auto_pick_champion_id = champ_id
            has_picked = False 
    else:
        # 如果不是有效英雄，则不更新ID和头像
        pass

def update_combo_list(*args):
    # ⭐️ 核心更改：将恢复默认英雄的逻辑移除，只做过滤
    
    keyword = combo_var.get().strip()
    lower_keyword = keyword.lower()
    
    # 核心搜索逻辑
    if not lower_keyword:
        # 如果搜索框为空，显示所有英雄称号
        filtered = list(champion_map.keys())
        
        # ⭐️ 关键修复：当输入为空时，确保输入框内容是空的
        #    这样用户删除所有字符后，输入框不会被默认英雄名补全
        combo.set("")
        
        # 同时，重置头像为默认英雄的头像，并设置秒选ID
        # 我们在这里恢复默认英雄的显示状态
        if DEFAULT_CHAMPION_NAME in champion_map:
             default_name = DEFAULT_CHAMPION_NAME
             photo = avatar_cache.get(default_name, blank_avatar)
             avatar_label.config(image=photo)
             avatar_label.image = photo
             global auto_pick_champion_id, has_picked
             auto_pick_champion_id = champion_map.get(default_name)
             has_picked = False # 恢复默认选择时，重置秒选状态
             
    else:
        filtered = []
        # 遍历 champion_map_search
        for search_term, official_name in champion_map_search.items():
            if lower_keyword in search_term.lower():
                if official_name not in filtered:
                    filtered.append(official_name)

        # 保持输入框显示用户输入的关键词
        combo.set(keyword) 
        
        # 3. 如果输入关键词是有效的英雄名，则预加载头像 (可选)
        if keyword in champion_map:
            photo = avatar_cache.get(keyword, blank_avatar)
            avatar_label.config(image=photo)
            avatar_label.image = photo
        else:
            # 否则，显示空白头像
            avatar_label.config(image=blank_avatar)
            avatar_label.image = blank_avatar

    # 1. 更新下拉菜单的候选项 (放在最后)
    combo["values"] = filtered


# ----------------------------------------------------
# ⬇️ UI 初始化及变量设置 (修改区域) ⬇️
# ----------------------------------------------------

champion_data = ensure_assets_ready()
champion_map = {info["name"]: int(info["key"]) for info in champion_data.values()}
champion_keys = {info["name"]: key for key, info in champion_data.items()}

# ⭐️ 新增：创建搜索映射表
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
auto_pick_champion_id = None 
has_picked = False

root = tk.Tk()
root.title("AutoPick Created by God")
icon_path = resource_path("app_icon.ico")
if os.path.exists(icon_path):
    root.iconbitmap(icon_path)
root.geometry("340x500")
root.configure(bg="#f2f2f2")
default_font = font.nametofont("TkDefaultFont")
default_font.configure(family="Microsoft YaHei", size=10)
blank_avatar = create_blank_avatar()
avatar_cache = load_local_avatars(champion_keys)

# ⭐️ 移除顶部的 "搜索英雄" 标签和输入框

# 选择英雄 (保留此标签)
tk.Label(root, text="🎯 选择英雄：", bg="#f2f2f2", font=("Microsoft YaHei", 10)).pack(pady=(20, 2))

# ⭐️ 重点：使用 combo_var 作为输入变量
combo_var = tk.StringVar(value=DEFAULT_CHAMPION_NAME) 
combo = ttk.Combobox(root, textvariable=combo_var, width=28, font=("Microsoft YaHei", 10))
combo.pack(pady=5)

# ⭐️ 绑定事件：
# 1. 绑定下拉列表选中事件 (用户点击选中项)
combo.bind("<<ComboboxSelected>>", update_avatar) 
# 2. 绑定输入追踪事件 (用户在框内输入文字)
combo_var.trace_add("write", update_combo_list)

# 头像显示
avatar_label = tk.Label(root, image=blank_avatar, bg="#f2f2f2")
avatar_label.image = blank_avatar
avatar_label.pack(pady=10)

update_combo_list() # 初始化下拉列表
combo.set(DEFAULT_CHAMPION_NAME) # 确保默认名称被选中
update_avatar() # 确保默认ID被设置

# 功能设置
tk.Label(root, text="⚙ 功能设置：", bg="#f2f2f2", font=("Microsoft YaHei", 10, "bold")).pack(pady=(10, 2))

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