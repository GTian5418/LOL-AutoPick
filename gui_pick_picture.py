import tkinter as tk
from tkinter import ttk, font, messagebox
from PIL import Image, ImageTk
import os, json, re, requests, threading, time, psutil
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from requests.auth import HTTPBasicAuth
import sys
from tqdm import tqdm
import logging
import pystray
from PIL import Image, ImageDraw

logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(levelname)s - %(message)s',
                   handlers=[
                       logging.StreamHandler()
                       # 可以添加 logging.FileHandler('app.log') 写入文件
                   ])
# logging.basicConfig(level=logging.DEBUG, 
#                     format='%(asctime)s - %(levelname)s - %(message)s')
# ----------------------------------------------------
# ⭐️ 全局变量初始化
# ----------------------------------------------------
# 英雄 ID 常量
DEFAULT_CHAMPION_ID = 157 # 默认英雄 (亚索)
DEFAULT_BAN_CHAMPION_ID = 484 # 默认禁用英雄 (俄洛伊)
DEFAULT_CHAMPION_NAME = "" # 动态确定 (秒选/预选默认名)
DEFAULT_BAN_NAME = "" # 动态确定 (禁用默认名)

# 动态 LCU 状态和 ID
lcu = None
AUTO_INTENT_ID = None # 预选ID (将与AUTO_PICK_ID同步)
AUTO_PICK_ID = None
AUTO_BAN_ID = None # 禁用ID
has_picked = False # 用于判断是否已完成 PICK 动作（防止重复秒选）

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
# 新增变量
auto_play_again_var = None # 自动再来一局变量
avatar_label = None
ban_avatar_label = None 
restart_lcu_button = None 

# ----------------------------------------------------
# 辅助函数 (保持不变)
# ----------------------------------------------------
def update_selection_id(hero_name, selection_type):
    # ... (保持不变)
    global AUTO_PICK_ID, AUTO_BAN_ID, AUTO_INTENT_ID, has_picked

    if not hero_name or hero_name not in champion_map:
        champ_id = None
    else:
        champ_id = champion_map.get(hero_name)

    if selection_type == "pick":
        AUTO_PICK_ID = champ_id
        AUTO_INTENT_ID = champ_id
        update_avatar_for_selection(hero_name, selection_type) 
    elif selection_type == "ban":
        AUTO_BAN_ID = champ_id
        update_avatar_for_selection(hero_name, selection_type) 

    has_picked = False

def update_avatar_for_selection(name, selection_type):
    # ... (保持不变)
    global avatar_cache, blank_avatar, avatar_label, ban_avatar_label 

    if name is None or name not in avatar_cache:
        photo = create_blank_avatar(size=(60, 60)) if selection_type == "ban" else blank_avatar
    else:
        if selection_type == "ban":
            img_key = champion_keys.get(name)
            try:
                img_path = resource_path(os.path.join("avatars", f"{img_key}.png"))
                pil_img = Image.open(img_path).resize((60, 60))
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
        
def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def is_frozen():
    return hasattr(sys, '_MEIPASS')

def get_lcu_credentials():
    logging.info("尝试获取 LCU 凭证...")
    for proc in psutil.process_iter(['name', 'cmdline']):
        if 'LeagueClientUx.exe' in proc.info['name'] or 'LeagueClient.exe' in proc.info['name']:
            try:
                cmdline = ' '.join(proc.info['cmdline'])
                port_match = re.search(r'--app-port=(\d+)', cmdline)
                token_match = re.search(r'--remoting-auth-token=([\w-]+)', cmdline)
                
                if port_match and token_match:
                    port = port_match.group(1)
                    token = token_match.group(1)
                    logging.info(f"成功找到 LCU 凭证。Port: {port}")
                    return port, token
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    
    logging.warning("未找到运行中的 LeagueClient 进程或未能获取到凭证。")
    return None, None

