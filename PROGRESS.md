# DOMINO 部署 PROGRESS.md

## 2026-10-18

### 部署前环境体检(只读)

- GPU:**RTX 2080 Ti 22.5GB**(`nvidia-smi`;项目说明原文写"RTX 2080 16GB",与实际不符,待回改说明文档)
- 驱动 550.107.02 / CUDA 12.4;Ubuntu 22.04;磁盘余 137G;内存 31G
- Python 3.10 在 `/usr/bin/python3.10`,anaconda3 可用;git/curl/wget 齐

### 第 1 步:图形栈验证 —— 通过

- `nvidia-smi` ✅ 认卡
- `sudo apt install vulkan-tools` 后 `vulkaninfo --summary`:
  - **GPU0 = NVIDIA GeForce RTX 2080 Ti**(Vulkan 1.3.277,NVIDIA proprietary driver 550.107.02)✅ 图形栈通
  - GPU1 = llvmpipe(CPU)—— 与 NVIDIA 并存是常态,判据"只见到 llvmpipe"不成立
  - 启动警告 `Failed to CreateInstance in ICD 0. Skipping ICD`:某个无关 ICD(机器无 Intel 核显)初始化失败被跳过,不影响 NVIDIA 枚举,忽略
- `DISPLAY` 未设置(无头 VM),Vulkan 离屏渲染不依赖显示服务
- 2080 Ti 为 Turing 架构带 RT core,满足 DOMINO 硬编码光追(VK_KHR_ray_tracing_pipeline)的硬件前提

### 第 2 步:依赖安装(后台进行中)

- 方案按文档踩坑记录:照 `_install.sh` 流程,但 **pytorch3d 跳过**(仅 pointcloud 用)、**curobo 用 PyPI `nvidia-curobo`**(不源码编译)、手动补 `toppra`/`opencv-python`/`pyyaml`
- 观察 1:`azure==4.0.0` 是元包,会拉 ~60 个 `azure-mgmt-*` 子包(都纯 Python,体积小),正常现象
- 观察 2:pip 对 torchvision 发生 backtracking(torch 2.4.1 只兼容 torchvision 0.19.x),pip 自行回退解析,无需干预
- 观察 3:`opencv-python` 实际也是 sapien 3.0.0b1 的依赖,即使 requirements 不写也会被装上
- 进行方式:后台 pip(task bash-fri5cvjy),完成后对 sapien `urdf_loader.py`、mplib `planner.py` 打 `_install.sh` 里的两个 sed 补丁

### 第 3 步:资产方案核实与下载(✅ 完成)

- HF 直连超时+镜像 429(文档记录),不硬磕,改 ModelScope
- 经 ModelScope API 核实,数据集结构与 DOMINO 代码期望**完全吻合**:
  - `byml2024/RoboTwin2.0_Objects/050_bell/` = `visual/base{0,1}.glb` + `collision/` + `model_data{0,1}.json` + `points_info.json` ← 正是 `create_actor()` 的加载布局
  - `zanxinchen/embodiments/aloha-agilex/` = `urdf/ meshes/ srdf/` + `config.yml` + `curobo_{left,right}_tmp.yml` ← `_tmp.yml` 供 `update_embodiment_config_path.py` 生成绝对路径配置
- `modelscope` CLI 装在 **base 环境**(不污染 domino 环境);下载结果:
  - 050_bell:7 文件 → `DOMINO/assets/objects/`(共 14M)✅
  - aloha-agilex:82 文件 → `DOMINO/assets/embodiments/`(共 745M)✅
- ModelScope 速度实测:objects 8 秒、embodiments 66 秒,网络通畅
- 11GB `background_texture.zip` 按文档不下载(demo_clean_dynamic 用不到)

### 第 4 步:依赖安装完成 + 补丁(✅ 完成)

