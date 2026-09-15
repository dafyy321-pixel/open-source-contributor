# 开源贡献助手

一个用于 Codex 的个人 skill：评估 GitHub 仓库、发现真实贡献机会，并在选题后推进复现、修复、验证和开源协作。

## 使用

安装后，在 Codex 中输入：

```text
$open-source-contributor 分析 https://github.com/owner/repo
```

默认先提供仓库评估、贡献规则和最多三个候选问题。选定问题后可以继续：

```text
$open-source-contributor 深入检查第二个候选，确认如何复现。
$open-source-contributor 修复这个 Issue：链接，完成本地验证并准备 PR 草稿。
$open-source-contributor 继续处理这个 PR：链接。
$open-source-contributor 整理这次贡献的技术复盘和简历素材。
```

## 安装

下载或克隆本仓库，将 `open-source-contributor` 文件夹放入个人 Codex skills 目录：

- 设置了 `CODEX_HOME`：`$CODEX_HOME/skills/open-source-contributor`
- 未设置：`~/.codex/skills/open-source-contributor`

确保 `SKILL.md` 直接位于该目录内。已有同名 skill 时，先检查现有修改再更新。

也可以请 Codex 使用 skill-installer 从本 GitHub 仓库安装。

## 包含的流程

- 调查项目职责、贡献指南、AI 辅助政策和外部贡献接受情况。
- 结合 Issues、PR、官方社区和公开讨论，核实问题、查重与评估成本。
- 根据仓库技术栈选择最小有效复现环境，完成聚焦的修复和验证。
- 准备 Issue/PR 内容，处理 CI、Review 和后续修改。
- 保存工作记录，支持中断恢复、贡献复盘与持续选题。

公开发布按用户实际授权执行。定期检查需要用户启用并由宿主调度工具支持；skill 本身不会常驻运行。AI 的分析不能代替真实复现，也不保证 PR 被合并。

## 文件

| 路径 | 用途 |
|---|---|
| [SKILL.md](SKILL.md) | 入口、默认行为与阶段路由 |
| [references/](references/) | 调查、实现、协作、记录、复盘与验收说明 |
| [scripts/workflow.py](scripts/workflow.py) | 本地工作记录和恢复 |
| [scripts/github_snapshot.py](scripts/github_snapshot.py) | 有界的 GitHub 只读首轮取样 |
| [tests/test_helpers.py](tests/test_helpers.py) | 辅助工具测试 |

两个辅助工具使用 Python 3.10+ 标准库。快照工具需要网络；实际贡献任务还需要目标仓库对应的开发工具。脚本取样不等于完整的仓库评估。

个人工作记录默认保存在 `~/.codex/open-source-contributions`，或已设置的 `CODEX_HOME` 下，不写入准备提交给上游的代码仓库。

## 验证

在仓库目录中运行：

```bash
python -m unittest discover -s tests -v
```

完整的技能行为检查见 [验收场景](references/evaluations.md)。
