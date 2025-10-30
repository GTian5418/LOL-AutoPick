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
                   ])
DEFAULT_CHAMPION_ID = 157
DEFAULT_BAN_CHAMPION_ID = 800
DEFAULT_CHAMPION_NAME = "" 
DEFAULT_BAN_NAME = "" 
lcu = None
AUTO_INTENT_ID = None
AUTO_PICK_ID = None
AUTO_BAN_ID = None
has_picked = False
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
auto_play_again_var = None
avatar_label = None
ban_avatar_label = None 
restart_lcu_button = None 
def update_selection_id(hero_name, selection_type):
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
        response = None
        try:
            if method == "GET":
                response = self.session.get(url, auth=self.auth)
            elif method == "POST":
                response = self.session.post(url, json=data, auth=self.auth)
            elif method == "PATCH":
                response = self.session.patch(url, json=data, auth=self.auth)
            else:
                raise ValueError(f"不支持的请求方法: {method}")
            if response.status_code == 404:
                if endpoint.startswith("/lol-gameflow") and response.json().get("errorCode") == "RPC_ERROR":
                    return {"phase": "None"} 
            response.raise_for_status()
            return response.json() if response.content else None
        except requests.exceptions.RequestException as e:
            if isinstance(e, requests.exceptions.ConnectionError):
                logging.error(f"LCU 连接失败: {url} -> {e}")
            elif response is not None and hasattr(e, 'response'):
                logging.error(f"LCU API 错误: {response.status_code} on {url} -> {response.text}")
            else:
                logging.error(f"LCU 请求发生未知或网络错误: {e}")
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
        return result is not None or True
    def lobby_play_again(self):
        logging.info("➡️ 尝试跳过结算等待/动画...")
        try:
            self.post("lol-end-of-game/v1/state", {}) 
        except Exception as e:
            logging.warning(f"跳过结算 API 调用失败: {e}") 
        try:
            logging.info("🔄 尝试调用 /lol-lobby/v2/play-again (再来一局)...")
            response = self.post("lol-lobby/v2/play-again", {}) 
            logging.info("✅ '再来一局' API 调用成功。")
            return response
        except Exception as e:
            logging.error(f"❌ '再来一局' API 调用失败 (可能是客户端不在正确状态): {e}")
            return None
    def lobby_play_again(self) -> bool:
        """发送 POST 请求跳过结算页面，回到大厅。"""
        path = "lol-lobby/v2/play-again"
        logging.info("发送 'Play Again' 请求...")
        result = self.post(path) 
        return result is not None or True
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
        version = "15.21.1" 
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
def update_status_ui(text, fg_color="#333"):
    """安全地在 Tkinter 主线程中更新状态标签"""
    global root, status_var, status_label
    if root and status_var:
        root.after(0, lambda: status_var.set(text))
        if status_label:
            root.after(0, lambda: status_label.config(fg=fg_color))
