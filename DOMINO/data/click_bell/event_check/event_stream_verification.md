# 事件流时间轴平滑性验证报告

- 日期:2026-10-18
- 对象:`click_bell` episode 0,双路事件相机(`left_camera` 左腕 / `head_camera` 头部)
- 管线:ESIM 事件仿真,固定子采样率 250Hz(每物理节点补渲一帧,SSAA×2),帧间事件时刻线性插值
- 参数:C = 0.3,σ = 0.02,refractory = 0,log_eps = 0.001

## 验证问题

事件时间戳是否**无帧化**:连续铺满时间轴,而不是聚集在渲染/存帧边界上。

## 方法与判据

脚本:`~/event_simulator/event_timeline_viz.py`(输入事件 npz,输出四联图 + 数字)。

| 证据 | 图/指标 | 帧化的表现 | 无帧化的表现 |
|---|---|---|---|
| ① 光栅图 | raster(时间×像素,红+/蓝-) | 水平断层、成段空缺 | 连续成带 |
| ② 事件率 | 4ms 粒度直方 + 60ms 存帧边界线 | 与灰线对齐的梳状脉冲 | 平滑钟形,贴线对齐为零 |
| ③ 相位 | (t mod 4ms) 直方 | 全部堆在 0(采样点) | 均匀铺满 [0, 4ms) |
| ④ 边界统计 | 60ms 边界 ±0.5ms 内事件占比 | 显著高于均匀期望 | ≈ 或 < 均匀期望 |

均匀期望 = 1ms/60ms ≈ **1.67%**(±0.5ms 窗宽 / 存帧周期)。

## 结果数字

| 指标 | head_camera | left_camera |
|---|---|---|
| 事件总数 | 598,345 | 510,528 |
| 活跃时间跨度 | 5.14 s | 4.99 s |
| 平均事件率 | 116,484 /s | 102,233 /s |
| 峰值(4ms 窗) | 3,441 | 2,048 |
| 相位均匀度 max/min(①~40 bin) | **2.08** | **3.45** |
| 60ms 边界 ±0.5ms 占比 | **0.62%** | **0.50%** |
| (均匀期望) | 1.67% | 1.67% |
| 空 4ms 间隔占比 | 11.8% | 9.8% |
| 最长静默 | 128 ms | 88 ms |
| 正极性占比 | 42.7% | 45.1% |
| 活跃像素 | 27,128 / 76,800 | 38,679 / 76,800 |

## 结论:无帧化成立,三层证据一致

1. **光栅连续**:头部相机 1.2–2.2s 绵密事件带;腕部相机两段运动间 ~130ms 静默是 `move` 段之间的规划停顿,非采集空洞。
2. **无帧锁定**:事件率曲线呈随运动速度起伏的平滑钟形,与 60ms 存帧边界无对齐;边界占比(0.5~0.62%)**低于**均匀期望(1.67%)。
3. **亚帧平滑**:相位直方铺满整个 4ms 区间、0 点无堆积——线性插值把事件推进了采样间隔内部。若时间戳量化在采样点,max/min 会是几十上百(实测 2~3.5)。

相位直方的轻微台阶纹理是插值固有现象(相邻 tick 亮度变化相似时跨越分数重复),非缺陷。
极性接近 1:1、静默段与运动学一致,符合物理直觉。

## 重要口径:时间轴换算(详解)

npz 中事件时间戳 = **仿真秒**(250Hz 物理时钟)。

**"每视频帧 60ms" 的来历**:物理步进 250Hz(每节点 4ms)× 存帧节奏 save_freq=15(每 15 个
控制步存一帧 RGB)= 每帧打包 **60ms 仿真时间**。视频组装统一用 30fps 编码,因此播放时长
只有 33.3ms/帧——**视频以 ~1.8× 速度播放**(本幕:76 帧 × 60ms = 4.56s 仿真运动在
2.53s 内播完)。RGB 视频在 benchmark 中历来如此(30fps 帧序列,不保证实时保真),
事件视频沿用同一约定,帧才能一一对应。

**换算公式**:
```
视频帧号 = floor( (t - sim_t_frame0) / 0.06 )      # t 为事件仿真秒
视频第 k 帧 ↔ 仿真时间窗 [sim_t_frame0 + k·0.06, sim_t_frame0 + (k+1)·0.06)
```
- 锚点 `sim_t_frame0` = 首帧 RGB 保存时刻(动态拦截段等 pre-motion 事件在其之前,
  全部画在事件视频第 0 帧)
- npz 已带元数据头:`sim_dt_per_frame` / `sim_t_frame0` / `sim_timestep` / `video_fps`
  / `save_freq` / `cfg_*`;2026-10-18 前补写的文件 `sim_t_frame0=nan`(当时未采集),
  之后每跑自动记录

## 产物清单(本目录)

```
video/
  episode0.mp4                   头 RGB(76 帧 @30fps)
  episode0_left_camera.mp4       左腕 RGB(76 帧)
  episode0_front_camera.mp4      侧视 RGB(76 帧,顺带产出)
  episode0_right_camera.mp4      右腕 RGB(76 帧,顺带产出)
  episode0_event_left_camera.mp4 左腕事件(黑底红蓝,76 帧)
  episode0_event_head_camera.mp4 头部事件(黑底红蓝,76 帧)
data/
  episode0_event_left_camera.npz (x, y, t[仿真秒], p) × 510,528
  episode0_event_head_camera.npz (x, y, t[仿真秒], p) × 598,345
  event_timeline_left_camera.png 时间轴四联验证图
  event_timeline_head_camera.png
  episode0.hdf5
```

## 复现

```bash
# 采集(双路事件 + 全部 RGB 视频)
cd ~/event_simulator && conda activate domino
DOMINO_EVENT_CAMERAS="left_camera,head_camera" python event_check.py
# 时间轴验证图
python event_timeline_viz.py
```

开关与参数(环境变量):`DOMINO_EVENT_CAMERAS`(空=关闭,逗号分隔多路)、
`DOMINO_EVENT_C`(默认 0.3)、`DOMINO_EVENT_SIGMA`(0.02)、`DOMINO_EVENT_REFRACTORY_NS`(0)、
`DOMINO_EVENT_LOG_EPS`(0.001)。

## 遗留观察(非本验证范围)

- tick 墙钟 13.27ms(75 FPS,双路),固定成本 ~8.4ms/节点疑似 `scene.update_render` 全场景 pass,待剖析。
- 事件 npz 尚无视频帧↔仿真时间映射元数据(每帧 60ms),需要时可加。
- 单路 ≥100fps 判据未达标(运动场景渲染变慢),见 PROGRESS.md 待办。
