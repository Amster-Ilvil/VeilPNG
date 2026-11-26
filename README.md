# VeilPNG v0.6.3 — 可核验工作台

> **与 VeilPNG 的 AES 加密功能完全独立。** 幻影坦克本质是标准 RGBA 透明 PNG，通过切换白色/黑色背景显示两种图像。它**不是加密、不是访问控制，也不能防止他人提取另一张图**；PNG 转 JPG 或压平后效果会消失。

## v0.6.3 · 防止并发覆盖 / 独立导出核验

- GUI 与 CLI 保存使用项目清单 SHA-256 作为修订标识；加载后的旧版本不得覆盖新的选区。项目写入使用协作式独占锁，进程异常终止可能留下 `.workspace-write.lock`，确认无写入进程后方可手动清理。直接调用底层保存 API 时须传 `expected_revision` 才会检查旧版本冲突。
- 新增 `workspace-verify`，从已确认的项目蒙版重新计算普通遮盖图的预期像素，在内存中比较实际导出文件、文件名单及报告哈希。区分 `EXACT`、`PIXELS_MATCH`、`PIXELS_DIFFER`、`INVALID_OR_MISSING`。不修改输入或输出。核验失败退出码为 2。
- GUI 文件菜单新增“核验已有导出”，保存时跟踪当前项目的修订标识。另存必须选择新/空目录。GUI 改动仅编译检查，未进行实际 Qt 窗口验收。
- 加强保存的矩阵、活动页、便携项目路径与清单符号链接校验。未改变 workspace v2 格式，未改动旧加密或中文移植算法。

```bash
python -m veilpng workspace-verify --project-dir ./portable_project --export-dir ./exports/VeilPNG_xxxxx
```

指定 `--page index:2` 或 `--color '#FFFFFF'` 时必须与当初导出范围、颜色相同。`pixels_match` 只代表解码像素相同；`passed` 还要求报告匹配、没有额外文件。此核验不是内容识别或语义审核。

## v0.6.2 · 可迁移项目 / CLI 回放

- 统一工作台保存每页已提交的蒙版状态（含中日双方映射后的蒙版）；记录操作类型和侧别，按内容哈希去重。不是鼠标坐标录像，也不是全局操作时间线。
- 工作台项目 `workspace.json` v2 采用原图 SHA-256、蒙版 SHA-256 与原子清单写入；兼容 v0.6.1 v1 清单。旧项目没有历史时以最后状态为基线。原图变更、蒙版损坏、目录穿越和非项目目录覆盖均拒绝。
- `文件 → 另存便携项目` 或 `workspace-pack` 会复制原图和蒙版，使项目可以迁移到另一台机器。**便携项目含私人未遮盖原图，切勿上传到公开平台或作为 AI 公开预览。** 普通遮盖 PNG 仍不含私有密文。
- `workspace-replay` 按页回放已提交的蒙版快照并生成普通遮盖 PNG；`workspace-export` / `workspace-replay` 支持 `--page` 和 `--color`。报告包含 PNG 文件及解码像素的 SHA-256。
- 中文移植工作台保存项目时记录原图/三层蒙版的 SHA-256 和矩阵；`translation-project-render` 直接读取该项目并使用原有 `translation_core`。由用户明确选择区域，不自动推断待替换内容。旧项目缺少哈希时报告 `recipe_hashes_verified: false`。

```bash
python -m veilpng workspace-pack --project-dir ./my_project --output-dir ./portable_project
mkdir -p ./exports
python -m veilpng workspace-replay --project-dir ./portable_project --output-dir ./exports
python -m veilpng translation-project-render --project-dir ./translation_project --output ./final.png --report ./final.json
python scripts/replay_demo.py ./demo_output
```

Codex 调用规范见 `CODEX_CLI.md`；实际验收与边界见 `QA_v062.md`。GUI 尚未在本轮真实启动验证。不同系统的 Pillow/OpenCV/zlib 版本可能导致编码或重采样差异，须通过哈希验证而非假设一致。旧加密/A1–A4 项目仍保持独立格式。

## v0.6.1 · GUI / CLI 一体化与云端复现


新增内容：
- 统一工作台项目支持 `文件 → 保存工作台项目…` / `打开工作台项目…`。项目目录固定为 `workspace.json + masks/`，保存绝对原图路径、文件指纹、配准矩阵和当前会话蒙版；不默认复制原图。
- 新增 CLI：`workspace-init`、`workspace-show`、`workspace-apply-mask`、`workspace-export`。同一项目既可在 GUI 中编辑，也可在云端 / Codex 中继续处理并导出，目标是**复现统一工作台的普通遮盖 PNG 结果**。
- `workspace-apply-mask --rect x0 y0 x1 y1` 可直接脚本化矩形遮盖；`--mask` 可导入外部二值蒙版；配对模式会沿配准矩阵同步另一侧。
- `workspace-export` 与 GUI 导出共用同一后端 `export_pages()`，因此在**输入图片未变化、工作台项目相同**的前提下，云端 CLI 与 GUI 的普通遮盖 PNG 输出应保持一致。

CLI 示例：

