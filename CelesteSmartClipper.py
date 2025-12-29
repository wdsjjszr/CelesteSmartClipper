#!/usr/bin/env python

import obspython as obs
import os, sys, subprocess, time, re, shutil
from time import sleep
from datetime import datetime
from importlib import util 
import winsound


# ================= 定义类 =================
class CelesteClipper:
    def __init__(self):
        self.enabled = True
        self.debug_mode = False
        self.include_map_name = True
        self.include_room_name = True
        self.enable_sound = True  # 声音提示开关

        # --- Celeste 配置 ---
        self.celeste_log_path = r""
        self.last_death_time = None
        self.last_map_name = ""  # 存储标记时的地图名
        self.last_room_name = "" # 存储标记时的房间名

        # --- 视频保存配置 ---
        self.replay1_path = ""
        self.use_custom_path = False
        self.replay1_remove = True
        self.buffer_seconds = 1.0  #默认缓冲时长
        self.min_duration_alert = 0.0 #过短警报阈值

        # 防抖锁：标记当前是否正在处理中
        self.is_processing = False
        


        # 智能清理相关的状态变量
        self.smart_cleanup = False     # 开关
        self.last_generated_clip = None # 记录上一次生成的文件路径
        self.last_used_marker = None    # 记录上一次使用的死亡标记时间

        # --- 内部热键 ID ---
        self.hotkey_mark_id = obs.OBS_INVALID_HOTKEY_ID
        self.hotkey_mark_prev_id = obs.OBS_INVALID_HOTKEY_ID
        self.hotkey_trigger_id = obs.OBS_INVALID_HOTKEY_ID


    # ================= 依赖管理 =================

    def check_package(self, package):
        return util.find_spec(package) is not None

    def install_package(self, package):
        print(f"[CelesteSmart] 正在安装 {package}...")
        python_path = os.path.join(sys.prefix, "python.exe")
        # 强制安装兼容版本 1.0.3，防止新版报错
        pkg_name = "moviepy==1.0.3" if package == "moviepy" else package
        subprocess.call([python_path, "-m", "pip", "install", pkg_name])
        print(f"[CelesteSmart] 安装完成，请重启 OBS。")

    def install_needed(self, props, prop):
        self.install_package("moviepy")
        self.install_package("imageio")
        self.install_package("numpy")

    # ================= 业务逻辑：默认设置 =================
    def update_settings(self, settings):
        self.enabled = obs.obs_data_get_bool(settings, "enabled")
        self.debug_mode = obs.obs_data_get_bool(settings, "debug_mode")
        self.enable_sound = obs.obs_data_get_bool(settings, "enable_sound")
        self.smart_cleanup = obs.obs_data_get_bool(settings, "smart_cleanup")
        
        game_dir = obs.obs_data_get_string(settings, "celeste_game_dir")
        if game_dir:
            self.celeste_log_path = os.path.join(game_dir, "VidCutter", "logs", "log.txt")
        
        self.buffer_seconds = obs.obs_data_get_double(settings, "buffer_seconds")
        self.use_custom_path = obs.obs_data_get_bool(settings, "use_custom_path")
        self.replay1_path = obs.obs_data_get_string(settings, "replay1_path")
        self.replay1_remove = obs.obs_data_get_bool(settings, "replay1_remove")
        self.include_map_name = obs.obs_data_get_bool(settings, "include_map_name")
        self.include_room_name = obs.obs_data_get_bool(settings, "include_room_name")
        self.min_duration_alert = obs.obs_data_get_double(settings, "min_duration_alert")


    # ================= 核心工具函数 =================

    def file_in_use(self, fpath):
        """ 检测文件是否被占用 """
        if os.path.exists(fpath):
            try:
                os.rename(fpath, fpath)
                return False
            except:
                return True
        return False

    def safe_remove_file(self, filepath):
        """ 安全删除文件，带重试机制 """
        if not os.path.exists(filepath): return
        try:
            # 尝试循环检测文件锁
            for x in range(10):
                if not self.file_in_use(filepath):
                    break
                if self.debug_mode: print("[CelesteSmart] 文件占用中，等待释放...")
                sleep(0.5)
            os.remove(filepath)
            if self.debug_mode: print(f"[CelesteSmart] 原始文件已删除: {filepath}")
        except Exception as e:
            print(f"[CelesteSmart] 删除失败: {e}")

    # 文件名净化工具
    def sanitize_filename_part(self, text, max_length=20):
        """ 去除非法字符并截断长度 """
        if not text: return ""
        # 替换 Windows 文件名非法字符为空格或下划线
        # 移除 < > : " / \ | ? *
        cleaned = re.sub(r'[<>:"/\\|?*]', '', text).strip()
        # 截取前 max_length 个字符
        return cleaned[:max_length]

    # 播放提示音工具
    def play_feedback(self, is_error=False, ignore_settings=False):
        """ 播放系统提示音: 成功=普通叮声, 失败=错误警告声 """
        if not self.enable_sound and not ignore_settings: return
        try:
            if is_error:
                # 错误提示音 (SystemHand)
                winsound.MessageBeep(winsound.MB_ICONHAND)
            else:
                # 成功提示音 (SystemAsterisk)
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except:
            pass

    def ffmpeg_extract_subclip(self, filename, t1, t2, targetname=None):
        # 延迟导入
        if "get_setting" not in sys.modules:
            from moviepy.config import get_setting
        if "subprocess_call" not in sys.modules:
            from moviepy.tools import subprocess_call
            
        name, ext = os.path.splitext(filename)
        if not targetname:
            targetname = f"{name}_SUB.{ext}"
        
        # 调用 FFmpeg
        cmd = [get_setting("FFMPEG_BINARY"), "-y",
            "-ss", "%0.6f"%t1,
            "-i", filename,
            "-t", "%0.2f"%(t2-t1),
            "-vcodec", "copy", "-acodec", "copy", targetname]
        
        if self.debug_mode:
            subprocess_call(cmd)
        else:
            subprocess_call(cmd, None)

    def get_last_replay_path(self):
        """ 获取 OBS 生成的最后一个回放文件路径 """
        replay_buffer = obs.obs_frontend_get_replay_buffer_output()
        if not replay_buffer: return None
        cd = obs.calldata_create()
        ph = obs.obs_output_get_proc_handler(replay_buffer)
        obs.proc_handler_call(ph, "get_last_replay", cd)
        path = obs.calldata_string(cd, "path")
        obs.calldata_destroy(cd)
        obs.obs_output_release(replay_buffer)
        return path

    def save_and_wait_for_file(self):
        """ 触发保存并等待文件写入完成 """
        timestamp = time.time()
        obs.obs_frontend_replay_buffer_save()
        
        path = self.get_last_replay_path()
        # 简单的轮询等待
        if not path or not os.path.exists(path):
            sleep(1)
            path = self.get_last_replay_path()
            
        # 确认文件是最新的
        for i in range(20):
            if path and os.path.exists(path):
                if os.path.getctime(path) >= timestamp:
                    return path
            sleep(0.5)
            path = self.get_last_replay_path()
        return None
    
    def _get_video_metadata(self, filepath):
        """ 获取视频时长和帧率，确保资源释放 """
        from moviepy.editor import VideoFileClip
        clip = None
        try:
            clip = VideoFileClip(filepath)
            return clip.duration, clip.fps
        except Exception as e:
            if self.debug_mode: print(f"[CelesteSmart] 读取元数据失败: {e}")
            return 0, 0
        finally:
            if clip: clip.close()

    def _calculate_aligned_duration(self, raw_duration, fps):
        """ 根据帧率对齐时长 """
        if fps and fps > 0:
            frame_time = 1.0 / fps
            target_frame_count = round(raw_duration / frame_time)
            aligned_duration = target_frame_count * frame_time
            if self.debug_mode:
                print(f"[CelesteSmart] 帧对齐: {raw_duration:.2f}s -> {aligned_duration:.2f}s ({target_frame_count}帧 @ {fps}fps)")
            return aligned_duration
        return raw_duration

    def _generate_output_path(self, original_path, wanted_duration, real_duration):
        """ 生成目标文件路径 """
        dir_name = os.path.dirname(os.path.abspath(original_path))
        base_name, ext = os.path.splitext(os.path.basename(original_path))
        
        # 确定目标目录
        target_dir = self.replay1_path if (self.use_custom_path and self.replay1_path and os.path.exists(self.replay1_path)) else dir_name
        
        # 构建文件名部分
        filename_parts = []
        if self.include_map_name and self.last_map_name:
            safe_map = self.sanitize_filename_part(self.last_map_name)
            if safe_map: filename_parts.append(safe_map)
            
        if self.include_room_name and self.last_room_name:
            safe_room = self.sanitize_filename_part(self.last_room_name)
            if safe_room: filename_parts.append(safe_room)

        # 确定时长标记
        final_seconds_int = int(real_duration) if wanted_duration >= real_duration else int(wanted_duration)
        filename_parts.append(f"{final_seconds_int}s")

        suffix = "_" + "_".join(filename_parts)
        return os.path.join(target_dir, f"{base_name}{suffix}{ext}")

    def _execute_file_operation(self, original_path, new_path, wanted_duration, real_duration):
        """ 执行移动或剪辑操作 """
        # 情况 A：请求时长 >= 视频全长 -> 直接改名/移动
        if wanted_duration >= real_duration:
            print(f"[CelesteSmart] 提示：请求时长 >= 视频全长，执行快速重命名。")
            shutil.move(original_path, new_path)
            print(f"[CelesteSmart] ✅ 已快速归档: {new_path}")
        # 情况 B：请求时长 < 视频全长 -> 需要剪辑 (调用 FFmpeg)
        else:
            start_time = max(0, real_duration - wanted_duration) # 防止负数
            print(f"[CelesteSmart] ✂️ 执行剪辑: {start_time:.2f}s -> {real_duration:.2f}s")
            
            self.ffmpeg_extract_subclip(original_path, start_time, real_duration, targetname=new_path)
            
            # 剪辑完成后，处理原始文件
            if self.replay1_remove and os.path.exists(new_path):
                self.safe_remove_file(original_path)
            print(f"[CelesteSmart] ✅ 剪辑完成: {new_path}")

    def _handle_deduplication(self, current_death_time, wanted_duration, real_duration):
        """ 处理智能去重逻辑 """
        if self.smart_cleanup and self.last_generated_clip and self.last_used_marker:
            if current_death_time == self.last_used_marker:
                if real_duration >= wanted_duration:
                    print(f"[CelesteSmart] 🗑️ 检测到冗余片段，正在删除: {self.last_generated_clip}")
                    self.safe_remove_file(self.last_generated_clip)
                else:
                    print(f"[CelesteSmart] ⚠️ 缓存上限导致新视频开头缺失，保留旧片段。")

    # ================= 业务逻辑：剪辑执行 =================
    def perform_smart_cut(self, death_time_point, trigger_time_point):
        # 基础环境检查
        if not self.enabled: return
        if not obs.obs_frontend_replay_buffer_active():
            print("[CelesteSmart] 错误：回放缓存未开启！")
            self.play_feedback(True)
            return
        if not self.check_package("moviepy"):
            print("[CelesteSmart] 严重错误：未安装 moviepy 库！")
            self.play_feedback(True)
            return

        # 保存并获取原始回放文件
        print(f"[CelesteSmart] 正在等待文件写入硬盘...")
        last_replay = self.save_and_wait_for_file()
        
        if not (last_replay and os.path.exists(last_replay)):
            print("[CelesteSmart] 获取回放文件失败 (超时或未找到)")
            self.play_feedback(True)
            return

        try:
            # 计算基础时长请求
            raw_delta = (trigger_time_point - death_time_point).total_seconds()
            raw_wanted_duration = raw_delta + self.buffer_seconds
            
            if raw_wanted_duration <= 0:
                print(f"[CelesteSmart] ❌ 错误：计算时长异常 ({raw_wanted_duration}秒)")
                self.play_feedback(True)
                return

            # 获取视频元数据 (时长 & FPS)
            real_duration, video_fps = self._get_video_metadata(last_replay)
            if real_duration <= 0:
                print("[CelesteSmart] ❌ 无法读取视频时长")
                self.play_feedback(True)
                return
            
            # 帧对齐计算最终时长
            wanted_duration = self._calculate_aligned_duration(raw_wanted_duration, video_fps)
            print(f"[CelesteSmart] ✅ 文件就绪，目标时长: {wanted_duration:.2f}秒")

            # 生成目标路径
            new_file_path = self._generate_output_path(last_replay, wanted_duration, real_duration)

            # 执行核心操作 (移动或剪辑)
            self._execute_file_operation(last_replay, new_file_path, wanted_duration, real_duration)

            # 智能去重处理
            self._handle_deduplication(death_time_point, wanted_duration, real_duration)

            # 过短警报检测
            if self.min_duration_alert > 0 and real_duration < self.min_duration_alert:
                print(f"[CelesteSmart] ⚠️ 警告：剪辑时长 ({wanted_duration:.2f}s) 小于设定阈值！")
                winsound.Beep(1000, 250)

            # 更新状态
            self.last_generated_clip = new_file_path
            self.last_used_marker = death_time_point

        except Exception as e:
            print(f"[CelesteSmart] 处理异常: {e}")
                
    # ================= 业务逻辑：Celeste 识别 =================

    def parse_log_time(self, time_str):
        try: return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f")
        except: return None

    # find_recent_deaths 函数
    def find_recent_deaths(self,filepath, count=1):
        """ 返回列表，每个元素为字典: {'time': datetime, 'map': str, 'room': str} """
        deaths = []
        if not os.path.exists(filepath): return deaths
        
        # 用于记录上一次遇到的 LEVEL LOADED 时间
        last_load_time = None

        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            for line in reversed(lines):
                if "DEATH" in line or "STATE" in line or "LEVEL LOADED"  in line :
                    # 匹配: [时间] 地图名 | 房间名 | 事件
                    match = re.search(r'^\[(.*?)\]\s*(.*?)\s*\|\s*(.*?)\s*\|', line)
                    if match:
                        t = self.parse_log_time(match.group(1))
                        map_str = match.group(2).strip()
                        room_str = match.group(3).strip()
                        
                        if t:
                            # 如果是 LEVEL LOADED，记录时间，作为屏蔽依据
                            if "LEVEL LOADED" in line:
                                last_load_time = t
                            
                            # 如果是 DEATH，检查是否需要屏蔽
                            elif "DEATH" in line:
                                # 如果之前刚读到过 LEVEL LOADED，且时间差在 2 秒内
                                if last_load_time and (last_load_time - t).total_seconds() < 2.0:
                                    # 认为这是传送/重开导致的“无效死亡”，跳过不记录
                                    continue 

                            # 存入字典
                            deaths.append({
                                'time': t, 
                                'map': map_str, 
                                'room': room_str
                            })
                            if len(deaths) >= count:
                                break
        except Exception as e:
            print(f"[CelesteSmart] 读取日志出错: {e}")
            
        return deaths

    #标记最近一次死亡
    def action_mark(self,pressed):
        if not pressed: return
        
        deaths = self.find_recent_deaths(self.celeste_log_path, 1)
        if deaths:
            # 提取字典里的数据
            data = deaths[0]
            self.last_death_time = data['time']
            self.last_map_name = data['map']
            self.last_room_name = data['room']
            
            print(f"[CelesteSmart] 📍 已标记: {self.last_death_time.strftime('%H:%M:%S')} (地图:{self.last_map_name} 房间:{self.last_room_name})")
            self.play_feedback(False)
        else:
            print("[CelesteSmart] ❌ 日志中未找到记录")
            self.play_feedback(True)

    # 标记上一次死亡 (追溯前一次)
    def action_mark_prev(self,pressed):
        if not pressed: return
        
        deaths = self.find_recent_deaths(self.celeste_log_path, 2)
        if len(deaths) >= 2:
            data = deaths[1]
            self.last_death_time = data['time']
            self.last_map_name = data['map']
            self.last_room_name = data['room']
            
            print(f"[CelesteSmart] ⏪ 已追溯: {self.last_death_time.strftime('%H:%M:%S')} (地图:{self.last_map_name} 房间:{self.last_room_name})")
            self.play_feedback(False)
        else:
            print("[CelesteSmart] ❌ 无足够记录追溯")
            self.play_feedback(True)
            
    # 触发剪辑
    def logic_trigger(self):
            
            # 检查锁：如果正在忙，直接无视这次按键
            if self.is_processing:
                self.play_feedback(True)
                print("[CelesteSmart] ⏳ 正在处理上一个请求，已忽略重复按键...")
                return

            # 检查是否已标记
            if not self.last_death_time:
                print("[CelesteSmart] ❌ 错误：请先按标记键！")
                self.play_feedback(True)
                return
            
            # 上锁
            self.is_processing = True

            try:
                #在保存之前，先记录当前时间
                trigger_time_snapshot = datetime.now()
                
                print("[CelesteSmart] 🎬 开始保存回放缓存...")
                self.play_feedback(False)
                
                # 把这个“快照时间”传给执行函数
                self.perform_smart_cut(self.last_death_time, trigger_time_snapshot)

            except Exception as e:
                # 捕获意料之外的错误，防止锁死
                print(f"[CelesteSmart] ⚠️ 发生未捕获异常: {e}")
                self.play_feedback(True)

            finally:
                # 解锁：无论成功还是失败，最后都必须把状态重置
                self.is_processing = False