class LoLHelper:
    """处理与 LCU API 通信的类 (已添加重启和再来一局功能)"""
    def __init__(self, port, token):
        self.port = port
        self.token = token
        self.base_url = f"https://127.0.0.1:{port}"
        self.auth = HTTPBasicAuth("riot", token)
        self.session = requests.Session()
        self.session.verify = False

    def _request(self, method, endpoint, data=None):
        url = f"{self.base_url}{endpoint}"
        try:
            if method == "GET":
                response = self.session.get(url, auth=self.auth)
            elif method == "POST":
                response = self.session.post(url, json=data, auth=self.auth)
            elif method == "PATCH":
                response = self.session.patch(url, json=data, auth=self.auth)
            else:
                raise ValueError(f"不支持的请求方法: {method}")
            
            response.raise_for_status() # 抛出 HTTPError 异常
            
            # 尝试返回 JSON，如果响应体为空则返回 None
            return response.json() if response.content else None

        except requests.exceptions.RequestException as e:
            # 区分连接错误和 API 错误
            if isinstance(e, requests.exceptions.ConnectionError):
                logging.error(f"LCU 连接失败: {url} -> {e}")
            elif hasattr(e, 'response'):
                logging.error(f"LCU API 错误: {e.response.status_code} on {url} -> {e.response.text}")
            else:
                logging.error(f"LCU 请求发生未知错误: {e}")
            return None
        except Exception as e:
            logging.error(f"请求过程中发生异常: {e}")
            return None


    def get(self, endpoint):
        return self._request("GET", f"/{endpoint}")

    def post(self, endpoint, data=None):
        return self._request("POST", f"/{endpoint}", data)
        
    def patch(self, endpoint, data):
        return self._request("PATCH", f"/{endpoint}", data)

    def restart_client_ux(self) -> bool:
        """向 LCU 发送 POST 请求以热重载客户端 UI。"""
        path = "/riotclient/kill-and-restart-ux"
        logging.info("发送 LCU UI 重启请求...")
        result = self.post(path)
        return result is not None or True # 重启请求通常成功返回 None 或 204

    # ----------------------------------------------------
    # 新增：跳过结算页面，回到大厅
    # ----------------------------------------------------
    def lobby_play_again(self) -> bool:
        """发送 POST 请求跳过结算页面，回到大厅。"""
        path = "/lol-lobby/v1/lobby/play-again"
        logging.info("发送 'Play Again' 请求...")
        # LCU 接口通常不要求 body
        result = self.post(path) 
        # 成功可能返回 None，失败会返回 None (通过 _request 处理)
        return result is not None or True # 成功返回 204 No Content

# ----------------------------------------------------
# LCU UI 重启的线程处理函数 (保持不变)
# ----------------------------------------------------

def start_restart_thread():
    global status_var, restart_lcu_button, root
    
    if restart_lcu_button:
        status_var.set("🔄 正在发送 LCU 重启请求...")
        restart_lcu_button.config(state=tk.DISABLED, text="重启中...")
        root.update_idletasks()
    
    thread = threading.Thread(target=handle_restart_click)
    thread.start()

def handle_restart_click():
    global lcu, status_var, restart_lcu_button, root
    
    logging.info("按钮被点击，开始执行 LCU UI 重启操作...")
    success = False
    
    try:
        port, token = get_lcu_credentials()
        
        if port and token:
            lcu_helper_temp = LoLHelper(port=port, token=token)
            success = lcu_helper_temp.restart_client_ux()
        else:
            logging.error("执行重启时，未能获取到最新的 LCU 凭证。")
            
        if success:
            root.after(0, lambda: update_ui_on_restart(
                "🎉 LCU UI 重启请求发送成功！", "green", tk.NORMAL, "热重载 LCU"))
        else:
            root.after(0, lambda: update_ui_on_restart(
                "❌ LCU UI 重启请求失败，请查看日志。", "red", tk.NORMAL, "热重载 LCU"))
            
    except Exception as e:
        logging.error(f"执行重启操作时发生异常: {e}")
        root.after(0, lambda: update_ui_on_restart(
            f"发生错误: {e}", "red", tk.NORMAL, "热重载 LCU"))