```bash
# 1) 用单张/批量/配对目录创建工作台项目
python -m veilpng workspace-init --single page.png --project-dir ./vp_project
python -m veilpng workspace-init --folder ./pages --project-dir ./vp_batch
python -m veilpng workspace-init --pair-bundle ./pair_bundle --project-dir ./vp_pair

# 2) 云端 / Codex 更新蒙版（矩形或外部 mask PNG）
python -m veilpng workspace-apply-mask --project-dir ./vp_pair --page 1 --side cn   --rect 120 80 300 220 --operation union
python -m veilpng workspace-apply-mask --project-dir ./vp_project --page 1 --side single   --mask ./mask.png --operation replace

# 3) 导出，与 GUI 结果使用同一普通 PNG 导出后端
python -m veilpng workspace-export --project-dir ./vp_pair --output-dir ./exports
```

默认启动 `python -m veilpng.gui`：顶部切换「单张 / 批量 / 中日配对」，左侧是带状态的图片列表，中央是单/双画布。默认矩形工具，也可选择画笔、橡皮、套索、多边形和平移。勾选纯黑预览检查效果，底部导出当前页或所有已标记页。批量支持多选文件、导入文件夹（非递归）、自然排序、搜索、上一页/下一页；切页保留本次会话蒙版，跨会话尚未实现项目保存。

- 中日配对：选择已解压的 Folirina 配准目录；按清单矩阵同步最近操作侧的选区，另一侧自动映射（含 1 像素边界扩张）。必须人工查看两侧覆盖范围；未配准的图片不自动配对。亦可通过专业工具菜单逐项选择 CSV 和目录。
- 新工作台导出**普通纯黑遮盖 PNG**，不携带私有加密层；空选区/不完整的配对默认不导出。批量后台运行、可取消，结果写入新的唯一子目录，避免覆盖原图及旧结果。更改过的源文件拒绝导出。
- 原有加密/解密、AI 回写、幻影坦克、中文移植等仍在「专业工具 → 打开经典工作台」，也可 `python -m veilpng.gui --classic` 直接启动。新旧工作台的编辑状态独立，不自动传递选区。
- 本次不修改密码学格式。回归测试及局限见 `QA_v060.md`。

以下历史版本的界面操作说明适用于经典工作台。

## v0.5.11 · 紧凑布局与配准目录导入

- 五个工作模式改成两行按钮，无需横向切换页签。侧栏支持拖动分隔线，单图按钮只在遮挡与 AI 配准页显示。
- 路径选择改为上方标签、下方输入框/浏览按钮；缩短长按钮文案，异常字体下允许横向滚动，避免控件被永久裁掉。
- 漫画项目、中文移植和幻影坦克画布工具栏调整为紧凑多行布局。
- 漫画项目新增「一键导入配准目录」：解压后选择包含 `registration_pairs.csv`（或 `pairs.csv`）及 `source/target`（或 `images/source` 和 `images/target`）的目录；自动填充路径，单页自动选中载入。也可以继续逐项浏览。
- 配对选择缓存以配准清单、源图/目标图路径和矩阵区分，避免不同项目同编号串用旧蒙版。
- 不修改加密格式和主要图像处理算法。注意：本版云端没有可用的 PySide6 Essentials，Qt 窗口实机验收尚未完成。

## v0.5.10 · 中文移植画质复核（候选提示，不是 OCR）

在「中文移植」页签新增 **4 · 标记疑似残字/接缝** 与 **导出复核报告**：
- 蓝/橙/红三层蒙版继续决定哪些像素可修改；新增质量检查**只读**，绝不自动删除残字或重绘漫画。
- **红色候选**：原日文去字选区内，原图与最终图仍有一致的深色笔画，且 Gemini 返回图在该位置亮度较高。仅限被选中去字区域；不代表 OCR 识别出了日文。
- **橙色候选**：选定移植/去字边界出现较大的原图—成品像素跳变。正常的文字触边也会产生误报。
- GUI 右侧新增「疑似残字／接缝标记」预览；可导出标注图、问题分布图及带坐标的 `translation_quality_report.json`。
- CLI `translation-transfer --quality-dir /path/to/empty-dir` 可一次导出相同证据。目标目录必须为空，防止覆盖私人文件。
- 检测默认需要**人工逐处检查**；不能证明没有日文残留，也不能替代出版级 OCR 或文字审校。

## v0.5.9 · 全面可靠性审计与修复

- **杜绝旧预览误导出：** 日文/Gemini 源图路径或文件内容在配准后变化时，禁止直接导出；修改去字底图会使预览失效，强制重新合成。
- **避免丢失手工选区：** 重新配准前如已有三层选区，必须确认清空。项目文件禁止通过 `../` 指向外部蒙版。
- **防止原图被覆盖：** GUI 保存双层 PNG、AI 公开预览、中文普通 PNG 时检查输入路径，使用安全写入；拒绝用 AI 结果文件名覆盖 Gemini 返回图。
- **配对项目跨平台搬迁：** 新建私有漫画项目额外保存 `registration_pairs.csv`；重新打开时优先读取项目目录副本。源/目标同名图片会分开保存，避免彼此覆盖。
- **图片与构建可靠性：** 日文图片按 EXIF 方向读取，拒绝动画输入和畸形配准矩阵；打包文件名读取实际软件版本。
- **验收边界：** Linux 云端实际运行 PySide6 GUI 与回归测试；Windows/macOS 安装包尚未原生运行验收。漫画文字清理仍须人工复核残笔和背景接缝。