- pip 三阶段全部成功:`REQUIREMENTS_EXIT=0` / `MISSING_PKGS_EXIT=0` / `CUROBO_EXIT=0`(nvidia-curobo-0.1)
- 关键版本:torch 2.4.1+cu121、torchvision 0.19.1、sapien 3.0.0b1、mplib 0.2.1、toppra 0.6.10、opencv-python 4.11.0.86、numpy 1.26.4
- **坑#1(新踩)**:sapien 3.0.0b1 的 `__init__.py` 依赖 `pkg_resources`,而 conda 默认装的 setuptools 84 已移除该模块 → 降级 `setuptools==69.5.1` 解决
- **坑#2(新踩)**:conda 创建的 env 默认不带 setuptools/ pip 环境变量问题?否——就是 setuptools 84 的坑,见上
- 两个 sed 补丁已照 `_install.sh` 打上并验证:sapien `urdf_loader.py` 667/673 行加 `encoding="utf-8"` ✅;mplib `planner.py` 807 行去掉 `or collide` ✅

### 第 5 步:渲染自检 test_render.py(✅ 通过)

- `python script/test_render.py` → 绿色 **Render Well**,exit 0
- RT 渲染配置(rt shader + 32spp + path_depth 8 + OIDN)在 2080 Ti 上初始化成功
- 仅两条 DeprecationWarning(Engine/SapienRenderer),无害

### 第 6 步:click_bell demo 端到端(进行中)

- demo_clean_dynamic.yml 的 `episode_num=50` 对部署验证太大,新建 `task_config/deploy_check.yml`(仅改 episode_num=2、language_num=2,其余与原配置一致,不动任务逻辑)
- 用包装脚本 `../deploy_check.py` 跑 `collect_data.main(click_bell, deploy_check)`:monkeypatch 计时 `scene.update_render()` 与 `Camera.update_picture()`,产出实测渲染帧率
- 备注:collect_data 结尾的 `gen_episode_instructions.sh` 需要 OpenAI key,本机没有,预期失败但 `os.system` 不阻断 demo,失败将记入本文档

### 第 6 步踩坑记录(demo 启动阶段)

- **坑#3**:`import envs` 时 `rand_create_cluttered_actor.py` 在模块级硬读 `assets/objects/objaverse/list.json`(即使配置 `cluttered_table: false`)→ ModelScope 单独下载补齐(22KB,27 类)
- **坑#4**:同上函数还硬读 `assets/objects/same.json`,而**该文件在 ModelScope 数据集里不存在**(根目录只有 .gitattributes/.gitignore;HF 侧它封在 objects.zip 内部,无法单拉)→ 判定为 ModelScope 移植遗漏
  - 用途分析:`same_obj` 仅被 `get_available_cluttered_table()` 用作"排除与任务物体相似的杂物";`get_cluttered_table()` 开头有 `clean_background_rate` 早退,且只在 cluttered_table 开启时走 → 对 demo_clean_dynamic/deploy_check 配置,stub `{}` 功能安全
  - **处置**:写入 stub `same.json = {}`;若日后要跑 `cluttered_table: true`,需从 HF objects.zip 取回真实文件替换
- 另注:ModelScope `repo/tree?Recursive=true` 有 100 条分页上限,排查看根目录要用非递归调用

#### 坑#5:PyPI 的 nvidia-curobo 是假包(文档路线失效)

- 现象:demo 启动 `import curobo` 失败;核查 PyPI:`nvidia-curobo` 全仓库仅 0.1 一个版本,元数据 "A simple python package",零模块;`curobo` 名字同样是 0.1/0.2 空壳假包(935 字节)→ **"用 PyPI 的 nvidia-curobo" 已事实失效**(疑似真包下架后名字被抢注)
- 处置:回退官方 `_install.sh` 路线,源码安装 NVlabs/curobo
- 版本定点:**v0.7.8**——v0.8.0 起 cu12 extra 要求 `torch>=2.5`,与 DOMINO 钉死的 torch 2.4.1 冲突;v0.7.8 无此限制(DOMINO 同期版本)
- 安装方式:`git clone --depth 1 --branch v0.7.8` 到 `DOMINO/envs/curobo`(照官方脚本布局)+ `pip install -e . --no-build-isolation`;浅克隆配 `SETUPTOOLS_SCM_PRETEND_VERSION=0.7.8` 绕开 setuptools_scm 对 git describe 的依赖
- 结果(✅):源码构建出的发行版名字正是 `nvidia_curobo-0.7.8`——说明真包本名就是 nvidia-curobo,文档作者当时装的 PyPI 真包现已不在,名字被 0.1 假包占据;安装自动卸掉了假包,`import curobo` 通过
- 依赖新增:yourdfpy、warp-lang、numpy-quaternion、pybind11、embreex、vhacdx、xatlas、scikit-image 等(纯 wheel,无编译)
- 网络备注:GitHub 对该机时快时慢,`git ls-remote` 曾 HTTP2 framing 错误/135 秒;`api.github.com` 与 `raw.githubusercontent.com` 较快,查 tag/读文件优先走 API

