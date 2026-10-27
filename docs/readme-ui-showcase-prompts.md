# README UI 展示图生成记录

## 当前版本：2026-10-27，以软件为主角

根据用户“背景太花哨，不符合 macOS 风格”和“重点是要突出软件”的反馈，使用内置 Image Gen 编辑原有四张展示图，供中英文 README 共用。新版图片采用 `-minimal.png` 文件名，避免复用旧图片地址时继续显示缓存的旧版风景背景。

这些图片是 macOS 风格的 UI 概念展示，并非当前 Windows 版本的实机截图。本次只更新展示图片、说明与生成记录，未实现图中的界面调整。

### 本次统一设计约束

- 外围背景采用接近 `#F3F4F6` 的浅灰白中性色，去除山景、树林、日出、雾气、河流及书页装饰；书库内部的书籍封面作为内容保留。
- 去掉大幅宣传标题、标语和功能说明行，顶部仅保留小尺寸品牌图标、名称和当前场景名称。
- 放大软件窗口，书库和阅读页占画面约九成宽度；悬浮窗同样以大尺寸完整呈现，确保正文和控件清楚。
- 采用正视构图、浅色窗口、轻阴影、细分隔线和克制的蓝紫色强调；保持整组图片的字体、边距及背景风格一致。
- 保留原有功能和示例内容，不添加账号、云同步或 macOS 平台支持等声明；纯正文悬浮窗内仅有文字，无标题栏和播放控件。
- 请求画布为 `1600 × 1100` 横向比例，最终 PNG 使用生成器原始输出尺寸，不拉伸或裁切。

### 图片与参考关系

| 输出文件 | 编辑参考 | 配套风格参考 |
| --- | --- | --- |
| `assets/screenshots/library-showcase-minimal.png` | 原书库展示图、品牌图标 | 本次系列基准 |
| `assets/screenshots/reader-showcase-minimal.png` | 原阅读展示图、品牌图标 | 本次新版书库图 |
| `assets/screenshots/floating-reader-showcase-minimal.png` | 原悬浮控制窗展示图、品牌图标 | 本次新版书库图 |
| `assets/screenshots/floating-reader-text-showcase-minimal.png` | 原纯正文展示图、品牌图标 | 本次新版悬浮控制窗图 |

### 统一提示词要点

```text
Edit the referenced existing README showcase. SOFTWARE FIRST.
Use a plain neutral #F3F4F6 background with no illustrated scenery,
wallpaper, ornamental geometry, colored gradients or book-page decorations.
Remove huge slogans; retain only compact top-left branding and a scene label.
Make the complete software window the dominant subject, front-on, readable,
with quiet macOS-inspired light surfaces, fine separators and a subtle shadow.
Keep the existing functions, Chinese content and exact brand identity.
For the library, keep illustrated covers only INSIDE the software.
For the text-only floating reader, the panel must contain TEXT ONLY,
without titlebar, icons, buttons, sliders, progress bars or resize controls.
Match the new library showcase as the series style reference;
match the new floating control window for the text-only variant.
No new functionality and no macOS availability claim.
```

以下为旧版生成记录，保留供追溯；其中风景背景和大幅标题的要求已由上述当前设计约束取代。

## 历史版本：2026-10-22

使用内置 Image Gen，以原有截图、用户提供的纯正文悬浮窗截图和品牌图标为参考生成四张配套位图。

## 纯正文悬浮朗读

输出：`assets/screenshots/floating-reader-text-showcase.png`

参考：用户提供的纯正文悬浮窗截图、`assets/screenshots/floating-reader-showcase.png`、`assets/qyreader-icon.png`。通过内置 Image Gen 生成，保留隐藏控制栏、上下句衔接及当前段落加粗的模式特点。

### 生成提示词