**兼容性：** v0.5.9 未变更 VeilPNG v1 的 AES-256-GCM 数据格式；旧双层 PNG 可继续用原密码读取。

**隐私警告：** 漫画项目 `assets/` 和 `registration_pairs.csv` 均是私人文件；只将单独导出的 `public_previews/` 图片发给 AI，不要上传整个项目目录、密文、原图或密码。

## v0.5.8 · 中文翻译移植工作台

GUI 新增第五个“中文移植”页签（主窗口切换至专用双视图）。流程：

1. 导入**日文原图**和**Gemini 中文返回图**。点击“配准并载入日文底图”；自动 SIFT+RANSAC 或通过 CLI 加载已保存的 JP→Gemini 3×3 矩阵。
2. 在左侧编辑三层互不混用的手动蒙版：**蓝色译文移植**、**橙色日文去字**、**红色原图保护**。支持画笔、矩形、套索、多边形、擦除、撤销、重做。可导入先前保存的选区 PNG。保护区优先且不会被去字或贴图覆盖。
3. 可选导入已经去字的日文底图（必须与输出画布同尺寸）；只在橙色去字选区内采用该底图，否则对橙色区域执行 OpenCV inpaint。白气泡可选“仅提取深色字形”；背景复杂或白描边效果字使用完整区域贴图，允许在 0–24px 范围内柔化拼接。
4. 右侧显示合成图、Gemini 图或去字日文底图。检查无残字、无接缝后，**直接导出普通 PNG**，不会生成新的双层密文文件。支持保存/重新载入三层选区项目以便逐页复审。

CLI: `python -m veilpng translation-transfer --japanese JP.jpg --gemini edited.png --translation-mask paste.png --erase-mask erase.png --protect-mask protect.png --output final.png`。

**限制：** 文字定位尚需人工 ROI，OpenCV 自动去字对复杂网点不能保证出版级修复；人工校对原文和接缝必需。不要将私有漫画或测试文件提交到公开 GitHub。

## 幻影坦克使用方法

1. 启动 `python -m veilpng.gui`，切到最右侧 **「幻影坦克」**。
2. 导入**白底表图**（白色背景下可见）和**黑底里图**（黑色背景下可见）。
3. 选择灰度精确模式（推荐）或彩色近似模式；选择居中裁剪、留白等比缩放或直接拉伸。
4. 调整白底亮度基准、表图对比度和里图对比度；中央同步看到同一 PNG 分别叠在白底和黑底上的效果。
5. 保存真正的 **RGBA PNG**，可额外导出白底、黑底、灰底预览、对比图、数值验证报告和 `preview.html`（在本地浏览器点击切换背景）。
6. 「打开已有幻影坦克 PNG 并解析」可以查看外部透明 PNG 的两种背景效果。

### 命令行（仅在本地处理文件，不会连接外部服务器）

```bash
python -m veilpng phantom-create --surface white.png --hidden black.png \
  --mode grayscale --fit cover -o phantom.png --preview-dir phantom-preview
python -m veilpng phantom-inspect -i phantom.png --preview-dir inspect-preview
```

灰度模式会把表图亮度压缩到浅色区间、里图压缩到暗色区间，然后逐像素解出真正的 RGB+Alpha；在 8-bit 量化误差范围内复现两种经过亮度处理的目标图。彩色模式为共享一个 Alpha 的近似最小二乘解，**任意两张全彩图不能都做到逐像素无损**，请检查报告中的 `white_target_error` / `black_target_error`。图片尺寸默认跟随表图；上限为 2400 万像素以控制内存。

### GitHub 参考项目（仅参考思想，未复制第三方代码）

- https://github.com/Aloxaf/MirageTankGo （亮度与缩放参数、黑白底效果；GPL-3.0）
- https://github.com/YamaArashiHZ/PhantomTankFactory （双背景预览；MIT）
- https://github.com/gnipbao/mirage-tank-creator （Alpha 验证、离线 HTML；MIT）
- https://github.com/Ebola-Chan-bot/MirageTank （双色背景与彩色模式参考）

---

## v0.5.4 A4 · 完整 Gemini 可见图移植（普通 PNG）

上一版 A3 只替换绿色 ROI，因此「Gemini 修改全部移植」并不成立。A3 保留为**日文高清底图优先、仅在绿色选区内编辑**；新增 A4 为**Gemini 可见整页优先**：将 Gemini 返回图整体对齐到日文尺寸，使用日本原图恢复加密遮盖区域，直接输出普通 PNG，**不生成双层文件**。

GUI 进入「漫画项目」使用 A4 按钮，明确确认整页重绘风险。CLI：

```bash
python -m veilpng manga-visible-transfer --project-dir /private/project_0050 \
  --source-ai /private/Gemini_return.png --alignment auto \
  --recover-expand-px 22 --feather-px 6
```

A4 保留 Gemini 的中文对白、效果字和可见画面，而非只处理右上角。它不保留 JP 的所有高清细节：JP 是配准尺寸基准及遮盖内容恢复来源。若要保留 JP 全页线稿，只替换局部文字，应使用 A3 并逐个文字区域选取 ROI。

## 双层加密与漫画工作区（历史功能）

