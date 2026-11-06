# -*- coding: utf-8 -*-
# ==============================================================================
# Celeste Smart Clipper v1.2
# Copyright (C) 2026 RemovableDiskC
#
# 基于 VidCutter 日志的 Celeste 自动化剪辑与合并工具
# ==============================================================================
import os, sys, subprocess, time, re, shutil, json
from time import sleep
from datetime import datetime
from importlib import util 
import winsound
import logging

# ==========================================
# 环境探测 
# ==========================================
try:
    import obspython as obs
    IN_OBS = True
except ImportError:
    IN_OBS = False
    obs = None
    # 在这里可以导入只有外部合成时才需要的重型库，避免拖慢 OBS 加载速度
    # from moviepy.editor import VideoFileClip, concatenate_videoclips

# ==========================================
# 共享工具函数
# ==========================================
def get_python_executable():
    """ 
    获取当前环境的 python.exe 路径 
    无论在 OBS 里还是外部，都通过这个逻辑找到同一个 python.exe
    """
    # 如果是在 OBS 里，sys.exec_prefix 指向在设置里选的 Python 目录
    # 如果是在外部，sys.exec_prefix 指向当前运行的 Python 目录
    base_path = sys.exec_prefix
    
    # 尝试寻找 python.exe
    candidate = os.path.join(base_path, "python.exe")
    if os.path.exists(candidate):
        return candidate
    return "python" # 保底

# 启动函数
def launch_external_wrapper(props, prop):
    print("正在启动外部合成进程...")
    
    # 获取当前脚本路径
    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path)
    
    # 获取 python.exe
    py_exe = get_python_executable()
    
    # 启动进程
    try:
        subprocess.Popen(
            [py_exe, script_path, "--run-external"],
            cwd=script_dir,
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
        print(f"✅ 已调用: {py_exe}")
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        # 尝试弹窗报错
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(e), "启动失败", 0x10)
        except: pass