# ================= 全局实例 =================
        
clipper_core = CelesteClipper()

# ================= 全局回调 =================

# 1. 标记的热键回调
def callback_mark(pressed):
    if pressed:
        clipper_core.action_mark(pressed)

# 2. 追溯的热键回调
def callback_mark_prev(pressed):
    if pressed:
        clipper_core.action_mark_prev(pressed)

# 3. 剪辑的热键回调
def callback_trigger(pressed):
    if pressed:
        clipper_core.logic_trigger()


# ================= OBS 接口 =================

# 设置界面
def script_properties():
    props = obs.obs_properties_create()
    
    obs.obs_properties_add_button(props, "btn_help", "📖 查看详细使用说明", open_help_log)
    
    if not clipper_core.check_package("moviepy"):
        obs.obs_properties_add_button(props, "install_btn", "🔴 点击修复依赖 (安装 moviepy)", clipper_core.install_needed)
    
    obs.obs_properties_add_bool(props, "enabled", "启用脚本")
    obs.obs_properties_add_bool(props, "enable_sound", "启用按键提示音") 
    obs.obs_properties_add_bool(props, "debug_mode", "调试模式")
    
    # 路径说明
    obs.obs_properties_add_path(props, "celeste_game_dir", "Celeste 游戏根目录", obs.OBS_PATH_DIRECTORY, "", None)
    
    # 缓冲时间设置
    obs.obs_properties_add_float(props, "buffer_seconds", "剪辑缓冲时间 (秒)", 0.0, 60.0, 0.5)

    
    g = obs.obs_properties_create()
    obs.obs_properties_add_group(props, "settings", "保存设置", obs.OBS_GROUP_NORMAL, g)
    obs.obs_properties_add_bool(g, "use_custom_path", "使用自定义保存目录 (不勾选则保存到回放原目录)")
    obs.obs_properties_add_path(g, "replay1_path", "保存目录（可选）", obs.OBS_PATH_DIRECTORY, "", None)
    obs.obs_properties_add_float(g, "min_duration_alert", "过短警报阈值 (秒, 0=关闭)", 0.0, 3600, 0.5)
    obs.obs_properties_add_bool(g, "include_map_name", "文件名包含地图名")
    obs.obs_properties_add_bool(g, "include_room_name", "文件名包含房间名")
    obs.obs_properties_add_bool(g, "replay1_remove", "剪辑后删除原片")
    obs.obs_properties_add_bool(g, "smart_cleanup", "自动去重 (若新片段包含旧片段则删除旧片段)")
    
    return props