本地优先的**选区加密 PNG 编辑器**：手绘涂抹、橡皮擦、矩形框选、自由套索、多边形选区。普通图片查看器只看到遮挡后的预览；使用密码可从**同一个 PNG**无损恢复原始文件字节。



## v0.5.3 · A3 日文高清底图优先（新增）

**A3 解决 Gemini 中文结果导入后却还是中文低清底图的问题。**

- 以项目配对中的 **日文高清 target 原图**为唯一底图；从 Gemini 编辑的中文 source 公开预览取修改内容。
- 第一段配准：Gemini 输出 → 中文公开预览，支持 Gemini 输出尺寸改变（ORB/RANSAC）。
- 第二段配准：中文 → 日文，读取 `pairs.csv` 中的 **原始 3×3 几何矩阵**。
- 用两侧绿色 ROI 限定可编辑范围，且永久排除双方红色保护区。A3 实际解密恢复的是**日文基底 + 允许的 Gemini 修改**。
- 两种迁移策略：**严格差异提取**（默认，真正只迁移检测到的改变；模型只做细微重绘时可能拒绝）；**明确绿色 ROI 整块替换**（用户二次确认后可覆盖日文文字，同时会替换 ROI 内部分纹理）。
- 支持 0–24px **内部边缘渐变**减少方形拼接痕迹，不修改选区外任何日文像素；输出修改蒙版、转移补丁、报告、新双层 PNG、真正无遮挡的日文合成 PNG。
- **不向 AI 上传未解密图或加密容器**；不会自动调用 GPT/Gemini API，不会上传 GitHub。

GUI：左侧“漫画项目”页 → 填入项目文件夹以及“中文 AI 返回图” → 选择 A3 策略 → 点击 **「A3 · Gemini 修改转移至日文高清底图并解密」**。整块覆盖模式会显示危险提示并需要明确确认。

CLI 示例（`VEILPNG_PASSWORD` 可避免终端交互式密码输入；请勿将真实密码写进脚本或仓库）：

```bash
# 严格差异模式（仅检测到真正变化的像素）
python -m veilpng manga-transfer --project-dir /path/to/manga-project --source-ai /path/to/Gemini.png --extraction monochrome

# 漫画文字整体替换（明确授权绿色区域，可能覆盖日文底纹）
python -m veilpng manga-transfer --project-dir /path/to/manga-project --source-ai /path/to/Gemini.png \
  --extraction patch --allow-entire-roi --edge-guard-px 0 --feather-px 12
```

> **画质提醒：** Gemini 输出可能与原中文预览几乎相同，不能把压缩或重采样差异冒充语义编辑。整块 ROI 策略迁移的是 **Gemini 在指定区域内的实际像素**，不保证每个像素都属于模型新生成的部分；日文高清底纹在该区域可能被低分辨率内容替换。请优先绘制紧贴文字的 ROI 并检查接缝。

## v0.5.2 · 漫画双画布工作区（本地云端测试版）

1. 打开左侧 **「漫画项目」** 页签；选择 `pairs.csv`、中文/source 图片文件夹、日文/target 图片文件夹，点击“读取配准清单”，从列表选择 `pair_id`（支持搜索）。
2. 中央自动出现 **中文 / 日文双画布**，任何一侧都可以用画笔、矩形、套索、多边形和橡皮擦编辑红色加密遮挡选区。每次鼠标操作完成后，使用清单中的真实矩阵同步另一侧，不进行粗略等比例缩放。
3. 顶部选择 **绿色 AI 编辑许可**，在任一画布编辑后投影绿色 ROI；和红色保护层相互独立，保护区域不会被许可改写。切回红色层可启用两张图片的纯色遮挡预览。
4. 在左侧填写本地项目目录并选择“用当前页面选区创建漫画模式项目”，一次生成两张双层加密 PNG 与 **两张不含密文的公开 AI 预览图**。项目 `assets/` 含原始图，**绝对不要将项目文件夹直接上传给 AI 或公开发布**；仅上传 `public_previews/` 下的普通 PNG。
5. 在 GPT/Gemini 之外完成图像编辑，把返回的图片填入“中文 AI 返回图” / “日文 AI 返回图”，选择 A1（原文件完全保留）或 A2（只改绿色区域）再导入。默认自动特征配准；手工选择风险较高的“只按尺寸缩放”会二次警告。完成后在 `resolved_outputs/` 获取解密后无遮挡的合成 PNG、新双层 PNG 与差异报告。

**注意：**此版不会自动向任何模型 API 上传文件；需要用户手动将两张公开 PNG 发送给模型并下载返回图。默认情况下，如果没有明确绘制绿色 ROI，A2 会拒绝无范围限制的全图回写。A1 解密恢复原文件，A2 才会将许可的编辑写入新密文。

## v0.4.2 GUI 优化（无云端依赖）

- 左侧改为「遮挡与选区」与「AI 与配准」两个可滚动页签，避免长侧栏操作拥挤。
- 新增「并排对比」：左侧原图/选区，右侧渲染后的公开预览；绿色 AI 选区模式仍显示原红色保护蒙版对应的公开效果。
- 切换绿色 AI 许可编辑后自动切到绘制工具页，并显示返回操作；可见提示区分保护蒙版与编辑许可蒙版。
- 高清画布的画笔预览采用 35 ms 合并刷新，鼠标松开时立即绘制最终掩模；不会跳过任何笔刷像素。
- 画布聚焦时支持 B/E/R/L/P/H 快捷工具切换，并显示当前缩放比例。
- 云端采用独立 PySide6 6.11.2 Linux 环境实测；其他系统仍需在本地运行或各自的 CI 环境验证。


