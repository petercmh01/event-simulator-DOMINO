"""事件相机部署验证:click_bell + 250Hz ESIM 补渲 + 黑底红蓝事件视频。

- 默认单路 left_camera(左腕部);可用 DOMINO_EVENT_CAMERAS 改
- 产物: DOMINO/data/click_bell/event_check/video/episode{0,1}_event_left_camera.mp4
        同目录 data/episode{K}_event_left_camera.npz (原始 x,y,t,p 事件流)
- 用法: python event_check.py  (domino conda 环境)
"""
import os
import sys
import time

DOMINO_ROOT = "/home/linux/event_simulator/DOMINO"
os.chdir(DOMINO_ROOT)
sys.path.insert(0, DOMINO_ROOT)
sys.path.insert(0, os.path.join(DOMINO_ROOT, "script"))

os.environ.setdefault("DOMINO_EVENT_CAMERAS", "left_camera")

stats_tick = {"n": 0, "t": 0.0}


def install_tick_timing():
    from envs.event_camera import EventCamera

    orig_tick = EventCamera.tick

    def timed_tick(self, t):
        t0 = time.perf_counter()
        r = orig_tick(self, t)
        stats_tick["n"] += 1
        stats_tick["t"] += time.perf_counter() - t0
        return r

    EventCamera.tick = timed_tick


if __name__ == "__main__":
    install_tick_timing()

    from collect_data import main
    try:
        main(task_name="click_bell", task_config="event_check")
    finally:
        if stats_tick["n"]:
            n, t = stats_tick["n"], stats_tick["t"]
            print("\n========== EVENT CAMERA REPORT ==========", flush=True)
            print(f"event tick: {n} 次 | avg {t / n * 1000:.2f} ms | "
                  f"{n / t:.0f} FPS(单路 250Hz 补渲+事件生成)", flush=True)
            print("=========================================", flush=True)
