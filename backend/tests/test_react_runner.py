from __future__ import annotations

import time

import pytest
from examtwin.assessment.answering_agent import (
    AgentFinalPayload,
    AnsweringAgentRuntime,
    AnswerTask,
    CapabilityRegistry,
    ReActHarnessRunner,
)
from examtwin.assessment.answering_agent.contracts import (
    AgentRunContext,
    QuestionSpec,
    SubjectSkill,
    ToolReplayPayload,
)
from examtwin.assessment.answering_agent.tools import (
    KnowledgeSearchTool,
    MathCalculateTool,
    MathDiagramTool,
    MathPlotTool,
)
from examtwin.contracts import SubpartRequirement
from examtwin.subjects.packages import get_subject_package
from llama_index.core.llms import (
    CustomLLM,
    MockLLM,
)
from llama_index.core.tools import BaseTool, FunctionTool

from backend.tests.answering_agent_support import (
    CapturingFinalAnswerProvider,
    NoEvidenceRunner,
    ScriptedReActLLM,
    _citation,
    _nodes,
    _runtime,
)

MATHEMATICS_9660 = get_subject_package("oxfordaqa-mathematics-9660").require_skill()


def test_runtime_refuses_to_mark_an_answer_grounded_without_search_evidence() -> None:
    result = _runtime(NoEvidenceRunner()).solve(
        AnswerTask(subject_code="9660", question="State an unsupported fact.")
    )

    assert result.answer_markdown.startswith("当前知识库没有找到足够证据")
    assert result.grounded is False
    assert result.confidence == 0
    assert "No knowledge_search evidence was retrieved." in result.warnings


def test_real_llamaindex_react_loop_calls_tool_then_uses_observation() -> None:
    llm = ScriptedReActLLM()
    runtime = AnsweringAgentRuntime(
        llm=llm,
        skills=(MATHEMATICS_9660,),
        registry=CapabilityRegistry(tools=(KnowledgeSearchTool(_nodes, _citation),)),
        max_iterations=4,
        max_tool_calls=2,
        timeout=15,
    )

    result = runtime.solve(
        AnswerTask(subject_code="9660", question="State the quadratic discriminant.")
    )

    assert result.grounded is True
    assert result.citations[0].document_id == "doc-1"
    assert "[S1]" in result.answer_markdown
    assert llm.calls == 2
    assert any(step.tool_name == "knowledge_search" for step in result.steps)


def test_react_loop_reuses_only_a_persisted_replay_safe_tool_result() -> None:
    class ReplayLedger:
        def __init__(self) -> None:
            self.started_tools: list[str] = []
            self.replay_queries = 0
            self.status: str | None = None

        def start_run(self, **_kwargs: object) -> None:
            return None

        def find_replay(self, **_kwargs: object) -> ToolReplayPayload:
            self.replay_queries += 1
            return ToolReplayPayload(observation="evaluate(2+2) = 4")

        def tool_started(self, *, tool_name: str, **_kwargs: object) -> None:
            self.started_tools.append(tool_name)

        def tool_finished(self, **_kwargs: object) -> None:
            return None

        def finish_run(self, status: str) -> None:
            self.status = status

    llm = ScriptedReActLLM(
        responses=(
            (
                "Thought: Retrieve evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "arithmetic", "top_k": 3}'
            ),
            (
                "Thought: Check the arithmetic.\n"
                "Action: math_calculate\n"
                'Action Input: {"operation": "evaluate", "expression": "2+2"}'
            ),
            (
                "Answer: "
                '{"answer_markdown":"The checked value is 4. [S1]",'
                '"citation_ids":["S1"],"confidence":0.9,'
                '"grounded":true,"warnings":[]}'
            ),
        )
    )
    ledger = ReplayLedger()

    result = _scripted_runtime(llm).solve(
        AnswerTask(subject_code="9660", question="Calculate 2+2."),
        ledger=ledger,
    )

    assert result.grounded is True
    assert ledger.replay_queries == 1
    assert ledger.started_tools == ["knowledge_search"]
    assert ledger.status == "completed"
    assert any("持久执行账本复用" in step.message for step in result.steps)


