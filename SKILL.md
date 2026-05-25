# TikTok Video Ad Analyzer

面向 `TikTok` 投放场景的视频广告素材分析与多市场文案生成 skill。

当前版本已经补成一个**可执行工作流**：

1. 用 `scripts/extract_frames.py` 抽取关键帧、音频和视频元数据
2. 基于帧观察结果填写结构化笔记（可人工填写，也可交给 AI 辅助整理）
3. 用 `scripts/analyze_video.py` 自动完成 8 维评分、本地化判断、文案生成与报告导出

## 核心能力

- **关键帧提取**：支持场景检测与时间采样两种模式
- **音频提取**：输出 `wav`，便于后续识别旁白语言
- **结构化分析**：基于观察笔记做 8 维评分
- **本地化诊断**：判断是否可直接投放、需本地化或不建议投放
- **多市场文案生成**：支持日本 `jp`、泰国 `th`、印尼 `id`
- **日本 TK 钩子标题引擎**：日本市场会额外输出反差颠覆型、功能揭秘型、痛点扎心型、价格刺激型、紧迫感型标题矩阵，并自动追加 `#关键词`
- **强点击标题模式**：支持 `safe` / `aggressive` / `hard_sell` 三档标题强度，默认 `aggressive`，优先生成买前确认、损失厌恶、避坑、反转、证明前置类标题
- **视频文案转 TK 正文**：当 notes 提供 `video_script` / `transcript` / `voiceover_text` 时，先过滤高风险声明，再生成 100 字以内、带 1-3 个 emoji 的日语 TikTok 正文
- **标题评分器**：按停顿感、好奇心、痛点命中、转化相关、合规安全给标题排序；支持用历史 CTR/CVR/ROAS/CPA 做角度校准
- **半自动 notes 草稿**：`scripts/generate_notes.py` 可根据抽帧、落地页和可选转写草稿生成 `notes.json`
- **批量分析**：`scripts/batch_analyze.py` 可递归分析目录中的多个 `extraction_result.json` 并汇总排行
- **落地页解析与一致性校验**：`scripts/fetch_landing_page.py` 可提取商品名、meta、JSON-LD 商品名、价格、优惠、CTA、保障信息；支持可选 `--render-js`
- **剪辑建议**：输出 15 秒强转化版、25 秒解释版结构，以及封面建议
- **日本美妆规则库**：`references/jp_beauty_rules.md` 约束日语美妆文案表达与禁区
- **报告导出**：同时生成 `report.md` 与 `report.json`

## 目录说明

- `scripts/extract_frames.py`：视频抽帧与音频提取
- `scripts/analyze_video.py`：素材诊断、文案生成、标题评分、落地页一致性校验、剪辑建议、报告导出
- `scripts/fetch_landing_page.py`：落地页信息提取，输出 landing page JSON；默认拒绝 localhost、内网与保留地址，避免 SSRF 风险
- `scripts/generate_notes.py`：从抽帧、落地页、可选转写生成 notes 草稿
- `scripts/batch_analyze.py`：批量分析目录里的多个素材并输出汇总
- `references/jp_ad_copy.md`：多市场文案参考模板
- `references/jp_beauty_rules.md`：日本美妆广告文案规则
- `references/analysis_notes.example.json`：结构化观察笔记示例

## 运行前准备

### 1. 安装依赖

本 skill 仅依赖 Python 标准库，但需要系统安装：

- `ffmpeg`
- `ffprobe`

### 2. 推荐输入素材

- 竖版 `9:16` 视频优先
- 时长优先 `15-45` 秒
- 画面中尽量包含：钩子、卖点展示、证明内容、优惠信息、CTA

## 工作流

### Step 1：提取关键帧与音频

```powershell
python scripts/extract_frames.py "视频路径" --output "输出目录"
```

#### 常用参数

- `--scene-threshold`：场景变化阈值，默认 `0.3`
- `--max-frames`：场景模式下最多保留多少帧，默认 `15`
- `--no-scene`：禁用场景检测，改用时间采样
- `--fps`：时间采样模式下的采样频率

#### 产物

运行后会在输出目录生成：

- `frame_000_0.0s.jpg` 等关键帧
- `audio.wav`（若原视频有音轨）
- `extraction_result.json`（供分析脚本直接读取）

### Step 2：整理结构化观察笔记

复制示例文件后填写：

```powershell
copy references\analysis_notes.example.json notes.json
```

建议至少填写这些字段：

