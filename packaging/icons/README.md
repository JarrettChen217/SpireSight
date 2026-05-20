# SpireSight 发布用图标

放 **应用包 / DMG / Windows zip** 用的图标资源（与 `src/spiresight/resources/icons/` 里的 UI 内嵌 SVG 无关）。

## 建议文件

| 文件 | 用途 |
|------|------|
| `source/main_icon-v2.png` | 桌面主图（1024×1024） |
| `source/menu_icon-v1.png` | 菜单栏原图（GPT 常把棋盘格画进 RGB，需后处理） |
| `menu-bar.png` | 去棋盘格后的透明 PNG（由脚本生成） |
| `menu-bar-22.png` | 缩放到 22×22 的菜单栏用图 |
| `icon.icns` | macOS（`spiresight.spec` → `BUNDLE` / `EXE`） |
| `icon.ico` | Windows |

## 去掉 GPT 假透明棋盘格

GPT 导出的 PNG 往往没有 alpha，而是用灰白棋盘格表示「透明」。脚本只从四边泛洪去掉外围棋盘格，**不挖空**图标中心（金环内侧等保持原样）：

```bash
uv run python packaging/icons/strip_checkerboard.py \
  packaging/icons/source/menu_icon-v1.png \
  -o packaging/icons/menu-bar.png
sips -z 22 22 packaging/icons/menu-bar.png --out packaging/icons/menu-bar-22.png
```

## 生成 `icon.icns` / `icon.ico` / `app_icon_512.png`

从 `source/main_icon-v2.png` 先缩放到画布 **80%** 并居中（留 macOS 圆角安全边距），再生成各尺寸（LANCZOS + 大图轻度锐化）：

```bash
uv run python packaging/icons/build_icons.py
```

产出：`icon.icns`（macOS 打包）、`icon.ico`（Windows）、`app_icon_512.png`（RGBA + 圆角透明，开发时 Dock / `QIcon`）。

开发模式 Dock 需透明圆角 PNG；可选安装 `pyobjc-framework-Cocoa` 以更稳地设置 Dock 图标：

```bash
uv sync --extra dev   # includes pyobjc-framework-Cocoa on macOS
```

`packaging/spiresight.spec` 已引用上述文件。