def test_react_loop_rejects_early_final_until_mandatory_search_completes() -> None:
    llm = ScriptedReActLLM(
        responses=(
            (
                "Answer: "
                '{"answer_markdown":"The roots are 2 and 3. [S1]",'
                '"citation_ids":["S1"],"confidence":0.9,'
                '"grounded":true,"warnings":[]}'
            ),
            (
                "Thought: I must retrieve evidence first.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic roots", "top_k": 3}'
            ),
            (
                "Answer: "
                '{"answer_markdown":"The roots are 2 and 3. [S1]",'
                '"citation_ids":["S1"],"confidence":0.9,'
                '"grounded":true,"warnings":[]}'
            ),
        )
    )

    result = _scripted_runtime(llm).solve(
        AnswerTask(subject_code="9660", question="Solve x^2 - 5x + 6 = 0.")
    )

    assert result.grounded is True
    assert len(result.citations) == 1
    assert llm.calls == 3
    assert any("补齐必要的知识检索" in step.message for step in result.steps)


def test_react_loop_requires_a_matching_plot_before_final_answer() -> None:
    llm = ScriptedReActLLM(
        responses=(
            (
                "Answer: "
                '{"answer_markdown":"The sketch is described here. [S1]",'
                '"citation_ids":["S1"],"confidence":0.9,'
                '"grounded":true,"warnings":[]}'
            ),
            (
                "Thought: I must retrieve evidence first.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic graph", "top_k": 3}'
            ),
            (
                "Answer: "
                '{"answer_markdown":"The sketch is still only prose. [S1]",'
                '"citation_ids":["S1"],"confidence":0.9,'
                '"grounded":true,"warnings":[]}'
            ),
            (
                "Thought: I must create the required coordinate plot.\n"
                "Action: math_plot\n"
                'Action Input: {"title":"Sketch of $y=x^2$",'
                '"x_range":[-2,2],"y_range":[-1,4],'
                '"curves":[{"expression":"x^2","label":"$y=x^2$"}]}'
            ),
            (
                "Answer: "
                '{"answer_markdown":"The curve is shown in the answer plot. [S1]",'
                '"citation_ids":["S1"],"confidence":0.9,'
                '"grounded":true,"warnings":[]}'
            ),
        )
    )
    runtime = AnsweringAgentRuntime(
        llm=llm,
        skills=(MATHEMATICS_9660,),
        registry=CapabilityRegistry(tools=(KnowledgeSearchTool(_nodes, _citation), MathPlotTool())),
        max_iterations=6,
        max_tool_calls=2,
        timeout=15,
    )

    result = runtime.solve(
        AnswerTask(subject_code="9660", question="7 (b) Sketch the graph of $y=x^2$.")
    )

    assert result.grounded is True
    assert [diagram.tool_name for diagram in result.diagrams] == ["math_plot"]
    assert llm.calls == 5
    assert any("补齐必要的答题工具" in step.message for step in result.steps)


def test_runtime_rejects_final_answer_without_required_visual_artifact() -> None:
    events = []
    runtime = AnsweringAgentRuntime(
        llm=MockLLM(),
        skills=(MATHEMATICS_9660,),
        registry=CapabilityRegistry(tools=(KnowledgeSearchTool(_nodes, _citation), MathPlotTool())),
        runner=NoEvidenceRunner(),
        timeout=15,
    )

    with pytest.raises(RuntimeError, match="none was produced"):
        runtime.solve(
            AnswerTask(subject_code="9660", question="Sketch the graph of $y=x^2$ on the axes."),
            event_sink=events.append,
        )

    assert events[-1].phase == "finalizing"
    assert events[-1].status == "failed"


def _scripted_runtime(
    llm: CustomLLM,
    *,
    max_iterations: int = 8,
    max_tool_calls: int = 6,
    final_answer_provider: CapturingFinalAnswerProvider | None = None,
    timeout: float = 15,
) -> AnsweringAgentRuntime:
    return AnsweringAgentRuntime(
        llm=llm,
        skills=(MATHEMATICS_9660,),
        registry=CapabilityRegistry(
            tools=(
                KnowledgeSearchTool(_nodes, _citation),
                MathCalculateTool(),
                MathDiagramTool(),
            )
        ),
        runner=(
            ReActHarnessRunner(final_answer_provider=final_answer_provider)
            if final_answer_provider is not None
            else None
        ),
        max_iterations=max_iterations,
        max_tool_calls=max_tool_calls,
        timeout=timeout,
    )