- `product_name`
- `category`
- `hook`
- `selling_points`
- `proof`
- `offer`
- `cta`
- `languages`
- `localization_signals`

如果你想先出一版草稿，可以直接跑；没有 OCR 文件时删掉 `--ocr-json`：

```powershell
python scripts/generate_notes.py --extraction-json "输出目录\extraction_result.json" --landing-page-json "输出目录\landing_page.json" --ocr-json "ocr.json" --transcribe --output "notes.json"
```

> 如果你是在 AI 工作流里使用这个 skill，可以先让 AI 阅读所有抽出来的帧和音频信息，再按 `analysis_notes.example.json` 的结构产出 `notes.json`。

### Step 3：可选，提取落地页信息

```powershell
python scripts/fetch_landing_page.py "落地页URL" --output "输出目录\landing_page.json"
```

如果页面是强 JS 渲染，可以加 `--render-js`。

### Step 4：生成诊断报告与多市场文案

```powershell
python scripts/analyze_video.py --extraction-json "输出目录\extraction_result.json" --notes "notes.json" --landing-page-json "输出目录\landing_page.json" --market jp --output "输出目录\report"
```

#### 参数说明

- `--extraction-json`：`extract_frames.py` 生成的结果文件
- `--notes`：结构化观察笔记，可省略；省略时仍可运行，但分析可信度更低
- `--landing-page-json`：`fetch_landing_page.py` 生成的落地页 JSON，可选；提供后会输出视频/落地页一致性校验
- `--performance-json`：可选历史投放表现 JSON，用于给标题角度做轻量校准
- `--market`：目标市场，可选 `jp` / `th` / `id`
- `--output`：报告输出目录

`--performance-json` 可传入数组或 `{ "records": [...] }`，字段可包含 `title`、`angle`、`ctr`、`cvr`、`roas`、`cpa`。

### Step 5：查看输出

输出目录会生成：

- `report.json`：结构化分析结果，适合继续喂给其他自动化流程
- `report.md`：适合直接阅读和复用的分析报告

### 批量分析

```powershell
python scripts/batch_analyze.py --input-dir "outputs" --market jp --output "batch_report"
```

## 输入/输出契约

### `extraction_result.json` 核心字段

```json
{
  "status": "ok",
  "video_path": "input.mp4",
  "metadata": {
    "duration": 28.0,
    "width": 1080,
    "height": 1920,
    "fps": 30.0,
    "has_audio": true
  },
  "frame_files": ["frame_000_0.0s.jpg"],
  "audio_file": "audio.wav",
  "warnings": []
}
```

### `notes.json` 建议字段

必填优先级最高：

- `product_name`：商品名
- `category`：`beauty` / `fashion` / `home` / `food` / `general`
- `hook`：开场钩子是否存在、类型与细节
- `selling_points`：至少 2 个卖点更可靠
- `proof`：真人演示、评价、对比、测试等证明内容
- `offer` / `price_sale` / `price_original`：优惠与价格
- `cta`：行动号召
- `video_script` / `transcript` / `voiceover_text`：视频旁白或字幕全文，用于生成 100 字以内 TK 正文；不要只填关键词
- `languages`：旁白、字幕、画面文字语言
- `localization_signals`：模特地区、BGM 风格、货币、是否需重剪
- `copy_requirements.title_intensity`：标题强度，推荐 `aggressive`；可选 `safe` / `aggressive` / `hard_sell`
- `copy_requirements.click_triggers`：想优先使用的点击机制，如买前确认、损失厌恶、避坑、反转、证明前置
- `copy_requirements.short_copy_char_limit`：短 TK 正文字数限制，日语默认 `100`

### `landing_page.json` 核心字段

```json
{
  "url": "https://example.com/product",
  "title": "页面标题",
  "meta": {
    "title": "OG/Twitter 标题",
    "description": "页面描述",
    "og_image": "主图"
  },
  "product_name_guess": "商品名猜测",
  "json_ld_product_names": ["结构化商品名"],
  "prices": ["¥2,980"],
  "discounts": ["送料無料"],
  "ctas": ["今すぐチェック"],
  "guarantees": ["品質保証"],
  "render_mode": "static",
  "limitations": ["未执行页面 JavaScript；动态渲染的价格、库存和优惠可能无法提取。"]
}
```

### `report.json` 核心字段

