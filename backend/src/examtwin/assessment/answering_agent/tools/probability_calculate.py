from __future__ import annotations

import math
from statistics import NormalDist
from typing import Literal

from llama_index.core.tools import BaseTool, FunctionTool
from pydantic import BaseModel, Field, model_validator

from examtwin.assessment.answering_agent.contracts import AgentRunContext


class ProbabilityInput(BaseModel):
    operation: Literal[
        "binomial_pmf",
        "binomial_cdf",
        "binomial_sf",
        "poisson_pmf",
        "poisson_cdf",
        "poisson_sf",
        "normal_cdf",
        "normal_sf",
        "normal_interval",
        "normal_ppf",
    ]
    n: int | None = Field(default=None, ge=0, le=100_000)
    p: float | None = Field(default=None, ge=0, le=1)
    k: int | None = Field(default=None, ge=0)
    rate: float | None = Field(default=None, ge=0)
    mean: float | None = None
    standard_deviation: float | None = Field(default=None, gt=0)
    value: float | None = None
    lower: float | None = None
    upper: float | None = None
    probability: float | None = Field(default=None, gt=0, lt=1)

    @model_validator(mode="after")
    def validate_operation_parameters(self) -> ProbabilityInput:
        if self.operation.startswith("binomial_"):
            if self.n is None or self.p is None or self.k is None:
                raise ValueError("binomial operations require n, p and k")
            if self.k > self.n:
                raise ValueError("k cannot exceed n")
        elif self.operation.startswith("poisson_"):
            if self.rate is None or self.k is None:
                raise ValueError("poisson operations require rate and k")
        elif self.operation in {"normal_cdf", "normal_sf"}:
            if self.mean is None or self.standard_deviation is None or self.value is None:
                raise ValueError(f"{self.operation} requires mean, standard_deviation and value")
        elif self.operation == "normal_interval":
            if (
                self.mean is None
                or self.standard_deviation is None
                or self.lower is None
                or self.upper is None
            ):
                raise ValueError(
                    "normal_interval requires mean, standard_deviation, lower and upper"
                )
            if self.lower > self.upper:
                raise ValueError("lower cannot exceed upper")
        elif self.operation == "normal_ppf" and (
            self.mean is None or self.standard_deviation is None or self.probability is None
        ):
            raise ValueError("normal_ppf requires mean, standard_deviation and probability")
        return self


def _binomial_pmf(n: int, p: float, k: int) -> float:
    return math.comb(n, k) * p**k * (1 - p) ** (n - k)


def _poisson_pmf(rate: float, k: int) -> float:
    return math.exp(-rate) * rate**k / math.factorial(k)


def calculate_probability(data: ProbabilityInput) -> str:
    operation = data.operation
    if operation.startswith("binomial_"):
        assert data.n is not None and data.p is not None and data.k is not None
        if operation == "binomial_pmf":
            result = _binomial_pmf(data.n, data.p, data.k)
            event = f"P(X = {data.k})"
        else:
            cdf = math.fsum(_binomial_pmf(data.n, data.p, value) for value in range(data.k + 1))
            result = cdf if operation == "binomial_cdf" else 1 - cdf
            event = f"P(X {'<=' if operation == 'binomial_cdf' else '>'} {data.k})"
        distribution = f"X ~ Bin({data.n}, {data.p})"
    elif operation.startswith("poisson_"):
        assert data.rate is not None and data.k is not None
        if operation == "poisson_pmf":
            result = _poisson_pmf(data.rate, data.k)
            event = f"P(X = {data.k})"
        else:
            cdf = math.fsum(_poisson_pmf(data.rate, value) for value in range(data.k + 1))
            result = cdf if operation == "poisson_cdf" else 1 - cdf
            event = f"P(X {'<=' if operation == 'poisson_cdf' else '>'} {data.k})"
        distribution = f"X ~ Poisson({data.rate})"
    else:
        assert data.mean is not None and data.standard_deviation is not None
        distribution_model = NormalDist(mu=data.mean, sigma=data.standard_deviation)
        distribution = f"X ~ N({data.mean}, {data.standard_deviation}^2)"
        if operation in {"normal_cdf", "normal_sf"}:
            assert data.value is not None
            if operation == "normal_cdf":
                result = distribution_model.cdf(data.value)
                event = f"P(X <= {data.value})"
            else:
                z = (data.value - data.mean) / data.standard_deviation
                result = 0.5 * math.erfc(z / math.sqrt(2))
                event = f"P(X > {data.value})"
        elif operation == "normal_interval":
            assert data.lower is not None and data.upper is not None
            result = distribution_model.cdf(data.upper) - distribution_model.cdf(data.lower)
            event = f"P({data.lower} <= X <= {data.upper})"
        else:
            assert data.probability is not None
            result = distribution_model.inv_cdf(data.probability)
            event = f"x such that P(X <= x) = {data.probability}"
    return (
        f"distribution={distribution}\n"
        f"event={event}\n"
        f"result={result:.15g}\n"
        "cdf uses P(X <= k); sf uses P(X > k). Apply any requested rounding only "
        "after using this unrounded result."
    )


class ProbabilityCalculateTool:
    name = "probability_calculate"

    def bind(self, context: AgentRunContext) -> BaseTool:
        del context

        async def probability_calculate(**kwargs: object) -> str:
            """Evaluate a named binomial, Poisson or normal probability exactly."""

            return calculate_probability(ProbabilityInput.model_validate(kwargs))

        return FunctionTool.from_defaults(
            async_fn=probability_calculate,
            name=self.name,
            fn_schema=ProbabilityInput,
            description=(
                "Compute verified binomial, Poisson or normal probabilities and quantiles. "
                "CDF means P(X <= k); SF means P(X > k). Use this instead of mental "
                "arithmetic for probability answers."
            ),
        )
