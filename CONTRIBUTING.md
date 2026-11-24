# 贡献指南

感谢你愿意改进 SFM Code Workshop。

## 开发环境

- Windows 10/11
- Python 3.12
- PySide6 6.8.3

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m sfm_workshop
```

## 提交前

1. 跑完整测试：`.venv\Scripts\python -m pytest -q`；
2. 不提交 `.venv/`、`dist/`、`build/`、用户工程、日志、截图临时文件；
3. 不提交真实 API Key、`.env`、个人目录或机器路径；
4. UI 改动请附截图或录屏，并说明明暗主题下的表现；
5. 生成代码/校验相关改动请补测试，覆盖错误路径。

## Pull Request

- 保持改动聚焦，避免无关格式化；
- 描述问题、根因、修复方式和复验命令；
- 不删除既有入口来“简化”问题；交互变更需说明兼容性；
- MPL-2.0 下贡献，提交即表示同意以同许可证分发。

## Issue

请提供：

- 应用版本 / 是否便携包；
- Windows 版本；
- 复现步骤、期望结果、实际结果；
- 相关日志（`%APPDATA%\SFMCodeWorkshop\logs`）和截图；
- 请先移除日志中的个人路径、服务器地址和 API Key。

## 安全

请不要在公开 Issue 中粘贴 API Key 或未修复漏洞细节；使用仓库的 Security Advisory。