- `scores`：8 维评分明细
- `total_score` / `summary`：总分与结论
- `execution_summary`：投放判断、首测标题、先做动作、风险复核
- `confidence`：分析可信度，综合字段覆盖、帧数量、元数据与音频信息估算
- `localization`：本地化状态与改造清单
- `copy`：标题、描述、正文、CTA、hashtags
- `title_scores`：`top5`、`approved`、`needs_review`、`rejected`
- `landing_page_check`：视频/落地页一致性
- `editing_advice`：15 秒与 25 秒剪辑建议

## 评分体系

| 维度 | 说明 | 满分 |
|------|------|------|
| 钩子强度 | 前 1-3 秒是否能打断用户 | 5 |
| 卖点清晰度 | 核心卖点是否明确 | 5 |
| 证明可信度 | 是否有演示、评价、对比 | 5 |
| 优惠驱动力 | 是否有价格、折扣、限时 | 5 |
| CTA 压迫感 | 是否明确引导行动 | 5 |
| 节奏/完播率 | 时长与信息密度是否合适 | 5 |
| 互动驱动 | 是否有评论/转发/讨论诱因 | 5 |
| 合规性 | 是否存在风险表述 | 5 |

### 总分区间

- `32-40`：优秀素材，可直接进入测试
- `25-31`：良好，建议补强弱项后测试
- `20-24`：一般，建议优化后再投
- `<20`：较差，建议重做素材结构

## 本地化判断逻辑

### 直接可投

- 语言、字幕、画面文字与目标市场匹配
- 货币、CTA、模特/风格基本贴近本地市场
- 时长适中，无明显中文化痕迹

### 需本地化

- 仍保留中文旁白、中文字幕、人民币价格等
- 模特、BGM、表达方式明显偏中国电商素材
- CTA 不符合当地平台习惯

### 不建议投放

- 时长过长且节奏松散
- 风格与目标市场偏差太大
- 高风险文案或合规问题明显

## 多市场说明

### 日本 `jp`

- 语言：日语
- 货币：`¥`
- CTA：`プロフィールへ`、`今すぐチェック`
- 重点：可信感、价格表达、季节节点、轻销售压迫感
- 标题策略：默认不写说明书式标题，优先写能让用户停手的 TikTok 标题
  - 买前确认型：`買う前にこれだけ見て`
  - 损失厌恶型：`まだ〇〇で損してるかも`
  - 避坑型：`〇〇選びで失敗する前に`
  - 反转型：`正直、期待してなかった`
  - 证明前置型：`レビューで多かった悩み`
  - 价格/优惠型：`通常価格→今だけ価格`（必须由 notes 或落地页承接）
  - 轻紧迫型：`見逃し注意`、`気になるなら早めにチェック`
- 合规边界：不编造视频/落地页没有的价格、折扣、功能、功效、销量；强销售但避免日本用户反感的过度命令式表达。

### 泰国 `th`

- 语言：泰语或英语
- 货币：`฿`
- CTA：`ดูเพิ่มเติม`、`ดูในโปรไฟล์`
- 重点：轻快节奏、价格优势、生活化表达

### 印尼 `id`

- 语言：印尼语或英语
- 货币：`Rp`
- CTA：`Lihat Selengkapnya`、`Lihat Profil`
- 重点：高性价比、实用性、直白结果导向

## 推荐用法

### 仅做预处理

```powershell
python scripts/extract_frames.py "input.mp4" -o "output"
```

### 做完整报告

```powershell
python scripts/analyze_video.py --extraction-json "output\extraction_result.json" --notes "notes.json" --market jp --output "output\report"
```

### 不提供笔记，先跑元数据级诊断

```powershell
python scripts/analyze_video.py --extraction-json "output\extraction_result.json" --market jp
```

## 常见问题

### Q：为什么现在还需要 `notes.json`？

因为当前版本是**结构化闭环**，不是假装全自动视觉识别。这样可以保证：

- 脚本是真能跑的
- 输出可复用、可自动化
- 后续如果接入视觉模型，只需要替换 `notes.json` 生成步骤

### Q：没有音频也能分析吗？

可以。脚本会继续运行，只是语言与本地化判断的可信度会下降。

### Q：可以只生成文案，不做评分吗？

可以，评分和文案都来自同一份结构化输入；如果结构化信息较少，文案会更通用。

## 后续可扩展方向

- 接入视觉模型，自动从帧图里提取 `notes.json`
- 接入语音识别，自动判断旁白语言与字幕文本
- 增加更多市场，如越南、菲律宾、美国
- 增加 CSV / Notion / 飞书报表输出