def monitor_game_state():
    global lcu, AUTO_PICK_ID, AUTO_INTENT_ID, AUTO_BAN_ID, has_picked, has_banned
    global auto_pick_var, auto_ban_var, status_var, auto_accept_var, auto_play_again_var,running
    BAN_TIME_THRESHOLD = 3.0 
    RETRY_INTERVAL = 5.0
    if auto_pick_var is None or auto_ban_var is None or status_var is None: 
        threading.Timer(0.5, monitor_game_state).start()
        return
    while running:
        if lcu is None or not isinstance(lcu, LoLHelper):
            port, token = get_lcu_credentials()
            if port and token:
                logging.info("🌟 成功找到 LCU 凭证，初始化 LoLHelper。")
                lcu = LoLHelper(port, token)
            else:
                if status_var:
                    update_status_ui("🔴 LCU 离线/未运行，5秒后重试...", "red")
                logging.warning("LCU 未连接，等待中...")
                time.sleep(RETRY_INTERVAL)
                continue
        try:
            if not running: break
            state = lcu.get("lol-gameflow/v1/session")
            if state is None:
                raise requests.exceptions.ConnectionError("LCU API 返回 None，可能连接中断。") 
            phase = state.get("phase", "None")
            if phase != "ChampSelect":
                has_picked = False
                has_banned = False 
            status_text_base = {
                "None": "未在房间", "Lobby": "正在房间 - 未排队",
                "Matchmaking": "正在房间 - 排队中", "ReadyCheck": "正在房间 - 接受中",
                "ChampSelect": "正在房间 - 选英雄", "InProgress": "游戏中",
                "WaitingForStats": "等待结算页面", "EndOfGame": "结算页面",
            }.get(phase, phase)
            current_status_text = f"当前状态：{status_text_base}"
            update_status_ui(current_status_text, "black")
            if auto_accept_var.get() and phase == "ReadyCheck":
                match_state = lcu.get("lol-matchmaking/v1/ready-check")
                if match_state and match_state.get("state") == "InProgress":
                     logging.info("🎮 检测到匹配成功，正在接受对局...")
                     lcu.post("lol-matchmaking/v1/ready-check/accept", {})
            if auto_play_again_var.get() and phase in ("WaitingForStats", "EndOfGame", "PreEndOfGame"):
                 logging.info(f"⏭️ 检测到阶段: {phase}，尝试发送 'Play Again' 请求。")
                 lcu.lobby_play_again()
            if phase == "ChampSelect":
                try:
                    session = lcu.get("lol-champ-select/v1/session")
                    if session is None: raise Exception("无法获取选人会话")
                    cell_id = session["localPlayerCellId"]
                    timer_data = session.get("timer", {})
                    current_champ_select_phase = timer_data.get("phase", "UNKNOWN")
                    time_remaining = timer_data.get("timeLeftInPhase", 0) / 1000.0 
                    sub_phase_text = {
                        "PLANNING": "预选/禁选", "BAN_PICK": "禁用/选择",
                        "PRE_BAN": "禁选 ", "BAN": "禁用中 ",
                        "PRE_PICK": "预选 ", "PICK": "选择中 ",
                        "FINAL_BANS": "最终禁用", "FINALIZATION": "选人结束/等待中",
                        "PreEndOfGame": "结算前等待/跳过结算",
                        "CLOSING": "选人结束"
                    }.get(current_champ_select_phase, "选英雄中...")
                    update_status_ui(f"当前状态：{status_text_base} ({sub_phase_text}) ", "darkgreen")
                    should_exit_outer_loop = False
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
                    for group_index, group in enumerate(session["actions"]):
                        if should_exit_outer_loop: break 
                        for action in group:
                            action_id = action["id"]
                            action_type = action["type"]
                            actor_cell_id = action["actorCellId"]
                            completed = action["completed"]
                            is_active = action.get("isInProgress", False) 
                            if actor_cell_id != cell_id or completed or not is_active: continue
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
                            elif action_type == "ban" and auto_ban_var.get() and AUTO_BAN_ID and not has_banned:
                                if current_champ_select_phase in ("BAN", "BAN_PICK"):
                                    if time_remaining <= BAN_TIME_THRESHOLD:
                                        try:
                                            logging.info(f"✅ BAN PATCH 自动禁用英雄 ID: {AUTO_BAN_ID} (倒计时: {time_remaining:.1f}s)")
                                            lcu.patch(
                                                f"lol-champ-select/v1/session/actions/{action_id}",
                                                data={"championId": AUTO_BAN_ID, "completed": True}
                                            )
                                            has_banned = True 
                                        except Exception as patch_e:
                                            logging.error(f"❌ BAN PATCH 失败: {patch_e}")
                                            has_banned = True
                                        should_exit_outer_loop = True
                                        break 
                except Exception as e:
                    logging.error(f"❌ 自动操作异常（选人阶段）：{e}")
                    pass
        except requests.exceptions.ConnectionError as e:
            if status_var and running:
                update_status_ui("🔴 LCU 离线/连接中断，正在尝试重新连接...", "red")
            logging.error(f"❌ 主循环 LCU 连接完全中断: {e}")
            lcu = None 
            has_picked = False
            has_banned = False
            time.sleep(RETRY_INTERVAL)
            continue
        except Exception as e:
            logging.error(f"❌ 主循环 LCU/状态获取发生非连接异常: {e}")
            if not running: break
            time.sleep(1.0)
            continue 
        time.sleep(0.1)
    logging.info("🛑 LCU 监控线程已安全退出。")
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
champion_data = ensure_assets_ready()
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
auto_accept_var = tk.BooleanVar(value=True)
auto_pick_var = tk.BooleanVar(value=True)
auto_ban_var = tk.BooleanVar(value=True)
auto_play_again_var = tk.BooleanVar(value=True)
status_var = tk.StringVar()
status_var.set("状态初始化中...")
running = True
exit_flag = False
blank_avatar = create_blank_avatar()
avatar_cache = load_local_avatars(champion_keys)
tk.Label(root, text="🎯 秒选英雄：", bg="#f2f2f2", font=("Microsoft YaHei", 10)).pack(pady=(10, 2))
pick_dropdown = ImageDropdown(
    root, champion_map, champion_keys, champion_data_info,
    lambda name: update_selection_id(name, "pick"), DEFAULT_CHAMPION_NAME
)
pick_dropdown.pack(pady=5, padx=20, fill="x")
avatar_label = tk.Label(root, image=blank_avatar, bg="#f2f2f2")
avatar_label.image = blank_avatar
avatar_label.pack(pady=5)
pick_dropdown.set(DEFAULT_CHAMPION_NAME)
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
checkbutton_frame = tk.Frame(root, bg="#f2f2f2")
checkbutton_frame.pack(pady=5, padx=0)
tk.Checkbutton(checkbutton_frame, text="开启自动同意", variable=auto_accept_var,
    font=("Microsoft YaHei", 10), bg="#f2f2f2", activebackground="#f2f2f2").pack(pady=2, padx=5, anchor='w')
