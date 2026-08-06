from __future__ import annotations

import asyncio
from typing import Protocol

from examtwin.assessment.answering_agent.contracts import AgentRunContext, AnswerTask, SubjectSkill
from examtwin.assessment.answering_agent.finalization import (
    FinalAnswerProvider,
    materialize_final_answer,
    validate_citation_contract,
)
from examtwin.assessment.answering_agent.llama_index_adapter import LlamaIndexReActProtocolAdapter
from examtwin.assessment.answering_agent.prompts import compose_system_prompt
from examtwin.assessment.answering_agent.run_policy import (
    FINAL_ONLY_OBSERVATION,
    FORMAT_REPAIR_OBSERVATION,
    TOOL_LABELS,
    required_artifact_tools,
    visible_model_output,
)
from examtwin.assessment.answering_agent.tool_lifecycle import AnsweringToolLifecycle
from examtwin.platform.agent_runtime import (
    AgentProtocolPort,
    ChatModelPort,
    HarnessMessage,
    HarnessTool,
    ProtocolEvent,
    ProtocolFinal,
    ProtocolInvalid,
    ProtocolToolCall,
    ToolCallDisposition,
    ToolCallEvent,
    ToolExecutor,
    ToolObservationEvent,
    ToolRunController,
)


class WorkflowRunner(Protocol):
    async def run(
        self,
        *,
        model: ChatModelPort,
        task: AnswerTask,
        skill: SubjectSkill,
        tools: list[HarnessTool],
        context: AgentRunContext,
        max_iterations: int,
        max_tool_calls: int,
        timeout: float,
        initial_observations: tuple[str, ...] = (),
    ) -> str: ...


