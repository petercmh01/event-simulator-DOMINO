"""ESIM 事件相机仿真(2026-10-18):250Hz 补渲 + 事件生成 + 黑底红蓝可视化视频。

事件生成算法向量化移植自 rpg_esim(commit 4cf0b89)
event_camera_simulator/esim/src/event_simulator.cpp(119 行,逐行对应见各方法注释);
采样策略:固定子采样率——take_action 控制循环每个物理节点(250Hz)补渲一帧,
帧间事件时刻线性插值(λ_eff = V_max/f_sub 浮动,见 PROGRESS.md 讨论)。
帧预处理顺序与 ESIM 一致:SSAA resolve(线性域 box 平均)→ 亮度 → log(eps)。

全部配置走环境变量,DOMINO_EVENT_CAMERAS 为空(默认)则管理器不启用,
_base_task 里的 tick/boundary/finalize 均为 no-op。
"""
import os

import numpy as np
import torch

_LUMA = torch.tensor([0.299, 0.587, 0.114])  # Rec.601,作用在渲染 RGB 上


class EventSimulator:
    """ESIM EventSimulator 的 PyTorch 向量化移植。

    状态与 C++ 版一一对应:last_L(it,上一帧 log 亮度)、ref_L(每像素上次跨越电平
    prev_cross)、last_event_t(每像素上次事件时刻,秒,0=无)、current_time。
    """

    def __init__(self, cp=0.3, cm=0.3, sigma_cp=0.02, sigma_cm=0.02,
                 refractory_s=0.0, log_eps=1e-3, device="cuda",
                 max_crossings=32):
        self.cp, self.cm = float(cp), float(cm)
        self.sigma_cp, self.sigma_cm = float(sigma_cp), float(sigma_cm)
        self.refractory_s = float(refractory_s)
        self.log_eps = float(log_eps)
        self.device = device
        self.max_crossings = int(max_crossings)
        self.is_initialized = False

    def init(self, log_img, t):
        # event_simulator.cpp: init() —— 像素电压用第一帧初始化
        self.last_L = log_img.clone()
        self.ref_L = log_img.clone()
        self.last_event_t = torch.zeros_like(log_img)
        self.current_time = float(t)
        self.is_initialized = True

    @torch.no_grad()
    def image_callback(self, log_img, t):
        """对应 C++ imageCallback(img, time)。输入单通道 log 亮度图,返回事件或 None。

        事件为 (xs, ys, ts, ps):像素坐标 + 时刻(秒) + 极性(True=正)。
        """
        if not self.is_initialized:
            self.init(log_img, t)
            return None

        dt = float(t) - self.current_time
        it, itdt = self.last_L, log_img  # C++: it=last_img, itdt=当前帧
        delta = itdt - it
        active = delta.abs() > 1e-6  # C++ tolerance
        pol = torch.where(delta >= 0, 1.0, -1.0)  # C++: pol = (itdt >= it) ? +1 : -1

        base_C = torch.where(pol > 0, self.cp, self.cm)
        sigma = torch.where(pol > 0, self.sigma_cp, self.sigma_cm)

        curr = self.ref_L.clone()
        ev_x, ev_y, ev_t, ev_p = [], [], [], []
        for _ in range(self.max_crossings):
            # C++: C = C(pol) + N(0, σ),钳位最小阈值 0.01(每事件独立采样)
            C = base_C
            if self.sigma_cp > 0 or self.sigma_cm > 0:
                C = (C + torch.randn_like(C) * sigma).clamp_min(0.01)
            curr = curr + pol * C  # C++: curr_cross += pol * C

            # C++: 正极性 (curr>it && curr<=itdt);负极性 (curr<it && curr>=itdt)
            crossed = torch.where(
                pol > 0,
                (curr > it) & (curr <= itdt),
                (curr < it) & (curr >= itdt),
            ) & active
            if crossed.any():
                # C++: edt = (curr_cross - it) * dt / (itdt - it) —— 线性插值事件时刻
                te = self.current_time + (curr - it) * dt / delta
                # C++: refractory —— 距上次事件不足不应期则丢弃
                fired = crossed & (
                    (self.last_event_t == 0)
                    | ((te - self.last_event_t) >= self.refractory_s)
                )
                if fired.any():
                    ys, xs = fired.nonzero(as_tuple=True)
                    ev_x.append(xs)
                    ev_y.append(ys)
                    ev_t.append(te[fired])
                    ev_p.append(pol[fired] > 0)
                    self.last_event_t = torch.where(fired, te, self.last_event_t)
                # C++: ref_values_ 更新为最后跨越电平(与 refractory 丢弃无关)
                self.ref_L = torch.where(crossed, curr, self.ref_L)

            # C++ do-while 终止:下一电平已越出 (it, itdt) 开区间即停
            nxt = torch.where(pol > 0, itdt - curr, curr - itdt)
            if not ((nxt >= 0.01) & active).any():
                break

        self.current_time = float(t)
        self.last_L = log_img.clone()

        if not ev_x:
            return None
        return (torch.cat(ev_x), torch.cat(ev_y),
                torch.cat(ev_t), torch.cat(ev_p))


