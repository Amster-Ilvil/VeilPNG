# VeilPNG 0.6.3 · Codex / 本地 CLI

## 环境
在源码根目录使用 Python 3.10+；`python -m pip install -e '.[ai]'` 安装 CLI/配准所需依赖。GUI 另需 PySide6。`python -m veilpng doctor` 检查环境。CLI 本地运行，不调用外部生成服务。使用系统提供的真实源文件和经过确认的选区，不猜测区域，也不将私人项目上传给第三方。

## 常用操作

```bash
python -m veilpng workspace-init --single input.png --project-dir project
# 批量：将 --single 改为 --folder pages 或 --images p1.png p2.png
# 中日配对：将 --single 改为 --pair-bundle bundle
python -m veilpng workspace-apply-mask --project-dir project --page index:1 --rect 30 40 120 160 --operation replace
python -m veilpng workspace-show --project-dir project
mkdir -p exports
python -m veilpng workspace-export --project-dir project --output-dir exports
python -m veilpng workspace-pack --project-dir project --output-dir portable
python -m veilpng workspace-replay --project-dir portable --output-dir exports
```

- 矩形坐标为解码后的像素坐标、两端包含；越界或反向坐标拒绝。可用 `--mask` 提供用户已确认的二值 PNG。`--side cn/jp` 指定配对编辑侧。`--page id:17` 与 `--page index:17` 区分配对 ID 与列表序号。
- 回放每页的已提交快照，不模拟 Qt 鼠标轨迹，不保存全局时间顺序。GUI 与 CLI 共用导出函数，保存前必须确认选区。复制便携项目会包含原图，属于私人文件。
- 命令成功返回 JSON；异常以非零退出码报错。不要只检查文件是否存在，检查报告与 `sha256` / `pixel_sha256`。不同库版本不能保证 PNG 文件编码一致。
- 中文移植：在经典工作台保存已审核的三层选区项目，再用 `python -m veilpng translation-project-render --project-dir project --output final.png --report final.json`。明确指定输出文件名，拒绝覆盖现有输出或输入。GUI 使用原有核心模块，CLI 读取保存的矩阵和选区；不新增自动检测遮盖或自动匹配外部返回图的功能。
- 原有 `create/restore/smart-edit/manga-*` 命令与格式保留。不要把明文源图、项目、密文和密码提交到公共仓库。

## 可重复示例
`python scripts/replay_demo.py ./new_demo_directory` 使用本地合成色块图测试真实 CLI 进程、三次提交、项目迁移与字节一致性。

## v0.6.3 导出独立核验

```bash
python -m veilpng workspace-verify --project-dir portable --export-dir exports/VeilPNG_xxxxx
```

- 用实际 `workspace-export` 或 `workspace-replay` 返回的 `output_dir`，而不是猜测目录名。单页导出核验须带相同的 `--page`，颜色须一致。
- `passed=true` 才表示全部图像、文件名单及报告均匹配。`bytes_match=false` 但 `pixels_match=true` 表示编码不同而解码像素一致；原报告未更新时仍会核验失败。
- 核验不会修改任何图片。退出码 0 为通过，2 为检查不通过；其它非零退出为执行异常。
- CLI 修改已有工作台项目时校验修订标识；发生冲突先重新读取，不要强行覆盖。异常中止后确认无写入进程才能移除 `.workspace-write.lock`。
