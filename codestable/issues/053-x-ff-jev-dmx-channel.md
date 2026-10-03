---
kind: issue
title: Jev demo 切换 DMX 原生接口
type: ff
status: closed
created: 2026-09-28
---

## 做了什么

按用户要求将独立 Jev demo 和既有口令保护网站切到 DMX `jev-1.13.0`。
原生接口为 `/typesafe/v1/systemone`；此前聊天接口的 503 不能证明 Jev 不可用。
正式项目的 Sol 规划、作答、范围复核和评分保持现状，本次核查其实现而未替换。

## 改了哪些

`demo-jev/`（Git 忽略）：Python 传输、Node 服务端、部署配置和说明；密钥仅服务端读取。
复用同一 Vercel 项目和访问口令，部署只上传七个白名单源文件，秘密扫描通过。

## 怎么验证的

Python 三组共 56 项、网站 11 项测试通过；DMX 原生连通性、选择题及越界范围判断真实调用成功。
公网选择题与范围复核分别约 1.73 / 1.88 秒；未登录与退出后访问被拒绝。只是运行验证，不是准确率评测。
无密钥记录：`demo-jev/results/dmx-native-20260928/`、`demo-jev/site/dmx-validation-20260928.json`。

## 对 codestable/ 的影响

已更正 issue 052 的渠道不可用结论；正式功能规格未变。未提交或推送 Git。