def update_ui_on_restart(text, color, button_state, button_text):
    global status_var, status_label, restart_lcu_button
    
    if status_label:
        status_label.config(fg=color)
    
    status_var.set(text)
    
    if restart_lcu_button:
        restart_lcu_button.config(state=button_state, text=button_text)


def create_blank_avatar(size=(120, 120), color="#e8e8e8"): 
    # ... (保持不变)
    img = Image.new("RGB", size, color)
    return ImageTk.PhotoImage(img)

def ensure_assets_ready():
    # ... (保持不变)
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
                return {} 
    
    try:
        with open(resource_path("champion.json"), encoding="utf-8") as f:
            champ_data = json.load(f)["data"]
    except Exception as e:
        print(f"❌ 读取英雄数据失败：{e}")
        return {}

    for key, info in champ_data.items():
        name = info["name"]
        champ_id = int(info["key"])
        champion_map[name] = champ_id
        champion_keys[name] = key
        champion_data_info[name] = info
        champion_map_search[name] = name 
        champion_map_search[info["title"]] = name 
        champion_map_search[info["id"]] = name 

    default_names = {}
    for name, champ_id in champion_map.items():
        if champ_id == DEFAULT_CHAMPION_ID:
            default_names[DEFAULT_CHAMPION_ID] = name
        if champ_id == DEFAULT_BAN_CHAMPION_ID:
            default_names[DEFAULT_BAN_CHAMPION_ID] = name

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
    # ... (保持不变)
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
    global lcu, AUTO_PICK_ID, AUTO_INTENT_ID, AUTO_BAN_ID, has_picked, has_banned
    global auto_pick_var, auto_ban_var, status_var, auto_accept_var, auto_play_again_var
    
    BAN_TIME_THRESHOLD = 3.0 
    
    # LCU 连接检查 (保持不变)
    if lcu is None or isinstance(lcu, MockLCU):
        port, token = get_lcu_credentials()
        if port and token:
            lcu = LoLHelper(port, token)
        elif status_var:
            status_var.set("状态获取失败或 LCU 未运行")
        if lcu is None or isinstance(lcu, MockLCU):
            threading.Timer(5.0, monitor_game_state).start() 
            return

    if auto_pick_var is None or auto_ban_var is None or status_var is None: 
        time.sleep(0.1)
        return
    
    while True:
        try:
            state = lcu.get("lol-gameflow/v1/session")
            phase = state.get("phase", "None")

            # 非选人阶段，重置状态
            if phase != "ChampSelect":
                has_picked = False
                has_banned = False 

            status_text_base = {
                "None": "未在房间", "Lobby": "正在房间 - 未排队",
                "Matchmaking": "正在房间 - 排队中", "ReadyCheck": "正在房间 - 接受中",
                "ChampSelect": "正在房间 - 选英雄", "InProgress": "游戏中",
                "WaitingForStats": "等待结算页面", "EndOfGame": "结算页面",
            }.get(phase, phase)

            status_var.set(f"当前状态：{status_text_base}")

            # 1. 自动接受匹配 Check 
            if auto_accept_var.get():
                if phase == "ReadyCheck":
                    time.sleep(0.05) 
                    match_state = lcu.get("lol-matchmaking/v1/ready-check")
                    if match_state and match_state.get("state") == "InProgress":
                        logging.info("🎮 检测到匹配成功，正在接受对局...")
                        lcu.post("lol-matchmaking/v1/ready-check/accept", {})
                        time.sleep(0.1)

            # 3. 自动再来一局 (保持不变)
            if auto_play_again_var.get() and phase in ("WaitingForStats", "EndOfGame"):
                 logging.info(f"⏭️ 检测到阶段: {phase}，尝试发送 'Play Again' 请求。")
                 lcu.lobby_play_again()
                 time.sleep(0.1) 

            # 4. 核心：处理 ChampSelect 阶段的 Ban, Intent, Pick
            if phase == "ChampSelect":
                try:
                    session = lcu.get("lol-champ-select/v1/session")
                    cell_id = session["localPlayerCellId"]
                    
                    timer_data = session.get("timer", {})
                    current_champ_select_phase = timer_data.get("phase", "UNKNOWN")
                    time_remaining = timer_data.get("timeLeftInPhase", 0) / 1000.0 
                    
                    # ⭐️ 调试点 1：打印 LCU 原始计时器数据
                    logging.debug(f"LCU Timer Raw Data: {timer_data}")
                    
                    sub_phase_text = {
                        "PLANNING": "预选/禁选", "BAN_PICK": "禁用/选择",
                        "PRE_BAN": "禁选 ", "BAN": "禁用中 ",
                        "PRE_PICK": "预选 ", "PICK": "选择中 ",
                        "FINAL_BANS": "最终禁用", "FINALIZATION": "选人结束/等待中",
                        "CLOSING": "选人结束"
                    }.get(current_champ_select_phase, "选英雄中...")

                    status_var.set(f"当前状态：{status_text_base} ({sub_phase_text}) ")
                    
                    should_exit_outer_loop = False
                    
                    # 1. 预选英雄 (Intent) 逻辑 (保持不变)
                    if auto_pick_var.get() and AUTO_PICK_ID and current_champ_select_phase in ("PLANNING", "PRE_BAN", "PRE_PICK"):
                        for group in session["actions"]:
                            for action in group:
                                action_type = action["type"]
                                actor_cell_id = action["actorCellId"]
                                completed = action["completed"]
                                is_active = action.get("isInProgress", False) 

                                if action_type == "pick" and actor_cell_id == cell_id and not completed and not is_active:
                                    action_id = action["id"]
                                    lcu.patch(
                                        f"lol-champ-select/v1/session/actions/{action_id}",
                                        data={"championId": AUTO_PICK_ID, "completed": False}
                                    )
                                    break 

                    # 2. 遍历动作组，执行 Ban 和 Lock 
                    for group_index, group in enumerate(session["actions"]):
                        if should_exit_outer_loop:
                            break 

                        for action in group:
                            action_id = action["id"]
                            action_type = action["type"]
                            actor_cell_id = action["actorCellId"]
                            completed = action["completed"]
                            is_active = action.get("isInProgress", False) 

                            # 只处理当前玩家、未完成且正在进行中的动作
                            if actor_cell_id != cell_id or completed or not is_active:
                                continue

                            # ⭐️ 调试点 2：打印激活动作的完整数据
                            logging.debug(f"Active Action Found: ID={action_id}, Type={action_type}, Action Data={action}")


                            # 优先级 A: Pick/Lock (秒选英雄) 
                            if action_type == "pick" and auto_pick_var.get() and AUTO_PICK_ID and not has_picked:
                                if current_champ_select_phase in ("PICK", "BAN_PICK"): 
                                    logging.info(f"✅ LOCK PATCH 自动秒选英雄 ID: {AUTO_PICK_ID}")
                                    lcu.patch(
                                        f"lol-champ-select/v1/session/actions/{action_id}",
                                        data={"championId": AUTO_PICK_ID, "completed": True}
                                    )
                                    has_picked = True
                                    should_exit_outer_loop = True
                                    break 

                            # 优先级 B: Ban (禁用英雄)
                            elif action_type == "ban" and auto_ban_var.get() and AUTO_BAN_ID and not has_banned:
                                
                                # 1. 严格限制阶段：只在实际的 BAN 或 BAN_PICK 阶段执行最终禁用
                                if current_champ_select_phase in ("BAN", "BAN_PICK"):
                                    
                                    # 2. 重新启用计时器判断（晚禁用/秒禁都可以）
                                    # BAN_TIME_THRESHOLD = 3.0s (或者您想要的秒禁时间)
                                    if time_remaining <= BAN_TIME_THRESHOLD:
                                        
                                        try:
                                            logging.info(f"✅ BAN PATCH 自动禁用英雄 ID: {AUTO_BAN_ID} (倒计时: {time_remaining:.1f}s)")
                                            lcu.patch(
                                                f"lol-champ-select/v1/session/actions/{action_id}",
                                                data={"championId": AUTO_BAN_ID, "completed": True}
                                            )
                                            has_banned = True 
                                        except Exception as patch_e:
                                            # 失败也标记已尝试，防止下一轮重复发送
                                            logging.error(f"❌ BAN PATCH 失败: {patch_e}")
                                            has_banned = True 
                                            
                                        should_exit_outer_loop = True
                                        break # 退出 inner loop
                                
                                # 3. 如果当前是 PLANNING 阶段，我们只进行预选意图（如果需要）
                                elif current_champ_select_phase in ("PLANNING", "PRE_BAN"):
                                    # LCU的Ban动作在PLANNING阶段可能是预禁选动作，
                                    # 但通常预禁选使用的是Pick动作类型，这里可以忽略或根据需求处理预禁选意图
                                    # 假设您只需要在正式阶段Ban英雄，这里不做任何操作，让它跳过。
                                    pass 

                        if should_exit_outer_loop:
                            break 

                except Exception as e:
                    logging.error(f"❌ 自动操作异常：{e}")

        except Exception as e:
            # LCU 连接失败或 session 错误
            logging.error(f"❌ 主循环 LCU/状态获取异常: {e}")
            if status_var:
                status_var.set("状态获取失败或 LCU 未运行")
            
            port, token = get_lcu_credentials()
            if port and token:
                lcu = LoLHelper(port, token)
            else:
                lcu = MockLCU() 

        time.sleep(0.1)