#### 坑#6:warp-lang 1.18 内置 CUDA 13,驱动 12.4 不满足 → cuRobo 失 GPU(关键坑)

- 现象:demo 跑起来后所有 seed 失败;日志头两行关键信息:
  - `Warp 1.18.0 initialized: CUDA Toolkit 13.4, Driver 12.4 (insufficient CUDA driver version!)`,设备只剩 CPU
  - seed 0 报 `list index out of range`(cuRobo 无 CUDA 设备的下游症状),之后全部 seed 报 `'Robot' object has no attribute 'left_planner'`
- 根因:cuRobo v0.7.8 对 warp-lang 无版本钉死,pip 拉了最新 1.18.0;其内置 CUDA 13.4 要求驱动 ≥13.x,本机 550.107.02(CUDA 12.4)不满足 → warp 只暴露 CPU → cuRobo 规划器初始化失败
- 级联 bug(记档不修):`Robot.set_planner()` 在 `communication_flag=False` 分支里 CuroboPlanner 初始化抛异常后,`left_planner` 属性永远缺失;`collect_data.run()` 的 seed 循环**无尝试上限**,后续每个 seed 都在 `robot.reset()` 的 `isinstance(self.left_planner, ...)` 处 AttributeError,无限烧 seed(本次烧到 442 被手动停)
- **修复**:`pip install "warp-lang==1.6.0"`(与 cuRobo v0.7.8 同时代,内置 CUDA 12.8)→ `wp.init()` 正常列出 `cuda:0 (RTX 2080 Ti, sm_75)` ✅;**未动系统驱动**(升级驱动到 580+ 是更大动作,能避则避)
- 调试辅助:`collect_data.py` 两处 except 的 `traceback.print_exc()` 被官方注释,已临时打开(纯打印,不改逻辑,事后可回退)

### 第 6 步完成:click_bell demo 端到端跑通(✅ 验收达成,2026-10-18 10:32)

- 第 4 次启动全流程成功(约 7 分钟):seed 规划(cuRobo)→ RT 渲染 → HDF5+MP4 落盘
- 产出 `DOMINO/data/click_bell/deploy_check/`:episode0(88 帧)/episode1(78 帧)HDF5
  (head/front/left/right 四路 RGB + endpose + qpos)+ 视频 320×240@30fps
- 验收① 画面目验正确:铃模型/夹爪/桌面/RT 软阴影正常(抽帧 `/tmp/ep0_f44.png`、`/tmp/ep1_f39.png`)
- 验收② 实测帧率(原配置 rt+32spp+path_depth8+OIDN,RTX 2080 Ti):
  - **渲染本体 `camera.update_picture`:1069 次,均 265.2ms → 3.77 FPS**
  - `scene.update_render`:2999 次,均 0.1ms(仅姿态同步;真实渲染在抓图时惰性发生,勿当帧率)
- 验收③ 即本文档
- 插曲:seed 7 曾在视频合成步失败(系统缺 ffmpeg)→ `apt install ffmpeg 4.4.2` 后管线自愈
- 遗留:结尾 description 生成需 OpenAI key(失败不影响数据);adjust_bottle/全量 50 幕未跑
- 新增文件:`task_config/deploy_check.yml`、`../deploy_check.py`(FPS 计时包装,可复用)

### 渲染降载优化(2026-10-18,用户决策启动)

- **基线(已测)**:rt + 32spp + path_depth 8 + OIDN,4 路相机 → **3.77 FPS**
- **已改**(只动渲染配置,不动任务逻辑):`_base_task.py:236-239` 与 `test_render.py:70-73` 同步
  `32spp→4spp`、`path_depth 8→4`,保留 OIDN;改后 FPS 待复测
- 相机路数现状(每帧 4 路,全 D435 320×240):
  - head_camera:embodiment `static_camera_list` 静态顶后俯视 → demo 视频主视角
  - front_camera:同上,静态前视(补充第三视角;task config 的 `third_view: false` 与它独立)
  - left/right_camera:腕部相机,`camera:` 段 `collect_wrist_camera` 开关控制