## v0.5.1 漫画模式（中日配准成组工作流）

- 新增 **漫画模式**：把一组已配准的日文 / 中文页面视为一个项目，同时生成两边的遮挡蒙版、双层 PNG 和可上传给 AI 的公开预览。
- 支持从 **source/中文** 或 **target/日文** 一侧绘制遮挡区与绿色 AI 可写区域，并用 `pairs.csv` 的真实 3×3 配准矩阵自动投影到另一侧。
- 新增 CLI `manga-init`：创建成组项目目录，包含两边的 `containers/`、`public_previews/`、`masks/` 和 `editable_rois/`。
- 新增 CLI `manga-resolve`：读取 AI 返回图后，按 A1/A2 或智能 ROI 模式回写，并输出 **真正解密后的无遮挡结果**。
- 该模式适合已有可靠日中配准矩阵的漫画页。

## v0.5.6：QQ / 微信 / 小红书平台适配与油猴（仅本地）

**不能保证平台图片服务保留 Alpha。** 幻影坦克效果依赖透明 PNG 和不同背景；若平台把它压平成 JPG，任何脚本都不能恢复其中丢失的另一幅图。

- GUI 幻影坦克页新增 `QQ`、`微信`、`小红书` **实验性导出预设**。输出 `upload_alpha.png`、未改尺寸原始 PNG、白/黑背景示意 JPG、`fallback_side_by_side.jpg` 和离线 HTML；小红书不保证透明 PNG 效果，建议使用备用对比图。
- GUI / CLI 支持**下载回传图验收**，按透明通道、尺寸和两种背景的像素误差判断 `PRESERVED`、`DEGRADED` 或 `ALPHA_LOST`。该检查只针对保存回来的图像文件，不代表 App 缩略图与点开后的渲染效果。
- `userscripts/VeilPNG-Alpha-Preview.user.js` 是独立油猴脚本。电脑版网页里 **Alt+单击图片**打开黑白/灰底预览；也可手动加载本地 PNG。脚本没有网络上传、网页自动批量扫描或平台接口劫持，不能用于原生 QQ/微信 App 或 iOS/Android 小红书。
- Mac Safari/Chrome 浏览器可用 `view_offline.html` 打开导出文件夹验证真实 Alpha。手机 App 本身是否显示双图仍需实机测试。

```bash
python -m veilpng phantom-platform-prepare -i phantom.png --platform qq -o qq_package
python -m veilpng phantom-platform-prepare -i phantom.png --platform wechat -o wechat_package
python -m veilpng phantom-platform-prepare -i phantom.png --platform xhs -o xhs_package
# 把上传后保存回的图片作为 returned-image
python -m veilpng phantom-platform-audit --original qq_package/upload_alpha.png --returned returned-image.png --report audit.json
```

## 运行环境与安装

- Python **3.10+**；macOS（含 Apple Silicon）、Windows、Linux。
- 桌面 GUI 采用 **PySide6**；安全模块使用 `cryptography`、`argon2-cffi`；图像处理使用 `Pillow`。真实 GPT 智能回写额外依赖可选的 `opencv-python-headless`、`numpy`。
- **不会自动联网**；没有模型、云端账号或外部 API 依赖。

```bash
# 在此目录运行
python3 -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
python -m pip install -U pip
python -m pip install -e '.[full]'
python -m veilpng.gui
```

macOS 可在终端使用 `python3`，Windows 可使用 `py -3` 建立虚拟环境。运行 `veilpng-gui` 与 `python -m veilpng.gui` 效果相同。此源码包不附带独立安装程序；在 macOS 上可运行 `zsh scripts/build_small_app.sh` 生成本机 `.app`。构建会将核心 Python 模块复制进应用包；运行库仍由项目目录中的 `.venv` 提供，因此请将 `.app` 与项目文件夹放在一起。修改源码后重新构建应用以更新包内模块。

## GUI 操作

1. **打开图片**：支持 PNG/JPEG/WebP/BMP/TIFF 等静态图片。支持直接打开 VeilPNG 双层 PNG，输入密码后显示真实图和已有选区。
2. **选择加密区域**：
   - `画笔涂抹`：左键涂红；调画笔宽度（2–250 px）。
   - `矩形框选`：左键拖拽选矩形。
   - `自由套索`：按住左键沿轮廓画一圈后松开。
   - `多边形选区`：逐点左键单击，**双击或 Enter 完成**，Esc 取消。
   - `橡皮擦`：从已经选中的区域移除遮挡。
   - `全图选中` + `橡皮擦`：实现“只开几个透明窗口露出原图”的**开孔模式**；其余位置遮挡。
   - `反选`、`清空`、`撤销 Ctrl+Z`、`重做 Ctrl+Shift+Z`。