# ... (ImageDropdown 类保持不变)

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

        self.entry = tk.Entry(self, textvariable=self.selected_champion_name, width=28, font=("Microsoft YaHei", 10), relief="flat")
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<KeyRelease>", self._on_key_release)
        self.entry.bind("<Return>", self._select_current)
        self.entry.bind("<Down>", lambda e: self._navigate(1))
        self.entry.bind("<Up>", lambda e: self._navigate(-1))

        self.arrow_button = tk.Button(self, text="▼", command=self._toggle_list, width=2, bd=0, relief="flat", bg="#f2f2f2")
        self.arrow_button.pack(side="right", fill="y")

        self.listbox_frame = None
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

        if keyword in self.champion_map:
            self.on_select_callback(keyword)
        elif not keyword:
            self.on_select_callback(self.default_name)
        else:
            self.on_select_callback(None)

        self.selected_champion_name.set(current_text)

    def _hide_list_now(self):
        if self.listbox_frame:
            try:
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
            for search_term, official_name in champion_map_search.items():
                if lower_keyword in search_term.lower():
                    if official_name not in filtered:
                        filtered.append(official_name)

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

        icon_path = resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.listbox_frame.iconbitmap(icon_path)
            except Exception as e:
                print(f"❌ 警告：无法设置 Toplevel 图标，请确保 'app_icon.ico' 是有效的 ICO 文件。{e}")

        self.update_idletasks()
        x = self.master.winfo_rootx() + self.winfo_x()
        y = self.master.winfo_rooty() + self.winfo_y() + self.winfo_height()

        self.listbox_frame.wm_geometry(f"{self.winfo_width()}x{self.DROPDOWN_HEIGHT}+{x}+{y}")

        self.master.after(50, self.listbox_frame.grab_set)
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
                self.on_select_callback(name)
                self.entry.focus_set()
                self._hide_list_now()

    def set(self, value):
        self.selected_champion_name.set(value)
        self.on_select_callback(value)
        self._hide_list_now()

