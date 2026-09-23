---
kind: issue
title: "数学与经济首批核心知识库构建"
type: ff
status: closed
created: 2026-09-08
epic: ""
---

## 做了什么
用户确认允许两份官方大纲与四本教材共6PDF/1497页用于本机知识库和外部解析/Embedding服务。通过Workspace上传、先大纲样本验证、串行版本构建，完成数学9660和经济9640核心库v1；未扩展试卷、图谱审核、难度评级。

## 改了哪些
- `scripts/local-proxy.conf.template`：代理26MiB上限错误拦截合法教材，改257MiB容纳业务256MiB上限和multipart；API各自的更小限制仍保留。已通过真实65.2MiB教材上传与nginx配置/健康检查。
- PostgreSQL/S3/Qdrant：6份授权core_knowledge原件和转换缓存、2份published版本及live alias。数学1128页/5014向量（版本611c7915-888b-48d4-99d8-f1d41a8a1d8f），经济369页/2086向量（版本16cb3ebe-2fad-4c9d-8b88-b1f1c4f4e2ad）。经济仅有AS教材，官方大纲选与当前包一致的v2.0。
- `data/local-builds/20260908-core/`：保留输入manifest、单次请求journal、逐文档向量覆盖、检索日志、真实页面截图与执行/验收脚本，详见其中README。

## 怎么验证的
两个build均HTTP200/published且failed=0。全量扫描7100个live点，6原件均有向量、科目/来源符合预期；5个真实检索各4命中且无串科。真实浏览器确认两科v1、向量数和6文件可见，无JS/接口错误；原PDF SHA256匹配，旧卷只读克隆审计后清理临时克隆，原卷未改。未调用答案LLM；未对逐页引用推断作验收，retriever节点page为空。

## 对 codestable/ 的影响
无业务规格变更；补齐当前开发库数据，不代表图谱、难度证据或试卷库也已构建。不把legacy inventory当Workspace建库，不覆盖旧索引/原件；本机数据状态以API和上述manifest/journal为准。