# 默认值设置
def script_defaults(settings):
    obs.obs_data_set_default_bool(settings, "enabled", True)
    obs.obs_data_set_default_bool(settings, "debug_mode", False)
    obs.obs_data_set_default_bool(settings, "replay1_remove", True)
    obs.obs_data_set_default_double(settings, "buffer_seconds", 1.0)
    obs.obs_data_set_default_bool(settings, "include_map_name", True)
    obs.obs_data_set_default_bool(settings, "include_room_name", True)
    obs.obs_data_set_default_bool(settings, "enable_sound", False)
    obs.obs_data_set_default_bool(settings, "smart_cleanup", True)
    obs.obs_data_set_default_bool(settings, "use_custom_path", False)
    obs.obs_data_set_default_double(settings, "min_duration_alert", 0.0)
    
    
# 将设置传给实例
def script_update(settings):
    clipper_core.update_settings(settings)

# 加载脚本
def script_load(settings):

    # 注册热键  
    clipper_core.hotkey_mark_id = obs.obs_hotkey_register_frontend(
        "celeste.mark", 
        "Celeste: 1. 标记本轮起点", 
        callback_mark
    )

    clipper_core.hotkey_mark_prev_id = obs.obs_hotkey_register_frontend(
        "celeste.mark_prev", 
        "Celeste: 2. 追溯上一轮起点", 
        callback_mark_prev
    )
    
    clipper_core.hotkey_trigger_id = obs.obs_hotkey_register_frontend(
        "celeste.trigger", 
        "Celeste: 3. 剪辑通过片段", 
        callback_trigger
    )
    
    # 加载热键数据
    data1 = obs.obs_data_get_array(settings, "celeste.mark")
    obs.obs_hotkey_load(clipper_core.hotkey_mark_id, data1)
    obs.obs_data_array_release(data1)
    
    # 加载热键数据
    data_prev = obs.obs_data_get_array(settings, "celeste.mark_prev")
    obs.obs_hotkey_load(clipper_core.hotkey_mark_prev_id, data_prev)
    obs.obs_data_array_release(data_prev)
    
    data2 = obs.obs_data_get_array(settings, "celeste.trigger")
    obs.obs_hotkey_load(clipper_core.hotkey_trigger_id, data2)
    obs.obs_data_array_release(data2)
    
    script_update(settings)

