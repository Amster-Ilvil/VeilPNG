# VeilPNG

**本地优先的图片遮盖、回传恢复与中日漫画配准工具。**

在本地标记需要保护的图片区域，导出普通遮盖图片；完成外部图像编辑后，再导入返回结果，在本地恢复原始区域。支持单张图片、批量图片及中日双图配准工作流程。

## 在线使用

**[打开 VeilPNG 网页版](https://amster-ilvil.github.io/VeilPNG/)**

- 网页版：v0.9.6（导出增强版），无需安装，在浏览器中处理图片。
- 桌面版：v0.6.4，支持 Windows、macOS、Linux。
- [版本发布与下载](https://github.com/Amster-Ilvil/VeilPNG/releases)

## 主要功能

| 功能 | 说明 |
| --- | --- |
| 本地遮盖 | 矩形、画笔和橡皮擦；支持黑色、白色遮盖与选区调整。 |
| 单图与批量处理 | 导入图片或文件夹，预览选区并导出普通 PNG。 |
| 中日双图配准 | 匹配对应页面，确认配准后同步遮盖；需人工核对位置。 |
| 回传恢复 | 导入外部编辑返回的图片，利用本地原图和蒙版恢复遮盖区域。 |
| 自适应边缘修复 | 检测选区周围的残影并进行有限范围过渡，减轻矩形边缘线；也可使用严格原选区模式。 |
| 工程保存 | 保留本地原图、选区与配对记录，便于继续编辑和恢复。 |
| 双层加密 PNG | 桌面经典模式支持 Argon2id 与 AES-256-GCM 加密保护原始数据。 |
| 命令行 | 支持工作区管理、遮盖导出、回传恢复、配准和结果校验。 |
| 透明 PNG 工具 | 桌面经典模式提供不同背景下的透明图预览及 Alpha 检测；此功能不等同于加密。 |

## 快速开始

### 网页版

1. 打开 [VeilPNG Web](https://amster-ilvil.github.io/VeilPNG/)。
2. 单图选择「普通导入」；中日双图分别导入中文和日文原图，识别同页并确认配准。
3. 在画布上框选或涂抹需要遮盖的区域，检查黑白遮盖预览。
4. 保存私人完整工程 ZIP，然后导出当前 PNG 或中日公开遮盖 ZIP。
5. 将公开遮盖图片交给外部图像编辑工具处理。
6. 返回 VeilPNG，打开原工程，导入返回的 PNG、JPEG、WebP 或 ZIP。
7. 确认配对，点击「恢复遮盖区域」，检查接缝和文字后导出结果。

遮盖图以原文件名为前缀，例如 `001_redacted.png`；恢复图使用同一前缀，例如 `001_restored.png`。恢复按钮旁可直接导出当前 PNG，或批量导出已确认页面。重名自动编号；公开文件名可能含私人信息，分享前请检查。

**公开遮盖 ZIP 与私人完整工程 ZIP 不同。** 私人工程包含原始图片，不应上传或公开分享。

网页端仅处理静态图片，每批最多 32 张，每张不超过 1200 万像素、20 MB，合计不超过 80 MB。建议使用近期版本的 Chrome、Edge、Firefox 或 Safari。

### 桌面版

可在 [Releases](https://github.com/Amster-Ilvil/VeilPNG/releases) 查看已发布的安装或便携包。也可以直接从源码运行，建议使用 Python 3.11 或 3.12（项目声明最低 Python 3.10，依赖须与实际平台兼容）。

```bash
git clone https://github.com/Amster-Ilvil/VeilPNG.git
cd VeilPNG
python -m venv .venv
```

macOS / Linux：

```bash
source .venv/bin/activate
python -m pip install ".[full]"
python -m veilpng.gui
```

Windows PowerShell（无需激活虚拟环境）：

```powershell
.venv\Scripts\python.exe -m pip install ".[full]"
.venv\Scripts\python.exe -m veilpng.gui
```

仓库的 `scripts/` 中也提供三平台启动脚本。首次安装依赖需要网络连接。默认打开简易图片工作台；如需经典模式，运行：

```bash
python -m veilpng.gui --classic
```

在桌面工作台完成遮盖后，可通过「导入 Gemini 图并恢复」导入返回图并检查接缝。严格原选区模式不会主动清理选区外残影。

## 命令行使用

安装核心依赖：

```bash
python -m pip install .
veilpng --help
veilpng doctor
```

使用本地原图、遮盖蒙版及返回图进行恢复：

```bash
veilpng restore-return --original original.png --mask mask.png --returned returned.webp --output restored.png
```

蒙版应与原图尺寸一致，白色表示遮盖区域。需要严格恢复原选区时，追加 `--exact`。需要图像配准功能时，安装 `.[ai]` 或 `.[full]`。

## 隐私与使用限制

- 网页版图像处理在浏览器本地完成，不需要账户；页面设置了限制网络连接的内容安全策略。
- 桌面端核心图像处理在本地执行，外部图像编辑服务由用户自行选择和使用。
- 普通遮盖图片不应含有私人工程中的原始像素或可恢复密文；导出前仍应人工检查遮盖范围、透明区域及文件类型。
- 私人工程、遮盖记录和双层加密容器应保存在本地。加密容器可能携带原始图像的加密数据，不等同于普通公开遮盖图。
- 浏览器本地备份默认关闭；开启后会保存原图及选区。公共设备上请勿启用。
- 外部服务、浏览器扩展及网站托管访问日志不属于本工具的控制范围。
- 图像缩放、裁切、压缩或大幅重绘可能影响配准及恢复质量；请检查恢复结果，尤其是文字、线条和网点附近。不要将自动恢复视为无条件精确还原。

## 目录结构

| 目录或文件 | 用途 |
| --- | --- |
| `veilpng/` | 桌面 GUI、CLI、图像处理、加密和工程管理 |
| `docs/` | 独立网页版及 GitHub Pages 静态资源 |
| `scripts/` | 三平台启动脚本与本地打包工具 |
| `userscripts/` | 可选的透明图片背景预览浏览器脚本，与主程序独立 |
| `pyproject.toml` | Python 项目配置及依赖 |
| `LICENSE` | MIT 许可证 |

## 问题反馈

欢迎通过 [Issues](https://github.com/Amster-Ilvil/VeilPNG/issues) 提交建议和问题。请注明版本、系统、操作步骤，并仅附上已脱敏的测试图片；不要上传私人原图、完整工程、密码或密钥。

## 开源许可

本项目采用 [MIT License](LICENSE)。