- 代码安全确认:`camera.py:291` 的 `update_wrist_camera` 有 `collect_wrist_camera` 守卫;
  `_base_task.py:791` 传入的 `robot.left/right_camera` 是机械臂物理 link(恒存在)→ config 关腕部相机不会崩
- **相机决策(用户拍板):4 路全保留**——保留 benchmark 原生数据格式,只享 spp 降载收益;
  32spp 基线产物已改名存档 `data/click_bell/deploy_check_spp32_baseline/`
- **复测结果(✅)**:rt + 4spp + depth4 + OIDN,4 路相机 → **11.45 FPS**(87.4ms/帧),
  较基线 3.77 FPS 提升 **3.03×**;2 幕端到端 80 秒(基线 428 秒)
- 画质目验:spp=4 抽帧无可见噪点(OIDN 兜住),铃/夹爪/软阴影正常,320×240 下与 32spp 观感一致
- 备注:提升低于 spp 线性预期(32→4 理论 ~8×)——OIDN 与每帧固定开销(4 相机渲染列构建+显存读回)
  不随 spp 缩减;再提速需动相机路数或分辨率(用户已决策暂不动)

### 光栅化单路测速(2026-10-18,目标修正:事件管线只挂 1–2 路,判定线单路 ≥100fps)

- **目标修正(用户拍板)**:100Hz 是单路事件锚点判据,非 4 路;4 路同冲 100 不需要
- 改动:`_base_task.py:236-246` 渲染模式改为 `DOMINO_SHADER_DIR` 环境变量切换
  (default/minimal/trivial=光栅,rt=光追+可配 DOMINO_RTD_SPP/DEPTH);相机/数据格式不动
- 新增 `../bench_single_cam.py`:click_bell 真实场景(need_plan=False 跳过规划),
  head_camera 320×240,预热 20 + 采样 300,分计 take_picture / get_picture(CPU) / get_picture_cuda(GPU)
- **单路结果(RTX 2080 Ti)**:

  | shader_dir | 渲染 take_picture | CPU 读回 | GPU 取图 | 渲染+CPU读回 |
  |---|---|---|---|---|
  | default    | 12.20ms (82fps) | 15.79ms | 0.46ms | 28.0ms (35.7fps) |
  | minimal    | 12.17ms (82fps) | 15.92ms | 0.53ms | 28.1ms (35.6fps) |
  | **trivial** | **1.05ms (952fps)** | **2.52ms** | **0.45ms** | **3.57ms (280fps)** |

- **判定: trivial 档单路 ≥100fps 达标**(渲染本体 952fps;含 CPU 读回 280fps,含 GPU 取图 ~660fps)
- default≈minimal 说明 12ms 瓶颈不在阴影/通道数量,而是 default 管线固定开销(每路全材质 gbuffer+composite)
- trivial 画质:几何/光照/纹理基本正确(抽帧 `/tmp/trivial_head.png`), bell 材质偏暗——光栅共性,
  与 rt 软阴影画风有差异;事件锚点用(差分/边缘)通常不敏感,正式取舍由用户定
- 附带发现:`get_picture_cuda`(GPU 直接出 torch tensor,免 CPU 往返)只要 ~0.5ms,
  事件管线若下游在 GPU,首选此路径;DOMINO 原代码已用该 API(camera.py:456)
- 遗留:4 路 trivial 同开未测(事件管线只挂 1-2 路,暂不需要);光栅 vs rt 数据分布差异未评估
- trivial 4 路 demo 视频已出:`data/click_bell/deploy_check/video/episode{0,1}.mp4`
  (原 default 版改名 `deploy_check_raster_default/`);抽帧 `/tmp/trivial_ep0_f40.png` 目验:
  几何/位姿正确,材质扁平、臂体发黑、无软阴影(光栅共性);事件锚点(差分/边缘)可用性由用户评估
- 备注:4 路 trivial update_picture 39.8ms(25.15fps)≈ default 44.9ms——4 路全开时瓶颈已转移到
  管线其它环节(物理步进/纹理转换/落盘),单路 1ms 的优势被稀释;事件管线按 1-2 路挂载不受影响