# 保存脚本
def script_save(settings):
    data1 = obs.obs_hotkey_save(clipper_core.hotkey_mark_id)
    obs.obs_data_set_array(settings, "celeste.mark", data1)
    obs.obs_data_array_release(data1)
    
    data_prev = obs.obs_hotkey_save(clipper_core.hotkey_mark_prev_id)
    obs.obs_data_set_array(settings, "celeste.mark_prev", data_prev)
    obs.obs_data_array_release(data_prev)
    
    data2 = obs.obs_hotkey_save(clipper_core.hotkey_trigger_id)
    obs.obs_data_set_array(settings, "celeste.trigger", data2)
    obs.obs_data_array_release(data2)

def open_help_log(props, prop):
    print("\n" + "="*60)
    print("🍓 CelesteSmartClipper - 使用手册")
    print("="*60)
    
    print("\n【脚本简介】")
    print("  本脚本通过读取 VidCutter 模组生成的日志，获取游戏内")
    print("  死亡/SL/重载等事件的精确时间，配合 OBS 回放缓存功能，")
    print("  实现\"通过即剪辑\"的自动化工作流。")
    
    print("\n【环境要求】")
    print("  ✓ Celeste 已安装 VidCutter 模组")
    print("  ✓ OBS 已开启「回放缓存」（建议 ≥ 5 分钟）")
    print("  ✓ 首次使用需安装 moviepy 依赖（点击脚本界面按钮即可）")
    
    print("\n【快速配置】")
    print("  1. 在下方填写 Celeste 游戏根目录路径")
    print("  2. 打开 OBS → 设置 → 热键，搜索「Celeste」")
    print("  3. 为以下三个功能绑定快捷键：")
    print("     · 标记本轮起点")
    print("     · 追溯上一轮起点")
    print("     · 剪辑通过片段")
    
    print("\n【标准工作流】")
    print("  ┌─────────────────────────────────────────────┐")
    print("  │  死亡 → 重试 → 通过 → [标记] → 切版 → [剪辑]  │")
    print("  └─────────────────────────────────────────────┘")
    print("  1. 正常游玩，反复尝试直到通过本面")
    print("  2. 通过后、切版前，按下「标记」键锁定最后一次死亡时间")
    print("  3. 切版后画面稳定时，按下「剪辑」键导出视频")
    
    print("\n【补救操作】")
    print("  · 标记前又死了一次？ → 按「追溯」改为上上次时间点")
    print("  · 标记前死了两次以上？ → 请立刻手动导出完整回放缓存后自行剪辑")
    print("  ┌─────────────────────────────────────────────────────────┐")
    print("  │  死亡 → 重试 → 通过 → 切版 → 不小心死亡 → [追溯] → [剪辑]  │")
    print("  └─────────────────────────────────────────────────────────┘")
    print("\n【唐死魅力时刻剪辑】")
    print("  ┌──────────────────────────────────────┐")
    print("  │  死亡 → 重试 → 唐死 → [追溯] → [剪辑]  │")
    print("  └──────────────────────────────────────┘")
    print("\n【拿到一次性收集品(如钥匙)后死亡的录像保留】")
    print("  ┌────────────────────────────────────────────┐")
    print("  │  死亡 → 重试 → 拿到收集品 → [追溯] → [剪辑]  │")
    print("  └────────────────────────────────────────────┘")
    
    print("\n【进阶设置说明】")
    print("  · 剪辑缓冲时间：在标记点前额外保留的秒数（推荐 1~2 秒）")
    print("  · 自动去重：连续剪辑同一标记点时，删除被新片段覆盖的旧片段")
    print("  · 过短警报：片段时长低于阈值时发出提示音（检测异常情况）")
    print("  · 文件命名：可自动附加地图名、房间名、时长标识")
    
    print("\n【技术说明】")
    print("  · 脚本识别的事件类型：DEATH / STATE / LEVEL LOADED")
    print("  · 这意味着 SL加载、F6传送、章节重开 也会被记录为有效标记点")
    print("  · ⚠️ 剪辑时长上限 = OBS 回放缓存设置时长,因此不适用于炼长金或打超长单面")
    
    print("\n【常见问题】")
    print("  Q: 按键没反应？")
    print("  A: 检查热键是否绑定 / 开启「按键提示音」确认触发状态")
    print("")
    print("  Q: 提示「日志未找到记录」？")
    print("  A: 确认 VidCutter 模组已正确安装并生成日志文件")
    print("")
    print("  Q: 视频开头缺失？")
    print("  A: 所需时长超出回放缓存上限，请增加 OBS 缓存时间设置")
    
    print("\n" + "="*60)
    print("💡 提示：按键提示音选项可帮助确认操作是否成功触发")
    print("="*60 + "\n")
    
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, 
            "完整说明已输出到「脚本日志」窗口。\n\n"
            "📍 日志窗口位置：当前界面底部中央的「脚本日志」按钮", 
            "CelesteSmartClipper", 
            0x40  # MB_ICONINFORMATION
        )
    except:
        pass