@pytest.mark.parametrize(
    "tool_response",
    (
        ('</think>\nAction: knowledge_search({"query": "quadratic discriminant", "top_k": 3})'),
        (
            "Thought: Search first.\n"
            "Action: knowledge_search\n"
            'Action: {"query": "quadratic discriminant", "top_k": 3}'
        ),
        ('Thought: Search first.\nAction: {"query": "quadratic discriminant", "top_k": 3}'),
    ),
)
def test_react_loop_normalizes_common_single_tool_variants(
    tool_response: str,
) -> None:
    llm = ScriptedReActLLM(
        responses=(
            tool_response,
            (
                "Answer: "
                '{"answer_markdown":"The discriminant is $b^2-4ac$. [S1]",'
                '"confidence":0.9,"grounded":true,"warnings":[]}'
            ),
        )
    )

    result = _scripted_runtime(llm).solve(
        AnswerTask(subject_code="9660", question="State the quadratic discriminant.")
    )

    assert result.grounded is True
    assert "[S1]" in result.answer_markdown
    assert llm.calls == 2


def test_react_loop_self_repairs_a_malformed_response_within_bounds() -> None:
    llm = ScriptedReActLLM(
        responses=(
            "I should search the knowledge base, but this is not valid ReAct.",
            (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic discriminant", "top_k": 3}'
            ),
            (
                "Answer: "
                '{"answer_markdown":"The discriminant is $b^2-4ac$. [S1]",'
                '"confidence":0.9,"grounded":true,"warnings":[]}'
            ),
        )
    )

    result = _scripted_runtime(llm).solve(
        AnswerTask(subject_code="9660", question="State the quadratic discriminant.")
    )

    assert result.grounded is True
    assert llm.calls == 3
    assert any(step.phase == "deciding" and "自动修复" in step.message for step in result.steps)
    assert "not valid ReAct" in llm.prompts[1]
    assert "previous response did not follow" in llm.prompts[1]


def test_react_loop_protocol_recovery_stops_after_bounded_final_attempts() -> None:
    llm = ScriptedReActLLM(responses=("Still not a valid ReAct response.",))

    with pytest.raises(RuntimeError, match="did not complete mandatory tools"):
        _scripted_runtime(llm, max_iterations=1).solve(
            AnswerTask(subject_code="9660", question="State the quadratic discriminant.")
        )

    assert llm.calls == 1


def test_react_loop_recovers_a_complete_answer_followed_by_json() -> None:
    llm = ScriptedReActLLM(
        responses=(
            (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic discriminant", "top_k": 3}'
            ),
            (
                "The complete answer is the discriminant formula.\n"
                '{"answer_markdown":"The discriminant is $b^2-4ac$. [S1]",'
                '"confidence":0.9,"grounded":true,"warnings":[]}'
            ),
        )
    )

    result = _scripted_runtime(llm).solve(
        AnswerTask(subject_code="9660", question="State the quadratic discriminant.")
    )

    assert result.answer_markdown == "The discriminant is $b^2-4ac$. [S1]"
    assert result.grounded is True


def test_react_loop_retries_when_legacy_json_contains_private_protocol() -> None:
    llm = ScriptedReActLLM(
        responses=(
            (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic discriminant", "top_k": 3}'
            ),
            (
                "Answer: "
                '{"answer_markdown":"Thought: private protocol\\nThe answer is [S1]",'
                '"confidence":0.9,"grounded":true,"warnings":[]}'
            ),
            (
                "Answer: "
                '{"answer_markdown":"The discriminant is $b^2-4ac$. [S1]",'
                '"confidence":0.9,"grounded":true,"warnings":[]}'
            ),
        )
    )

    result = _scripted_runtime(llm).solve(
        AnswerTask(subject_code="9660", question="State the quadratic discriminant.")
    )

    assert "private protocol" not in result.answer_markdown
    assert result.grounded is True
    assert llm.calls == 3
    assert any("自动修复" in step.message for step in result.steps)


