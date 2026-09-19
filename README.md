# MeetingMind

[![MeetingMind CI](https://github.com/TY-SF/meetingmind/actions/workflows/ci.yml/badge.svg)](https://github.com/TY-SF/meetingmind/actions/workflows/ci.yml)

MeetingMind 是一个本地优先的中文会议音频整理项目。

截至 2026 年 9 月 19 日：

- 第一阶段：FastAPI 最小闭环，已完成
- 第二阶段：FFmpeg + WhisperX 中文转录，已完成
- 第三阶段：MySQL 8 持久化，已完成
- 第四阶段：AI 分析后端已完成，并已通过真实 OpenAI + MySQL 链路验证
- 第五阶段：说话人映射、Outlook 兼容 ICS、Markdown 导出、启动恢复、Gold Standard 评估和 GitHub Actions 工作流已完成
- 前端已切换至真实 FastAPI HTTP API（开发环境通过 Vite 代理）
- 已接入 WhisperX + pyannote 自动说话人分离，失败时保留转录并明确标记降级
- 第六阶段：Redis + RQ、Docker Compose、媒体预检、WhisperX 对齐、任务重试、队列故障恢复、结构化日志与删除补偿，已完成
- 第七阶段：发布级自动检查、Docker Compose 校验、Redis/RQ Worker 门禁、真实链路验收、故障恢复验收和无敏感值 JSON 检查报告已完成；当前为本地单机发布候选
- 第八阶段进行中：访问令牌、HTTPS/Caddy、一致性备份与隔离恢复、有界结构化日志和本地运行监控已完成；下一项为容量、限流与正式多人身份系统
- Outlook Classic 已完成 ICS 实际导入验收，中文内容和 Asia/Shanghai 时间转换正确
- 三组非敏感合成音频已完成上传、RQ、WhisperX、pyannote、OpenAI、导出和删除的端到端验收；最新脱敏证据为 `evaluation/reports/day7-e2e-latest.json`
- GitHub Actions 已连接远程仓库并持续运行；后端测试、完整 Git 历史审计、Gold Standard、Day-7 证据校验、前端测试和生产构建均纳入主分支门禁



第七阶段说明见 `D:\MeetingMind\docs\第七阶段开发说明.md`；第八阶段说明见 `D:\MeetingMind\docs\第八阶段开发说明.md`；接口文档见 `D:\MeetingMind\docs\OpenAPI使用说明.md`；演示脚本见 `D:\MeetingMind\docs\演示材料.md`；可重复执行的发布前检查见 `D:\MeetingMind\docs\发布前检查清单.md`。 本次本地检查记录见 `D:\MeetingMind\docs\发布前检查记录-2026-09-17.md`。

完整设计基线见 `D:\MeetingMind\MeetingMind开发设计文档.md`，后端说明见 `D:\MeetingMind\backend\README.md`。

统一运行数据目录的迁移与复验记录见 `D:\MeetingMind\docs\运行数据目录迁移记录-2026-09-17.md`。

隐私、外部模型传输与无自动脱敏边界见 `D:\MeetingMind\docs\隐私与数据边界.md`。 访问控制与部署边界见 `D:\MeetingMind\docs\访问控制与部署边界.md`。 HTTPS 与反向代理见 `D:\MeetingMind\docs\HTTPS与反向代理.md`。 备份与恢复边界见 `D:\MeetingMind\docs\数据库与会议文件备份恢复.md`。 日志与监控边界见 `D:\MeetingMind\docs\日志保留监控与告警.md`。 验证记录见 `D:\MeetingMind\docs\HTTPS反向代理验证记录-2026-09-17.md`。 验证记录见 `D:\MeetingMind\docs\访问控制验证记录-2026-09-17.md`。 验证记录见 `D:\MeetingMind\docs\隐私数据边界验证记录-2026-09-17.md`。

## 本机完整启动（推荐）

不要直接调用系统 `python`，也不要手工猜测虚拟环境。项目启动入口会自动选择已验证的完整音频运行环境。

```powershell
cd D:\MeetingMind
.\scripts\start_local_stack.ps1 -WithHttps
```

该命令会启动并检查 MySQL、Redis，执行数据库迁移，启动 FastAPI 和 RQ Worker，构建前端并启动 Caddy。完成后访问 `https://localhost:8443`。

如需 Vite 开发模式，先执行 `.\scripts\start_local_stack.ps1`，再在另一个 PowerShell 中执行 `cd D:\MeetingMind\frontend; npm run dev`，访问 `http://localhost:5173`。
## 第六阶段基础设施启动

1. 将 `.env.compose.example` 复制为 `.env.compose`，填写两项 Docker 密码（该文件已被 Git 忽略）。
2. 在 `D:\MeetingMind` 执行：

```powershell
docker compose --env-file .env.compose up -d mysql redis
.\scripts\start_rq_worker.ps1
```

后端的 `backend\.env\meetingmind.env` 需要配置 `REDIS_URL=redis://127.0.0.1:6379/0` 和 `MEETINGMIND_QUEUE_BACKEND=rq`。API 与 RQ Worker 必须同时运行；Redis 不可用时上传会返回 `503 QUEUE_UNAVAILABLE`，不会伪装成已进入队列。Windows 下 `start_rq_worker.ps1` 会使用兼容的 `SimpleWorker`；需要后台常驻时执行 `scripts\start_rq_worker_background.ps1`。可通过带 Bearer 令牌的 `GET /api/v1/health/queue` 检查 Redis 与 Worker。真实发布配置还必须设置至少 32 个字符的 `MEETINGMIND_API_TOKEN`。

## 前端快速启动

先启动后端，再启动前端。前端会把 `/api` 请求代理到 `http://127.0.0.1:8000`：

```powershell
cd D:\MeetingMind\frontend
npm install
npm run dev
```

## 后端快速启动

```powershell
cd D:\MeetingMind
$env:PYTHONPATH = "D:\MeetingMind\backend"
$venv = (& .\scripts\resolve_runtime_venv.ps1 -RequireAudio | Select-Object -Last 1).Trim()
& (Join-Path $venv 'Scripts\python.exe') -m uvicorn app.main:app --app-dir backend --reload
```

## 第五阶段验证摘要

截至 2026 年 9 月 19 日：

- 后端自动化测试：`73 passed`（包含备份/恢复、日志遮盖/轮转和运行监控边界测试）；
- 前端 Vitest 单元测试：`18 passed`；
- 前端类型检查和生产构建：通过；
- 三组受控 Gold Standard：结构化输出成功率、待办 Precision/Recall、负责人、日期和状态指标均为 `1.0`；
- 中断音频任务会校验源文件哈希与处理配置，并从最近一个原子写入的有效阶段检查点继续；
- Outlook ICS 使用 `VEVENT`、UTF-8 BOM、CRLF 和 UTF-8 字节级折行。

评估样本规模很小，只用于回归和项目验收，不代表生产环境准确率。评估方法与结果见 `D:\MeetingMind\evaluation\README.md` 、`D:\MeetingMind\evaluation\reports\latest.json` 和 `D:\MeetingMind\evaluation\reports\day7-e2e-latest.json`。