class ReActHarnessRunner:
    """Compose generic harness primitives with examination-answering policies."""

    def __init__(
        self,
        final_answer_provider: FinalAnswerProvider | None = None,
        *,
        protocol: AgentProtocolPort | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self.final_answer_provider = final_answer_provider
        self.protocol = protocol or LlamaIndexReActProtocolAdapter()
        self.tool_executor = tool_executor or ToolExecutor()

    async def run(
        self,
        *,
        model: ChatModelPort,
        task: AnswerTask,
        skill: SubjectSkill,
        tools: list[HarnessTool],
        context: AgentRunContext,
        max_iterations: int,
        max_tool_calls: int,
        timeout: float,
        initial_observations: tuple[str, ...] = (),
    ) -> str:
        by_name = {tool.spec.name: tool for tool in tools}
        if len(by_name) != len(tools):
            raise ValueError("answering capabilities contain duplicate tool names")
        required_artifact_tool_names = required_artifact_tools(skill, task)
        unavailable_artifact_tools = set(required_artifact_tool_names) - set(by_name)
        if unavailable_artifact_tools:
            raise RuntimeError(
                "question requires unavailable visual tools: "
                + ", ".join(sorted(unavailable_artifact_tools))
            )
        mandatory_tool_names = set(skill.mandatory_tool_names)
        mandatory_tool_names.update(required_artifact_tool_names)
        if task.pair_key and "paired_exam_lookup" in by_name:
            mandatory_tool_names.add("paired_exam_lookup")
        calls = ToolRunController(
            available_tool_names=set(by_name),
            mandatory_tool_names=mandatory_tool_names,
            max_tool_calls=max_tool_calls,
        )
        lifecycle = AnsweringToolLifecycle(context, skill)
        system_prompt = compose_system_prompt(
            skill,
            task,
            required_artifact_tools=required_artifact_tool_names,
            paired_exam_available="paired_exam_lookup" in by_name,
        )
        context.prompt_digest = system_prompt.digest
        if context.ledger is not None:
            context.ledger.start_run(
                package_id=skill.name,
                package_version=skill.version,
                package_digest=skill.package_digest,
                skill_digest=skill.digest,
                prompt_digest=system_prompt.digest,
                model_name=model.model_name,
                max_iterations=max_iterations,
                max_tool_calls=max_tool_calls,
                knowledge_base_version_ids=task.knowledge_base_version_ids,
                graph_version_id=task.graph_version_id,
            )

        events: list[ProtocolEvent] = [
            ToolObservationEvent(content=observation[:12_000])
            for observation in initial_observations
            if observation.strip()
        ]
        corrections: list[HarnessMessage] = []
        structured_finalizer_available = self.final_answer_provider is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        fallback_reserve = min(45.0, timeout / 3)

        def formatted_messages() -> tuple[HarnessMessage, ...]:
            return self.protocol.format_messages(
                system_prompt=system_prompt.text,
                question=task.question,
                tools=tools,
                events=events,
                corrections=corrections,
            )

        async def request() -> str:
            messages = formatted_messages()
            corrections.clear()
            return visible_model_output(await model.complete(messages))

        def queue_protocol_retry(content: str, instruction: str) -> None:
            corrections.extend(
                (
                    HarnessMessage(role="assistant", content=content[-12_000:]),
                    HarnessMessage(role="user", content=instruction),
                )
            )

        def require_mandatory_tools_before_final(content: str) -> bool:
            missing = calls.missing_mandatory
            if not missing:
                return False
            context.emit(
                "deciding",
                "running",
                (
                    "最终回答前正在补齐必要的知识检索"
                    if missing == ("knowledge_search",)
                    else "最终回答前正在补齐必要的答题工具"
                ),
            )
            queue_protocol_retry(
                content,
                (
                    "A final answer is not allowed yet. Call exactly one of these "
                    f"mandatory tools now: {', '.join(missing)}."
                ),
            )
            return True

        async def request_structured_final(draft: str | None = None) -> str | None:
            nonlocal structured_finalizer_available
            if self.final_answer_provider is None or not structured_finalizer_available:
                return None
            structured_budget = deadline - loop.time() - fallback_reserve
            if structured_budget <= 0:
                structured_finalizer_available = False
                context.emit(
                    "deciding",
                    "running",
                    "剩余时间不足以安全整理结构化答案，正在使用兼容恢复",
                )
                return None
            allowed_citation_ids = tuple(
                f"S{index}" for index in range(1, len(context.citations) + 1)
            )
            required_subpart_labels = task.question_spec.labelled_subparts
            try:
                payload = await self.final_answer_provider.finalize(
                    formatted_messages(),
                    draft=draft,
                    allowed_citation_ids=allowed_citation_ids,
                    required_subpart_labels=required_subpart_labels,
                    timeout=structured_budget,
                )
                payload = materialize_final_answer(
                    payload,
                    required_subpart_labels=required_subpart_labels,
                )
                validate_citation_contract(
                    payload,
                    allowed_citation_ids=allowed_citation_ids,
                )
            except Exception:
                structured_finalizer_available = False
                context.emit(
                    "deciding",
                    "running",
                    "结构化答案整理不可用，正在使用兼容恢复",
                )
                return None
            return payload.model_dump_json()

        async def finish_protocol_turn(turn: ProtocolFinal) -> str | None:
            if require_mandatory_tools_before_final(turn.draft):
                return None
            structured = await request_structured_final(turn.draft)
            return structured or turn.output_json

        async def request_final(message: str) -> str:
            if calls.missing_mandatory:
                raise RuntimeError(
                    "answering Agent did not complete mandatory tools: "
                    + ", ".join(calls.missing_mandatory)
                )
            context.emit("deciding", "running", message)
            events.append(ToolObservationEvent(content=FINAL_ONLY_OBSERVATION))
            structured = await request_structured_final()
            if structured is not None:
                return structured
            for _attempt in range(2):
                content = await request()
                turn = self.protocol.parse(
                    content,
                    tools=tools,
                    grounded=bool(context.citations),
                )
                if isinstance(turn, ProtocolFinal):
                    completed = await finish_protocol_turn(turn)
                    if completed is not None:
                        return completed
                queue_protocol_retry(content, FINAL_ONLY_OBSERVATION)
            raise RuntimeError(
                "answering Agent could not produce a valid final answer after recovery"
            )

        async with asyncio.timeout(timeout):
            for _iteration in range(max_iterations):
                content = await request()
                turn = self.protocol.parse(
                    content,
                    tools=tools,
                    grounded=bool(context.citations),
                )
                if isinstance(turn, ProtocolFinal):
                    completed = await finish_protocol_turn(turn)
                    if completed is not None:
                        return completed
                    if calls.missing_mandatory:
                        continue
                    context.emit(
                        "deciding",
                        "running",
                        "Agent 输出格式不完整，正在自动修复",
                    )
                    queue_protocol_retry(content, FORMAT_REPAIR_OBSERVATION)
                    continue
                if isinstance(turn, ProtocolInvalid):
                    context.emit(
                        "deciding",
                        "running",
                        "Agent 输出格式不完整，正在自动修复",
                    )
                    queue_protocol_retry(content, FORMAT_REPAIR_OBSERVATION)
                    continue
                if not isinstance(turn, ProtocolToolCall):
                    raise TypeError("agent protocol returned an unsupported turn")

                events.append(
                    ToolCallEvent(
                        thought=turn.thought,
                        tool_name=turn.tool_name,
                        arguments=turn.arguments,
                    )
                )
                decision = calls.decide(turn.tool_name, turn.arguments)
                label = TOOL_LABELS.get(turn.tool_name, turn.tool_name)
                if decision.disposition == ToolCallDisposition.SUPPRESSED_FAILURE:
                    context.emit(
                        "tool",
                        "failed",
                        f"{label}重复失败，已停止调用",
                        tool_name=turn.tool_name,
                    )
                    events.append(
                        ToolObservationEvent(
                            content=(
                                "This failed tool call was suppressed. Finish from the "
                                "available evidence without calling it again."
                            )
                        )
                    )
                    return await request_final("重复失败工具已停止，正在整理已有结果")
                if decision.disposition == ToolCallDisposition.UNKNOWN:
                    events.append(
                        ToolObservationEvent(content=f"Unknown or forbidden tool: {turn.tool_name}")
                    )
                    continue
                if decision.disposition == ToolCallDisposition.DUPLICATE_SUCCESS:
                    context.emit(
                        "tool",
                        "completed",
                        f"{label}重复请求已复用既有结果",
                        tool_name=turn.tool_name,
                    )
                    events.append(
                        ToolObservationEvent(
                            content=(
                                "This exact successful tool call was already completed. "
                                "Use its existing observation or refine the arguments."
                            )
                        )
                    )
                    continue
                if decision.disposition == ToolCallDisposition.RESERVED_FOR_MANDATORY:
                    events.append(
                        ToolObservationEvent(
                            content=(
                                "This optional tool call was not run because the remaining "
                                "budget is reserved for mandatory tools. Call one of: "
                                + ", ".join(decision.missing_mandatory)
                            )
                        )
                    )
                    continue
                if decision.disposition == ToolCallDisposition.BUDGET_EXHAUSTED:
                    events.append(
                        ToolObservationEvent(
                            content="The tool-call budget is exhausted; this call was not run."
                        )
                    )
                    return await request_final("工具预算已用完，正在整理已有结果")

                tool = by_name[turn.tool_name]
                replay = lifecycle.replay(decision.call)
                if replay is not None:
                    calls.record_success(decision.call)
                    context.emit(
                        "tool",
                        "completed",
                        f"{label}已从持久执行账本复用",
                        tool_name=turn.tool_name,
                    )
                    events.append(ToolObservationEvent(content=replay.content))
                    continue

                context.emit("tool", "running", f"{label}中", tool_name=turn.tool_name)
                calls.mark_started()
                result = await self.tool_executor.execute(
                    decision.call,
                    tool,
                    lifecycle,
                    allow_replay=False,
                )
                if result.is_error:
                    calls.record_failure(decision.call)
                else:
                    calls.record_success(decision.call)
                context.emit(
                    "tool",
                    "failed" if result.is_error else "completed",
                    f"{label}{'失败' if result.is_error else '完成'}",
                    tool_name=turn.tool_name,
                )
                events.append(ToolObservationEvent(content=result.content))

            return await request_final("常规步骤已结束，正在整理最终答案")
