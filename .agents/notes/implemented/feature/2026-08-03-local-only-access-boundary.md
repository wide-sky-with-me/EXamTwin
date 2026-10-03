# Agent Note: 本机单用户边界由 loopback、Host/Origin 校验与健康降级共同守住

Status: implemented

## Problem

系统没有认证、授权或租户边界。PostgreSQL 与 Qdrant 端口曾监听所有地址；关闭本地访问中间件后 API 裸露
而健康检查仍显示正常；loopback 检查与 CORS 不能阻止恶意网页向本机 API 发起简单 POST，WebSocket 也缺少
Origin 校验。

## Decision

- PostgreSQL、Qdrant、SeaweedFS 与 API 只监听 loopback；ASGI 边界拒绝非 loopback 的 HTTP 与 WebSocket。
- HTTP 与 WebSocket 都校验 Host 与浏览器 Origin：允许配置的 `CORS_ORIGINS` 与本机同源，保留无 Origin 的
  本机 CLI 请求，拒绝任意 Host 与不可信 Origin。CORS 响应头不承担阻止副作用请求的职责。
- `LOCAL_ACCESS_ONLY=false` 且绑定非 loopback 时，健康检查返回 `degraded` 并指出没有认证边界，容器健康
  检查因此失败。
- 内部异常与供应商响应不回显给客户端，只返回稳定错误码。
- 多用户或 LAN 部署前必须先建立认证、授权与租户绑定。

## Alternatives considered

- **依赖 CORS 限制浏览器访问** — 已有配置即可。CORS 只限制读取响应，不阻止简单请求的副作用。
- **现在实现账号与认证** — 一次解决暴露问题。当前产品明确为本机单用户，认证属于独立的多用户范围。

## Consequences

- **收益**：误配置可直接从健康状态观察；默认部署不暴露到 LAN。
- **代价与已知上限**：自定义前端域名必须加入 `CORS_ORIGINS`；这仍不是认证，不能直接公开部署。