```text
Use case: ui-mockup / final README product showcase.
Generate exactly ONE additional coordinated macOS-style design presentation for QYReader 启远阅读. Target dimensions 1600 x 1100 landscape. It must match the premium existing showcase series while specifically showing the PURE TEXT floating reader state from the user's supplied reference.

Input references:
Image 1 user screenshot: the authoritative layout/behavior reference. It is a rounded white floating panel displaying ONLY three text passages: small subdued previous sentence at top, large bold current sentence in the middle, small subdued next sentence at bottom. ALL CHROME IS HIDDEN. No titlebar or buttons. Match its simple 443:268 panel proportions.
Image 2 existing QYReader showcase: style-family reference ONLY, for pearl ivory, delicate cool-blue mountains, navy typography, sunlit atmosphere and brand placement. DO NOT copy its visible player controls.
Image 3 QYReader icon: faithful brand identity. Use original logo, not Apple branding.

Create realistic, production-quality UI, very sophisticated spacing and type hierarchy. This is ONE final presentation, not a contact sheet or alternative set. Top brand lockup "QYReader 启远阅读". Main headline in beautiful large Chinese editorial type "只留文字，静静听。" Quiet subtitle below it "纯正文悬浮模式 · 上下句衔接 · 专注当前朗读". Use the same headline scale and placement as the existing series.

Center ONE wide translucent ivory floating panel, about 900 wide by 540 high within the 1600 x 1100 composition. Smooth macOS-style 30px radius, extremely delicate edge and soft realistic shadow, subtle frosted appearance, no nested cards. No titlebar, no window traffic lights, no pin icon, no close icon, no fullscreen icon, no playback button, no progress bar, no opacity slider, no resize handle, no dot, no audio waveform, no labels INSIDE the panel. THE PANEL CONTAINS TEXT ONLY. The panel must have generous symmetric padding and balanced vertical spacing, exactly as the user's pure-text reference. Don't add a chapter title or app logo within the panel.

Use these exact ORIGINAL synthetic passages, not the supplied screenshot's medical/educational discussion:
Small previous sentence in medium-gray PingFang-like sans-serif, two centered lines:
"他把书放在窗边，让第一缕阳光落在纸上。
风翻过书页，也带来了草木清新的气息。"
Large current passage in bold dark-charcoal PingFang-like sans-serif, center aligned, 3 generously spaced lines, the strongest element INSIDE the panel:
"有些远方，不必急着抵达。
沿途的一树花开，一次驻足，
都值得慢慢收藏。"
Small next sentence in medium-gray sans-serif, two centered lines:
"阅读让时间有了另一种刻度。
我们在别人的故事里，认出自己的心事。"

Backdrop: understated pale-blue layered mountains, morning mist and warm ivory book-page landscape, matching previous series but less busy behind text, premium and restrained. Leave clear separation between headline and floating panel. Below panel OUTSIDE its bounds one small unobtrusive supporting caption "鼠标移开，控件隐去；文字与声音，继续陪伴。". Bottom-right small label "UI 设计展示". No feature-card row, no second window, no mouse cursor, no arrows/callout bubbles, no fake dates or metrics, no new features. Real application is Windows; only visual styling is macOS-inspired, do not claim macOS platform support. Accurate Chinese, readable fonts, no clipped text. Avoid excessive gradients, excessive shadows, frame distortions and crowded UI. This image is a conceptual README illustration, not a screenshot claim.
```

## 本地书库

输出：`assets/screenshots/library-showcase.png`

参考：`assets/screenshots/library.png`、`assets/qyreader-icon.png`。

### 生成提示词

