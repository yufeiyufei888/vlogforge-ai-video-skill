# VlogForge AI

**面向旅行、城市漫步、探店与美食 Vlog 的生产级 AI 视频剪辑 Skill。**

[English](README.md) · [Skill 入口](skills/travel-vlog-pipeline/SKILL.md) · [参与贡献](CONTRIBUTING.md)

VlogForge AI 可以把一整批原始视频整理为可审查的故事方案，并最终输出带版本号的成片。它将镜头分类、本地选择性转写、故事板审核、素材规格统一、确定性渲染、完整性审批以及 FFmpeg 质量检查整合在一个 Codex 兼容 Skill 中。

它尤其适合不希望把私人素材随意上传云端，同时又想利用 AI 提高剪辑效率的创作者和开发者。

## 核心能力

- 保留旅行或探店从抵达、环境、点单、上菜、品尝到总结离店的叙事流程。
- 先抽帧和人工检查，再决定镜头职责，不只依赖文件名猜测。
- 只对确实需要理解语音的片段运行本地 faster-whisper。
- 自动生成故事板和审核面板，在正式渲染前检查顺序、覆盖缺口和切口。
- 将混合手机素材统一为稳定的分辨率、帧率、像素格式和音频规格。
- 编译唯一的时间线、字幕、渲染配置和报告，避免维护两套互相矛盾的数据。
- 正式审批前先渲染 5–8 秒技术预览，并绑定输入、代理素材、字幕、BGM、预览和运行环境哈希。
- 成片始终使用版本化文件名，不覆盖上一个可用版本。
- 通过 FFprobe、严格全文件解码、上游 QA 以及人工视听检查完成交付验证。

## 快速开始

环境要求：Windows 10/11、PowerShell 5.1+、Python 3.12+、`curl.exe` 和 Windows `tar.exe`。

```powershell
git clone https://github.com/yufeiyufei888/vlogforge-ai-video-skill.git
Set-Location .\vlogforge-ai-video-skill
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap-workspace.ps1 -WithAsr
```

然后在 Codex 中打开该仓库，并使用：

```text
skills/travel-vlog-pipeline/SKILL.md
```

示例：

```text
使用 $travel-vlog-pipeline，把 D:\素材\青岛探店 整理成两分钟左右的美食 Vlog。
保留从到店到离店的完整叙事，不修改原视频，正式渲染前先让我审核故事顺序和技术预览。
```

该 Skill 目前采用工作区本地运行方式。请保留仓库中的 `skills/`，以及安装后生成的 `.vendor/`、`.venv/` 和 `.tools/` 目录关系，以便安全启动器校验完整运行边界。

## 隐私与安全边界

- 默认复制素材，绝不修改原视频。
- 未获得明确同意时，不把视频或抽帧上传给第三方视觉 API。
- 上游依赖按提交、完整目录哈希和文件数量锁定。
- 发现字节码缓存、软链接、目录联接或依赖变化时直接停止。
- 故事板审核不等于正式渲染授权；必须继续检查编译结果和技术预览。
- 自动 QA 只是证据，最终仍需真实观看、试听和完整解码。

## 第三方依赖说明

本项目不会复制发布 `.vendor` 中的第三方源码。启动脚本会从原作者仓库下载指定版本，并在本地校验完整目录：

- `maxazure/video-editing-skill`：负责项目结构、渲染与 QA；检查到的版本没有根许可证，因此只作为本地依赖使用。
- `znyupup/ai-video-editing-skill`：提供 Vlog 叙事参考；检查到的版本采用 MIT License。

如果这个项目对你有帮助，欢迎点一个 Star，让更多需要本地 AI 视频剪辑工作流的人看到它。
