---
kind: issue
title: "恢复本地开发与联调基线"
type: ff
status: closed
created: 2026-09-08
epic: ""
---

## 做了什么
恢复锁定依赖，解决端口、Docker Desktop 网络和单测隔离问题，使本机可以继续开发。前端运行于 `127.0.0.1:5173`，API 为 `127.0.0.1:18000`；原始资料、旧数据卷和其他项目服务保持不动。

## 改了哪些
- `.env`：API 端口改为 18000；S3 改用本机随机非默认凭据，仍不受 Git 跟踪且权限 600。
- `compose.local.yaml`、`scripts/local-proxy.conf.template`：Desktop 使用桥接服务发现与同网络命名空间的 loopback API 代理，只向宿主机 loopback 发布；保留 `LOCAL_ACCESS_ONLY`，屏蔽调用者转发头并校验代理健康。
- `backend/tests/conftest.py`、`test_difficulty_evidence_api.py`、`test_rag.py`、`test_test_isolation.py`：禁止依赖自动加载真实 dotenv、逐测试重置配置、注入工作区仓储输入、阻止单测外部网络/数据库访问；集成测试仅操作临时数据库，补 11 项隔离回归。未修改生产业务逻辑。
- `frontend/playwright.config.ts`、`frontend/e2e/layout.responsive.spec.ts`：浏览器端口显式可选且禁止自动漂移；回收站测试等待真实列表加载完成，消除 180ms 延迟加载窗口中的点击竞态。
- `frontend/e2e/__screenshots__/linux/` 与相邻 README：经图像/几何对照建立 Linux 基线，保留旧参考图及原阈值；差异包含字体指标和既有主题底色，不声称全是 OS 差异。根 README 补本地启动、验证与安全边界。

## 怎么验证的
后端 `539 passed, 39 deselected`；真实 PostgreSQL/S3 集成 `36 passed, 542 deselected`；前端 22 个文件 / 179 项 Vitest、7 项 Playwright（不带更新标志）通过。Ruff、格式、BasedPyright、架构、OpenAPI、ESLint、TypeScript/Vite 和 Compose 配置通过。实际浏览器验证科目、详情、资料、知识库、试卷和复核页，无 JS 错误或失败 API 请求；390px 页面无横向溢出。API/代理、PostgreSQL、Qdrant 与 S3 可用，API/两 Worker/GC 使用同一镜像，Alembic 为 `20260820_0028`。

## 对 codestable/ 的影响
无业务规格变更；保持单机单用户、人工评分复核和模型调用边界。已在 README 记录开发运维方式。当前新开发库仅注册数学/经济，资料和向量仍为 0；2025 份原始资料没有被自动入库，旧卷没有自动迁移，未执行付费建库或供应商验收。