3. 选择**纯色遮盖（推荐）**、**随机噪声**或**马赛克（有隐私泄露风险）**。纯色新增**颜色选择器**与 `#RRGGBB` 直接输入，默认 `#222838`；支持纯黑 `#000000`、纯白 `#FFFFFF` 以及自定义颜色，**强制不透明**。勾选“显示公开预览”可预览最终公开像素。颜色会写入容器认证头部，重新打开时自动恢复；旧版 VeilPNG v0.1.0 PNG 兼容。
4. 点击**保存为加密双层 PNG**，输入密码两次。保存后会做一次解密校验。
5. 使用**解密并无损恢复**，输入密码，恢复**原始文件每个字节**。

### AI 往返流程

- **务必先保存加密双层 PNG**，并使用 GUI **“导出可上传给 AI 的预览”**：程序要求输入密码做机械隐私检查，确保导出的普通 PNG **不含私有密文块、遮挡像素全不透明、在纯色模式下每个遮挡像素都等于指定颜色**。仅检查像素，不保证图像语义一定合规。
- 上传 `*_AI_公开预览.png` 给 AI，让它处理可见区域。**不要上传加密双层 PNG 本体**。
- 下载 GPT 输出图。**智能 A1/A2** 现在支持 GPT 输出分辨率改变：先缩放，再用 ORB/RANSAC 自动配准，不可信的配准会直接拒绝；旧版 2A/2B 仍要求尺寸严格一致。
- **模式 2A｜安全回封装表层**：选择原双层 PNG 和 AI 返回图，输入密码；**自动把原有公开遮挡区域的预览像素恢复**，只采用 AI 对公开区域的修改。随后重新附上**逐字节相同**的原密文，解密结果仍为**最初的原始文件**。若必须使用不输入密码的旧版原样回封装，请在 CLI 使用明确的 `--unsafe-allow-covered-preview-changes` 选项；它不自动保护 AI 输出的遮挡区像素。
- **模式 2B｜合并 AI 修改**：选择原双层 PNG 和 AI 返回图，输入密码；仅把**未选择遮挡的区域**中的 AI 像素覆盖到解密图，然后生成**新的加密 PNG**。被选遮挡区域的像素和蒙版不改变。

> **新版推荐：智能 A1/A2（带绿色独立授权区）。** 首先保存加密双层文件，点击 **「3 · 编辑 GPT 可写入区域（绿色）」**，用现有矩形、画笔或套索工具选择 GPT **允许改动的位置**；点击按钮保存绿色区域并返回原有红色遮盖蒙版。选 `彩色标记提取`（适用于黑白漫画上新增彩色文字或红色标记），再点击 **「4A · 智能 A1」** 或 **「4B · 智能 A2」**。程序自动对齐图片，仅将绿色区域内侦测到的编辑像素写入，遮挡区及绿色区域以外一律保留。会额外输出修改像素蒙版及 JSON 报告。

> **重要限制：** 黑白文字替换、网点修复和真正的跨场景内容重绘，无法保证仅凭差异计算准确分离。`像素差异提取` 可能纳入 GPT 重绘和抗锯齿噪声，必须谨慎缩小绿色区域并人工核验。智能模式不是通用的完美修图工具。

## CLI（无 GUI 亦可使用）

```bash
python -m pip install -e .
# mask.png: 与原图同尺寸、白色=加密遮挡、黑色=公开可见
python -m veilpng create -i photo.jpg -m mask.png -o photo_sealed.png --style solid --color '#000000' 
python -m veilpng verify -i photo_sealed.png
python -m veilpng preview -i photo_sealed.png -o public_only.png
python -m veilpng audit -i photo_sealed.png -p public_only.png
python -m veilpng repack -i photo_sealed.png -p ai_output.png -o ai_repacked.png
python -m veilpng merge -i photo_sealed.png -p ai_output.png -o ai_merged.png
# v0.3: 白色=GPT允许编辑；与密文内的保护蒙版独立
python -m pip install -e '.[ai]'
python -m veilpng smart-edit -i photo_sealed.png -p gpt_output.png \
  --roi-mask gpt_edit_area.png --mode A2 --extraction color --alignment auto \
  -o selective_merged.png --report qa.json --delta-mask actual_changes.png \
  --preview-output selective_public.png
# A1（更新公开预览但严格保留原密文）：把 --mode A2 改成 --mode A1
python -m veilpng restore -i photo_sealed.png -o photo_restored.jpg
```

所有需要密码的操作默认在终端**隐藏输入**；自动化可使用环境变量 `VEILPNG_PASSWORD`（可能被本机进程环境查看工具读取，请注意设备安全）。不提供 `--password` 参数，以免出现在 shell 历史或进程命令行。

## 格式和安全模型

