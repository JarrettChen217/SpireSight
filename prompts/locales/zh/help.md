# SpireSight — 快速帮助

## 全局快捷键

`Ctrl/Cmd + Shift + S` 用当前截图重新触发上一次的 Quick Action。

## 迷你栏模式

点击右上角的迷你栏图标（或菜单 **App → Mini-bar mode**），主窗口会折叠
成一条常驻置顶的小条，仍然能触发 Quick Action。再次点击恢复。

## Inspect 流程

1. 在侧栏按 **📷 Capture** 抓取一张或多张牌组截图（最多 6 张）。
   缩略图会以条带显示，每张缩略图上的 × 可移除该帧。
2. 按 **✓ Done** 将所有帧一起送给 LLM 解析。
3. 解析结果显示在 **Run State** tab，并自动附加到后续每次 Quick Action
   作为上下文。
4. **✕ Clear** 清掉已捕获的帧和已解析的状态。

## 添加 API Key

**App → Settings → API Keys** — 粘贴 Provider Key 并保存。MVP 阶段
Key 以明文存储于本地配置文件；切换到操作系统 keyring 在路线图中。

## 杀戮尖塔 II 术语

- **Archetype（流派）**：Inspect 尝试识别的牌组身份（Frost / Focus /
  Strength 等）。
- **Usefulness（实用度）**：LLM 针对识别出的流派给每张牌打的分
  — Key / Good / Situational / Skip。在 Run State tab 中按颜色分组。
- **稀有度图标**：`○` starter · `●` common · `◆` uncommon/rare。