tk.Checkbutton(checkbutton_frame, text="开启自动秒选", variable=auto_pick_var,
    font=("Microsoft YaHei", 10), bg="#f2f2f2", activebackground="#f2f2f2").pack(pady=2, padx=5, anchor='w')
tk.Checkbutton(checkbutton_frame, text="开启自动禁用", variable=auto_ban_var,
    font=("Microsoft YaHei", 10), bg="#f2f2f2", activebackground="#f2f2f2").pack(pady=2, padx=5, anchor='w')
tk.Checkbutton(checkbutton_frame, text="开启跳过结算", variable=auto_play_again_var,
    font=("Microsoft YaHei", 10), bg="#f2f2f2", activebackground="#f2f2f2").pack(pady=2, padx=5, anchor='w')
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
restart_lcu_button.pack(pady=(15, 10), padx=50, fill='x') 
status_label = tk.Label(root, textvariable=status_var,
    font=("Microsoft YaHei", 10, "bold"), bg="#f2f2f2", fg="#333")
status_label.pack(pady=(0, 10))
tray_icon = None
def reload_lcu(icon, item):
    """
    托盘菜单回调：执行 LCU UI 重启，并重置程序连接状态。
    直接在 pystray 线程中调用 handle_restart_click 执行 API 操作。
    """
    global lcu, has_picked, has_banned
    logging.info("⚡ 接收到托盘 LCU UI 重启请求...")
    try:
        handle_restart_click() 
        logging.info("✅ LCU UI 重启核心逻辑执行完毕。")
    except NameError:
        logging.error("❌ 错误：请确保 handle_restart_click 函数在 reload_lcu 之前定义。")
    except Exception as e:
        logging.error(f"❌ LCU UI 重启操作失败 (执行核心逻辑时): {e}")
    lcu = None
    has_picked = False
    has_banned = False
    print("LCU 客户端 UI 正在重启。程序将在几秒内自动重新连接。")
