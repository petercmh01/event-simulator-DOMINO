"""单相机渲染微基准:click_bell 场景,单路 320×240。

用法: python bench_single_cam.py <shader_dir>   # default | minimal | trivial | rt
环境变量 DOMINO_WARMUP / DOMINO_ITERS 可改预热与采样次数(默认 20 / 300)。
只计时,不落盘;need_plan=False 跳过运动规划,纯测渲染管线。
"""
import os
import sys
import time

DOMINO_ROOT = "/home/linux/event_simulator/DOMINO"
os.chdir(DOMINO_ROOT)
sys.path.insert(0, DOMINO_ROOT)
sys.path.insert(0, os.path.join(DOMINO_ROOT, "script"))

shader_dir = sys.argv[1] if len(sys.argv) > 1 else "default"
os.environ["DOMINO_SHADER_DIR"] = shader_dir
WARMUP = int(os.environ.get("DOMINO_WARMUP", "20"))
ITERS = int(os.environ.get("DOMINO_ITERS", "300"))

import numpy as np
import yaml

from collect_data import class_decorator, get_embodiment_config
from envs._GLOBAL_CONFIGS import CONFIGS_PATH


def build_args(task_name="click_bell", task_config="deploy_check"):
    config_path = f"./task_config/{task_config}.yml"
    with open(config_path, "r", encoding="utf-8") as f:
        args = yaml.load(f.read(), Loader=yaml.FullLoader)
    args["task_name"] = task_name

    with open(os.path.join(CONFIGS_PATH, "_embodiment_config.yml"), "r", encoding="utf-8") as f:
        _emb_types = yaml.load(f.read(), Loader=yaml.FullLoader)

    emb_type = args.get("embodiment")
    if len(emb_type) == 1:
        args["left_robot_file"] = _emb_types[emb_type[0]]["file_path"]
        args["right_robot_file"] = _emb_types[emb_type[0]]["file_path"]
        args["dual_arm_embodied"] = True
    else:
        raise RuntimeError("unexpected embodiment config")
    args["left_embodiment_config"] = get_embodiment_config(args["left_robot_file"])
    args["right_embodiment_config"] = get_embodiment_config(args["right_robot_file"])
    args["embodiment_name"] = str(emb_type[0])
    args["task_config"] = task_config
    args["save_path"] = os.path.join(args["save_path"], task_name, task_config)
    return args


def stats(name, xs):
    xs = np.array(xs) * 1000.0
    avg = xs.mean()
    p50 = np.median(xs)
    print(f"{name:28s} avg {avg:7.2f} ms | p50 {p50:7.2f} ms | {1000.0 / avg:7.2f} FPS(avg)", flush=True)
    return avg


def main():
    args = build_args()
    env = class_decorator("click_bell")
    t0 = time.perf_counter()
    env.setup_demo(now_ep_num=0, seed=0, need_plan=False, **args)
    print(f"scene setup (no planning): {time.perf_counter() - t0:.1f}s", flush=True)

    cam = env.cameras.static_camera_list[env.cameras.head_camera_id]
    w, h = cam.get_width(), cam.get_height()
    print(f"camera: head_camera {w}x{h} | shader_dir={shader_dir}", flush=True)

    # 轻微扰动相机位姿,避免驱动极端优化(也模拟真实挂载的视角变化)
    orig_pose = cam.entity.get_pose()

    take_ts, read_ts, cuda_ts = [], [], []
    cuda_err = None
    for i in range(WARMUP + ITERS):
        p = orig_pose
        p.set_p([orig_pose.p[0], orig_pose.p[1], orig_pose.p[2] + 1e-5 * (i % 7)])
        cam.entity.set_pose(p)

        t0 = time.perf_counter()
        cam.take_picture()
        t1 = time.perf_counter()
        if i >= WARMUP:
            take_ts.append(t1 - t0)

        if i >= WARMUP and i < WARMUP + 50:
            t2 = time.perf_counter()
            _ = cam.get_picture("Color")
            read_ts.append(time.perf_counter() - t2)
            t3 = time.perf_counter()
            try:
                _ = cam.get_picture_cuda("Color").torch()
                cuda_ts.append(time.perf_counter() - t3)
            except Exception as e:
                if not cuda_err:
                    cuda_err = f"{type(e).__name__}: {e}"

    print(f"\n===== SINGLE-CAM BENCH: shader_dir={shader_dir} =====")
    take_avg = stats("take_picture (渲染)", take_ts)
    stats("get_picture (CPU读回)", read_ts)
    if cuda_ts:
        stats("get_picture_cuda (GPU取图)", cuda_ts)
    else:
        print(f"get_picture_cuda: 不可用 ({cuda_err})", flush=True)
    total = take_avg + (np.mean(read_ts) * 1000.0 if read_ts else 0.0)
    print(f"{'渲染+读回合计':28s} {total:7.2f} ms | {1000.0 / total:7.2f} FPS", flush=True)
    print("=====================================================", flush=True)

    env.close_env() if hasattr(env, "close_env") else None


if __name__ == "__main__":
    main()