def test_react_loop_requests_a_final_answer_when_tool_budget_is_exhausted() -> None:
    llm = ScriptedReActLLM(
        responses=(
            (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic discriminant", "top_k": 3}'
            ),
            (
                "Thought: I will calculate too.\n"
                "Action: math_calculate\n"
                'Action Input: {"operation": "simplify", "expression": "b^2-4*a*c"}'
            ),
            (
                "Answer: "
                '{"answer_markdown":"The discriminant is $b^2-4ac$. [S1]",'
                '"confidence":0.85,"grounded":true,"warnings":[]}'
            ),
        )
    )

    result = _scripted_runtime(llm, max_tool_calls=1).solve(
        AnswerTask(subject_code="9660", question="State the quadratic discriminant.")
    )

    assert result.grounded is True
    assert llm.calls == 3
    assert not any(
        step.tool_name == "math_calculate" and step.status == "running" for step in result.steps
    )
    assert any("工具预算已用完" in step.message for step in result.steps)


def test_react_loop_suppresses_an_identical_failed_tool_call() -> None:
    invalid_calculation = (
        "Thought: I will calculate it.\n"
        "Action: math_calculate\n"
        'Action Input: {"operation":"evaluate","expression":"__import__(os)"}'
    )
    llm = ScriptedReActLLM(
        responses=(
            (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic discriminant", "top_k": 3}'
            ),
            invalid_calculation,
            invalid_calculation,
            (
                "Answer: "
                '{"answer_markdown":"The discriminant is $b^2-4ac$. [S1]",'
                '"confidence":0.8,"grounded":true,'
                '"warnings":["Calculation omitted after tool failure."]}'
            ),
        )
    )

    result = _scripted_runtime(llm).solve(
        AnswerTask(subject_code="9660", question="State the quadratic discriminant.")
    )

    assert result.grounded is True
    assert result.diagrams == ()
    assert llm.calls == 4
    assert (
        sum(
            step.tool_name == "math_calculate" and step.status == "running" for step in result.steps
        )
        == 1
    )
    assert any("重复失败" in step.message for step in result.steps)


def test_react_loop_forces_finalization_after_iteration_budget() -> None:
    llm = ScriptedReActLLM(
        responses=(
            (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic discriminant", "top_k": 3}'
            ),
            (
                "Answer: "
                '{"answer_markdown":"The discriminant is $b^2-4ac$. [S1]",'
                '"confidence":0.8,"grounded":true,"warnings":[]}'
            ),
        )
    )

    result = _scripted_runtime(llm, max_iterations=1, max_tool_calls=1).solve(
        AnswerTask(subject_code="9660", question="State the quadratic discriminant.")
    )

    assert result.grounded is True
    assert llm.calls == 2
    assert any("常规步骤已结束" in step.message for step in result.steps)


def test_react_loop_uses_structured_finalizer_and_discards_hidden_reasoning() -> None:
    llm = ScriptedReActLLM(
        responses=(
            (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic discriminant", "top_k": 3}'
            ),
            (
                "<think>private chain-of-thought that must not leave the provider</think>\n"
                "Thought: I can now prepare the public answer.\n"
                "Answer: The discriminant is supported by the retrieved source."
            ),
        )
    )
    finalizer = CapturingFinalAnswerProvider()

    result = _scripted_runtime(llm, final_answer_provider=finalizer).solve(
        AnswerTask(subject_code="9660", question="State the quadratic discriminant.")
    )

    assert result.answer_markdown == "The discriminant is $b^2-4ac$. [S1]"
    assert result.grounded is True
    assert finalizer.calls == 1
    assert finalizer.draft is not None
    assert "private chain-of-thought" not in finalizer.draft


def test_react_loop_renders_exact_question_contract_labels_from_structured_bodies() -> None:
    llm = ScriptedReActLLM(
        responses=(
            (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "triangle congruence", "top_k": 3}'
            ),
            "Answer: The two requested results follow from the evidence.",
        )
    )
    finalizer = CapturingFinalAnswerProvider(
        AgentFinalPayload(
            answer_markdown="",
            subparts=[
                {"label": "(a)", "answer_markdown": "The triangles are congruent. [S1]"},
                {"label": "(b)", "answer_markdown": "Hence $CD=4.2$ cm. [S1]"},
            ],
            citation_ids=["S1"],
            confidence=0.9,
            grounded=True,
        )
    )
    task = AnswerTask(
        subject_code="9660",
        question="Prove the result in (a), then calculate the length in (b).",
        question_spec=QuestionSpec(
            subparts=(
                SubpartRequirement(label="(a)", marks=2, answer_kind="proof"),
                SubpartRequirement(label="(b)", marks=5, answer_kind="numeric"),
            ),
            total_marks=7,
        ),
    )

    result = _scripted_runtime(llm, final_answer_provider=finalizer).solve(task)

    assert result.answer_markdown.startswith("### (a)\n\n")
    assert "\n\n### (b)\n\n" in result.answer_markdown
    assert finalizer.required_subpart_labels == ("(a)", "(b)")


