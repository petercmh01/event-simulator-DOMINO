"""事件流时间轴平滑性可视化(2026-10-18)。

检验"无帧化":事件时间戳应连续铺满时间轴(250Hz 采样内线性插值),
不应出现 1) 存帧周期(60ms save_freq / 33ms 视频帧)的梳状对齐,
2) 时间戳只落在 4ms 采样点上的量化。

用法: python event_timeline_viz.py [npz ...]
输出: /tmp/event_timeline_<相机>.png + 数字报告
"""
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

TICK = 0.004          # 250Hz 节点间隔
SAVE_FREQ = 15        # _take_picture 每 15 个控制步一次 → 60ms
VIDEO_FPS = 30.0


def report(name, ev):
    xs, ys, t, p = ev[:, 0], ev[:, 1], ev[:, 2], ev[:, 3] > 0.5
    ts = np.sort(ev[:, 2].astype(np.float64))
    T0, T1 = ts[0], ts[-1]
    span = T1 - T0
    n = len(ts)

    # 4ms 粒度事件率
    edges = np.arange(T0, T1 + TICK, TICK)
    rate, _ = np.histogram(ts, bins=edges)

    # 1) 4ms 空隙覆盖率(有事件的间隔占比)
    coverage = (rate > 0).mean()

    # 2) 相位均匀度:t mod 4ms 应铺满 [0,TICK);只落在采样点的实现会堆在 0
    phase = (ts % TICK) / TICK
    ph_hist, _ = np.histogram(phase, bins=40, range=(0, 1))
    ph_ratio = ph_hist.max() / max(ph_hist.min(), 1)

    # 3) 与存帧周期(60ms)的对齐:事件落在 60ms 边界 ±0.5ms 内的占比 vs 均匀期望(1/60/0.001≈1.67%)
    near_save = (np.abs((ts % (SAVE_FREQ * TICK)) - 0) < 5e-4).mean()
    expect = 1e-3 / (SAVE_FREQ * TICK)

    # 4) 最长静默(连续空 4ms 间隔的时长)
    gaps = np.diff(np.flatnonzero(rate > 0)) - 1  # 连续空间隔数
    max_gap_ms = gaps.max() * TICK * 1000 if len(gaps) else 0.0

    # 5) 事件间隔分布分位(全局)
    dt = np.diff(ts)
    q = np.percentile(dt, [50, 90, 99, 99.9]) * 1000

    print(f"===== {name} =====")
    print(f"事件数 {n} | 时间跨度 {span:.3f}s | 平均率 {n / span:.0f} 事件/s")
    print(f"峰值 4ms 率 {rate.max()} | 空 4ms 间隔占比 {1 - coverage:.3f}")
    print(f"相位均匀度(t mod 4ms, 40 bin): max/min = {ph_ratio:.2f} (1.0=理想均匀)")
    print(f"60ms 存帧边界 ±0.5ms 内事件占比 {near_save * 100:.2f}% (均匀期望 {expect * 100:.2f}%)")
    print(f"最长静默 {max_gap_ms:.1f} ms")
    print(f"事件间隔分位 ms: p50={q[0]:.3f} p90={q[1]:.3f} p99={q[2]:.3f} p99.9={q[3]:.3f}")
    n_active = len(np.unique((ev[:, 1] * 1000 + ev[:, 0]).astype(np.int64)))
    print(f"正极性 {int(p.sum())} ({p.mean() * 100:.1f}%) | 活跃像素 {n_active} / 76800")

    fig = plt.figure(figsize=(16, 12))
    gs = fig.add_gridspec(4, 1, height_ratios=[2, 1, 2, 1], hspace=0.35)

    # A: 全段光栅(>40万点时随机抽样子集保证可读性)
    ax = fig.add_subplot(gs[0])
    idx = np.arange(n)
    if n > 400000:
        idx = np.random.default_rng(0).choice(n, 400000, replace=False)
        idx = idx[np.argsort(ts[idx])]
    pix = ev[idx, 1] * 320 + ev[idx, 0]
    col = np.where(p[idx], "#ff2222", "#2244ff")
    ax.scatter(ts[idx], pix, s=0.05, c=col, alpha=0.6, lw=0)
    ax.set_ylabel("pixel index (y*320+x)")
    ax.set_title(f"{name}: event raster ({len(idx)}/{n} shown)")
    ax.set_xlim(T0, T1)

    # B: 4ms 事件率 + 存帧边界
    ax = fig.add_subplot(gs[1], sharex=ax)
    ax.step(edges[:-1], rate, where="post", lw=0.8, color="k")
    for tb in np.arange(0, T1, SAVE_FREQ * TICK):
        ax.axvline(tb, color="gray", alpha=0.25, lw=0.5)
    ax.set_ylabel("events / 4ms")
    ax.set_title(f"event rate (gray lines = {SAVE_FREQ * TICK * 1000:.0f}ms save-frame boundaries)")

    # C: 峰值 1s 窗口光栅(全量)
    ax = fig.add_subplot(gs[2], sharex=ax)
    pk = edges[:-1][rate.argmax()]
    m = (ts >= pk) & (ts <= pk + 1.0)
    if m.sum() > 0:
        mm = np.flatnonzero(m)
        ax.scatter(ts[mm], ev[mm, 1] * 320 + ev[mm, 0], s=0.3,
                   c=np.where(p[mm], "#ff2222", "#2244ff"), alpha=0.8, lw=0)
    ax.set_ylabel("pixel index")
    ax.set_title(f"zoom: 1s window at peak rate (t={pk:.2f}s, {int(m.sum())} events)")
    ax.set_xlim(pk, pk + 1.0)
    plt.setp(ax.get_xticklabels(), visible=True)

    # D: 相位分布
    ax = fig.add_subplot(gs[3])
    ax.bar(np.linspace(0, 1, 40, endpoint=False), ph_hist, width=1 / 40,
           align="edge", color="steelblue")
    ax.axhline(ph_hist.mean(), color="r", ls="--", lw=1,
               label=f"uniform={ph_hist.mean():.0f}")
    ax.set_xlabel("phase within 4ms tick (t mod 4ms)")
    ax.set_title("timestamp phase uniformity")
    ax.legend()

    out = f"/tmp/event_timeline_{name.replace('/', '_')}.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print(f"图已存 {out}\n")
    return rate, edges


if __name__ == "__main__":
    files = sys.argv[1:] or [
        "/home/linux/event_simulator/DOMINO/data/click_bell/event_check/data/episode0_event_head_camera.npz",
        "/home/linux/event_simulator/DOMINO/data/click_bell/event_check/data/episode0_event_left_camera.npz",
    ]
    for f in files:
        d = np.load(f)
        report(f.split("_event_")[-1].replace(".npz", ""), d["events"])