# ==========================================
# 日志系统配置
# ==========================================
def setup_logger():
    """配置日志系统"""
    logger = logging.getLogger("CelesteSmart")
    
    # 避免重复添加 handler（OBS 可能多次加载脚本）
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.DEBUG)  # 最低级别，实际输出由 handler 控制
    
    # 控制台输出（OBS 脚本日志窗口）
    # console_handler = logging.StreamHandler()
    console_handler = logging.StreamHandler(sys.stdout) 
    console_handler.setLevel(logging.INFO)  # 默认只显示 INFO 及以上
    
    
    # 格式化器
    formatter = logging.Formatter(
        '[%(name)s] %(levelname)-7s: %(message)s'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件输出（调试时启用）
    # file_handler = logging.FileHandler("celeste_clipper.log", encoding='utf-8')
    # file_handler.setLevel(logging.DEBUG)
    # file_handler.setFormatter(logging.Formatter(
    #     '%(asctime)s [%(levelname)s] %(message)s'
    # ))
    # logger.addHandler(file_handler)
    
    return logger


# 全局 logger 实例
log = setup_logger()


# ==========================================
# 外部进程逻辑(未实装)
# ==========================================
def run_external_processor():
    print("\n" + "="*50)
    print("🎬 Celeste 自动合成工具 (独立进程模式)")
    print("="*50)
    print(f"🔧 当前使用 Python: {sys.executable}")
    print(f"📂 工作目录: {os.getcwd()}")
    print("-" * 50)

    # -----------------------------------------------
    # TODO: 在这里写入读取 json、合成视频的逻辑
    # -----------------------------------------------
    time.sleep(1)
    print("正在合成高光集锦 (模拟中)...")
    
    for i in range(10):
        # 模拟进度条
        sys.stdout.write(f"\r进度: [{'#'*(i+1)}{' '*(9-i)}] {i*10}%")
        sys.stdout.flush()
        time.sleep(0.5)
        
    print("\n\n✅ 合成完成！文件已保存。")
    print("窗口将在 5 秒后关闭...")
    time.sleep(5)

# ==========================================
# OBS 内部逻辑 (只有在 OBS 里才加载)
# ==========================================
if IN_OBS:

# ================= 定义类 =================
    class CelesteClipper:
        # 匹配: [时间] 地图名 | 房间名 | 事件
        LOG_PATTERN = re.compile(r'^\[(.*?)\]\s*(.*?)\s*\|\s*(.*?)\s*\|')

        def __init__(self):
            self.enabled = True
            # self.debug_mode = False
            self.log_level = "INFO"
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
            self._show_custom_path = False
            self.replay1_remove = True
            self.buffer_seconds = 1.0  #默认缓冲时长
            self.min_duration_alert = 0.0 #过短警报阈值

            # --- 起点裁剪配置 ---
            self.trim_respawn = True       # 只保留复活结束后的片段
            self.respawn_offset = 1.0      # 从死亡标记点向后跳过的秒数（死亡+复活动画时长）
            self.accurate_cut = True       # 重新编码以保证起点精确（否则会对齐到关键帧）

            # 智能清理相关的状态变量
            self.smart_cleanup = False     # 开关
            self.last_generated_clip = None # 记录上一次生成的文件路径
            self.last_used_marker = None    # 记录上一次使用的死亡标记时间

            # --- 内部热键 ID ---
            self.hotkey_mark_id = obs.OBS_INVALID_HOTKEY_ID
            self.hotkey_mark_prev_id = obs.OBS_INVALID_HOTKEY_ID
            self.hotkey_trigger_id = obs.OBS_INVALID_HOTKEY_ID

            #自动合成功能的配置变量
            self.auto_merge_enabled = False      # 是否启用记录功能
            self.auto_merge_use_custom_path = False
            self.auto_merge_output_dir = ""      # 最终文件保存目录
            self.auto_merge_offset = 0.0         # 时间偏移量
            self.auto_merge_transition = True    # 是否加入过渡效果


        # ================= 依赖管理 =================

        def check_package(self, package):
            return util.find_spec(package) is not None

        def install_package(self, package):
            log.info(f"✅ 正在安装 {package}...")
            python_path = os.path.join(sys.prefix, "python.exe")
            # 强制安装兼容版本 1.0.3，防止新版报错
            pkg_name = "moviepy==1.0.3" if package == "moviepy" else package
            subprocess.call([python_path, "-m", "pip", "install", pkg_name])
            log.info(f"✅ 安装完成，请重启 OBS。")

        def install_needed(self, props, prop):
            self.install_package("moviepy")
            self.install_package("imageio")
            self.install_package("numpy")

        # ================= 业务逻辑：默认设置 =================
        def update_settings(self, settings):
            self.enabled = obs.obs_data_get_bool(settings, "enabled")
            log_level_str = obs.obs_data_get_string(settings, "log_level")
            level = logging.DEBUG if log_level_str == "DEBUG" else logging.INFO
            if log.handlers:
                log.handlers[0].setLevel(level)            
            self.enable_sound = obs.obs_data_get_bool(settings, "enable_sound")
            self.smart_cleanup = obs.obs_data_get_bool(settings, "smart_cleanup")
            
            game_dir = obs.obs_data_get_string(settings, "celeste_game_dir")
            if game_dir:
                self.celeste_log_path = os.path.join(game_dir, "VidCutter", "logs", "log.txt")
            
            self.buffer_seconds = obs.obs_data_get_double(settings, "buffer_seconds")
            self.trim_respawn = obs.obs_data_get_bool(settings, "trim_respawn")
            self.respawn_offset = obs.obs_data_get_double(settings, "respawn_offset")
            self.accurate_cut = obs.obs_data_get_bool(settings, "accurate_cut")
            self.use_custom_path = obs.obs_data_get_bool(settings, "use_custom_path")
            self._show_custom_path = obs.obs_data_get_bool(settings, "use_custom_path")
            self.replay1_path = obs.obs_data_get_string(settings, "replay1_path")
            self.replay1_remove = obs.obs_data_get_bool(settings, "replay1_remove")
            self.include_map_name = obs.obs_data_get_bool(settings, "include_map_name")
            self.include_room_name = obs.obs_data_get_bool(settings, "include_room_name")
            self.min_duration_alert = obs.obs_data_get_double(settings, "min_duration_alert")

            self.auto_merge_enabled = obs.obs_data_get_bool(settings, "auto_merge_enabled")
            self.auto_merge_use_custom_path = obs.obs_data_get_bool(settings, "auto_merge_use_custom_path")
            self.auto_merge_output_dir = obs.obs_data_get_string(settings, "auto_merge_output_dir")
            self.auto_merge_offset = obs.obs_data_get_double(settings, "auto_merge_offset")
            self.auto_merge_transition = obs.obs_data_get_bool(settings, "auto_merge_transition")


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
                    log.debug(f"⚙️ 文件占用中，等待释放...")
                    sleep(0.5)
                os.remove(filepath)
                log.debug(f"⚙️ 原始文件已删除: {filepath}")
            except Exception as e:
                log.error(f"❌ 删除文件失败: {filepath}", exc_info=True)

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

        def ffmpeg_extract_subclip(self, filename, t1, t2, targetname=None, accurate=False):
            """
            截取 [t1, t2) 片段。
            accurate=True: 重新编码，起点精确，不会因为关键帧而多出复活画面；
            accurate=False: 流复制，速度快，但起点会对齐到上一个关键帧。
            """
            from moviepy.config import get_setting
            # from moviepy.tools import subprocess_call

            name, ext = os.path.splitext(filename)
            if not targetname:
                targetname = f"{name}_SUB.{ext}"

            ffmpeg_bin = get_setting("FFMPEG_BINARY")
            duration = max(0.0, t2 - t1)

            if accurate:
                # 重新编码：保证片头从指定时间点精确开始
                cmd = [ffmpeg_bin, "-y",
                    "-ss", "%0.6f"%t1,
                    "-i", filename,
                    "-t", "%0.3f"%duration,
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-crf", "18",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    targetname]
            else:
                # 调用 FFmpeg（流复制）
                cmd = [ffmpeg_bin, "-y",
                    "-ss", "%0.6f"%t1,
                    "-i", filename,
                    "-t", "%0.3f"%duration,
                    "-vcodec", "copy", "-acodec", "copy", targetname]
            
            # logger = "bar" if log.isEnabledFor(logging.DEBUG) else None
            # subprocess_call(cmd, logger)

            # 记录 DEBUG 日志 (只有开启调试模式才会显示，且格式统一)
            cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
            log.debug(f"⚙️ 正在执行 FFmpeg: {cmd_str}")

            # 执行命令 (静默模式)
            # creationflags=0x08000000 是 CREATE_NO_WINDOW，防止弹黑框
            # capture_output=True 会吞掉 ffmpeg 的原生输出
            try:
                subprocess.run(
                    cmd, 
                    check=True, 
                    capture_output=True, 
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                log.debug("⚙️ FFmpeg 执行成功")
            except subprocess.CalledProcessError as e:
                log.error(f"❌ FFmpeg 执行失败: {e.stderr.decode('utf-8', errors='ignore')}")
                raise e

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
                log.error(f"❌ 读取元数据失败: {e}")
                return 0, 0
            finally:
                if clip: clip.close()

        def _calculate_aligned_duration(self, raw_duration, fps):
            """ 根据帧率对齐时长 """
            if fps and fps > 0:
                frame_time = 1.0 / fps
                target_frame_count = round(raw_duration / frame_time)
                aligned_duration = target_frame_count * frame_time
                log.debug(f"⚙️ 帧对齐: {raw_duration:.2f}s -> {aligned_duration:.2f}s ({target_frame_count}帧 @ {fps}fps)")
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
                log.warning(f"⚠️ 请求时长 >= 视频全长，执行快速重命名。")
                shutil.move(original_path, new_path)
                log.info(f"✅ 已快速归档: {new_path}")
            # 情况 B：请求时长 < 视频全长 -> 需要剪辑 (调用 FFmpeg)
            else:
                start_time = max(0, real_duration - wanted_duration) # 防止负数
                log.info(f"✅ ✂️ 执行剪辑: {start_time:.2f}s -> {real_duration:.2f}s")
                
                self.ffmpeg_extract_subclip(
                    original_path, start_time, real_duration,
                    targetname=new_path, accurate=self.accurate_cut
                )
                
                # 剪辑完成后，处理原始文件
                if self.replay1_remove and os.path.exists(new_path):
                    self.safe_remove_file(original_path)
                log.info(f"✅ 剪辑完成: {new_path}")

        def _handle_deduplication(self, current_death_time, wanted_duration, real_duration):
            """ 处理智能去重逻辑 """
            if self.smart_cleanup and self.last_generated_clip and self.last_used_marker:
                if current_death_time == self.last_used_marker:
                    if real_duration >= wanted_duration:
                        log.info(f"✅ 🗑️ 检测到冗余片段，正在删除: {self.last_generated_clip}")
                        self.safe_remove_file(self.last_generated_clip)
                        self._update_json_record("remove", self.last_generated_clip)
                    else:
                        log.warning(f"⚠️ 缓存上限导致新视频开头缺失，保留旧片段。")

        def _update_json_record(self, action, file_path, raw_delta=0.0, original_buffer=0.0):
            """ 
            更新 segments.json 元数据文件 
            """
            if not self.auto_merge_enabled: return
            
            try:
                target_dir = os.path.dirname(file_path)
                json_path = os.path.join(target_dir, "segments.json")
                filename = os.path.basename(file_path)
                
                # 读取旧数据
                data = []
                if os.path.exists(json_path):
                    try:
                        with open(json_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                    except: data = []
                
                if action == "remove":
                    data = [item for item in data if item.get('filename') != filename]
                    
                elif action == "add":
                    final_duration = 0.0
                    try:
                        # 再次利用 moviepy 或 ffmpeg 探测最终文件时长
                        # 为了性能，这里可以用简单的 ffmpeg probe，或者复用 moviepy
                        # 为了省事，直接用 self._get_video_metadata(file_path)
                        # 注意：这会带来一点点IO开销，但为了精准是必须的
                        final_duration, _ = self._get_video_metadata(file_path)
                    except:
                        log.error("❌ 无法读取生成文件的时长，无法计算死亡点")
                    
                    # 倒推法计算死亡点
                    # 视频总长 - (从死亡到剪辑经过的时间)
                    death_point = final_duration - raw_delta
                    
                    # 算出来是负数，说明死亡点在视频开始之前
                    if death_point < 0:
                        if self.trim_respawn:
                            # 开启裁剪时这是预期结果：死亡点本来就被剪掉了
                            log.debug(f"⚙️ 死亡点位于片段起点前 {-death_point:.2f}s（已去除死亡/复活动画）")
                        else:
                            log.warning(f"⚠️ 死亡点在视频范围外 ({death_point:.2f}s)，可能是回放缓存太短")
                    
                    new_record = {
                        "filename": filename,
                        # 核心数据：死亡点时间戳
                        "death_point_in_video": round(death_point, 6),
                        
                        # 辅助数据：记录当时的缓冲设置，方便后期调整
                        "original_buffer": original_buffer, 
                        
                        # 调试数据：保留原始时长信息
                        "final_file_duration": round(final_duration, 6),
                        
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    
                    # 先删旧后加新，防止重复
                    data = [item for item in data if item.get('filename') != filename]
                    data.append(new_record)
                
                # 写入
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    
                if action == "add":
                    log.debug(f"⚙️ JSON记录: 死亡点位于视频 {death_point:.2f}s")

            except Exception as e:
                log.error(f"❌ 写入元数据失败: {e}")

        # ================= 业务逻辑：剪辑执行 =================
        def perform_smart_cut(self, death_time_point, trigger_time_point):
            # 基础环境检查
            if not self.enabled: return
            if not obs.obs_frontend_replay_buffer_active():
                log.error("❌ 回放缓存未开启！")
                self.play_feedback(True)
                return
            if not self.check_package("moviepy"):
                log.error("❌ 严重未安装 moviepy 库！")
                self.play_feedback(True)
                return

            # 保存并获取原始回放文件
            log.info(f"✅ 正在等待文件写入硬盘...")
            last_replay = self.save_and_wait_for_file()
            
            if not (last_replay and os.path.exists(last_replay)):
                log.error("❌ 获取回放文件失败 (超时或未找到)")
                self.play_feedback(True)
                return

            try:
                # 1. 计算理论请求时长 (Wanted Duration)
                raw_delta = (trigger_time_point - death_time_point).total_seconds()

                if self.trim_respawn:
                    # 新逻辑：从复活动画结束后开始，只保留「复活结束 → 触发剪辑」
                    # 片段起点 = 死亡时间 + respawn_offset，不再向前保留死亡前画面
                    raw_wanted_duration = raw_delta - self.respawn_offset
                    log.debug(
                        f"⚙️ 去除死亡/复活动画: 死亡→触发 {raw_delta:.2f}s, "
                        f"跳过 {self.respawn_offset:.2f}s, 保留 {raw_wanted_duration:.2f}s"
                    )
                else:
                    # 旧逻辑: (触发时间 - 死亡时间) + 缓冲时间
                    raw_wanted_duration = raw_delta + self.buffer_seconds

                if raw_wanted_duration <= 0:
                    log.error(
                        f"❌ 计算时长异常 ({raw_wanted_duration:.2f}秒)："
                        f"请确认触发时间晚于复活动画结束时间，或调小「死亡后跳过时间」"
                    )
                    self.play_feedback(True)
                    return

                # 获取视频元数据 (时长 & FPS)
                real_duration, video_fps = self._get_video_metadata(last_replay)
                if real_duration <= 0:
                    log.error("❌ 无法读取视频时长")
                    self.play_feedback(True)
                    return
                
                # 帧对齐计算最终时长
                wanted_duration = self._calculate_aligned_duration(raw_wanted_duration, video_fps)
                log.debug(f"⚙️ 文件就绪，目标时长: {wanted_duration:.2f}秒")

                # 生成目标路径
                new_file_path = self._generate_output_path(last_replay, wanted_duration, real_duration)

                # 执行核心操作 (移动或剪辑)
                self._execute_file_operation(last_replay, new_file_path, wanted_duration, real_duration)
                # 写入元数据
                self._update_json_record(
                    action="add", 
                    file_path=new_file_path, 
                    raw_delta=raw_delta,           # 传入真实时间差
                    original_buffer=self.buffer_seconds
                )

                # 智能去重处理
                self._handle_deduplication(death_time_point, wanted_duration, real_duration)

                # 过短警报检测（注意：应该检查最终片段时长，而不是原始回放时长）
                final_duration = min(wanted_duration, real_duration)
                if self.min_duration_alert > 0 and final_duration < self.min_duration_alert:
                    log.warning(f"⚠️ 剪辑时长 ({final_duration:.2f}s) 小于设定阈值！")
                    winsound.Beep(1000, 250)

                # 更新状态
                self.last_generated_clip = new_file_path
                self.last_used_marker = death_time_point

            except Exception as e:
                log.error(f"❌ 处理异常: {e}", exc_info=True)

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
                        match = self.LOG_PATTERN.search(line)
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
                log.error(f"❌ 读取日志出错: {e}")
                
            return deaths

        #标记最近一次死亡
        def action_mark(self,pressed):
            if not pressed: return

            if not obs.obs_frontend_replay_buffer_active():
                log.error("❌ 回放缓存未开启！")
                self.play_feedback(True)
                return
            
            deaths = self.find_recent_deaths(self.celeste_log_path, 1)
            if deaths:
                # 提取字典里的数据
                data = deaths[0]
                self.last_death_time = data['time']
                self.last_map_name = data['map']
                self.last_room_name = data['room']
                
                log.info(f"✅ 📍 已标记: {self.last_death_time.strftime('%H:%M:%S')} (地图:{self.last_map_name} 房间:{self.last_room_name})")
                self.play_feedback(False)
            else:
                log.warning("⚠️ 日志中未找到记录")
                self.play_feedback(True)

        # 标记上一次死亡 (追溯前一次)
        def action_mark_prev(self,pressed):
            if not pressed: return
            
            if not obs.obs_frontend_replay_buffer_active():
                log.error("❌ 回放缓存未开启！")
                self.play_feedback(True)
                return

            deaths = self.find_recent_deaths(self.celeste_log_path, 2)
            if len(deaths) >= 2:
                data = deaths[1]
                self.last_death_time = data['time']
                self.last_map_name = data['map']
                self.last_room_name = data['room']
                
                log.info(f"✅ ⏪ 已追溯: {self.last_death_time.strftime('%H:%M:%S')} (地图:{self.last_map_name} 房间:{self.last_room_name})")
                self.play_feedback(False)
            else:
                log.warning("⚠️ 无足够记录追溯")
                self.play_feedback(True)
                
        # 触发剪辑
        def logic_trigger(self):
            
                # 检查是否已标记
                if not self.last_death_time:
                    log.error("❌ 请先按标记键！")
                    self.play_feedback(True)
                    return
                

                try:
                    #在保存之前，先记录当前时间
                    trigger_time_snapshot = datetime.now()
                    
                    log.info("✅ 🎬 开始保存回放缓存...")
                    self.play_feedback(False)
                    
                    # 把这个“快照时间”传给执行函数
                    self.perform_smart_cut(self.last_death_time, trigger_time_snapshot)

                except Exception as e:
                    # 捕获意料之外的错误，防止锁死
                    log.error(f"❌ 发生未捕获异常: {e}")
                    self.play_feedback(True)


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


        p_enable_sound = obs.obs_properties_add_bool(props, "enable_sound", "启用按键提示音") 
        obs.obs_property_set_long_description(p_enable_sound, "启用后会在按下按键时播放windows音效\n可以通过在obs场景里添加\"应用程序音频采集\"源来避免提示音效被录入视频")


        # 日志级别选择
        log_level_list = obs.obs_properties_add_list(
            props, "log_level", "日志详细程度",
            obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING
        )
        obs.obs_property_list_add_string(log_level_list, "ERROR", "ERROR")
        obs.obs_property_list_add_string(log_level_list, "WARNING", "WARNING")
        obs.obs_property_list_add_string(log_level_list, "INFO", "INFO")
        obs.obs_property_list_add_string(log_level_list, "DEBUG", "DEBUG")


        p_celeste_game_dir = obs.obs_properties_add_path(props, "celeste_game_dir", "Celeste 游戏根目录", obs.OBS_PATH_DIRECTORY, "", None)
        obs.obs_property_set_long_description(p_celeste_game_dir, "选择你的游戏根目录\n即要以\"/Celeste\"为结尾")


        p_buffer = obs.obs_properties_add_float(props, "buffer_seconds", "剪辑缓冲时间 (秒)", 0.0, 60.0, 0.5)
        obs.obs_property_set_long_description(p_buffer, "在触发剪辑点之前额外向前回溯的时间。\n例如设置为 5.0，则会多保存事件发生前 5 秒的内容。\n要注意由于FFmpeg是以关键帧分割视频的,\n所以片头还会额外多出随机几秒\n\n⚠️ 开启「只保留复活结束后的片段」后，此项不再生效")


        p_trim_respawn = obs.obs_properties_add_bool(props, "trim_respawn", "只保留复活结束后的片段")
        obs.obs_property_set_long_description(p_trim_respawn, "勾选后，片段只包含「复活动画结束 → 按下剪辑键」的画面，\n不再包含死亡前的缓冲画面以及死亡/复活动画。\n\n注意：该模式下「剪辑缓冲时间」不再生效。")


        p_respawn_offset = obs.obs_properties_add_float(props, "respawn_offset", "死亡后跳过时间 (秒)", 0.0, 10.0, 0.1)
        obs.obs_property_set_long_description(p_respawn_offset, "从死亡标记点向后跳过的时长，用于去掉死亡动画与复活过场。\nCeleste 的死亡+复活渐变通常约 1~1.5 秒；\n如果片段开头仍残留复活过程，请调大此值；\n如果剪掉了复活后已经可以操作的部分，请调小此值。\n\n仅在开启「只保留复活结束后的片段」时生效。")


        p_accurate_cut = obs.obs_properties_add_bool(props, "accurate_cut", "精确起点（重新编码）")
        obs.obs_property_set_long_description(p_accurate_cut, "开启：重新编码视频以精确裁切起点，速度较慢但片头不会多出画面。\n关闭：无损快速剪切，起点可能向前偏移到上一个关键帧，\n从而在片头多出少量死亡/复活画面。\n\n推荐开启，尤其是希望片头正好从复活结束时开始时。")

        # "保存设置"分组
        g = obs.obs_properties_create()
        obs.obs_properties_add_group(props, "settings", "保存设置", obs.OBS_GROUP_NORMAL, g)
        

        p_use_custom = obs.obs_properties_add_bool(g, "use_custom_path", "使用自定义保存目录")
        p_path = obs.obs_properties_add_path(g, "replay1_path", "保存目录（可选）", obs.OBS_PATH_DIRECTORY, "", None)
        obs.obs_property_set_visible(p_path, clipper_core._show_custom_path)
        obs.obs_property_set_modified_callback(p_use_custom, toggle_custom_path)
        obs.obs_property_set_long_description(p_use_custom,"最终剪辑出来的片段的存放点\n如果不勾选则保存到原回放缓存所在目录")

       
        p_min_duration_alert = obs.obs_properties_add_float(g, "min_duration_alert", "过短警报阈值 (秒, 0=关闭)", 0.0, 3600, 0.5)
        obs.obs_property_set_long_description(p_min_duration_alert,"如果最终剪辑得到的视频长度少于设定的值,则播放一声短促的警告声\n设置为0则关闭报警功能")


        obs.obs_properties_add_bool(g, "include_map_name", "文件名包含地图名")


        obs.obs_properties_add_bool(g, "include_room_name", "文件名包含房间名")


        p_replay1_remove = obs.obs_properties_add_bool(g, "replay1_remove", "剪辑后删除原片")
        obs.obs_property_set_long_description(p_replay1_remove,"脚本原理是导出回放缓存后进行剪辑,\n勾选会在剪辑完毕后清理导出的回放缓存文件")


        p_smart_cleanup = obs.obs_properties_add_bool(g, "smart_cleanup", "自动去重")
        obs.obs_property_set_long_description(p_smart_cleanup,"若新片段完全包含旧片段则删除旧片段\n如果怕误删可以关掉\n目前测试下来还没有误删案例")


        # # === 自动合成设置分组 ===(暂时终止)
        # g_merge = obs.obs_properties_create()
        # obs.obs_properties_add_group(props, "auto_merge_settings", "🎞️ 片段合并(测试)", obs.OBS_GROUP_NORMAL, g_merge)
        # obs.obs_properties_add_bool(g_merge, "auto_merge_enabled", "启用片段合并")
        # obs.obs_properties_add_bool(g_merge, "auto_merge_use_custom_path", "使用自定义保存目录 (不勾选则保存到第一个片段所在目录)")
        # obs.obs_properties_add_path(g_merge, "auto_merge_output_dir", "最终保存目录（可选）", obs.OBS_PATH_DIRECTORY, "", None)
        # # 时间偏移量 (支持负数，步长0.05秒)
        # # 比如：填 -0.5 表示每个片段的开始时间再提前 0.5 秒
        # obs.obs_properties_add_float(g_merge, "auto_merge_offset", "片段开始时间偏移 (秒)", -10.0, 10.0, 0.05)
        # obs.obs_properties_add_bool(g_merge, "auto_merge_transition", "启用淡入淡出过渡效果")
        # obs.obs_properties_add_button(g_merge, "btn_test_editor", "🚀 开始合并", launch_external_wrapper)


        return props

    # 默认值设置
    def script_defaults(settings):
        obs.obs_data_set_default_bool(settings, "enabled", True)
        obs.obs_data_set_default_string(settings, "log_level", "INFO")
        obs.obs_data_set_default_bool(settings, "replay1_remove", True)
        obs.obs_data_set_default_double(settings, "buffer_seconds", 1.0)
        obs.obs_data_set_default_bool(settings, "trim_respawn", True)
        obs.obs_data_set_default_double(settings, "respawn_offset", 1.0)
        obs.obs_data_set_default_bool(settings, "accurate_cut", True)
        obs.obs_data_set_default_bool(settings, "include_map_name", True)
        obs.obs_data_set_default_bool(settings, "include_room_name", True)
        obs.obs_data_set_default_bool(settings, "enable_sound", False)
        obs.obs_data_set_default_bool(settings, "smart_cleanup", True)
        obs.obs_data_set_default_bool(settings, "use_custom_path", False)
        obs.obs_data_set_default_double(settings, "min_duration_alert", 0.0)

        # 片段合并
        obs.obs_data_set_default_bool(settings, "auto_merge_enabled", False)
        obs.obs_data_set_default_bool(settings, "auto_merge_use_custom_path", False)
        obs.obs_data_set_default_string(settings, "auto_merge_output_dir", "") 
        obs.obs_data_set_default_double(settings, "auto_merge_offset", 0.0)
        obs.obs_data_set_default_bool(settings, "auto_merge_transition", True)
        
        
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
        print("  · 只保留复活结束后的片段：去掉死亡前缓冲与死亡/复活动画")
        print("  · 死亡后跳过时间：从死亡标记点向后跳过多久开始保留")
        print("    （Celeste 死亡+复活过场通常约 1~1.5 秒，不同章节可微调）")
        print("  · 精确起点（重新编码）：较慢，但片头不会因关键帧多出复活画面")
        print("  · 剪辑缓冲时间：仅在关闭「只保留复活结束后的片段」时生效，")
        print("    表示在标记点前额外保留的秒数（推荐 1~2 秒）")
        print("  · 自动去重：连续剪辑同一标记点时，删除被新片段覆盖的旧片段")
        print("  · 过短警报：片段时长低于阈值时发出提示音（检测异常情况）")
        print("  · 文件命名：可自动附加地图名、房间名、时长标识")
        
        print("\n【技术说明】")
        print("  · 默认剪辑范围：复活动画结束 → 按下「剪辑」键（保存点）")
        print("  · 片头如需 100% 精确，请开启「精确起点（重新编码）」；")
        print("    关闭时会使用流复制快速剪切，起点可能对齐到上一个关键帧")
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
            "<p><b>Celeste 智能回放剪辑脚本v1.1</b></p>"
            "<hr>"
            "<p>配合 VidCutter 模组的输出日志，自动识别游戏内死亡/重生事件，<br>"
            "一键从 OBS 回放缓存中精准截取通过片段，告别海量素材堆积。</p>"
            "<p style='color:#888; font-size:14px'>▸ 支持地图/房间名自动命名 ▸ 自动去重 ▸ 过短片段提示</p>"
            "<hr>"
            "<p><b>⌨️ 三键操作：</b></p>"
            "<table style='margin-left:10px'>"
            "<tr><td><b>标记</b></td><td>记录最近一次死亡/重生时间点</td></tr>"
            "<tr><td><b>追溯</b></td><td>改为记录上上次时间点（误操作补救/唐死保存）</td></tr>"
            "<tr><td><b>剪辑</b></td><td>导出「复活动画结束 → 当前」的视频片段</td></tr>"
            "</table>"
            "<hr>"
            "<p>⚙️ 首次使用：设置游戏目录 → <b>obs设置-热键</b> 中搜索 <code>Celeste</code> 绑定快捷键</p>"
            "<p>📖 点击下方按钮查看完整教程</p>"
        )
    
    def toggle_custom_path(props, prop, settings):
        """
        回调函数逻辑：
        1. 获取 'use_custom_path' 当前的勾选状态
        2. 找到 'replay1_path' 这个控件
        3. 根据勾选状态，设置 'replay1_path' 显示或隐藏
        """
        # 获取用户现在的设置 (True/False)
        use_custom = obs.obs_data_get_bool(settings, "use_custom_path")
        
        # 从 props 中找到要控制的那个控件 (replay1_path)
        p_target = obs.obs_properties_get(props, "replay1_path")
        
        # 设置可见性 (Visible)
        obs.obs_property_set_visible(p_target, use_custom)
        
        return True



# ==========================================
# 程序入口分流
# ==========================================
if __name__ == "__main__":
    # 只有当这个文件被 python.exe 直接运行时，才会执行这里
    # OBS 加载脚本时，是作为模块导入 (import)，不会执行这里
    
    if "--run-external" in sys.argv:
        run_external_processor()
    else:
        # 用户直接双击了脚本，提示一下
        print("请不要直接运行此脚本。")
        print("请在 OBS -> 工具 -> 脚本 中加载它。")
        time.sleep(3)