def test_react_loop_falls_back_once_when_structured_finalizer_fails() -> None:
    llm = ScriptedReActLLM(
        responses=(
            (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic discriminant", "top_k": 3}'
            ),
            (
                "Answer: "
                '{"answer_markdown":"The discriminant is $b^2-4ac$. [S1]",'
                '"confidence":0.84,"grounded":true,"warnings":[]}'
            ),
        )
    )
    finalizer = CapturingFinalAnswerProvider(error=RuntimeError("schema unavailable"))

    result = _scripted_runtime(llm, final_answer_provider=finalizer).solve(
        AnswerTask(subject_code="9660", question="State the quadratic discriminant.")
    )

    assert result.grounded is True
    assert finalizer.calls == 1
    assert any(
        "兼容恢复" in step.message and "RuntimeError" in step.message for step in result.steps
    )


def test_react_loop_derives_compatibility_citations_from_public_markdown() -> None:
    llm = ScriptedReActLLM(
        responses=(
            (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic discriminant", "top_k": 3}'
            ),
            (
                "Answer: "
                '{"answer_markdown":"The discriminant is $b^2-4ac$. [S1]",'
                '"citation_ids":["S2"],'
                '"confidence":0.84,"grounded":true,"warnings":[]}'
            ),
        )
    )
    finalizer = CapturingFinalAnswerProvider(error=RuntimeError("schema unavailable"))

    result = _scripted_runtime(llm, final_answer_provider=finalizer).solve(
        AnswerTask(subject_code="9660", question="State the quadratic discriminant.")
    )

    assert result.answer_markdown.endswith("[S1]")
    assert result.grounded is True


def test_iteration_budget_uses_structured_finalizer_without_an_extra_react_call() -> None:
    llm = ScriptedReActLLM(
        responses=(
            (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic discriminant", "top_k": 3}'
            ),
        )
    )
    finalizer = CapturingFinalAnswerProvider()

    result = _scripted_runtime(
        llm,
        max_iterations=1,
        max_tool_calls=1,
        final_answer_provider=finalizer,
    ).solve(AnswerTask(subject_code="9660", question="State the quadratic discriminant."))

    assert result.grounded is True
    assert llm.calls == 1
    assert finalizer.calls == 1
    assert finalizer.draft is None
    assert any("[S1]" in (message.content or "") for message in finalizer.messages)


def test_runtime_rejects_fabricated_structured_citation_ids() -> None:
    llm = ScriptedReActLLM(
        responses=(
            (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic discriminant", "top_k": 3}'
            ),
            (
                "Answer: "
                '{"answer_markdown":"The discriminant is $b^2-4ac$. [S1]",'
                '"confidence":0.82,"grounded":true,"warnings":[]}'
            ),
        )
    )
    finalizer = CapturingFinalAnswerProvider(
        AgentFinalPayload(
            answer_markdown="The discriminant is $b^2-4ac$. [S2]",
            citation_ids=["S2"],
            confidence=0.9,
            grounded=True,
            warnings=[],
        )
    )

    result = _scripted_runtime(
        llm,
        max_iterations=1,
        final_answer_provider=finalizer,
    ).solve(AnswerTask(subject_code="9660", question="State the quadratic discriminant."))

    assert result.answer_markdown.endswith("[S1]")
    assert result.grounded is True
    assert any("兼容恢复" in step.message for step in result.steps)


