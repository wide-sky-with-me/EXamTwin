# subject-packs 规则

每个目录是一个声明式 SubjectPack，说明见 [subject-packs](../docs/subsystems/subject-packs.md)，新增步骤见
[adding-a-subject](../docs/cookbook/adding-a-subject.md)。

- 包内只放 `manifest.json`、`SKILL.md`、`retrieval-eval.json` 等数据，不放可执行代码。
- `manifest.json` 只引用宿主已注册的 Board、normalizer、视觉政策与答题能力 ID；新能力先在后端注册。
- `SKILL.md` 只写已审核的学科作答语义；证据、引用与输出不变量属于平台模板，不在这里重复或放宽。
- 修改 manifest 或 SKILL 会改变 Package 摘要，属于非平凡改动，需要更新对应笔记。
- 修改 `retrieval-eval.json` 的门禁阈值需要写明理由；评测运行会外发查询，需要授权。