class EventCamera:
    """一路事件相机:持有 sapien 相机句柄 + 一个 EventSimulator,按节点补渲。"""

    def __init__(self, name, sapien_camera, ssaa, device="cuda", **sim_kwargs):
        self.name = name
        self.cam = sapien_camera
        self.ssaa = ssaa
        self.device = device
        self.sim = EventSimulator(device=device, **sim_kwargs)
        self.width = sapien_camera.width // ssaa
        self.height = sapien_camera.height // ssaa

    @torch.no_grad()
    def render_log_image(self):
        """SSAA resolve(线性域 box 平均,同 envs/camera/camera.py)→ 亮度 → log。"""
        self.cam.take_picture()
        rgba = self.cam.get_picture_cuda("Color").torch()  # [H,W,4] float32 GPU
        if self.ssaa > 1:
            f = self.ssaa
            rgba = torch.nn.functional.avg_pool2d(
                rgba.permute(2, 0, 1).unsqueeze(0), f
            ).squeeze(0).permute(1, 2, 0)
        luma = _LUMA.to(rgba.device)
        gray = (rgba[..., :3] * luma).sum(-1)  # [h, w]
        return torch.log(gray + self.sim.log_eps)

    @torch.no_grad()
    def tick(self, t):
        """渲染当前节点帧并推进事件模拟。返回 (xs, ys, ts, ps) 或 None。"""
        return self.sim.image_callback(self.render_log_image(), t)