- **真正加密**：Argon2id（默认 64 MiB、3 次迭代、并行度 1）导出密钥；AES-256-GCM（随机 salt/nonce）加密包含原始文件和选区蒙版的二进制负载；AEAD 认证可检测密文的未授权更改。
- **标准 PNG**：用 PNG 私有辅助数据块 `vpNg` 保存密文，普通解码器可跳过未知辅助数据块显示遮挡预览。容器只支持单个加密块。
- **保护范围**：公开图像只能控制哪些**像素可见**；完整原始文件（包括原始 EXIF、元数据、潜在隐藏数据）被完整加密。公开图像的尺寸、选区轮廓及可见部分不是秘密。
- **重要设计选择**：对初次保存的预览计算 SHA-256 并写入被认证的头部。**AI 改动公开预览后该校验将不再相同，但加密底层的 AEAD 验证仍然有效。** 因而初始预览是否改变可以检测，但公开预览**不是不可篡改的**。如需强身份认证和来源证明，必须额外实现数字签名。
- **防窥推荐**：完全不透明的纯色遮挡（真正以指定颜色替代所有被选中的像素）或独立随机噪声。纯色遮挡不会在公开 PNG 的选中区域保留原像素的轮廓或颜色统计，但**选区外的公开画面仍然可能泄露信息**，遮挡不等于规避图像服务政策。**像素马赛克不是密码学保护，它保留轮廓与色彩统计，可能泄露局部信息。**
- **PNG 传输风险**：图片平台、AI 图像服务和编辑软件可能转码/压缩/移除辅助数据，必须以**原文件方式**传递完整容器；需要 AI 处理时，只上传不含密文的普通预览，之后本地回封装。
- **大小限制**：私有密文块最高 512 MiB；暂不支持多帧图片、GIF、视频、密钥恢复、分层权限和原生安装包。新增自动特征对齐适合大体保持构图的同页图；严重重排、非刚性重绘或缺少稳定特征时会拒绝。
- **密码丢失无法恢复**；不将密码写入文件或本地设置。敏感图片请保留离线备份。

## 项目结构

```text
veilpng/
  core.py           二进制封装/解密/AI 回封装/局部合成
  smart_edit.py     GPT 自动配准 + 颜色/差异提取 + 双掩模安全回写
  crypto.py         Argon2id 参数和密钥派生
  png_container.py  PNG CRC、私有辅助块
  imaging.py        蒙版、遮挡、限定区域合成
  canvas.py         PySide6 图像蒙版编辑器
  gui.py            桌面 UI
  gui_theme.py      独立蓝白主题（借鉴 Folirina 设计理念，不复制源码）
  mask_transfer.py  Folirina pairs.csv 真实 SOURCE↔TARGET 蒙版配准
  platform_check.py Python/系统/运行依赖诊断
  cli.py            命令行
  __main__.py       python -m veilpng
examples/            小型测试原图及示范蒙版
tests/             核心加密和往返测试
```

## 测试

```bash
python -m pip install -e '.[test]'
pytest -q
```

本版已在 Linux 云端对**51 项自动化测试**、真实 示例日文页 漫画的三种纯色遮挡、A1/A2 回封装与命令行往返做实际验收。**PySide6 6.11.2 四个 wheel 已从 GPT Library 取回并离线安装，Linux offscreen GUI 实测成功**。已复用用户上一轮真正 GPT 图像编辑产生的 1052×1495 PNG，完成自动配准 + 精确局部写回 + 解密验证（见 `QA_REPORT_v0.3.0.md`）。Qt GUI 的矩形、画笔、橡皮擦、套索、多边形、撤销/重做、加密保存/恢复、配准映射均已通过真实 Qt 鼠标事件测试。macOS/Windows 原生 GUI 尚未在对应系统实测。

## 相关开源项目（只参考设计，不包含其源码）