### 优化1:RGB 采集改 GPU 取图(2026-10-18,用户拍板走 default 光栅)

- 改动:`envs/camera/camera.py` `_get_rgba`:CPU `get_picture` → `get_picture_cuda("Color").torch()`
  在 GPU 上完成 `*255/clamp/uint8`,最后 `.cpu().numpy()`;输出与旧路径逐位一致(最大差 0)
- 采集主链路确认走该函数:`get_rgb()` 包装 `get_rgba()`,`_base_task.py:816/871` 调用
- 单元微基准:4 路 get_rgba 63ms → 4.67ms;端到端 2 幕墙钟 83.8s → 80.4s(提升小于微基准,
  因管线内 CPU 读回与 GPU 渲染本就部分重叠,15.8ms 单路读回含同步等待成分)
- 遗留:default 光栅渲染本体 12.2ms/路 ×4=44ms 仍是瓶颈;`get_observer_rgb` 仍走 CPU 路径(非主链路)

### 优化3:关点光阴影(方案A,2026-10-18)——default 渲染瓶颈定位 ✅

- 场景灯光结构(_base_task.py:262-283,默认):ambient + 1 方向光(阴影=1 pass) + 2 点光(阴影=cubemap 6 pass/盏)
- 新增开关:`DOMINO_POINT_SHADOW=0`(关点光阴影)、`DOMINO_DIR_SHADOW=0`(关方向光阴影),默认行为不变
- **bench(default 单路 head_camera 320×240)**:
  - 全阴影(基线):12.20ms (82fps)
  - **方案A(关点光阴影,保方向光):2.14ms (468fps)** —— 阴影占 10ms/12.2ms ≈ 83%,其中点光 cubemap 是绝对大头
  - 方案A + CPU 读回:6.26ms (160fps);+ GPU 取图:2.6ms (~385fps) —— 三种口径全部 ≥100fps
- 画质抽帧 `/tmp/planA_head.png`:方向光地面接触阴影保留(铃下软阴影在),点光阴影消失
- 结论:default 的 12ms"固定开销"实为点光 cubemap 阴影;优化5(材质上限)优先级骤降,暂未测
- **固化(2026-10-18 晚)**:点光不投阴影已写为代码默认(`_base_task.py`,DOMINO_POINT_SHADOW=1 可回退旧行为);
  rt 光追路径不受影响(rt 配置独立于光栅灯光逻辑)

### 画质实验:MSAA / SSAA / 补光灯(2026-10-18 晚,用户要求"画质再优化")

- **MSAA(排除)**:`sapien.render.set_msaa(4/8)` API 接受且几乎零耗时(2.61/2.72ms),
  但出图与基线**字节级相同**(md5 一致)——对 default 光栅管线是无操作,仅特定管线生效
- **SSAA(暂缓)**:640×480 渲染耗时与 320×240 相同(2.64ms,4 倍像素零成本),技术成立;
  但 320×240 下边缘锯齿非痛点,接入需改相机分辨率配置+取图降采样(动 HDF5 链路),收益存疑搁置
- **补光灯(否决,已默认关闭)**:加 2 盏不投影点光(前主光 0.7@ [0,-0.8,1.5] + 顶后 0.4@[0.5,0.3,1.2]),
  静态与视频双层验证:场景过曝、方向光接触阴影被冲淡、**臂体仍黑**;
  结论:臂体/铃发黑是光栅管线对部分 PBR 材质的渲染差异(金属度工作流无环境贴图),光照角度救不了
  ——`DOMINO_FILL_LIGHT=1` 可再开(默认 0),实验视频存 `deploy_check_fill_rejected/`
- 最终画质基线 = 方案A(点光无阴影,方向光接触阴影保留)+ GPU 取图;臂体偏暗为已知限制

### SSAA 抗锯齿接入(2026-10-18,用户定为画质优先项)

- MSAA 已被实验排除(set_msaa 对 default 管线是 no-op,出图字节级相同);补光灯否决(过曝、救不了材质发黑)
- **实现**(envs/camera/camera.py,`DOMINO_SSAA` 环境变量,默认 2,设 1 关闭):
  - 相机按 ssaa 倍分辨率创建(static + wrist 全生效);fov/near/far 不变
  - `_get_rgba`:GPU 上 `avg_pool2d` box filter 降采样(= SSAA resolve)再 uint8 化
  - `get_config` 内参 fx/fy/cx/cy 同步 ÷ssaa,与降采样后图像严格一致(实测 SSAA=2/1 的 K 完全相同)
  - depth/segmentation 取图走 INTER_NEAREST 降采样(保几何/标签有效)
