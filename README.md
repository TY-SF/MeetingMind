# MeetingMind

MeetingMind 是一个本地优先的中文会议音频整理项目。

截至 2026 年 9 月 11 日：

- 第一阶段：FastAPI 最小闭环，已完成
- 第二阶段：FFmpeg + WhisperX 中文转录，已完成
- 第三阶段：MySQL 8 持久化，已完成
- 第四阶段：AI 分析后端已完成，并已通过真实 OpenAI + MySQL 链路验证
- 第五阶段：说话人映射、Outlook 兼容 ICS、Markdown 导出、启动恢复、Gold Standard 评估和 GitHub Actions 已完成
- 前端已切换至真实 FastAPI HTTP API（开发环境通过 Vite 代理）
- 已接入 WhisperX + pyannote 自动说话人分离，失败时保留转录并明确标记降级
- 第六阶段：Redis + RQ、Docker Compose、媒体预检、WhisperX 对齐、任务重试、队列故障恢复、结构化日志与删除补偿，已完成
- 第七阶段：发布级检查脚本、Docker Compose 校验、Redis/RQ Worker 门禁和无敏感值 JSON 检查报告已开始；完整运行态验收进行中



第七阶段说明见 `D:\MeetingMind\docs\第七阶段开发说明.md`；接口文档见 `D:\MeetingMind\docs\OpenAPI使用说明.md`；演示脚本见 `D:\MeetingMind\docs\演示材料.md`；可重复执行的发布前检查见 `D:\MeetingMind\docs\发布前检查清单.md`。 本次本地检查记录见 `D:\MeetingMind\docs\发布前检查记录-2026-09-10.md`。

完整设计基线见 `D:\MeetingMind\MeetingMind开发设计文档.md`，后端说明见 `D:\MeetingMind\backend\README.md`。

## 第六阶段基础设施启动

1. 将 `.env.compose.example` 复制为 `.env.compose`，填写两项 Docker 密码（该文件已被 Git 忽略）。
2. 在 `D:\MeetingMind` 执行：

```powershell
docker compose --env-file .env.compose up -d mysql redis
.\scripts\start_rq_worker.ps1
```

后端的 `backend\.env\meetingmind.env` 需要配置 `REDIS_URL=redis://127.0.0.1:6379/0` 和 `MEETINGMIND_QUEUE_BACKEND=rq`。API 与 RQ Worker 必须同时运行；Redis 不可用时上传会返回 `503 QUEUE_UNAVAILABLE`，不会伪装成已进入队列。Windows 下 `start_rq_worker.ps1` 会使用兼容的 `SimpleWorker`；需要后台常驻时执行 `scripts\start_rq_worker_background.ps1`。可通过 `GET /api/v1/health/queue` 检查 Redis 与 Worker。

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
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:PYTHONPATH = "D:\MeetingMind\backend"
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

## 第五阶段验证摘要

截至 2026 年 9 月 11 日：

- 后端自动化测试：`37 passed`；
- 前端类型检查和生产构建：通过；
- 三组受控 Gold Standard：结构化输出成功率、待办 Precision/Recall、负责人、日期和状态指标均为 `1.0`；
- 中断音频任务可在服务重启后从原始音频自动恢复；
- Outlook ICS 使用 `VEVENT`、UTF-8 BOM、CRLF 和 UTF-8 字节级折行。

评估样本规模很小，只用于回归和项目验收，不代表生产环境准确率。评估方法与结果见 `D:\MeetingMind\evaluation\README.md` 和 `D:\MeetingMind\evaluation\reports\latest.json`。