# ----------------------------------------------------
# ⬇️ UI 初始化及变量设置 (新增“自动再来一局”复选框) ⬇️
# ----------------------------------------------------

# 资源和数据加载
champion_data = ensure_assets_ready()

# LCU 连接和全局变量初始化
port, token = get_lcu_credentials()
class MockLCU:
    def get(self, endpoint): return {"phase": "LCU_OFFLINE"}
    def post(self, endpoint, data=None): return None
    def patch(self, endpoint, data): return None
    def lobby_play_again(self): return False
    def restart_client_ux(self): return False

if port and token:
    lcu = LoLHelper(port, token)
else:
    logging.warning("❌ 未找到 LeagueClientUx.exe 进程，LCU 连接失败。使用 MockLCU。")
    lcu = MockLCU()

root = tk.Tk()
root.title("AutoPick Created by God")
root.geometry("360x600") 
root.resizable(False, False)
root.configure(bg="#f2f2f2")
default_font = font.nametofont("TkDefaultFont")
default_font.configure(family="Microsoft YaHei", size=10)

icon_path = resource_path("app_icon.ico")
if os.path.exists(icon_path):
    try:
        root.iconbitmap(icon_path)
    except Exception as e:
        logging.error(f"❌ 警告：无法设置主窗口图标。{e}")