- **验证**:native 640×480 → 输出 (240,320,4);K fx=358.6/cx=160 与原生一致;
  4 路 get_rgba 4.62ms(比关闭时 +0.8ms);抽帧对比边缘平滑(dome 轮廓/阴影渐变)
- 数据格式不变(HDF5 仍是 320×240),benchmark 格式兼容性保住
- **端到端回归(✅)**:`data/click_bell/deploy_check/` HDF5 结构与原格式逐 key 一致,
  rgb 解码 (240,320,3),存储 K fx=358.64/cx=160(320×240 口径);视频抽帧边缘平滑、接触阴影在
- 最终渲染配置定格:**光栅 default + 方案A(点光无阴影) + GPU 取图 + SSAA×2**
  (DOMINO_SSAA=1 / DOMINO_POINT_SHADOW=1 / DOMINO_FILL_LIGHT=1 / DOMINO_SHADER_DIR=rt 均可回退)
- 遗留观察:4 路 update_picture 在"机械臂运动"的采集场景 ~40ms(静态场景 9ms),
  单路 2.6ms 的优势被运动场景稀释,疑似腕部相机近距几何/每帧阴影重刷;事件管线(1-2路)不受影响,全量采集若要再提速可单列排查

## 状态快照(2026-10-18 收尾扫)

- 最终优化版视频(光栅 default + 方案A + GPU取图 + SSAA×2):
  `data/click_bell/deploy_check/video/episode{0,1}.mp4`(78+77 帧,320×240)+ 同目录 `data/*.hdf5`
- 产物归档(`data/click_bell/` 下 8 个目录):
  deploy_check=最终版 | planA_final=SSAA前定稿 | fullshadow_gpufetch=全阴影+GPU取图 |
  raster_default=光栅全阴影+CPU取图 | raster_trivial=trivial 档 | fill_rejected=补光否决版 |
  rt_spp4 / spp32_baseline=光追两档基线
- 生效默认:SHADER_DIR=default / 点光无阴影 / 补光关 / SSAA=2(均可环境变量回退)
- 新增工具(项目根):deploy_check.py(FPS 计时)、bench_single_cam.py(单路微基准)、quality_ab.py(画质 A/B)
- **rt 光追路线回退(用户裁定,2026-10-18)**:4spp+depth4 降载版 OIDN 时域不稳→画面闪烁,
  rt 模式恢复 benchmark 原版 32spp+depth8+OIDN(`_base_task.py` 默认值与 `test_render.py` 同步回退,
  仍可用 DOMINO_RTD_SPP/DEPTH 覆盖);默认渲染路线(光栅)不受影响

## ESIM 参考准备(2026-10-18,✅ 完成)

- 任务:读 ESIM 论文 + clone rpg_esim 代码做参考(不配环境、不直接用代码)
- 论文:Rebecq/Gehrig/Scaramuzza, "ESIM: an Open Event Camera Simulator", CoRL 2018,
  PMLR v87 p969-982, http://proceedings.mlr.press/v87/rebecq18a.html (全文已读)
- 仓库:git clone --depth 1 --recursive https://github.com/uzh-rpg/rpg_esim.git
  → /home/linux/event_simulator/rpg_esim
- 论文要点(供事件管线设计参考):
  1. 事件模型:亮度=log 辐照度 L=log E;像素亮度相对上次事件位置变化超过阈值 C+/C- 时触发正/负事件
  2. 自适应采样:按最大光流/最大亮度变化率决定下一帧渲染时刻(λ=0.5),论文实测比固定采样省 60% 渲染
  3. 噪声模型:阈值按 N(C, σC) 逐帧抖动;支持 C+≠C-
  4. 像素位移法(λv)实测精度/效率比亮度变化法(λb)更好
  5. OpenGL 光栅渲染引擎 ~1ms/帧(笔记本),UE5 引擎画质高但慢(1 秒数据约 2 分钟)