```text
Use case: ui-mockup / polished README product showcase.
Create ONE final beautiful high-end macOS-style UI presentation image for QYReader 启远阅读, named "静谧书库". Target dimensions 1600 x 1100 landscape, crisp high resolution. This is a final repository marketing illustration, not a webpage implementation. Create realistic, production-quality UI designs with clear hierarchy, strong typography, intentional imagery, purposeful spacing.
References: attached existing library screenshot is the factual product source; attached app icon is the exact brand identity. Redesign visual polish in macOS native style while retaining this app's identity and real features. Keep app logo faithful, never substitute Apple branding. The app is for Windows; this is macOS-inspired visual styling, do not claim a macOS version.
Composition: warm porcelain background with barely perceptible cool pearl light; beautiful spacious top typography, tiny brand lockup QYReader 启远阅读, large confident simplified Chinese headline "把喜欢的文字，留在身边。" and quiet subline "本地书库 · 多格式导入 · 随时继续阅读". Lower 75% is one large complete straight-on app window, native 18px radius, delicate brushed-silver toolbar, three tiny window dots, left translucent sidebar, fine dividers, gentle physically believable shadow. No laptop or phone frame, no perspective distortion, no giant decorative 3D objects, no flashy purple gradients.
App hierarchy: compact sidebar with 阅读 / 内容库 / 阅读统计 / 设置; 内容库 selected with quiet desaturated indigo. Main content title "我的书库", search field and ONE primary "导入内容" action. Slim inline secondary "粘贴文本" and "网页链接". Below compact filter row 小说 / 文章 / 资料 and 阅读中 / 待读. Hero content is an exceptionally crafted row of FOUR editorial book covers, not stock photos: paper-cut landscapes inspired by the reference covers with rich navy, warm ochre, sage, muted slate. Synthetic titles "山海之间", "长夜微光", "慢读生活", "远方来信". Realistic author metadata and very subtle progress lines at 38%, 12%, 67%, 24%. One quiet "继续阅读" affordance for the leading book. Book covers and comfortable whitespace dominate, no inventory of every feature. At bottom a small supporting format line "TXT · EPUB · PDF · Word · Markdown".
SF Pro / PingFang SC style typography, sharp accurate readable simplified Chinese. Body 14-16 px at app scale. Deep charcoal ink, warm light surfaces, fine gray separators, restrained indigo accent #686ed8. At most two fonts. Differentiation by spacing and alignment first, minimal borders, no nested cards, no excessive badges.
Use only actual features: local file/text/web import, library, categories/tags/reading state/progress. No accounts, cloud sync, online bookstore, AI summaries, podcasts, transcription, payments, timer, downloads marketplace. No fake metrics or dates. No watermark, no numbered variant label. Small discreet bottom-right caption "UI 设计展示". Clean complete composition, no clipped corners or cropped text.
```

## 沉浸阅读

输出：`assets/screenshots/reader-showcase.png`

参考：`assets/screenshots/reader.png`、`assets/qyreader-icon.png`、本组书库展示图。

### 生成提示词

```text
Use case: ui-mockup / final README product showcase.
Create ONE polished premium macOS-inspired desktop UI presentation for QYReader 启远阅读, direction "沉浸阅读". Target 1600 x 1100 landscape, crisp legible text. The attached actual reader screenshot is factual UI/function grounding; the attached app icon is brand identity; the attached generated library presentation defines a coordinated visual family, palette and editorial polish. This is a concept presentation of a Windows app, no claim of native macOS support. Create realistic production-quality UI with strong typography, spacing and hierarchy.
Top 20% warm porcelain canvas with small QYReader 启远阅读 brand lockup, beautiful large simplified Chinese headline "读进去，也听进去。" and understated line "沉浸阅读 · 免费离线朗读 · 划线笔记". Lower 75% a complete large straight-on native macOS-styled reading app window, no device hardware. Silver/porcelain titlebar, three discreet native window dots, translucent slim chapter sidebar, quiet neutral page, restrained periwinkle #686ed8 accent, ultrafine dividers, refined soft shadow. Barely visible pale blue mountain silhouette at canvas edges matching the coordinated library reference; no saturated gradients, no decorative floating panels.
Show ONE focused reading state. Sidebar title "目录" and 6 elegant chapter rows with active "第三章 山间来信". Main reading area wide with generous margins, heading "第三章 山间来信". Typeset 5 airy paragraphs in readable Chinese Song style prose at ~20px, short comfortable line lengths, not a dense wall. Use this ORIGINAL synthetic prose accurately:
"清晨，山谷里的雾还没有散。林间的小路像一封尚未拆开的信，静静地延伸到远处。"
"他把书放在窗边，让第一缕阳光落在纸上。风翻过书页，也带来了草木清新的气息。"
"有些远方，不必急着抵达。沿途的一树花开，一次驻足，都值得慢慢收藏。"
"阅读让时间有了另一种刻度。我们在别人的故事里，认出自己的心事。"
"当文字成为声音，目光便可以稍作休息。故事仍在继续，陪着我们走过平常的一天。"
Highlight the sentence "有些远方，不必急着抵达。" in a soft desaturated gold; a SMALL elegant selection-attached annotation toolbar just above it with four color circles, "写笔记" and "朗读", correct lightweight contextual UI, no big notes sidebar. Another single current spoken sentence with barely visible indigo emphasis. Right of top toolbar only typography "Aa", search, bookmark, floating reader icons.
Bottom full-width clean playback bar: small real app icon + "Kokoro · 晓晓" + quiet "离线朗读" label, previous/pause/next controls in center with circular periwinkle pause button; subtle 38% whole-book progress; speed "1.0×" and volume icon. No meaningless audio waveform/chart, no fake audio duration.
No AI assistant, cloud, accounts, sync, timer, podcast, marketplace, voice cloning, novel generation. No software implementation claims. Avoid nested cards and feature inventory. Leave realistic padding and no clipped page, prose, controls. Fine Chinese accuracy, beautiful minimal design. Discreet bottom-right "UI 设计展示".
```