def test_runtime_rejects_empty_structured_citation_declaration() -> None:
    llm = ScriptedReActLLM(
        responses=(
            (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic discriminant", "top_k": 3}'
            ),
            (
                "Answer: "
                '{"answer_markdown":"The discriminant is $b^2-4ac$. [S1]",'
                '"confidence":0.82,"grounded":true,"warnings":[]}'
            ),
        )
    )
    finalizer = CapturingFinalAnswerProvider(
        AgentFinalPayload(
            answer_markdown="The discriminant is $b^2-4ac$. [S1]",
            citation_ids=[],
            confidence=0.9,
            grounded=True,
            warnings=[],
        )
    )

    result = _scripted_runtime(
        llm,
        final_answer_provider=finalizer,
    ).solve(AnswerTask(subject_code="9660", question="State the quadratic discriminant."))

    assert result.answer_markdown.endswith("[S1]")
    assert result.grounded is True
    assert any("兼容恢复" in step.message for step in result.steps)


def test_structured_finalizer_timeout_preserves_time_for_compatible_fallback() -> None:
    llm = ScriptedReActLLM(
        responses=(
            (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic discriminant", "top_k": 3}'
            ),
            (
                "Answer: "
                '{"answer_markdown":"The discriminant is $b^2-4ac$. [S1]",'
                '"confidence":0.82,"grounded":true,"warnings":[]}'
            ),
        )
    )
    finalizer = CapturingFinalAnswerProvider(delay=0.5)
    started = time.monotonic()

    result = _scripted_runtime(
        llm,
        final_answer_provider=finalizer,
        timeout=0.5,
    ).solve(AnswerTask(subject_code="9660", question="State the quadratic discriminant."))

    assert result.grounded is True
    assert time.monotonic() - started < 0.5
    assert finalizer.calls == 1
    assert finalizer.finalize_timeout is not None
    assert 0 < finalizer.finalize_timeout < 0.5
    assert any("兼容恢复" in step.message for step in result.steps)


@pytest.mark.asyncio
async def test_diagram_tool_rejects_unsafe_path() -> None:
    context = AgentRunContext(task=AnswerTask(subject_code="9660", question="Draw it."))
    tool = MathDiagramTool().bind(context)

    with pytest.raises(ValueError, match="unsupported characters"):
        await tool.acall(
            title="Unsafe",
            elements=[{"kind": "path", "d": "M0 0 onclick=alert(1)"}],
        )

    assert context.diagrams == []


@pytest.mark.asyncio
async def test_mcp_provider_calls_only_explicitly_allowed_tool(monkeypatch) -> None:
    from examtwin.assessment.answering_agent.mcp import MCPServerConfig, MCPToolProvider
    from llama_index.tools import mcp as mcp_module

    async def echo(value: str) -> str:
        return f"observed:{value}"

    async def forbidden() -> str:
        return "must not be exposed"

    class FakeClient:
        def __init__(self, command_or_url: str, args: list[str]):
            self.command_or_url = command_or_url
            self.args = args

    class FakeSpec:
        def __init__(
            self,
            _client: FakeClient,
            *,
            allowed_tools: list[str],
            include_resources: bool,
        ):
            assert allowed_tools == ["echo"]
            assert include_resources is False

        async def to_tool_list_async(self) -> list[BaseTool]:
            return [
                FunctionTool.from_defaults(async_fn=echo, name="echo"),
                FunctionTool.from_defaults(async_fn=forbidden, name="forbidden"),
            ]

    monkeypatch.setattr(mcp_module, "BasicMCPClient", FakeClient)
    monkeypatch.setattr(mcp_module, "McpToolSpec", FakeSpec)

    provider = MCPToolProvider(
        MCPServerConfig(
            name="test",
            command_or_url="test-command",
            args=("server.py",),
            allowed_tools=("echo",),
            timeout_seconds=10,
        )
    )

    assert await provider.load_tools({"forbidden"}) == []
    tools = await provider.load_tools({"echo"})
    output = await tools[0].acall(value="evidence")

    assert output.is_error is False
    assert "observed:evidence" in output.content


def test_subject_skill_requires_only_real_registered_capabilities() -> None:
    skill = SubjectSkill(
        name="fake-physics",
        subject_codes=("fake",),
        instructions="Answer physics questions.",
        tool_names=("knowledge_search", "physics_diagram"),
        required_tool_names=("knowledge_search",),
    )
    runtime = AnsweringAgentRuntime(
        llm=MockLLM(),
        skills=(skill,),
        registry=CapabilityRegistry(tools=(KnowledgeSearchTool(_nodes, _citation),)),
        runner=NoEvidenceRunner(),
    )

    result = runtime.solve(AnswerTask(subject_code="fake", question="Explain motion."))

    assert result.grounded is False
