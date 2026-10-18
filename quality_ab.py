"""画质 A/B:方案A基线 / 补光灯(2候选) / MSAA / SSAA。

用法:
  python quality_ab.py main    # 基线+点光补光+方向光补光+SSAA(同一进程,4张快照)
  python quality_ab.py msaa 4  # MSAA=4(独立进程)
  python quality_ab.py msaa 8  # MSAA=8(独立进程)
每张快照附带 take_picture 计时(预热20+采样200)。
"""
import os
import sys
import time

DOMINO_ROOT = "/home/linux/event_simulator/DOMINO"
mode = sys.argv[1] if len(sys.argv) > 1 else "main"
if mode == "msaa":
    import sapien.render as _r
    _r.set_msaa(int(sys.argv[2]))

os.chdir(DOMINO_ROOT)
sys.path.insert(0, "/home/linux/event_simulator")
sys.path.insert(0, DOMINO_ROOT)
sys.path.insert(0, DOMINO_ROOT + "/script")

import numpy as np
import cv2
import PIL.Image as I
import sapien.core as sapien

from collect_data import class_decorator, get_embodiment_config
from envs._GLOBAL_CONFIGS import CONFIGS_PATH


def build_args(task_name="click_bell", task_config="deploy_check"):
    import yaml
    with open(f"./task_config/{task_config}.yml", "r", encoding="utf-8") as f:
        args = yaml.load(f.read(), Loader=yaml.FullLoader)
    args["task_name"] = task_name
    with open(os.path.join(CONFIGS_PATH, "_embodiment_config.yml"), "r", encoding="utf-8") as f:
        _emb_types = yaml.load(f.read(), Loader=yaml.FullLoader)
    emb_type = args.get("embodiment")
    args["left_robot_file"] = _emb_types[emb_type[0]]["file_path"]
    args["right_robot_file"] = _emb_types[emb_type[0]]["file_path"]
    args["dual_arm_embodied"] = True
    args["left_embodiment_config"] = get_embodiment_config(args["left_robot_file"])
    args["right_embodiment_config"] = get_embodiment_config(args["right_robot_file"])
    args["embodiment_name"] = str(emb_type[0])
    args["task_config"] = task_config
    args["save_path"] = os.path.join(args["save_path"], task_name, task_config)
    return args


def snap(cam, path):
    for _ in range(5):
        cam.take_picture()
    rgba = cam.get_picture("Color")
    img = (np.clip(rgba[..., :3], 0, 1) * 255).astype(np.uint8)
    I.fromarray(img).save(path)
    print("saved", path, flush=True)


def bench_take(cam, label, iters=200, warmup=20):
    ts = []
    for i in range(warmup + iters):
        t0 = time.perf_counter()
        cam.take_picture()
        dt = time.perf_counter() - t0
        if i >= warmup:
            ts.append(dt)
    avg = np.mean(ts) * 1000
    print(f"[bench] {label:34s} take_picture avg {avg:6.2f} ms | {1000/avg:7.2f} FPS", flush=True)
    return avg


def main():
    args = build_args()
    env = class_decorator("click_bell")
    env.setup_demo(now_ep_num=0, seed=0, need_plan=False, **args)
    scene = env.scene
    cam = env.cameras.static_camera_list[env.cameras.head_camera_id]

    # A. 方案A基线
    bench_take(cam, "A: planA(点光无阴影)")
    snap(cam, "/tmp/qa_A_planA.png")

    # B1. 点光补光:放在 head_camera 位置(不投影)
    cam_pos = cam.entity.get_pose().p
    fill1 = scene.add_point_light([cam_pos[0], cam_pos[1], cam_pos[2]], [0.7, 0.7, 0.7], shadow=False)
    bench_take(cam, "B1: planA + 点光补光@相机")
    snap(cam, "/tmp/qa_B1_fill_point.png")
    scene.remove_light(fill1)

    # B2. 方向光补光:从 +y 正面打向 -y(不投影)
    fill2 = scene.add_directional_light([0, -1, -0.35], [0.5, 0.5, 0.5], shadow=False)
    bench_take(cam, "B2: planA + 方向光补光(正面)")
    snap(cam, "/tmp/qa_B2_fill_dir.png")
    scene.remove_light(fill2)

    # C. SSAA:2× 分辨率渲染后降采样
    pose = cam.entity.get_pose()
    cam2 = scene.add_camera(
        name="ssaa_cam",
        width=640, height=480,
        fovy=np.deg2rad(37),  # D435 fovy,与 _camera_config.yml 一致
        near=0.1, far=100,
    )
    cam2.entity.set_pose(sapien.Pose(pose.p, pose.q))
    scene.update_render()
    bench_take(cam2, "C: SSAA(640x480渲染)")
    for _ in range(5):
        cam2.take_picture()
    rgba2 = cam2.get_picture("Color")
    img2 = (np.clip(rgba2[..., :3], 0, 1) * 255).astype(np.uint8)
    down = cv2.resize(img2, (320, 240), interpolation=cv2.INTER_AREA)
    I.fromarray(down).save("/tmp/qa_C_ssaa2x.png")
    print("saved /tmp/qa_C_ssaa2x.png", flush=True)


def msaa():
    import sapien.render as sr
    args = build_args()
    env = class_decorator("click_bell")
    env.setup_demo(now_ep_num=0, seed=0, need_plan=False, **args)
    cam = env.cameras.static_camera_list[env.cameras.head_camera_id]
    n = sys.argv[2]
    bench_take(cam, f"MSAA={n}")
    snap(cam, f"/tmp/qa_msaa{n}.png")


if __name__ == "__main__":
    if mode == "msaa":
        msaa()
    else:
        main()