- [Image-Encryptor](https://github.com/ShuaiKeAng/Image-Encryptor)（交互式局部加密）
- [CuteCanvas](https://github.com/Artificial-Sweetener/CuteCanvas)（蒙版与选区编辑器设计）
- [CryptoImage](https://github.com/guillaumefe/cryptoimage)（PNG 封装加密信息）
- [OptiCipher](https://github.com/bio-colab/OptiCipher)（自包含加密图像）
- [W3C PNG Specification](https://www.w3.org/TR/png/)（私有辅助数据块）

此项目独立实现，不表示上述项目的作者为本项目背书。

## v0.2.0 更新与重要界限

- **纯色不是透明图层**：公开 PNG 对选区使用 100% 不透明 RGB 填充；加密原图仍放在 PNG 私有辅助数据块中，二者相互独立。
- **机械审计不是内容安全认证**：检查导出 PNG 是否含密文、遮盖是否不透明且颜色一致，并不推断未遮盖区域是否透露敏感内容；也不预测 AI 服务是否接受输入。
- **原图完整恢复（A1）与 AI 修改写回（A2）不同**：A1 恢复的是初始原文件，A2 经局部合并生成新加密原图，原文件 SHA-256 理应变化；遮盖选区保持原像素。
- **色彩是新认证头字段**：v0.2.0 写入 `preview_solid_color`；读取旧容器时回退到 `#222838`，不改变旧密文认证数据。
- **GUI 默认安全行为**：纯色仅允许十六进制 RGB，不能设半透明颜色；A1 回封装需要密码并保持遮盖像素原样；AI 结果必须仍然与原图同尺寸。

## v0.3.0 安全限制与验收说明

- v0.3 与 v0.2 使用**同一个 VeilPNG v1 加密容器格式**；已有加密文件不需要迁移。
- `smart-edit` **必须输入独立绿色 ROI**，超过全图 65% 的编辑范围会拒绝；加密保护蒙版来自容器内的已认证密文，用户 ROI 不能解除它。
- 默认 `--alignment auto` 进行 ORB 特征匹配、RANSAC 部分仿射配准并检查内点比例/尺度/平移。自动对齐失败时**不会悄悄缩放后写入**；只有明确指定 `--alignment resize` 才可绕过配准验证。
- 默认 `--extraction color` 只提取在黑白底图上显著新增的彩色像素，不会同步 GPT 产生的灰度变化。彩色原图会自动拒绝此模式；可手动选择 `--extraction difference`，须人工复核。
- A1 严格复用原加密密文，原文件解密字节不变；A2 只修改被独立 ROI 允许、且原保护蒙版未覆盖的像素，重新加密并生成新的 PNG 原文。
- 配准验证是几何一致性检验，不是图像含义、内容安全或局部画质保证；应检查输出差异蒙版和局部缝合质量。


## v0.4.0 新增功能与实际验收（2026-11-20）

- **Folirina 风格工作站 GUI**：独立蓝白浅色主题，工具区双列排列、中央大画布、工作区信息、适应窗口/100% 缩放按钮；重新调整 QGraphicsView 背景与侧栏滚动，不依赖 Folirina 源码或运行环境。风格参考文件为用户提供的 Folirina v3.0.0 源码 `gui_theme.py`、`gui_qt.py` 等。
- **真实 Qt 操作测试**：Linux x86_64 / Python 3.13.5 / Qt(Pyside6) 6.11.2；通过 Qt 鼠标事件在画布执行矩形、画笔拖动、橡皮擦、套索、自由多边形、撤销/重做；另测红绿分离选区、双层保存、公开预览机械审计、解密还原以及 GUI 中的 pairs.csv 精确映射。测试在 `tests/test_gui_interaction.py`。
- **实际 CN/JP 配准流程**：读取真实 `registration/pairs.csv` 的 Pair 0050，按 3×3 矩阵把 示例日文页.jpeg（1441×2048）上的保护选区映射到 示例中文页.webp（800×1137），得到 97,400 个被遮挡像素（10.708%）。GUI 真实保存加密 PNG、导出无密文纯黑预览、逐字节恢复 示例中文页，SHA-256 一致；截图与报告随独立 QA 压缩包交付。
- **多平台源码兼容**：运行入口支持 macOS（含 Apple Silicon）、Windows、Linux；`.github/workflows/cross-platform.yml` 配置 Linux、Windows、macOS ARM64/Intel 原生构建作业，`scripts/build_release.py` 基于 PyInstaller 打包。**该 CI 配置不代表这些平台已经成功构建或完成实机验收**。
- **不能跨平台直接使用 Linux wheel**：本轮离线加载的 PySide6 6.11.2 wheel 为 `manylinux_2_34_x86_64`；macOS/Windows 必须使用适配各自平台和架构的 wheel/安装源。Windows/macOS .exe/.app 当前不包含在源码 ZIP 中。

### 当前云端离线恢复四个 PySide6 wheel

```bash
# 仅 Linux x86_64、Python 3.10+ (ABI3)、glibc>=2.34
python -m venv .venv
.venv/bin/python -m pip install --no-index --find-links ./wheelhouse \
  PySide6==6.11.2 PySide6_Essentials==6.11.2 \
  PySide6_Addons==6.11.2 shiboken6==6.11.2
# 仍需另外安装 core、opencv、numpy 等运行依赖；wheelhouse 仅包含 Qt 四个 wheel
```

### 运行 GUI / 测试

```bash
python -m veilpng.gui
python -m pytest -q
python -m veilpng doctor
# 在无显示器的 Linux CI 中
QT_QPA_PLATFORM=offscreen python -m veilpng.gui --smoke-test
```

**GUI 测试范围：** 已完成 Linux Qt `offscreen` 鼠标事件驱动测试和真实图片 GUI 流程；颜色选择对话框仅通过输入框 / 设置颜色的代码路径验证，**没有实际操作系统文件对话框、系统色板或 macOS/Windows 原生交互**。图像服务是否接受任何公开图片也不属于密码学验收结论。

## v0.4.2 local-only changes

- Two new AI return extraction modes: grayscale stroke-difference (`monochrome`)
  and explicit whole-ROI patch (`patch`). Existing `color` and `difference` remain.
- User-adjustable 0–24px boundary guard prevents AI writes along an editable
  region's outermost pixels. Do not place required text strokes in that margin.
- A2 independently audits the *decrypted pixel array* and aborts if either
  protected pixels or pixels outside the approved green ROI change.
- Grayscale changes are **experimental**: the extraction is geometric/pixel-based,
  not OCR or text-aware. A manual inspection of text, screentone, and seams is
  required.

The 214-pair manga scan data and private test evidence are not part of the
source archive. Cross-platform GUI builds remain subject to native OS verification.


## v0.5.7：平台回传检查（本地使用，不上传文件）

1. 在 QQ、微信或小红书中发送 `upload_alpha.png`，从接收端**真正保存**图片文件。
2. Mac 双击候选包的 `verify_return_offline.html`（Safari/Chrome），选择发送前 PNG 和返回的文件，查看 Alpha 是否保留及双背景外观。
3. 或在命令行执行：

   ```bash
   veilpng phantom-platform-audit --original upload_alpha.png --returned returned.png --evidence-dir fresh_evidence
   ```

4. GUI 的“回传图片差异可视化”也能生成 `white_black_before_after.jpg`、`alpha_change_heatmap.png` 和 `audit.json`。

**边界：** 这些检查只能验证本地拿到的图片文件，不会模拟 QQ / 微信 / 小红书原生客户端的聊天缩略图与点击大图背景，也不能恢复被转码压平的透明像素。
