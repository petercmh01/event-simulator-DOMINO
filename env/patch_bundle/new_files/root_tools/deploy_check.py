"""DOMINO 部署验证包装:跑 click_bell demo,同时实测渲染帧率。

- 不改 DOMINO 任何源码,用 monkeypatch 计时:
  - Base_Task._update_render 里的 scene.update_render()(Vulkan RT 渲染本体)
  - Camera.update_picture()(相机图像抓取)
- 用法: python deploy_check.py  (在 domino conda 环境下)
"""
import os
import sys
import time

DOMINO_ROOT = "/home/linux/event_simulator/DOMINO"
os.chdir(DOMINO_ROOT)
sys.path.insert(0, DOMINO_ROOT)
sys.path.insert(0, os.path.join(DOMINO_ROOT, "script"))

stats_render = {"n": 0, "t": 0.0}
stats_pic = {"n": 0, "t": 0.0}


def install_timing_hooks():
    import envs._base_task as bt
    from envs.camera.camera import Camera

    orig_update_render = bt.Base_Task._update_render

    def timed_update_render(self):
        t0 = time.perf_counter()
        orig_update_render(self)
        stats_render["n"] += 1
        stats_render["t"] += time.perf_counter() - t0

    bt.Base_Task._update_render = timed_update_render

    orig_update_picture = Camera.update_picture

    def timed_update_picture(self):
        t0 = time.perf_counter()
        orig_update_picture(self)
        stats_pic["n"] += 1
        stats_pic["t"] += time.perf_counter() - t0

    Camera.update_picture = timed_update_picture


def print_report():
    print("\n========== RENDER FPS REPORT ==========", flush=True)
    if stats_render["t"] > 0:
        n, t = stats_render["n"], stats_render["t"]
        print(f"scene.update_render : {n} calls | avg {t / n * 1000:.1f} ms/call | {n / t:.2f} FPS", flush=True)
    else:
        print("scene.update_render : 0 calls (未触发)", flush=True)
    if stats_pic["t"] > 0:
        n, t = stats_pic["n"], stats_pic["t"]
        print(f"camera.update_picture: {n} calls | avg {t / n * 1000:.1f} ms/call | {n / t:.2f} FPS", flush=True)
    else:
        print("camera.update_picture: 0 calls (未触发)", flush=True)
    print("=======================================", flush=True)


if __name__ == "__main__":
    install_timing_hooks()

    from test_render import Sapien_TEST
    Sapien_TEST()

    import torch.multiprocessing as mp
    mp.set_start_method("spawn", force=True)

    from collect_data import main
    try:
        main(task_name="click_bell", task_config="deploy_check")
    finally:
        print_report()
