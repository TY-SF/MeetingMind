# HTTPS 与反向代理边界

> 更新日期：2026 年 9 月 17 日。当前仓库提供已实际验证的本机 HTTPS 边界和生产 Caddy 示例；真实公网域名、可信证书、DNS、防火墙与云网络仍需在目标部署环境完成。

## 第一性原则

Bearer 令牌只证明客户端持有秘密。如果传输链路没有 TLS，令牌和会议数据都可能被窃听。因此访问控制之后必须立即建立加密传输边界，并让后端 API 继续处于不可直接暴露的位置。

MeetingMind 的边界设计是：

```text
浏览器 / API 客户端
        │ HTTPS
        ▼
Caddy：TLS、静态前端、安全响应头、请求体上限
        │ 仅主机内部或私有容器网络 HTTP
        ▼
FastAPI 127.0.0.1:8000
```

## 本机 HTTPS 边界

仓库包含：

- `deploy/Caddyfile.local`：使用 Caddy 内部 CA 签发 `localhost` 证书；
- `docker-compose.yml` 的 `edge` profile：只绑定回环地址；
- `scripts/start_secure_edge.ps1`：构建前端、启动 Caddy并等待 HTTPS 就绪；
- `scripts/stop_secure_edge.ps1`：停止边界容器；
- `scripts/validate_secure_edge.ps1`：验证 Compose、本地 Caddyfile 和生产示例。

启动：

```powershell
cd D:\MeetingMind
.\scripts\start_secure_edge.ps1
```

默认地址：

- HTTPS：`https://localhost:8443`
- HTTP：`http://localhost:8080`，返回 308 并跳转到 HTTPS

端口可在被 Git 忽略的 `.env.compose` 中修改：

```env
EDGE_HTTP_PORT=8080
EDGE_HTTPS_PORT=8443
```

默认只绑定 `127.0.0.1`，不会因为启动 Caddy 而自动向局域网或公网开放。

### 本地证书信任

`tls internal` 使用 Caddy 内部 CA。自动检查通过 `curl -k` 验证加密链路，但这不等于操作系统或浏览器信任该 CA。未安装根证书时浏览器会显示证书不受信任，这是本地开发预期行为。

根证书位于 Caddy 数据卷中的：

```text
/data/caddy/pki/authorities/local/root.crt
```

安装根证书会改变操作系统信任库，应由使用者明确决定并按组织安全流程执行；自动化脚本不会擅自安装。

## 路由边界

Caddy 将以下路径反向代理到主机回环 API：

- `/api/*`
- `/docs*`
- `/redoc*`
- `/openapi.json`

其他路径从 `frontend/dist` 提供静态文件，并回退到 `index.html` 支持 Vue Router。

Docker Desktop 中，容器通过 `host.docker.internal:8000` 连接仅监听 `127.0.0.1:8000` 的 API。生产示例默认让同主机 Caddy 连接 `127.0.0.1:8000`；如果使用容器网络，应改为只在私有网络可解析的服务名，不能直接公开 API 端口。

## 安全控制

本机和生产配置均包含：

- HTTP 自动跳转 HTTPS；
- gzip / zstd 压缩；
- 最大 210 MB 的边界请求体限制，后端仍执行更严格的默认 200 MB 音频限制；
- `Content-Security-Policy`；
- `X-Content-Type-Options: nosniff`；
- `X-Frame-Options: DENY`；
- `Referrer-Policy: no-referrer`；
- 禁用摄像头、麦克风和定位的 `Permissions-Policy`；
- 移除 HTTPS 业务响应的 `Server` 标头；
- API 自身额外返回 `Cache-Control: no-store`，避免会议数据被浏览器或中间缓存保存；
- 两小时上游响应头超时，避免长音频处理相关请求被过早切断；
- Docker Caddy 日志轮换上限为 10 MB × 5 个文件。

生产示例额外包含一年 HSTS。只有在真实域名、可信证书和所有子域均已确认支持 HTTPS 后才应启用 `includeSubDomains`。

## 生产部署示例

`deploy/Caddyfile.production.example` 不使用内部 CA，由 Caddy 为真实域名申请可信证书。部署前必须：

1. 将示例域名改为实际 DNS 名称；
2. 确保 80/443 只指向反向代理；
3. 保持 FastAPI 监听回环或私有容器网络；
4. 配置持久化且有限期的 Caddy 日志目录；
5. 设置并轮换 `MEETINGMIND_API_TOKEN`；
6. 将 `FRONTEND_ORIGIN` 限定为实际 HTTPS 来源；
7. 验证证书自动续期、HTTP→HTTPS、上传大小和长请求超时；
8. 在防火墙/安全组中禁止直接访问 8000、3306 和 6379。

## 验证命令

```powershell
.\scriptsalidate_secure_edge.ps1
.\scripts\pre_release_check.ps1 -ReportPath .\dataelease-check\phase8-https-edge-final-2026-09-17.json
```

验证包括：

- 两份 Caddyfile 均能被固定版本 Caddy 解析；
- 本地配置明确使用内部 CA，生产示例禁止 `tls internal`；
- 生产示例包含 HSTS 且默认代理到回环 API；
- HTTPS 健康接口可用并带 CSP、nosniff 等响应头；
- HTTPS 受保护业务接口必须使用 Bearer 令牌；
- 前端生产构建和所有既有自动检查继续通过。

## 仍未完成

- 真实公网域名和受信任证书的现场验收；
- 防火墙、安全组或零信任网络策略；
- 正式 OIDC/OAuth2 用户身份；
- 证书到期和反向代理故障告警；
- 生产日志集中收集与审计归属。

下一项按顺序是数据库与 `data/meetings` 的备份、恢复和恢复演练。