## 悬浮朗读

输出：`assets/screenshots/floating-reader-showcase.png`

参考：`assets/screenshots/floating-reader-controls.png`、`assets/qyreader-icon.png`、本组书库展示图。

### 生成提示词

```text
Use case: ui-mockup / final README feature presentation.
Create ONE beautiful premium macOS-inspired QYReader 启远阅读 floating reader presentation, direction "轻盈随听". Target dimensions 1600 x 1100 landscape. High-end refined editorial composition, legible accurate simplified Chinese, meticulous whitespace. The attached original floating window is the factual product reference; the attached app icon is exact identity; the attached generated library presentation is the coordinated style-family reference. This is a Windows app with macOS-inspired styling, don't imply a Mac release.
The subject is ONE independent floating read-aloud window, not a main library app, no device frame. Match the same pearl ivory / ink navy / muted periwinkle family, slightly richer slate-blue paper-cut mountain atmosphere behind, softly out of focus. Minimal calm backdrop. Small QYReader 启远阅读 brand lockup at top. Large confident Chinese headline "让故事，轻轻陪着你。" and quiet subheading "独立悬浮朗读 · 主窗同步 · 自由调整". Place the large floating reader in the middle with extremely beautiful translucent frosted porcelain material, subtle edges, tasteful 24px corner radius, natural shadow, no excess glow. The app window should fill roughly 70% image width, 48% image height, enough for highly legible text.
Floating window structure:
Top drag strip: tiny brand dot on left, "第三章 山间来信" and small subtle status "正在朗读"; right only three refined line icons for pin, return to main window, close. Pin selected in soft periwinkle.
Main content three sentences vertically centered with ample spacing, showing actual behavior:
small subdued previous sentence "风翻过书页，也带来了草木清新的气息。"
larger strong dark current sentence over two beautiful centered lines "有些远方，不必急着抵达。"
smaller subdued next sentence "沿途的一树花开，一次驻足，都值得慢慢收藏。"
Bottom control footer separated by a fine line: slim progress track and "全文 38.0%"; beneath simple previous / round periwinkle pause / next on left, "背景 85%" small opacity slider on right and tiny resize grip. Keep rational real control arrangement faithful to reference.
Below window, outside UI, three editorial captions in one airy row separated by whitespace or hairlines, not cards: "置顶陪伴" / "透明度可调" / "进度同步". Optional 1 short supporting line beneath them "读到哪里，听到哪里。" No arrows, no extra floating windows, no annotation callout cards, no settings modal, no fake waveform, no metrics, no dates, no circular feature bubbles. Caption conveys only actual functions. No timer, transcript generation, AI summaries, cloud/account/sync/bookstore/podcast. Excellent spacing/alignment first, separators second, minimal border, shadow only for floating panel. Chinese accuracy and realistic product look matter most. Small discreet bottom-right caption "UI 设计展示".
```
