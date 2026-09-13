# OpenAPI 文档与接口使用说明

**版本：0.5.0｜更新：2026 年 9 月 12 日**

MeetingMind 的 API 契约由 FastAPI 在运行时生成。以运行中服务的文档为准，避免维护一份可能过期的手写 JSON 副本：

| 文档 | 本机地址 | 用途 |
| --- | --- | --- |
| Swagger UI | `http://127.0.0.1:8000/docs` | 查看、填写参数并在本机调试接口 |
| ReDoc | `http://127.0.0.1:8000/redoc` | 阅读型 API 参考 |
| OpenAPI JSON | `http://127.0.0.1:8000/openapi.json` | 前端、测试或其他工具读取的机器可读契约 |

## 数据边界

- 音频规范化、WhisperX 转录与 pyannote 说话人分离在本机执行。
- 仅在调用 `POST /api/v1/meetings/{meeting_id}/analysis` 时，已保存的**转录文本**才会发送到已配置的模型服务；音频文件不会被该接口发送。
- `OPENAI_API_KEY`、`HF_TOKEN`、MySQL 密码只保存在 `backend/.env/meetingmind.env`，不能放入请求体、前端变量、截图或版本库。

## 接口分组

| 分组 | 关键接口 | 说明 |
| --- | --- | --- |
| 健康检查 | `GET /health`、`GET /health/ready`、`GET /health/queue` | 检查服务、数据库，以及 Redis/RQ Worker 是否可用。 |
| 会议与处理任务 | `POST /meetings`、`GET /meetings/{id}`、`GET /jobs/{id}` | 上传音频、读取会议和轮询异步进度。 |
| AI 分析与审核 | `GET/POST/PATCH /meetings/{id}/analysis`、`GET /analysis/audit` | 生成草稿、人工审核、比对原始草稿和当前结果。 |
| 说话人与导出 | `PATCH /speakers`、`GET /exports/markdown`、`GET /exports/calendar` | 映射显示姓名，下载 Markdown 或 Outlook 兼容 ICS。 |

完整路径均以 `/api/v1` 为前缀。

## 上传与轮询流程

1. `POST /api/v1/meetings` 使用 `multipart/form-data` 上传 `file`、`title`、`meeting_started_at`、`participants`、`context`。
2. 接口返回 `202 Accepted`、`meeting_id` 和 `job_id`，这表示任务已进入队列，**不表示处理完成**。
3. 可并行轮询 `GET /api/v1/health/queue`；若 `worker_online=false`，应启动 Worker。
4. 轮询 `GET /api/v1/jobs/{job_id}`，直到 `stage` 为 `SUCCEEDED` 或 `FAILED`。
5. 成功后读取 `GET /api/v1/meetings/{meeting_id}`；必要时再触发 AI 分析、人工审核和导出。

PowerShell 示例（不包含任何密钥）：

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/meetings `
  -F "file=@C:/path/to/meeting.mp3;type=audio/mpeg" `
  -F "title=产品迭代周会" `
  -F "meeting_started_at=2026-09-10T14:00:00+08:00" `
  -F "participants=[\"张三\",\"李四\"]" `
  -F "context=确认版本范围与交付安排"
```

`participants` 是一个 **JSON 字符串数组**，不是逗号分隔文本；最多支持 10 人。音频仅支持 MP3、WAV、M4A，默认上限为 200 MB，实际值以后端配置和运行中的 OpenAPI 为准。

## Redis/RQ 队列健康

`GET /api/v1/health/queue` 返回：

- `redis=ok`：Redis 可连接；
- `worker_online=true`：至少一个 Worker 心跳正常；
- `queue_length`：等待执行任务数；
- `intermediate_job_count`：RQ 中间队列任务数；
- `started_job_count`：已开始执行的任务数。

Worker 缺失不会让 API 假装任务已处理；处理页会显示启动提示。超过 `RQ_STALE_JOB_SECONDS` 的遗留任务会被标记为失败，并可通过 `POST /api/v1/jobs/{job_id}/retry` 重新执行。

## 处理与说话人分离状态

`ProcessingJob.stage` 的正常顺序为：

```text
QUEUED → PREPROCESSING → TRANSCRIBING → ALIGNING → DIARIZING → SUCCEEDED
```

`stage_events` 保存每次阶段的真实开始时间、结束时间、耗时和自动恢复尝试编号。服务中断后，系统会从不可变的原始音频重新执行可恢复任务；RQ Worker 异常退出时，任务会被对账为 `FAILED`，错误码为 `QUEUE_JOB_INTERRUPTED` 或 `QUEUE_JOB_FAILED`，之后可调用重试接口。

`diarization_status` 不应通过 `SPEAKER_00` 是否存在来推断，因为单人会议也可能只有一个标签：

| 值 | 含义 | 会议状态 |
| --- | --- | --- |
| `SUCCEEDED` | 已完成 pyannote 自动说话人分离 | `SUCCEEDED`（无其他警告时） |
| `DEGRADED` | 分离失败或缺少可用令牌，保留转录并使用默认标签 | `SUCCEEDED_WITH_WARNINGS` |
| `DISABLED` | 当前部署配置显式关闭自动分离 | 可正常完成 |
| `NOT_RUN` | 旧记录或尚未执行到该能力 | 不应误报已完成 |

## AI 审核与并发控制

- `POST /analysis` 只在转录已存在且后端配置了模型服务凭据时可调用。
- `PATCH /analysis` 必须发送当前 `version`；保存成功后版本递增。
- 版本已过期时，接口返回 `409` 和 `ANALYSIS_VERSION_CONFLICT`。调用方必须重新读取结果，不能以旧版本覆盖新审核内容。
- `GET /analysis/audit` 返回 AI 原始草稿、当前人工结果以及发生变化的字段，便于演示人工审核边界。

## 导出约束

- Markdown 与 ICS 均要求已存在分析结果，否则返回 `409`。
- ICS 只包含截止时间为 `EXPLICIT` 或 `CONFIRMED` 的待办。
- ICS 使用 `VEVENT`、UTF-8 BOM、CRLF 与 UTF-8 字节级折行，以兼容 Outlook 导入路径；无可导出的待办时返回 `409 NO_EXPORTABLE_ACTION_ITEMS`。

## 发布前契约校验

执行 `scripts/pre_release_check.ps1` 会访问 `/openapi.json`，确认文档端点、关键路径和 `ProcessingJob` 的说话人分离字段存在。接口或 Schema 改动后，应同步更新本文件、`docs/api-contract.md` 和自动化测试。
