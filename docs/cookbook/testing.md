# 测试与检查

普通回归从项目根目录执行，不依赖容器，不读取或调用真实供应商凭据。改了哪一层就跑哪一层的检查；
完整矩阵交给 CI（`.github/workflows/ci.yml`）。

## 后端

```bash
uv run ruff check .
uv run ruff format --check backend
uv run basedpyright
uv run python scripts/check_architecture.py
uv run python scripts/export_openapi.py --check frontend/openapi.json
uv run pytest -m "not integration and not local_assets" -q
```

单测阻止外部网络和数据库访问；CI 在 Python 3.11、3.12、3.13 上运行非集成测试。

## 文档与决策笔记

```bash
uv run python scripts/check_docs.py
uv run python scripts/agent_notes.py check
uv run python scripts/build_wiki.py --check
```

## 集成测试

`integration` 测试只在本次生成的临时数据库中迁移和清理，不使用开发库。连接串使用 `postgresql://`。

```bash
EXAMTWIN_TEST_DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:<port>/examtwin_test \
EXAMTWIN_TEST_S3_ENDPOINT=http://127.0.0.1:8333 \
EXAMTWIN_TEST_S3_BUCKET=examtwin \
EXAMTWIN_TEST_S3_ACCESS_KEY=<key> EXAMTWIN_TEST_S3_SECRET_KEY=<secret> \
uv run pytest -m "integration and not local_assets" -q
```

推荐用一次性 PostgreSQL 17 容器提供 `EXAMTWIN_TEST_DATABASE_URL`；S3 往返测试只写入并删除随机
`integration/` 键。宿主 shell 设有 HTTP 代理时，运行前清除代理变量，避免本机请求被转发。

`local_assets` 测试依赖本机原始资料，默认跳过。

## 前端

```bash
cd frontend
pnpm test && pnpm lint && pnpm build && pnpm api:types:check
PLAYWRIGHT_PORT=4175 pnpm test:visual
```

浏览器测试端口必须显式指定空闲端口，不自动漂移。截图基线按平台分目录，见
`frontend/e2e/__screenshots__/README.md`；不要用放宽阈值替代人工对照。原卷导出真实样本测试需设置
`EXAMTWIN_PDF_SAMPLE_DIR`，否则跳过。

## 付费冒烟与评测

`uv run examtwin provider-smoke` 核对真实供应商响应契约；`backend/evals/` 是可重跑的评分准确性评测。
两者都会调用付费模型，只在明确授权后执行。
