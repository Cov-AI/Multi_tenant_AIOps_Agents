# 贡献指南

感谢你考虑为 Multi tenant AIOps Agents 做出贡献！

## 🌟 贡献方式

你可以通过以下方式为项目做出贡献：

- 🐛 报告 Bug
- 💡 提出新功能建议
- 📝 改进文档
- 🔧 提交代码修复或新功能
- 🎨 改进 UI/UX
- 🧪 编写测试用例

## 📋 开始之前

### 1. 了解项目

- 阅读 [README.md](README.md) 了解项目概况
- 查看 [设计文档](.kiro/specs/multi-tenant-oncall-platform/design.md) 了解架构
- 浏览 [ADR 文档](.kiro/specs/multi-tenant-oncall-platform/adr/) 了解技术决策

### 2. 设置开发环境

```bash
# 1. Fork 并克隆仓库
git clone https://github.com/YOUR_USERNAME/super_biz_agent_py.git
cd super_biz_agent_py

# 2. 安装开发依赖
make install-dev

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的配置

# 4. 启动开发环境
make init
```

### 3. 创建分支

```bash
# 从 main 分支创建新分支
git checkout -b feature/your-feature-name

# 或修复 Bug
git checkout -b fix/bug-description
```

## 🔧 开发流程

### 代码规范

我们使用以下工具确保代码质量：

- **black** - 代码格式化
- **isort** - import 排序
- **ruff** - 代码检查
- **mypy** - 类型检查

运行代码检查：

```bash
# 格式化代码
make format

# 运行 linter
make lint

# 类型检查
make type-check
```

### 提交规范

使用清晰的提交信息，遵循以下格式：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Type 类型**：
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `style`: 代码格式（不影响功能）
- `refactor`: 重构
- `test`: 测试相关
- `chore`: 构建/工具相关

**示例**：

```bash
feat(aiops): 添加自动重试机制

- 在 MCP 调用失败时自动重试 3 次
- 使用指数退避策略
- 添加重试次数的 Prometheus 指标

Closes #123
```

### 测试

在提交 PR 前，确保：

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_aiops.py

# 查看测试覆盖率
pytest --cov=app --cov-report=html
```

## 📝 提交 Pull Request

### 1. 确保代码质量

```bash
# 运行所有检查
make format
make lint
make type-check
pytest
```

### 2. 更新文档

如果你的更改影响了：
- API 接口 → 更新 README.md 的 API 部分
- 配置选项 → 更新 .env.example 和配置说明
- 架构设计 → 考虑更新设计文档或创建 ADR

### 3. 创建 Pull Request

1. 推送你的分支到 GitHub
   ```bash
   git push origin feature/your-feature-name
   ```

2. 在 GitHub 上创建 Pull Request

3. 填写 PR 模板（如果有）

4. 等待 Review

### PR 检查清单

- [ ] 代码通过所有测试
- [ ] 代码符合项目规范（black、ruff、mypy）
- [ ] 添加了必要的测试用例
- [ ] 更新了相关文档
- [ ] 提交信息清晰明确
- [ ] 没有不相关的文件更改
- [ ] 解决了所有 Review 意见

## 🐛 报告 Bug

### 提交 Bug 报告前

1. 检查是否已有相同的 Issue
2. 确认是否是最新版本的问题
3. 收集必要的信息

### Bug 报告模板

```markdown
**描述问题**
清晰简洁地描述 Bug

**复现步骤**
1. 执行 '...'
2. 点击 '...'
3. 看到错误

**期望行为**
描述你期望发生什么

**实际行为**
描述实际发生了什么

**环境信息**
- OS: [e.g. macOS 13.0]
- Python 版本: [e.g. 3.10.8]
- 项目版本: [e.g. commit hash]

**日志**
```
粘贴相关日志
```

**截图**
如果适用，添加截图
```

## 💡 功能建议

### 提交功能建议前

1. 检查是否已有类似建议
2. 确认功能符合项目定位
3. 考虑实现的可行性

### 功能建议模板

```markdown
**功能描述**
清晰描述你想要的功能

**使用场景**
描述这个功能解决什么问题

**建议的实现方式**
如果有想法，描述可能的实现方式

**替代方案**
是否考虑过其他解决方案

**额外信息**
其他相关信息或参考资料
```

## 📐 架构决策记录（ADR）

如果你的贡献涉及重要的架构决策，请创建 ADR 文档：

1. 复制 [ADR 模板](.kiro/specs/multi-tenant-oncall-platform/adr/template.md)
2. 填写决策的上下文、理由和后果
3. 在 PR 中包含 ADR 文档

## 🎯 优先级

我们特别欢迎以下方面的贡献：

- 🔥 **高优先级**
  - Bug 修复
  - 性能优化
  - 安全问题修复
  - 文档改进

- 📌 **中优先级**
  - 新功能实现
  - 测试覆盖率提升
  - 代码重构

- 💡 **低优先级**
  - UI/UX 改进
  - 示例代码
  - 工具脚本

## 🤝 行为准则

### 我们的承诺

为了营造开放和友好的环境，我们承诺：

- 使用友好和包容的语言
- 尊重不同的观点和经验
- 优雅地接受建设性批评
- 关注对社区最有利的事情
- 对其他社区成员表示同理心

### 不可接受的行为

- 使用性暗示的语言或图像
- 人身攻击或侮辱性评论
- 公开或私下骚扰
- 未经许可发布他人的私人信息
- 其他不道德或不专业的行为

## 📞 联系方式

如有问题，可以通过以下方式联系：

- 提交 [GitHub Issue](../../issues)
- 发送邮件到项目维护者

## 📄 许可证

通过贡献代码，你同意你的贡献将在 [MIT License](LICENSE) 下发布。

---

再次感谢你的贡献！🎉
