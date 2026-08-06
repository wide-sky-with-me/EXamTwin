from __future__ import annotations

from typing import Literal

from llama_index.core.tools import BaseTool, FunctionTool
from pydantic import BaseModel, Field
from sympy import N, Symbol, diff, integrate, simplify, solve

from examtwin.assessment.answering_agent.blocking import run_blocking_bounded
from examtwin.assessment.answering_agent.contracts import AgentRunContext
from examtwin.assessment.symbolic import parse_safe_expression


class MathCalculateInput(BaseModel):
    operation: Literal[
        "simplify",
        "solve",
        "differentiate",
        "integrate",
        "evaluate",
    ]
    expression: str = Field(min_length=1, max_length=500)
    variable: str = Field(default="x", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,15}$")


class MathCalculateTool:
    name = "math_calculate"

    def bind(self, context: AgentRunContext) -> BaseTool:
        async def math_calculate(
            operation: Literal["simplify", "solve", "differentiate", "integrate", "evaluate"],
            expression: str,
            variable: str = "x",
        ) -> str:
            """Run a bounded symbolic calculation to check mathematical working."""
            return await run_blocking_bounded(
                calculate,
                operation,
                expression,
                variable,
                timeout=15,
            )

        def calculate(
            operation: Literal[
                "simplify",
                "solve",
                "differentiate",
                "integrate",
                "evaluate",
            ],
            expression: str,
            variable: str,
        ) -> str:
            symbol = Symbol(variable)
            if operation == "solve" and "=" in expression:
                left, right = expression.split("=", 1)
                parsed = parse_safe_expression(left, variable) - parse_safe_expression(
                    right, variable
                )
            else:
                parsed = parse_safe_expression(expression, variable)

            if operation == "simplify":
                result = simplify(parsed)
            elif operation == "solve":
                result = solve(parsed, symbol)
            elif operation == "differentiate":
                result = diff(parsed, symbol)
            elif operation == "integrate":
                result = integrate(parsed, symbol)
            else:
                result = N(parsed, 15)
            rendered = str(result)
            if len(rendered) > 2000:
                raise ValueError("symbolic result exceeds the tool output limit")
            return f"{operation}({expression}) = {rendered}"

        return FunctionTool.from_defaults(
            async_fn=math_calculate,
            name=self.name,
            fn_schema=MathCalculateInput,
            description=(
                "Check a bounded symbolic calculation. Supports simplify, solve, "
                "differentiate, integrate and numerical evaluate. Use ASCII SymPy syntax "
                "with * and ^; binomial(n, k), factorial(n), exp(x), log(x) and sqrt(x) "
                "are supported. It corroborates working but does not replace cited "
                "knowledge evidence."
            ),
        )
