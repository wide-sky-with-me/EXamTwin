from __future__ import annotations

import json
import math
import statistics
from typing import Literal

from llama_index.core.tools import BaseTool, FunctionTool
from pydantic import BaseModel, Field, field_validator

from examtwin.answering_agent.contracts import AgentRunContext

EconomicsOperation = Literal[
    "ratio",
    "difference",
    "mean",
    "median",
    "sum",
    "percentage_of_total",
    "percentage_change",
    "percentage_point_change",
    "elasticity",
    "concentration_ratio",
    "index_value",
    "index_deflation",
    "multiplier",
    "per_capita",
    "total_revenue",
    "simple_interest",
    "compound_interest",
    "triangle_area",
]


class EconomicsCalculateInput(BaseModel):
    """Named inputs for common examination calculations in Economics 9640."""

    operation: EconomicsOperation
    values: dict[str, float] = Field(
        min_length=1,
        max_length=20,
        description=(
            "Named numeric inputs. Use old/new for changes; quantity_change/driver_change "
            "for elasticity; share_1...share_n and firms for concentration_ratio; "
            "current/base for index_value; nominal/price_index for index_deflation; "
            "mpc or mps for multiplier; principal/rate/years for interest, with rate as a "
            "percentage; price/quantity for total_revenue; minuend/subtrahend for difference; "
            "total/population for per_capita; numerator/denominator for ratio; "
            "value_1...value_n for mean or median; term_1...term_n for a signed sum; "
            "part/total for a percentage share; base/height for triangle_area."
        ),
    )
    precision: int = Field(default=3, ge=0, le=10)

    @field_validator("values")
    @classmethod
    def finite_values(cls, values: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("economics calculation inputs must be finite")
        return values


def _required(values: dict[str, float], *names: str) -> tuple[float, ...]:
    missing = [name for name in names if name not in values]
    if missing:
        raise ValueError("missing economics calculation inputs: " + ", ".join(missing))
    return tuple(values[name] for name in names)


def calculate_economics(spec: EconomicsCalculateInput) -> dict[str, object]:
    values = spec.values
    operation = spec.operation
    if operation == "ratio":
        numerator, denominator = _required(values, "numerator", "denominator")
        if denominator == 0:
            raise ValueError("denominator must be non-zero for ratio")
        result = numerator / denominator
        working = f"{numerator} / {denominator}"
        unit = ""
    elif operation == "difference":
        minuend, subtrahend = _required(values, "minuend", "subtrahend")
        result = minuend - subtrahend
        working = f"{minuend} - {subtrahend}"
        unit = ""
    elif operation in {"mean", "median"}:
        observations = [value for name, value in values.items() if name.startswith("value_")]
        if not observations:
            raise ValueError(f"{operation} requires value_1 ... value_n inputs")
        if operation == "mean":
            result = sum(observations) / len(observations)
            working = f"({' + '.join(str(value) for value in observations)}) / {len(observations)}"
        else:
            ordered = sorted(observations)
            result = statistics.median(ordered)
            working = f"median({', '.join(str(value) for value in ordered)})"
        unit = ""
    elif operation == "sum":
        terms = [value for name, value in values.items() if name.startswith("term_")]
        if not terms:
            raise ValueError(
                "sum requires term_1 ... term_n inputs; use negative values for outflows"
            )
        result = sum(terms)
        working = " + ".join(str(value) for value in terms)
        unit = ""
    elif operation == "percentage_of_total":
        part, total = _required(values, "part", "total")
        if total == 0:
            raise ValueError("total must be non-zero for percentage_of_total")
        result = part / total * 100
        working = f"({part} / {total}) x 100"
        unit = "%"
    elif operation == "percentage_change":
        old, new = _required(values, "old", "new")
        if old == 0:
            raise ValueError("old must be non-zero for percentage_change")
        result = (new - old) / old * 100
        working = f"(({new} - {old}) / {old}) x 100"
        unit = "%"
    elif operation == "percentage_point_change":
        old, new = _required(values, "old", "new")
        result = new - old
        working = f"{new} - {old}"
        unit = "percentage points"
    elif operation == "elasticity":
        quantity_change, driver_change = _required(
            values,
            "quantity_change",
            "driver_change",
        )
        if driver_change == 0:
            raise ValueError("driver_change must be non-zero for elasticity")
        result = quantity_change / driver_change
        working = f"{quantity_change}% / {driver_change}%"
        unit = ""
    elif operation == "concentration_ratio":
        shares = sorted(
            (value for name, value in values.items() if name.startswith("share_")),
            reverse=True,
        )
        firms = int(values.get("firms", len(shares)))
        if firms < 1 or firms > len(shares):
            raise ValueError("firms must select at least one available share")
        selected = shares[:firms]
        result = sum(selected)
        working = " + ".join(str(value) for value in selected)
        unit = "%"
    elif operation == "index_value":
        current, base = _required(values, "current", "base")
        if base == 0:
            raise ValueError("base must be non-zero for index_value")
        result = current / base * 100
        working = f"({current} / {base}) x 100"
        unit = "index points"
    elif operation == "index_deflation":
        nominal, price_index = _required(values, "nominal", "price_index")
        if price_index <= 0:
            raise ValueError("price_index must be positive")
        result = nominal / price_index * 100
        working = f"({nominal} / {price_index}) x 100"
        unit = "real-value units"
    elif operation == "multiplier":
        if "mpc" in values:
            mpc = values["mpc"]
            if not 0 <= mpc < 1:
                raise ValueError("mpc must satisfy 0 <= mpc < 1")
            result = 1 / (1 - mpc)
            working = f"1 / (1 - {mpc})"
        else:
            (mps,) = _required(values, "mps")
            if not 0 < mps <= 1:
                raise ValueError("mps must satisfy 0 < mps <= 1")
            result = 1 / mps
            working = f"1 / {mps}"
        unit = ""
    elif operation == "per_capita":
        total, population = _required(values, "total", "population")
        if population <= 0:
            raise ValueError("population must be positive")
        result = total / population
        working = f"{total} / {population}"
        unit = "per person"
    elif operation == "total_revenue":
        price, quantity = _required(values, "price", "quantity")
        result = price * quantity
        working = f"{price} x {quantity}"
        unit = "currency units"
    elif operation in {"simple_interest", "compound_interest"}:
        principal, rate, years = _required(values, "principal", "rate", "years")
        if principal < 0 or rate < 0 or years < 0:
            raise ValueError("principal, rate and years must be non-negative")
        if operation == "simple_interest":
            result = principal * (rate / 100) * years
            working = f"{principal} x ({rate} / 100) x {years}"
        else:
            result = principal * ((1 + rate / 100) ** years - 1)
            working = f"{principal} x ((1 + {rate} / 100) ^ {years} - 1)"
        unit = "currency units"
    elif operation == "triangle_area":
        base, height = _required(values, "base", "height")
        if base < 0 or height < 0:
            raise ValueError("base and height must be non-negative")
        result = 0.5 * base * height
        working = f"0.5 x {base} x {height}"
        unit = "square units"
    else:  # pragma: no cover - Literal and Pydantic keep this branch unreachable.
        raise ValueError(f"unsupported economics operation: {operation}")

    rounded = round(result, spec.precision)
    return {
        "operation": operation,
        "working": working,
        "result": rounded,
        "unrounded_result": result,
        "unit": unit,
    }


class EconomicsCalculateTool:
    name = "economics_calculate"

    def bind(self, context: AgentRunContext) -> BaseTool:
        del context

        async def economics_calculate(
            operation: EconomicsOperation,
            values: dict[str, float],
            precision: int = 3,
        ) -> str:
            """Calculate a standard economics quantity with visible working."""

            result = calculate_economics(
                EconomicsCalculateInput(
                    operation=operation,
                    values=values,
                    precision=precision,
                )
            )
            return json.dumps(result, ensure_ascii=False, separators=(",", ":"))

        return FunctionTool.from_defaults(
            async_fn=economics_calculate,
            name=self.name,
            fn_schema=EconomicsCalculateInput,
            description=(
                "Perform a deterministic OxfordAQA Economics calculation and return the "
                "working, unrounded value and rounded result. Use this for percentage changes, "
                "percentage-point changes, ratios, differences, means, medians, signed sums, "
                "percentages of totals, elasticities, concentration ratios, index values and "
                "deflation, multipliers, per-capita values, revenue, simple or compound interest, "
                "and triangular welfare areas."
            ),
        )
