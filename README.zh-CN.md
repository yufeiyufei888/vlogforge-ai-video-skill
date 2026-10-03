# VlogForge AI

**面向旅行、城市漫步、探店与美食 Vlog 的可审查剪辑工作流：可编辑剪映草稿，或带版本号的 MP4。**

[English](README.md) · [Skill 入口](skills/travel-vlog-pipeline/SKILL.md) · [参与贡献](CONTRIBUTING.md)

VlogForge AI 认真审查完整原片、理解旅行／探店叙事，并提供两条交付分支：引用完整原片的**剪映可编辑草稿**，以及原有 MaxAzure **版本化 MP4 渲染**。旅行取舍规则在本仓库维护；机械剪映操作交给独立的 [jianying-MCP](https://github.com/yufeiyufei888/jianying-MCP)，不重复维护完整旅行 skill。

它尤其适合不希望把私人素材随意上传云端，同时又想利用 AI 提高剪辑效率的创作者和开发者。

## 核心能力

- 保留旅行或探店从抵达、环境、点单、上菜、品尝到总结离店的叙事流程。
- 每段原片分布式抽帧，重要动作、变化、遮挡和入出点加密检查；如未连续观看／试听，明确说明，不以执行速度或文件名代替认真审查。
- 保留完整有意义的口播，避免过度压缩，长版按内容决定时长；对少数漏镜头优先局部修补，不重新铺主轨。
- 原生草稿直接引用完整原片，不复制、不转码、不要求安装语音模型；可复用用户授权的完整原片 SRT。原渲染分支仍保留可选的本地 faster-whisper，不自动安装。
- 使用底部居中、清楚且可编辑的字幕；转场克制；BGM、口播避让区间和发布授权分别确认。
- 自动生成故事板和审核面板，在正式渲染前检查顺序、覆盖缺口和切口。
- 仅在 MP4 渲染分支将混合手机素材统一为稳定的分辨率、帧率、像素格式和音频规格。
- 编译唯一的时间线、字幕、渲染配置和报告，避免维护两套互相矛盾的数据。
- 正式审批前先渲染 5–8 秒技术预览，并绑定输入、代理素材、字幕、BGM、预览和运行环境哈希。
- 成片始终使用版本化文件名，不覆盖上一个可用版本。
- 通过 FFprobe、严格全文件解码、上游 QA 以及人工视听检查完成交付验证。

## 快速开始

### 剪映原生草稿（不运行渲染 bootstrap）

克隆本仓库使用旅行 skill，再按 [jianying-MCP 安装说明](https://github.com/yufeiyufei888/jianying-MCP/blob/main/docs/install.md) 单独配置机械工具。复用已有 Python／FFmpeg，不复制视频、不自动安装 ASR，不抢鼠标；本机格式与五组原生验收通过后才能写入或显式注册。新安装默认为“未验收”，CI 不替代剪映播放／保存／重开。

```text
使用 $travel-vlog-pipeline，仔细审查 <素材目录> 的每段完整原片和有意义的声音。
保留景点、过程与完整口播，视频可以长一些；生成新的剪映可编辑草稿副本。
通过已验证的 jianying-local MCP 执行，原片原位引用，不重铺已有手工精剪，导出我自己操作。
```

详细规则：[原生草稿流程](skills/travel-vlog-pipeline/references/jianying-native-draft.md)、[MCP/CLI 调用](skills/travel-vlog-pipeline/references/jianying-local-adapter.md)、[通用剪辑与码率要求](skills/travel-vlog-pipeline/references/editing-preferences.md)。

### 原有版本化 MP4 渲染

环境要求：Windows 10/11、PowerShell 5.1+、Python 3.12+、`curl.exe` 和 Windows `tar.exe`。

```powershell
git clone https://github.com/yufeiyufei888/vlogforge-ai-video-skill.git
Set-Location .\vlogforge-ai-video-skill
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap-workspace.ps1
```

然后在 Codex 中打开该仓库，并使用：

```text
skills/travel-vlog-pipeline/SKILL.md
```

示例：

```text
使用 $travel-vlog-pipeline，把 <素材目录> 整理为版本化 MP4 美食 Vlog。
保留到店至离店的完整叙事和口播，不强制压到两分钟；正式渲染前先审核故事顺序和技术预览。
```

原渲染分支采用工作区本地运行方式，保留 `skills/` 与安装后 `.vendor/`、`.venv/`、`.tools/` 的关系，继续校验原有依赖锁和完整运行边界；只有明确需要且授权本地 ASR 时才加 `-WithAsr`。这些渲染依赖不是剪映原生草稿的必装条件。

## 隐私与安全边界

- 剪映草稿完整原片原位引用；旧 MP4 渲染分支仍默认复制素材。两者都不修改原视频。
- 未获得明确同意时，不把视频或抽帧上传给第三方视觉 API。
- 上游依赖按提交、完整目录哈希和文件数量锁定。
- 发现字节码缓存、软链接、目录联接或依赖变化时直接停止。
- 故事板审核不等于正式渲染授权；必须继续检查编译结果和技术预览。
- 自动 QA 只是证据，最终仍需真实观看、试听和完整解码。
- 文件校验、原生打开／保存／重开、真实试听及音乐发布授权分别记录；音轨可见不代表听感已确认。
- 导出前 FFprobe 实测每个原片视频码率／编码／分辨率／帧率，按原片质量基准试编码动态画面；交付报告原片与成片码率、编码、时长和大小，不用固定统一高码率，也不宣称能恢复原片缺失细节。

## 测试与许可

Windows CI 在 Python 3.12／3.13 验证旧渲染测试与公开文档；不下载私人素材、不启动剪映。原生兼容性需在实际本机通过独立测试，不由 CI 推定。

自制整合、skill 和文档采用 [Apache-2.0](LICENSE)；第三方保持原许可。此次新增原生分支没有改动既有渲染代码或依赖锁。机械工具、配置、安装与回滚说明只在 [jianying-MCP](https://github.com/yufeiyufei888/jianying-MCP) 维护。

## 第三方依赖说明

本项目不会复制发布 `.vendor` 中的第三方源码。启动脚本会从原作者仓库下载指定版本，并在本地校验完整目录：

- `maxazure/video-editing-skill`：负责项目结构、渲染与 QA；检查到的版本没有根许可证，因此只作为本地依赖使用。
- `znyupup/ai-video-editing-skill`：提供 Vlog 叙事参考；检查到的版本采用 MIT License。

如果这个项目对你有帮助，欢迎点一个 Star，让更多需要本地 AI 视频剪辑工作流的人看到它。