- **落地**:GitHub 直连 git clone 停滞(5min 只收 128K),codeload tarball 直连却很稳
  (66MB/5.8s)→ 改 `curl -L https://codeload.github.com/uzh-rpg/rpg_esim/tar.gz/refs/heads/master`
  解压,commit `4cf0b89`,无 .git 历史(纯参考,够用)
- **代码核心文件**(全部已读,均在 event_camera_simulator/ 下):
  - 事件生成算法 119 行:`esim/src/event_simulator.cpp` —— log 亮度(log_eps=0.001)→
    每像素对比"上次帧 vs 本次帧",跨越 ref 每 C 一步线性插值出事件时刻;
    C+/C- 可不同;σ 抖动(N(0,σ) 每事件采样,钳 ≥0.01);refractory 逐像素;
    事件按 t 排序;ref_values_ 记录每像素上次跨越电平
  - 自适应采样:`esim_data_provider/src/data_provider_online_simple.cpp:90-106`
    —— delta_t = λ/max|dL/dt| 或 λ/max‖optic flow‖,λ 默认 0.5
  - 默认参数(esim_node.cpp):Cp=Cm=1.0,σ=0.021,refractory=0,log_eps=0.001;
    示例 cfg 按场景用 0.1~0.6
  - 渲染引擎可换:imp_opengl_renderer(光栅 ~1ms/帧)/ unrealcv / planar / multi_objects_2d

## ESIM 事件相机部署(2026-10-18,✅ 首版交付)

- **方案落地**:固定子采样率 250Hz(每物理节点补渲一帧,SSAA×2 保留——事件边缘质量依赖抗混叠,
  用户裁定);帧间事件时刻线性插值;λ_eff 随速度浮动(策略讨论见上节)
- **代码**:
  - `DOMINO/envs/event_camera.py`(新):EventSimulator = rpg_esim event_simulator.cpp 的
    PyTorch 向量化移植(119 行逐行对应:log 亮度/多档跨越/每事件阈值抖动 N(0,σ) 钳 0.01/
    refractory/ref 电平推进);EventCamera(SSAA resolve→luma→log);EventCameraManager
    (bin 与 RGB 帧一一对应 + 黑底红蓝视频 + npz 原始事件流)
  - `DOMINO/envs/_base_task.py` 4 处挂载:__init__ 置 None;_init_task_env_ 末尾建管理器
    (每幕重建);take_action/take_dense_action 控制循环 scene.step 后 tick(250Hz);
    _take_picture 开头 step_boundary(bin 轮转与 FRAME_IDX 严格同步);
    merge_pkl_to_hdf5_video 里 finalize
  - 配置全环境变量:DOMINO_EVENT_CAMERAS(空=关)/_C=0.3/_SIGMA=0.02/_REFRACTORY_NS=0/_LOG_EPS=0.001
- **单元自测**(`~/event_simulator/test_event_simulator.py`,6 项全过):静态无事件/线性斜坡
  ±极性双事件+时间戳解析解/refractory 截断/C+≠C- 分效/单帧多档跨越时间戳
- **首跑**(event_check.py,click_bell 两幕):
  - 帧数严格对齐:ep0 76=76,ep1 77=77 @30fps;事件量 ep0 506,323 / ep1 73,058(动态拦截段差异)
  - 产物:`data/click_bell/event_check/video/episode{K}_event_left_camera.mp4` +
    `data/episode{K}_event_left_camera.npz`(原始 x,y,t,p 流)
  - 事件帧验证:铃沿弧线红蓝双极性分布,教科书级 DVS 边缘特征 ✅
- **观测/遗留**:
  1. tick 均值 10.83ms(92 FPS 墙钟)≫ 静态微基准 2.6ms——运动场景渲染变慢的已知问题在
     单路+事件管线复现(此前 4 路 40ms 谜题同族);仿真时率仍 250Hz,离线生成无碍,
     但"单路 ≥100fps"判据未达标,待 V_max 实测时一并剖析(渲染 vs 事件模拟占比)
  2. bin0 含动态拦截段事件(execute_dynamic_workflow 的 take_action 路径在首帧
     _take_picture 前已 tick)——语义合理(到达 frame0 状态前的运动),保留
  3. 事件视频是腕部视角,RGB 视频是头部视角(用户要求对齐的是时长/帧率);
     多路事件相机改 DOMINO_EVENT_CAMERAS=left_camera,head_camera 即可
