# MeetingMind 前后端 API 契约

> 运行中 API 的权威 OpenAPI 文档：`http://127.0.0.1:8000/docs`、`/redoc`、`/openapi.json`。使用说明见 `docs/OpenAPI使用说明.md`；隐私与数据边界见 `docs/隐私与数据边界.md`。

前端页面只通过 Pinia Store 和 `MeetingApi` 访问数据；默认实现为 `frontend/src/api/httpApi.ts`，不再使用 Mock API。

## 部署级访问控制

配置 `MEETINGMIND_API_TOKEN` 后，除 `/health`、`/health/ready`、`/auth/status` 和 OpenAPI 文档外，所有业务请求必须发送 Bearer 令牌。前端从 `sessionStorage` 读取令牌并注入 `Authorization`，不会将令牌编译进静态资源。401 使用稳定错误码 `ACCESS_TOKEN_REQUIRED` / `ACCESS_TOKEN_INVALID`。该令牌不是用户身份或角色授权。

## 会议与任务

- `GET /api/v1/meetings`：获取会议列表
- `POST /api/v1/meetings`：以 `multipart/form-data` 上传录音并创建异步转录任务
- `GET /api/v1/meetings/{meeting_id}`：获取会议详情、转录、当前分析和任务状态
- `GET /api/v1/jobs/{job_id}`：查询任务状态
- `DELETE /api/v1/meetings/{meeting_id}`：永久删除会议、关联数据库记录和本地文件

上传字段：`file`、`title`、`meeting_started_at`、`participants`（JSON 字符串数组）、`context` 和 `data_processing_confirmed`。确认字段必须为 `true`；否则返回 `422 DATA_PROCESSING_CONFIRMATION_REQUIRED`，且不会保存文件。

## AI 分析与人工审核

- `GET /api/v1/meetings/{meeting_id}/analysis`：读取当前分析结果
- `POST /api/v1/meetings/{meeting_id}/analysis`：将已经保存的带时间戳转录、会议时间和背景发送给模型服务，生成结构化 AI 草稿；原始音频不会发送
- `PATCH /api/v1/meetings/{meeting_id}/analysis`：整体保存人工审核结果

每次 `POST /analysis` 必须发送 `{ "analysis_data_confirmed": true }`。缺失或为 `false` 时返回 `422 ANALYSIS_DATA_CONFIRMATION_REQUIRED`，不会调用模型服务。系统不会自动脱敏，调用方必须在每次生成或重新生成前自行确认内容适合外发。

`PATCH` 请求必须包含当前 `version`。若版本过期，后端返回 `409` 和 `ANALYSIS_VERSION_CONFLICT`；前端会重新加载最新内容，避免覆盖他人的修改。

## 开发环境连接

Vite 默认将 `/api` 代理至 `http://127.0.0.1:8000`。如果后端地址不同，可在 `frontend/.env` 中设置：

```env
VITE_API_BASE_URL=http://你的后端地址/api/v1
```

后端允许 `FRONTEND_ORIGIN` 中配置的来源访问 API，并显式允许 `Authorization` 请求头。真实 API Key 只留在后端 `backend/.env/meetingmind.env`，前端不会读取或保存该密钥。

## 第五阶段：说话人与导出

- `PATCH /api/v1/meetings/{meeting_id}/speakers`：提交 `{ "mappings": [{ "speaker_label": "SPEAKER_00", "speaker_name": "张三" }] }`；原始标签不变，详情页显示姓名。
- `GET /api/v1/meetings/{meeting_id}/exports/markdown`：下载当前人工审核后的 Markdown。
- `GET /api/v1/meetings/{meeting_id}/exports/calendar`：下载 Outlook 兼容的 ICS `VEVENT`。文件以 UTF-8 BOM 输出，避免 Outlook 的实际导入路径将中文按本地代码页错误解码；仅包含有明确或人工确认截止时间的待办，每条待办表示为截止前 1 小时开始、截止时结束的透明日历事件。没有可导出的待办时返回 `409 NO_EXPORTABLE_ACTION_ITEMS`。


## 第五阶段任务恢复字段

`ProcessingJob` 在原字段基础上增加：

- `error_code: string | null`：稳定、可用于前端和测试判断的错误码；
- `retry_count: number`：服务启动自动恢复次数；
- `diarization_status: NOT_RUN | SUCCEEDED | DEGRADED | DISABLED`：自动说话人分离的明确结果，不能通过标签数量推断；
- `speaker_count: number`：本次自动分离识别到的说话人数。

服务启动时只恢复处于 `PROCESSING` 且阶段为 `QUEUED`、`PREPROCESSING`、`TRANSCRIBING` 或 `DIARIZING` 的音频任务。恢复始终从已保存的原始音频重新执行，不信任可能只写入一半的中间文件；若原始音频不存在，任务终止为 `FAILED / SOURCE_FILE_MISSING`。


## OpenAPI 与第五阶段分离语义

OpenAPI 将接口分为健康检查、会议与处理任务、AI 分析与审核、说话人与导出四组，并在 `/docs`、`/redoc` 与 `/openapi.json` 提供运行时契约。上传成功只表示任务已入队（`202 Accepted`）；调用方必须轮询任务直到 `SUCCEEDED` 或 `FAILED`。

自动分离成功时，任务为 `diarization_status=SUCCEEDED`；未配置令牌或推理失败时会保留转录，以 `DEGRADED` 和 `SUCCEEDED_WITH_WARNINGS` 标记。单人会议同样可能只有 `SPEAKER_00`，因此不能把单一标签误判为分离失败。
