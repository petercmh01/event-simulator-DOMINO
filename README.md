# event_simulator — DOMINO 事件相机仿真项目

在 [DOMINO](https://github.com/H-EmbodVis/DOMINO)(ECCV 2026 动态操作 benchmark)上
扩展**事件相机模态**:250Hz 补渲 + ESIM 事件仿真 + 黑底红蓝事件视频。
本仓库为工作存档,包含全部代码、关键数据与完整过程记录。

## 目录结构

```
DOMINO/                  DOMINO 源码(fork,含本地改动,见下)
  envs/event_camera.py   ESIM 事件模拟器(PyTorch 向量化移植)+ 250Hz 补渲管理器 ★
  data/click_bell/       关键数据:事件检查演示套装 + 渲染优化历史归档
env/                     环境重建资料(重要!)
  环境重建指南.md          异地重建全流程:版本锚点/安装/cuRobo/资产/验证链/坑速查
  environment_domino_full.yml / environment_domino.yml
  patch_bundle/          本地改动补丁与新文件(等价于本仓库 DOMINO/ 目录内容)
PROGRESS.md              项目全程记录:部署→渲染优化(3.77fps→22fps+SSAA)→事件管线
项目说明.md               最初的任务书
test_event_simulator.py  事件模拟器单元自测(6 项)
event_check.py           事件管线采集驱动(click_bell 双路)
event_timeline_viz.py    事件流时间轴平滑性验证(光栅/事件率/相位四联图)
deploy_check.py / bench_single_cam.py / quality_ab.py   渲染优化期工具
```

## 溯源与改动

- **上游**:H-EmbodVis/DOMINO @ `9c94f2d`([docs] add Ascend NPU training guide),
  以纯文件方式并入(未保留上游 .git;assets 素材包与 envs/curobo 按 .gitignore 排除,
  重建方法见 env/环境重建指南.md)。
- **本地改动**(相对上游,2026-10-16 ~ 10-18):
  渲染优化(光栅 default 档 / 方案A 点光无阴影 / GPU 取图 / SSAA×2,均有环境变量回退)
  + 事件相机管线(`envs/event_camera.py`、`_base_task.py` 四处挂载、
  `pkl2hdf5.py` 逐相机视频、`task_config/event_check.yml`)。
  完整清单见 PROGRESS.md「工作树快照」。

## 快速验证(在新机器上)

```bash
conda env create -f env/environment_domino_full.yml   # 或按 env/环境重建指南.md
conda activate domino
python test_event_simulator.py        # 事件模拟器单元自测(~5s)
cd DOMINO && DOMINO_EVENT_CAMERAS="left_camera,head_camera" python ../event_check.py
```

## 数据说明

`DOMINO/data/click_bell/` 下:`event_check/` = 双路事件演示全套
(4 RGB + 2 事件视频 + npz 事件流 + 验证报告,帧级 76=76@30fps 对齐);
其余 9 个 `deploy_check_*` 目录 = 渲染优化阶段对照归档;
时间轴换算口径(1 视频帧 = 60ms 仿真)见 event_check/event_stream_verification.md。
