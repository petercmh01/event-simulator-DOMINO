"""EventSimulator 单元自测(不依赖 sapien/DOMINO,直接测 DOMINO/envs/event_camera.py)。

验证点(对照 rpg_esim event_simulator.cpp 行为):
1. 静态图 → 无事件
2. 线性增亮 ΔL=0.7, C=0.3 → 正极性 2 个事件,时间戳线性插值正确
3. 线性变暗 → 负极性
4. refractory:单帧大跳变,不应期内只发第一个事件
5. C+≠C- 分别生效
运行: python test_event_simulator.py  (需 GPU;无 GPU 改 device='cpu')
"""
import importlib.util

import torch

# 直接按文件路径加载,绕开 envs/__init__.py(会链式 import sapien/资产路径)
_spec = importlib.util.spec_from_file_location(
    "event_camera", "/home/linux/event_simulator/DOMINO/envs/event_camera.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
EventSimulator = _mod.EventSimulator

DEV = "cuda" if torch.cuda.is_available() else "cpu"
DT = 1.0 / 250.0


def run_steps(sim, images, sigma_off=True):
    """逐帧喂 log 亮度图序列,收集全部事件。"""
    out = []
    for i, img in enumerate(images):
        ev = sim.image_callback(img.to(DEV), t=i * DT)
        if ev is not None:
            out.append(ev)
    return out


def collect(evs):
    if not evs:
        return torch.zeros(0), torch.zeros(0), torch.zeros(0), torch.zeros(0, dtype=torch.bool)
    return tuple(torch.cat([e[k] for e in evs]) for k in range(4))


def test_static():
    sim = EventSimulator(cp=0.3, cm=0.3, sigma_cp=0, sigma_cm=0, device=DEV)
    img = torch.full((8, 8), 1.0)
    for _ in range(5):
        assert sim.image_callback(img.to(DEV), 0.0) is None
    print("PASS static: 无事件")


def test_ramp_positive():
    sim = EventSimulator(cp=0.3, cm=0.3, sigma_cp=0, sigma_cm=0, device=DEV)
    # 从 1.0 线性升到 1.7,每帧 +0.07(共 10 帧)。跨越 1.3 与 1.6 两档
    imgs = [torch.full((8, 8), 1.0 + 0.07 * i) for i in range(11)]
    evs = run_steps(sim, imgs)
    xs, ys, ts, ps = collect(evs)
    assert len(ts) == 2 * 64, f"8x8 每像素 2 事件, 实际 {len(ts)}"
    assert ps.all(), "应全为正极性"
    # 事件时刻:L(t)=1+0.7*t/T_total, T_total=10*DT; L=1.3 → t=0.3/0.7*T; L=1.6 → t=0.6/0.7*T
    T = 10 * DT
    expect = sorted([0.3 / 0.7 * T, 0.6 / 0.7 * T])
    got = sorted(set(ts.tolist()))  # 64 像素同图,时刻去重后应只剩 2 个
    for g, e in zip(got, expect):
        assert abs(g - e) < 1e-5, f"时间戳 {g} != 期望 {e}"
    print(f"PASS ramp_positive: 2 正事件, t={['%.5f' % g for g in got]}")


def test_ramp_negative():
    sim = EventSimulator(cp=0.3, cm=0.3, sigma_cp=0, sigma_cm=0, device=DEV)
    imgs = [torch.full((8, 8), 2.0 - 0.07 * i) for i in range(11)]  # 2.0 → 1.3
    evs = run_steps(sim, imgs)
    xs, ys, ts, ps = collect(evs)
    assert len(ts) == 2 * 64, f"8x8 每像素 2 事件, 实际 {len(ts)}"
    assert (~ps).all(), "应全为负极性"
    print("PASS ramp_negative: 2 负事件")


def test_refractory():
    sim = EventSimulator(cp=0.3, cm=0.3, sigma_cp=0, sigma_cm=0,
                         refractory_s=10e-3, device=DEV)
    sim.image_callback(torch.full((8, 8), 1.0).to(DEV), 0.0)
    # 单帧内 1.0 → 2.2(Δ=1.2,够 4 档),但不应期 10ms ≫ 帧间隔 4ms
    ev = sim.image_callback(torch.full((8, 8), 2.2).to(DEV), DT)
    xs, ys, ts, ps = ev
    assert len(ts) == 64, f"8x8 不应期内每像素 1 个, 实际 {len(ts)}"
    # 之后持续静止 → ref 已推进,不再发
    ev2 = sim.image_callback(torch.full((8, 8), 2.2).to(DEV), 2 * DT)
    assert ev2 is None
    print("PASS refractory: 大跳变只发 1 事件")


def test_cp_cm_split():
    sim = EventSimulator(cp=0.5, cm=0.1, sigma_cp=0, sigma_cm=0, device=DEV)
    a = torch.full((4, 8), 1.0)
    a[:, :4] = 0.0  # 左半暗右半亮,让两半各自触发不同极性
    sim.image_callback(a.to(DEV), 0.0)
    b = a.clone()
    b[:, 4:] = 1.5   # 亮半 +0.5 → 按 C+=0.5 恰好 1 正事件
    b[:, :4] = 0.0   # 暗半保持静止(无跨越,ref 不动)
    c = b.clone()
    c[:, :4] = -0.1  # 暗半 -0.1 → 按 C-=0.1 恰好 1 负事件(ref=0.0 在区间内)
    ev1 = sim.image_callback(b.to(DEV), DT)
    ev2 = sim.image_callback(c.to(DEV), 2 * DT)
    xs1, ys1, ts1, ps1 = ev1
    assert len(ts1) == 16 and ps1.all(), "亮半 4x4 每像素 1 个正事件(C+=0.5)"
    xs2, ys2, ts2, ps2 = ev2
    assert len(ts2) == 16 and (~ps2).all(), "暗半 4x4 每像素 1 个负事件(C-=0.1)"
    assert xs1[0] >= 4 and xs2[0] < 4
    print("PASS cp_cm_split: C+≠C- 分别生效")


def test_multi_crossing_single_frame():
    sim = EventSimulator(cp=0.3, cm=0.3, sigma_cp=0, sigma_cm=0, device=DEV)
    sim.image_callback(torch.full((8, 8), 1.0).to(DEV), 0.0)
    ev = sim.image_callback(torch.full((8, 8), 1.75).to(DEV), DT)  # Δ=0.75 → 2 档
    xs, ys, ts, ps = ev
    assert len(ts) == 2 * 64 and ps.all()
    assert abs(ts[0].item() - (0.3 / 0.75) * DT) < 1e-6   # k=1 档(前 64 个像素)
    assert abs(ts[64].item() - (0.6 / 0.75) * DT) < 1e-6  # k=2 档
    print("PASS multi_crossing: 单帧 2 事件, 时间戳正确")


if __name__ == "__main__":
    test_static()
    test_ramp_positive()
    test_ramp_negative()
    test_refractory()
    test_cp_cm_split()
    test_multi_crossing_single_frame()
    print("\nALL PASS")