def script_description():
    return (
        "<h2 style='color:#ff6b81'>🍓 CelesteSmartClipper</h2>"
        "<p><b>Celeste 智能回放剪辑脚本v1.0</b></p>"
        "<hr>"
        "<p>配合 VidCutter 模组的输出日志，自动识别游戏内死亡/重生事件，<br>"
        "一键从 OBS 回放缓存中精准截取通过片段，告别海量素材堆积。</p>"
        "<p style='color:#888; font-size:14px'>▸ 支持地图/房间名自动命名 ▸ 自动去重 ▸ 过短片段提示</p>"
        "<hr>"
        "<p><b>⌨️ 三键操作：</b></p>"
        "<table style='margin-left:10px'>"
        "<tr><td><b>标记</b></td><td>记录最近一次死亡/重生时间点</td></tr>"
        "<tr><td><b>追溯</b></td><td>改为记录上上次时间点（误操作补救/唐死保存）</td></tr>"
        "<tr><td><b>剪辑</b></td><td>导出「标记点 → 当前」的视频片段</td></tr>"
        "</table>"
        "<hr>"
        "<p>⚙️ 首次使用：设置游戏目录 → <b>obs设置-热键</b> 中搜索 <code>Celeste</code> 绑定快捷键</p>"
        "<p>📖 点击下方按钮查看完整教程</p>"

    )