def quit_window(icon, item):
    """托盘菜单 - 退出程序 (设置标志，让主线程自行退出)"""
    global tray_icon, running, exit_flag
    running = False
    logging.info("📢 接收到退出信号，正在停止后台 LCU 监控线程...")
    if icon:
        icon.stop()
    exit_flag = True
    logging.info("✅ Tkinter 主循环退出标志已设置。")
def show_window(icon, item):
    """托盘菜单 - 恢复主窗口 (必须使用 root.after 确保线程安全)"""
    global tray_icon, exit_flag
    if exit_flag:
        return
    def restore_ui():
        if tray_icon:
            tray_icon.visible = False
        root.deiconify() 
        root.lift() 
        root.focus_force() 
        root.attributes('-topmost', True)
        root.after_idle(root.attributes, '-topmost', False)
    root.after(0, restore_ui)
def withdraw_window():
    """窗口关闭按钮 (X) - 隐藏到托盘"""
    global tray_icon
    root.withdraw()
    menu_items = [
        pystray.MenuItem('开启自动同意', toggle_auto_accept, checked=is_auto_accept_checked),
        pystray.MenuItem('开启自动秒选', toggle_auto_pick, checked=is_auto_pick_checked),
        pystray.MenuItem('开启自动禁用', toggle_auto_ban, checked=is_auto_ban_checked),
        pystray.MenuItem('开启跳过结算', toggle_auto_play_again, checked=is_auto_play_again_checked),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('热重载LCU', reload_lcu),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('显示窗口', show_window, default=True),
        pystray.MenuItem('退出程序', quit_window)
    ]
    menu = pystray.Menu(*menu_items)
    if tray_icon is None:
        image = None
        try:
            image = Image.open(icon_path)
        except Exception as e:
            logging.error(f"❌ 无法加载托盘图标 {icon_path}，使用默认占位符。错误: {e}")
            image = Image.new('RGB', (64, 64), 'white')
            d = ImageDraw.Draw(image)
            d.ellipse((10, 10, 54, 54), fill='#0078D7')
        tray_icon = pystray.Icon(
            name="AutoPick", 
            icon=image, 
            title="AutoPick Created by God", 
            menu=menu 
        )
        tray_icon.run_detached()
    else:
        tray_icon.menu = menu 
        tray_icon.visible = True
def toggle_var(tk_var):
    root.after(0, lambda: tk_var.set(not tk_var.get()))  
def toggle_auto_accept(icon, item):
    toggle_var(auto_accept_var)
def toggle_auto_pick(icon, item):
    toggle_var(auto_pick_var)
def toggle_auto_ban(icon, item):
    toggle_var(auto_ban_var)
def toggle_auto_play_again(icon, item):
    toggle_var(auto_play_again_var)
def check_var(tk_var):
    try:
        return tk_var.get()
    except:
        return False
def is_auto_accept_checked(item):
    return check_var(auto_accept_var)
def is_auto_pick_checked(item):
    return check_var(auto_pick_var)
def is_auto_ban_checked(item):
    return check_var(auto_ban_var)
def is_auto_play_again_checked(item):
    return check_var(auto_play_again_var)
status_label = tk.Label(root, textvariable=status_var,
    font=("Microsoft YaHei", 10, "bold"), bg="#f2f2f2", fg="#333")
status_label.pack(pady=(0, 10))
root.protocol("WM_DELETE_WINDOW", withdraw_window)
threading.Thread(target=monitor_game_state, daemon=True).start()
def check_for_exit():
    global root, exit_flag
    if exit_flag:
        root.quit()
        return
    root.after(100, check_for_exit) 
check_for_exit()
root.mainloop()