- **双路对照版(2026-10-18,✅)**:DOMINO_EVENT_CAMERAS="left_camera,head_camera" 重跑 ep0
  - 产物齐:`video/episode0{,_left_camera,_event_left_camera,_event_head_camera}.mp4`
    (pkl2hdf5.py 改为逐相机出 RGB 视频,right/front 腕/侧视也顺带产出)+ 两路事件 npz
  - 全部 76 帧 @30fps 严格对齐;事件量:left 510,528 / head 598,345(静态头相机反而更多——
    全场景运动尽收)
  - tick 13.27ms(75 FPS 墙钟);对比单路 10.83ms → 第二路相机边际成本仅 ~2.4ms,
    固定成本 ~8.4ms/节点(疑似 scene.update_render 全场景 pass,剖析待办时验证)
- **时间轴平滑性验证(2026-10-18,✅)**:event_timeline_viz.py(光栅/4ms率/峰值放大/相位四联图)
  - head:598,345 事件,活跃段 5.14s,均值 11.6万/s,峰值 3441/4ms;相位 max/min=2.08(无 0 点堆积,
    亚帧插值成立);60ms 边界占比 0.62% < 均匀期望 1.67%(无帧锁定)
  - left:510,528 事件,活跃段 4.99s,相位 max/min=3.45;静默段=move 段间停顿(88/128ms)
  - 结论:事件流连续无帧化 ✅;注:npz 时间戳为仿真秒,视频按 benchmark 惯例 30fps 播放
    (每帧打包 60ms 仿真时间,RGB 视频历来如此)
- **时间轴元数据(2026-10-18 补)**:npz 现带 sim_dt_per_frame(=save_freq×步长,本幕 60ms)/
  sim_t_frame0(首帧锚点,新跑自动记录)/sim_timestep/video_fps/save_freq/cfg_*;
  event_camera.py finalize 加 frame_dt 参数,_base_task 传入;存量两枚 npz 已补丁
  (sim_t_frame0=nan,因当时未采集);报告 md 已补 60ms 推导与 1.8× 播放说明
- **演示套装(2026-10-18)**:2x2 对照视频 `video/episode0_grid2x2.mp4`(左列 RGB 头/腕,
  右列事件头/腕,640×480@30fps,ffmpeg xstack+角标);整目录打包
  `~/event_simulator/event_check_ep0.tar.gz`(8.8MB,含全部视频/npz/验证图/报告/traj)
- **取文件踩坑(2026-10-18,用户实踩)**:Windows 端 OpenSSH scp 默认走 SFTP 协议,
  `~` 不展开 → 必须给绝对路径 `/home/linux/event_simulator/...`;且曾把 tar 包路径
  误写成 `~/event_check_ep0.tar.gz`(漏 event_simulator 段)。正解:
  `scp -P 24194 linux@175.155.64.171:/home/linux/event_simulator/event_check_ep0.tar.gz .`
- **工作树快照(2026-10-18)**:DOMINO 仓库改动均未提交——新增 envs/event_camera.py;
  修改 envs/_base_task.py(方案A默认+SSAA钩子+事件挂载)、envs/camera/camera.py(SSAA)、
  envs/utils/pkl2hdf5.py(逐相机视频)、script/collect_data.py(仅 +2 行 traceback,部署期排障);
  项目根工具:deploy_check/bench_single_cam/quality_ab/event_check/event_timeline_viz/
  test_event_simulator.py
- **环境打包(2026-10-18 收官,✅)**:env/ 目录=environment_domino_full.yml(curobo 行已注释)/
  environment_domino.yml(核心锚点)/环境重建指南.md(7 节:锚点表/系统前提/安装/cuRobo/资产/
  验证链/坑速查)/patch_bundle/(DOMINO_local.patch 268 行 + 事件相机等新文件,异地重建事件管线用);
  总包 ~/event_simulator/env_domino_docs.tar.gz。关键事实:官方仓库 H-EmbodVis/DOMINO
  (本地 commit 9c94f2d + 未提交改动);cuRobo=nvidia_curobo 0.7.8 editable 源码装于
  DOMINO/envs/curobo(PyPI 无);warp-lang 1.6.0 钉死;实测 scipy 1.15.3≠requirements 的 1.10.1