# ⭐️ UI 变量初始化
auto_accept_var = tk.BooleanVar(value=True)
auto_pick_var = tk.BooleanVar(value=True)
auto_ban_var = tk.BooleanVar(value=True)
auto_play_again_var = tk.BooleanVar(value=True) # 新增：默认不开启自动再来一局
status_var = tk.StringVar()
status_var.set("状态初始化中...")

blank_avatar = create_blank_avatar()
avatar_cache = load_local_avatars(champion_keys)


# ------------------------------
# 1. 秒选/预选英雄设置
# ------------------------------
tk.Label(root, text="🎯 秒选英雄：", bg="#f2f2f2", font=("Microsoft YaHei", 10)).pack(pady=(10, 2))
pick_dropdown = ImageDropdown(
    root, champion_map, champion_keys, champion_data_info,
    lambda name: update_selection_id(name, "pick"), DEFAULT_CHAMPION_NAME
)
pick_dropdown.pack(pady=5, padx=20, fill="x")

# 2. 主头像显示
avatar_label = tk.Label(root, image=blank_avatar, bg="#f2f2f2")
avatar_label.image = blank_avatar
avatar_label.pack(pady=5)
pick_dropdown.set(DEFAULT_CHAMPION_NAME)


# 3. 禁用英雄设置
tk.Label(root, text="🚫 禁用英雄：", bg="#f2f2f2", font=("Microsoft YaHei", 10)).pack(pady=(10, 2))
ban_dropdown = ImageDropdown(
    root, champion_map, champion_keys, champion_data_info,
    lambda name: update_selection_id(name, "ban"), DEFAULT_BAN_NAME
)
ban_dropdown.pack(pady=5, padx=20, fill="x")

ban_avatar_label = tk.Label(root, image=create_blank_avatar(size=(60, 60)), bg="#f2f2f2")
ban_avatar_label.image = create_blank_avatar(size=(60, 60))
ban_avatar_label.pack(pady=5)
ban_dropdown.set(DEFAULT_BAN_NAME)


# ------------------------------
# 4. 功能设置 (新增 '开启自动再来一局')
# ------------------------------
checkbutton_frame = tk.Frame(root, bg="#f2f2f2")
checkbutton_frame.pack(pady=5, padx=0) # padx=0 确保 Frame 本身居中

# Frame 内部的 Checkbutton 使用 pack(anchor='w') 保持左对齐
tk.Checkbutton(checkbutton_frame, text="开启自动同意", variable=auto_accept_var,
    font=("Microsoft YaHei", 10), bg="#f2f2f2", activebackground="#f2f2f2").pack(pady=2, padx=5, anchor='w')

tk.Checkbutton(checkbutton_frame, text="开启自动秒选", variable=auto_pick_var,
    font=("Microsoft YaHei", 10), bg="#f2f2f2", activebackground="#f2f2f2").pack(pady=2, padx=5, anchor='w')

tk.Checkbutton(checkbutton_frame, text="开启自动禁用", variable=auto_ban_var,
    font=("Microsoft YaHei", 10), bg="#f2f2f2", activebackground="#f2f2f2").pack(pady=2, padx=5, anchor='w')

# 自动再来一局复选框 (名称改为“开启跳过结算”更贴合功能)
tk.Checkbutton(checkbutton_frame, text="开启跳过结算", variable=auto_play_again_var,
    font=("Microsoft YaHei", 10), bg="#f2f2f2", activebackground="#f2f2f2").pack(pady=2, padx=5, anchor='w')