class EventCameraManager:
    """管理若干路事件相机 + 分幕事件累积 + 黑底红蓝视频写出。

    bin 与 RGB 视频帧的对齐约定(见 PROGRESS.md):
    RGB 第 j 帧(1-based,take_action 开头写的"上一步末状态")对应 bin[j-1],
    即第 k 次 take_action 产生的事件落在 bin[k],最终取前 M 个 bin(M=RGB 帧数)。
    """

    def __init__(self, cameras, spec, timestep=1.0 / 250.0, device="cuda"):
        self.enabled = bool(spec.strip())
        self.timestep = timestep
        self.device = device
        self.sim_time = 0.0
        self.cams = []
        if not self.enabled:
            return
        sim_kwargs = dict(
            cp=os.environ.get("DOMINO_EVENT_C", "0.3"),
            cm=os.environ.get("DOMINO_EVENT_C", "0.3"),
            sigma_cp=os.environ.get("DOMINO_EVENT_SIGMA", "0.02"),
            sigma_cm=os.environ.get("DOMINO_EVENT_SIGMA", "0.02"),
            refractory_s=float(os.environ.get("DOMINO_EVENT_REFRACTORY_NS", "0")) * 1e-9,
            log_eps=os.environ.get("DOMINO_EVENT_LOG_EPS", "0.001"),
        )
        candidates = {}
        if getattr(cameras, "collect_wrist_camera", False):
            candidates["left_camera"] = cameras.left_camera
            candidates["right_camera"] = cameras.right_camera
        for cam, nm in zip(cameras.static_camera_list, cameras.static_camera_name):
            candidates[nm] = cam
        for name in [s.strip() for s in spec.split(",") if s.strip()]:
            if name not in candidates:
                raise ValueError(f"DOMINO_EVENT_CAMERAS: 未知相机 '{name}',"
                                 f"可选: {sorted(candidates.keys())}")
            self.cams.append(EventCamera(name, candidates[name], cameras.ssaa,
                                         device=device, **sim_kwargs))
        print(f"[EventCamera] 启用 {len(self.cams)} 路事件相机: "
              f"{[c.name for c in self.cams]}, 补渲 {1 / timestep:.0f} Hz")
        self._frame0_t = None     # 首帧 RGB 仿真时刻锚点,首个 step_boundary 时记录
        self.sim_kwargs = sim_kwargs
        self.bins = []          # 每个 bin: {cam_name: (pos[H,W], neg[H,W]) int32 GPU}
        self.raw = []           # 每个 bin: {cam_name: (N,4) float32 CPU (x,y,t,p)}
        self._new_bin()

    def _new_bin(self):
        self.bins.append({c.name: [None, None] for c in self.cams})
        self.raw.append({c.name: np.zeros((0, 4), np.float32) for c in self.cams})

    def tick(self):
        """每个物理节点调用一次(250Hz):补渲所有事件相机并累积事件到当前 bin。"""
        if not self.enabled:
            return
        self.sim_time += self.timestep
        bin_idx = len(self.bins) - 1
        for c in self.cams:
            ev = c.tick(self.sim_time)
            pos, neg = self.bins[bin_idx][c.name]
            if pos is None:
                pos = torch.zeros(c.height, c.width, dtype=torch.int32,
                                  device=self.device)
                neg = torch.zeros_like(pos)
            if ev is not None:
                xs, ys, ts, ps = ev
                pos = pos.index_put_(
                    (ys[ps], xs[ps]),
                    torch.ones(int(ps.sum()), dtype=torch.int32, device=self.device),
                    accumulate=True,
                )
                nps = ~ps
                neg = neg.index_put_(
                    (ys[nps], xs[nps]),
                    torch.ones(int(nps.sum()), dtype=torch.int32, device=self.device),
                    accumulate=True,
                )
                rec = torch.stack([xs.float(), ys.float(), ts,
                                   ps.float()], dim=1).cpu().numpy()
                self.raw[bin_idx][c.name] = np.concatenate(
                    [self.raw[bin_idx][c.name], rec], axis=0)
            self.bins[bin_idx][c.name] = [pos, neg]

    def step_boundary(self):
        """take_action 计数 +1 时调用:事件落入新 bin。"""
        if self.enabled:
            if self._frame0_t is None:
                self._frame0_t = self.sim_time  # 首帧 RGB 的仿真时刻(时间轴换算锚点)
            self._new_bin()

    def finalize(self, save_dir, ep_num, fps=30.0, frame_dt=None):
        """按 RGB 视频实际帧数取 bin,写黑底红蓝事件视频 + 原始事件 npz(含时间轴元数据)。"""
        if not self.enabled:
            return
        import cv2
        from envs.utils.images_to_video import images_to_video

        rgb_video = f"{save_dir}/video/episode{ep_num}.mp4"
        n_target = None
        if os.path.exists(rgb_video):
            cap = cv2.VideoCapture(rgb_video)
            n_target = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
        n = n_target if n_target else len(self.bins)

        total_ev = 0
        for c in self.cams:
            frames = np.zeros((n, c.height, c.width, 3), np.uint8)
            for j in range(min(n, len(self.bins))):
                pos, neg = self.bins[j][c.name]
                if pos is None:
                    continue
                p = pos.cpu().numpy() > 0
                ng = neg.cpu().numpy() > 0
                frames[j, p] = [255, 0, 0]              # 正事件红
                frames[j, ng] = [0, 0, 255]             # 负事件蓝
                frames[j, p & ng] = [255, 0, 255]       # 同帧同像素双极性→品红
            out = f"{save_dir}/video/episode{ep_num}_event_{c.name}.mp4"
            images_to_video(frames, out_path=out, fps=fps)
            ev_cnt = sum(len(r[c.name]) for r in self.raw)
            total_ev += ev_cnt
            raw = np.concatenate(
                [r[c.name] for r in self.raw if len(r[c.name])], axis=0
            ) if ev_cnt else np.zeros((0, 4), np.float32)
            meta = dict(
                camera=c.name,
                video_fps=float(fps),
                n_video_frames=int(n),
                sim_timestep=float(self.timestep),
                # 时间轴换算口径:npz 的 t 是仿真秒;每视频帧打包 frame_dt 秒仿真时间
                # (save_freq×物理步长,如 15×4ms=60ms);视频按 fps 播放(≠实时)。
                # 事件→视频帧: floor((t - sim_t_frame0) / sim_dt_per_frame)
                sim_dt_per_frame=float(frame_dt) if frame_dt else float("nan"),
                sim_t_frame0=(float(self._frame0_t)
                              if self._frame0_t is not None else float("nan")),
                **{f"cfg_{k}": float(v) for k, v in self.sim_kwargs.items()},
            )
            np.savez_compressed(
                f"{save_dir}/data/episode{ep_num}_event_{c.name}.npz",
                events=raw, **meta)
            print(f"[EventCamera] {c.name}: {ev_cnt} 事件, "
                  f"{len(self.bins)} bins → {n} 帧 @ {fps:.0f}fps")
        print(f"[EventCamera] episode{ep_num} 共 {total_ev} 事件")