# 5. 热重载 LCU 按钮
restart_lcu_button = tk.Button(
    root, 
    text="热重载 LCU", 
    command=start_restart_thread,  
    fg='white', 
    bg='#0078D7', 
    padx=10, 
    pady=5,
    relief=tk.FLAT, 
    font=('Microsoft YaHei', 10, 'bold')
)
# ⭐️ 关键改动：按钮使用 fill='x' 和 padx 确保居中和与窗口边缘的距离
restart_lcu_button.pack(pady=(15, 10), padx=50, fill='x') 

# 6. 当前状态标签
status_label = tk.Label(root, textvariable=status_var,
    font=("Microsoft YaHei", 10, "bold"), bg="#f2f2f2", fg="#333")
status_label.pack(pady=(0, 10))







tray_icon = None

def quit_window(icon, item):
    """托盘菜单 - 退出程序"""
    global tray_icon
    icon.stop()
    # 彻底关闭主窗口和应用程序
    # 使用 root.quit() 和 root.destroy() 确保 Tkinter 进程干净退出
    root.quit() 
    root.destroy()
    # sys.exit() 是为了确保如果 Tkinter 主循环已经退出，整个 Python 进程也能结束
    sys.exit() 

def show_window(icon, item):
    """托盘菜单 - 恢复主窗口"""
    global tray_icon
    
    # 1. 停止托盘图标
    icon.stop()
    
    # 2. 恢复主窗口
    root.deiconify() 
    
    # ⭐️ 关键修复：确保窗口被置于顶层并获得焦点
    # root.lift()：将窗口移动到堆叠顺序的顶部 (Z-order)
    root.lift() 
    
    # root.focus_force()：强制窗口获取输入焦点
    root.focus_force() 
    
    # root.attributes('-topmost', True)：这是一个额外的保险，短暂置顶，
    # 确保它出现在最前面，然后立即取消，以防止干扰正常窗口行为。
    root.attributes('-topmost', True)
    root.after_idle(root.attributes, '-topmost', False) 
    
    # 3. 确保它不再处于最小化/被隐藏的状态（这通常是 deiconify() 做的，但重复执行无害）
    # root.state('normal')

def withdraw_window():
    """窗口关闭按钮 (X) - 隐藏到托盘"""
    global tray_icon
    
    # 1. 隐藏主窗口
    root.withdraw()
    
    # 2. 加载图标
    image = None
    try:
        # ⭐️ 使用全局定义的 icon_path 变量加载图像
        # pystray 运行良好，通常不需要 .resize，但如果 ICO 包含多尺寸，PIL 会自动选择。
        image = Image.open(icon_path)
    except Exception as e:
        # 如果加载图标文件失败，创建一个默认的占位符图标
        logging.error(f"❌ 无法加载托盘图标 {icon_path}，使用默认占位符。错误: {e}")
        image = Image.new('RGB', (64, 64), 'white')
        d = ImageDraw.Draw(image)
        d.ellipse((10, 10, 54, 54), fill='#0078D7') # 绘制一个蓝色圆圈
    
    # 3. 定义托盘菜单
    menu = (
        pystray.MenuItem('显示窗口', show_window, default=True),
        pystray.MenuItem('退出程序', quit_window)
    )
    
    # 4. 创建并运行托盘图标
    tray_icon = pystray.Icon(
        name="AutoPick", 
        icon=image, # 传入 PIL Image 对象
        title="AutoPick Created by God", 
        menu=menu
    )
    
    # 启动托盘图标（它会自动在一个单独的线程中运行）
    tray_icon.run()


# 6. 当前状态标签
status_label = tk.Label(root, textvariable=status_var,
    font=("Microsoft YaHei", 10, "bold"), bg="#f2f2f2", fg="#333")
status_label.pack(pady=(0, 10))

# --- 绑定窗口关闭事件 ---
# 绑定窗口关闭事件 (右上角 X) 到自定义的 withdraw_window 函数
root.protocol("WM_DELETE_WINDOW", withdraw_window)

# 线程启动
threading.Thread(target=monitor_game_state, daemon=True).start()

root.mainloop()