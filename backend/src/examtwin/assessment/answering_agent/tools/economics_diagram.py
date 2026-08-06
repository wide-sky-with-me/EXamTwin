from __future__ import annotations

from typing import Any, Literal

from llama_index.core.tools import BaseTool, FunctionTool
from pydantic import BaseModel, Field, field_validator

from examtwin.assessment.answering_agent.contracts import AgentRunContext
from examtwin.contracts.evidence import AnswerDiagram, DiagramElement, DiagramLegendItem

EconomicsDiagramTemplate = Literal[
    "supply_demand",
    "ad_as",
    "ppc",
    "lorenz_curve",
    "externality",
    "positive_externality",
    "tariff",
    "cost_revenue",
    "perfect_competition_exit",
    "lrac",
    "marginal_utility",
    "production_function",
    "circular_flow",
    "foreign_exchange",
    "labour_market",
    "monopsony_labour",
    "phillips_curve",
]
EconomicsDiagramChange = Literal["none", "increase", "decrease", "improvement"]
EconomicsDiagramCurve = Literal[
    "none",
    "demand",
    "supply",
    "ad",
    "sras",
    "lras",
    "ppc",
    "lorenz",
]
EconomicsDiagramPolicy = Literal[
    "none",
    "tax",
    "subsidy",
    "price_ceiling",
    "price_floor",
    "tariff",
]


class EconomicsDiagramInput(BaseModel):
    """High-level, exam-safe template instead of arbitrary hand-positioned SVG."""

    template: EconomicsDiagramTemplate
    title: str = Field(min_length=1, max_length=160)
    change: EconomicsDiagramChange = "none"
    curve: EconomicsDiagramCurve = "none"
    policy: EconomicsDiagramPolicy = "none"
    caption: str = Field(default="", max_length=500)
    labels: dict[str, str] = Field(
        default_factory=dict,
        max_length=16,
        description="Optional short label overrides such as x_axis, y_axis and market.",
    )

    @field_validator("labels")
    @classmethod
    def bounded_labels(cls, labels: dict[str, str]) -> dict[str, str]:
        normalized = {key.strip(): value.strip() for key, value in labels.items()}
        if any(
            not key or len(key) > 40 or not value or len(value) > 80
            for key, value in normalized.items()
        ):
            raise ValueError("economics diagram labels must be short non-empty strings")
        return normalized


def _element(kind: str, **values: object) -> DiagramElement:
    return DiagramElement.model_validate({"kind": kind, **values})


def _axes(x_label: str, y_label: str) -> list[DiagramElement]:
    return [
        _element("line", x1=80, y1=330, x2=555, y2=330, arrow_end=True),
        _element("line", x1=80, y1=330, x2=80, y2=45, arrow_end=True),
        _element("text", x=500, y=365, text=x_label, tone="muted"),
        _element("text", x=18, y=55, text=y_label, tone="muted"),
        _element("text", x=61, y=352, text="O", tone="muted"),
    ]


def _label(spec: EconomicsDiagramInput, key: str, fallback: str) -> str:
    return spec.labels.get(key, fallback)


def _supply_demand(
    spec: EconomicsDiagramInput,
) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = _axes(_label(spec, "x_axis", "Quantity"), _label(spec, "y_axis", "Price"))
    demand = "M 125 85 C 245 130 365 235 505 305"
    supply = "M 125 300 C 245 250 365 150 505 80"
    elements.extend(
        [
            _element("path", d=demand, emphasis=True, tone="primary"),
            _element("path", d=supply, emphasis=True, tone="secondary"),
            _element("text", x=505, y=313, text="D", tone="primary"),
            _element("text", x=505, y=78, text="S", tone="secondary"),
        ]
    )
    shifted_path: str | None = None
    shifted_label = ""
    offset = 0
    if spec.curve == "demand" and spec.change != "none":
        offset = 45 if spec.change == "increase" else -45
        shifted_path = (
            f"M {125 + offset} 85 C {245 + offset} 130 {365 + offset} 235 {505 + offset} 305"
        )
        shifted_label = "D2"
    elif spec.curve == "supply" and spec.change != "none":
        offset = 45 if spec.change == "increase" else -45
        shifted_path = (
            f"M {125 + offset} 300 C {245 + offset} 250 {365 + offset} 150 {505 + offset} 80"
        )
        shifted_label = "S2"
    if shifted_path:
        label_x = min(555, 505 + offset)
        label_y = 313 if spec.curve == "demand" else 78
        elements.extend(
            [
                _element("path", d=shifted_path, emphasis=True, tone="tertiary"),
                _element("text", x=label_x, y=label_y, text=shifted_label, tone="tertiary"),
            ]
        )
    if spec.policy in {"price_ceiling", "price_floor"}:
        y = 245 if spec.policy == "price_ceiling" else 145
        label = "Maximum price" if spec.policy == "price_ceiling" else "Minimum price"
        elements.extend(
            [
                _element("line", x1=80, y1=y, x2=520, y2=y, dashed=True, tone="tertiary"),
                _element("text", x=340, y=y - 9, text=label, tone="tertiary"),
            ]
        )
    if spec.policy in {"tax", "subsidy"}:
        label = "S + tax" if spec.policy == "tax" else "S + subsidy"
        offset = -42 if spec.policy == "tax" else 42
        elements.extend(
            [
                _element(
                    "path",
                    d=(
                        f"M {125 + offset} 300 C {245 + offset} 250 "
                        f"{365 + offset} 150 {505 + offset} 80"
                    ),
                    emphasis=True,
                    tone="tertiary",
                ),
                _element("text", x=440, y=115, text=label, tone="tertiary"),
            ]
        )
    legend = [
        DiagramLegendItem(label="Demand", tone="primary"),
        DiagramLegendItem(label="Supply", tone="secondary"),
    ]
    return elements, legend


def _ad_as(spec: EconomicsDiagramInput) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = _axes(
        _label(spec, "x_axis", "Real national output"),
        _label(spec, "y_axis", "Price level"),
    )
    elements.extend(
        [
            _element("path", d="M 125 90 C 250 145 365 245 505 305", emphasis=True, tone="primary"),
            _element(
                "path", d="M 125 300 C 245 255 365 165 505 90", emphasis=True, tone="secondary"
            ),
            _element("line", x1=420, y1=315, x2=420, y2=70, emphasis=True, tone="default"),
            _element("text", x=500, y=312, text="AD", tone="primary"),
            _element("text", x=500, y=92, text="SRAS", tone="secondary"),
            _element("text", x=429, y=73, text="LRAS", tone="default"),
        ]
    )
    curve_map = {"ad": "AD2", "sras": "SRAS2", "lras": "LRAS2"}
    if spec.curve in curve_map and spec.change != "none":
        offset = 48 if spec.change in {"increase", "improvement"} else -48
        if spec.curve == "ad":
            path = f"M {125 + offset} 90 C {250 + offset} 145 {365 + offset} 245 {505 + offset} 305"
            elements.append(_element("path", d=path, emphasis=True, tone="tertiary"))
            label_x, label_y = min(555, 505 + offset), 313
        elif spec.curve == "sras":
            path = f"M {125 + offset} 300 C {245 + offset} 255 {365 + offset} 165 {505 + offset} 90"
            elements.append(_element("path", d=path, emphasis=True, tone="tertiary"))
            label_x, label_y = min(555, 505 + offset), 92
        else:
            elements.append(
                _element(
                    "line",
                    x1=420 + offset,
                    y1=315,
                    x2=420 + offset,
                    y2=70,
                    emphasis=True,
                    tone="tertiary",
                )
            )
            label_x, label_y = 428 + offset, 73
        elements.append(
            _element(
                "text",
                x=label_x,
                y=label_y,
                text=curve_map[spec.curve],
                tone="tertiary",
            )
        )
    return elements, [
        DiagramLegendItem(label="Aggregate demand", tone="primary"),
        DiagramLegendItem(label="Short-run aggregate supply", tone="secondary"),
        DiagramLegendItem(label="Changed curve", tone="tertiary"),
    ]


def _ppc(spec: EconomicsDiagramInput) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = _axes(_label(spec, "x_axis", "Good X"), _label(spec, "y_axis", "Good Y"))
    elements.extend(
        [
            _element("path", d="M 105 75 C 130 200 285 315 510 325", emphasis=True, tone="primary"),
            _element("text", x=475, y=305, text="PPC1", tone="primary"),
        ]
    )
    if spec.change != "none":
        outward = spec.change in {"increase", "improvement"}
        path = (
            "M 105 52 C 145 168 325 300 545 322"
            if outward
            else "M 110 105 C 135 225 260 320 455 327"
        )
        elements.extend(
            [
                _element("path", d=path, emphasis=True, tone="tertiary"),
                _element("text", x=510 if outward else 425, y=295, text="PPC2", tone="tertiary"),
            ]
        )
    return elements, [DiagramLegendItem(label="Production possibility frontier", tone="primary")]


def _lorenz(spec: EconomicsDiagramInput) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = _axes(
        _label(spec, "x_axis", "Cumulative population (%)"),
        _label(spec, "y_axis", "Cumulative income (%)"),
    )
    elements.extend(
        [
            _element("line", x1=80, y1=330, x2=520, y2=60, dashed=True, tone="muted"),
            _element("path", d="M 80 330 C 230 330 390 260 520 60", emphasis=True, tone="primary"),
            _element("text", x=290, y=160, text="Line of equality", tone="muted"),
            _element("text", x=360, y=285, text="L1", tone="primary"),
        ]
    )
    if spec.change in {"improvement", "increase"} or spec.curve == "lorenz":
        elements.extend(
            [
                _element(
                    "path", d="M 80 330 C 215 310 375 210 520 60", emphasis=True, tone="tertiary"
                ),
                _element("text", x=370, y=235, text="L2", tone="tertiary"),
            ]
        )
    return elements, [
        DiagramLegendItem(label="Original distribution", tone="primary"),
        DiagramLegendItem(label="More equal distribution", tone="tertiary"),
    ]


def _externality(
    spec: EconomicsDiagramInput,
) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = _axes(_label(spec, "x_axis", "Quantity"), _label(spec, "y_axis", "Cost / benefit"))
    elements.extend(
        [
            _element(
                "path", d="M 125 300 C 245 250 365 150 505 80", emphasis=True, tone="secondary"
            ),
            _element("path", d="M 125 90 C 245 145 365 235 505 305", emphasis=True, tone="primary"),
            _element(
                "path", d="M 125 250 C 245 205 365 115 505 52", emphasis=True, tone="tertiary"
            ),
            _element("text", x=500, y=82, text="MPC", tone="secondary"),
            _element("text", x=500, y=307, text="MPB", tone="primary"),
            _element("text", x=500, y=50, text="MSC", tone="tertiary"),
        ]
    )
    return elements, [
        DiagramLegendItem(label="Private benefit", tone="primary"),
        DiagramLegendItem(label="Private cost", tone="secondary"),
        DiagramLegendItem(label="Social cost", tone="tertiary"),
    ]


def _positive_externality(
    spec: EconomicsDiagramInput,
) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = _axes(_label(spec, "x_axis", "Quantity"), _label(spec, "y_axis", "Cost / benefit"))
    elements.extend(
        [
            _element(
                "path", d="M 125 300 C 245 250 365 150 505 80", emphasis=True, tone="secondary"
            ),
            _element(
                "path", d="M 125 125 C 245 165 365 240 505 305", emphasis=True, tone="primary"
            ),
            _element(
                "path", d="M 125 78 C 245 118 365 195 505 260", emphasis=True, tone="tertiary"
            ),
            _element("text", x=500, y=82, text="MPC = MSC", tone="secondary"),
            _element("text", x=500, y=307, text="MPB", tone="primary"),
            _element("text", x=500, y=260, text="MSB", tone="tertiary"),
        ]
    )
    return elements, [
        DiagramLegendItem(label="Marginal private benefit", tone="primary"),
        DiagramLegendItem(label="Marginal social benefit", tone="tertiary"),
        DiagramLegendItem(label="Marginal social cost", tone="secondary"),
    ]


def _tariff(spec: EconomicsDiagramInput) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements, legend = _supply_demand(spec)
    elements.extend(
        [
            _element("line", x1=80, y1=245, x2=520, y2=245, emphasis=True, tone="muted"),
            _element("line", x1=80, y1=195, x2=520, y2=195, emphasis=True, tone="tertiary"),
            _element("text", x=430, y=238, text="World price", tone="muted"),
            _element("text", x=420, y=187, text="World price + tariff", tone="tertiary"),
        ]
    )
    legend.append(DiagramLegendItem(label="Price after tariff", tone="tertiary"))
    return elements, legend


def _cost_revenue(
    spec: EconomicsDiagramInput,
) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = _axes(_label(spec, "x_axis", "Output"), _label(spec, "y_axis", "Cost / revenue"))
    elements.extend(
        [
            _element(
                "path", d="M 120 95 C 205 275 390 285 510 100", emphasis=True, tone="secondary"
            ),
            _element(
                "path", d="M 120 120 C 220 260 390 250 510 75", emphasis=True, tone="tertiary"
            ),
            _element("line", x1=120, y1=145, x2=510, y2=285, emphasis=True, tone="primary"),
            _element("line", x1=120, y1=145, x2=390, y2=330, emphasis=True, tone="muted"),
            _element("text", x=500, y=104, text="AC", tone="secondary"),
            _element("text", x=500, y=76, text="MC", tone="tertiary"),
            _element("text", x=500, y=288, text="AR", tone="primary"),
            _element("text", x=388, y=324, text="MR", tone="muted"),
        ]
    )
    return elements, [
        DiagramLegendItem(label="Average revenue", tone="primary"),
        DiagramLegendItem(label="Marginal revenue", tone="muted"),
        DiagramLegendItem(label="Average cost", tone="secondary"),
        DiagramLegendItem(label="Marginal cost", tone="tertiary"),
    ]


def _perfect_competition_exit(
    spec: EconomicsDiagramInput,
) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = _axes(_label(spec, "x_axis", "Output"), _label(spec, "y_axis", "Cost / revenue"))
    elements.extend(
        [
            _element(
                "path", d="M 120 100 C 210 292 420 292 510 100", emphasis=True, tone="secondary"
            ),
            _element(
                "path",
                d="M 135 215 C 205 315 280 302 340 245 C 400 175 450 95 505 55",
                emphasis=True,
                tone="tertiary",
            ),
            _element("line", x1=115, y1=305, x2=520, y2=305, emphasis=True, tone="primary"),
            _element("text", x=500, y=102, text="AC", tone="secondary"),
            _element("text", x=500, y=56, text="MC", tone="tertiary"),
            _element("text", x=485, y=297, text="AR = P", tone="primary"),
        ]
    )
    return elements, [
        DiagramLegendItem(label="Average revenue below average cost", tone="primary"),
        DiagramLegendItem(label="Average cost", tone="secondary"),
        DiagramLegendItem(label="Marginal cost", tone="tertiary"),
    ]


def _lrac(spec: EconomicsDiagramInput) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = _axes(
        _label(spec, "x_axis", "Output"), _label(spec, "y_axis", "Long-run average cost")
    )
    elements.extend(
        [
            _element(
                "path",
                d="M 115 80 C 185 250 300 285 395 270 C 455 258 500 215 525 145",
                emphasis=True,
                tone="primary",
            ),
            _element("line", x1=395, y1=330, x2=395, y2=270, dashed=True, tone="tertiary"),
            _element("point", x=395, y=270, label="MES", tone="tertiary"),
            _element("text", x=470, y=210, text="LRAC", tone="primary"),
        ]
    )
    return elements, [DiagramLegendItem(label="Long-run average cost", tone="primary")]


def _marginal_utility(
    spec: EconomicsDiagramInput,
) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = _axes(
        _label(spec, "x_axis", "Quantity consumed"),
        _label(spec, "y_axis", "Marginal utility / price"),
    )
    elements.extend(
        [
            _element("path", d="M 125 75 C 235 125 360 220 510 305", emphasis=True, tone="primary"),
            _element("line", x1=110, y1=220, x2=520, y2=220, emphasis=True, tone="secondary"),
            _element("line", x1=360, y1=330, x2=360, y2=220, dashed=True, tone="tertiary"),
            _element("point", x=360, y=220, label="MU = price", tone="tertiary"),
            _element("text", x=495, y=307, text="MU", tone="primary"),
            _element("text", x=480, y=212, text="Price", tone="secondary"),
            _element("text", x=350, y=355, text="Q*", tone="tertiary"),
        ]
    )
    return elements, [
        DiagramLegendItem(label="Marginal utility", tone="primary"),
        DiagramLegendItem(label="Price", tone="secondary"),
    ]


def _production_function(
    spec: EconomicsDiagramInput,
) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = _axes(
        _label(spec, "x_axis", "Variable input"), _label(spec, "y_axis", "Total product")
    )
    elements.extend(
        [
            _element(
                "path",
                d="M 100 315 C 165 300 205 225 250 135 C 295 55 390 70 510 145",
                emphasis=True,
                tone="primary",
            ),
            _element("line", x1=300, y1=330, x2=300, y2=82, dashed=True, tone="tertiary"),
            _element("point", x=300, y=82, label="Diminishing returns begin", tone="tertiary"),
            _element("text", x=470, y=135, text="TP", tone="primary"),
        ]
    )
    return elements, [DiagramLegendItem(label="Total product", tone="primary")]


def _circular_flow(
    spec: EconomicsDiagramInput,
) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = [
        _element(
            "polygon",
            points=[(70, 130), (235, 130), (235, 245), (70, 245)],
            fill="light",
            tone="primary",
        ),
        _element(
            "polygon",
            points=[(365, 130), (530, 130), (530, 245), (365, 245)],
            fill="light",
            tone="secondary",
        ),
        _element("text", x=110, y=190, text="Households", tone="primary"),
        _element("text", x=420, y=190, text="Firms", tone="secondary"),
        _element("line", x1=235, y1=150, x2=365, y2=150, arrow_end=True, tone="primary"),
        _element("text", x=258, y=139, text="Consumption", tone="primary"),
        _element("line", x1=365, y1=225, x2=235, y2=225, arrow_end=True, tone="secondary"),
        _element("text", x=270, y=250, text="Income", tone="secondary"),
        _element("line", x1=150, y1=130, x2=150, y2=62, arrow_end=True, tone="muted"),
        _element("text", x=88, y=48, text="Withdrawals", tone="muted"),
        _element("line", x1=450, y1=62, x2=450, y2=130, arrow_end=True, tone="tertiary"),
        _element("text", x=410, y=48, text="Injections", tone="tertiary"),
    ]
    return elements, [
        DiagramLegendItem(label="Real and money flows", tone="primary"),
        DiagramLegendItem(label="Injections", tone="tertiary"),
        DiagramLegendItem(label="Withdrawals", tone="muted"),
    ]


def _foreign_exchange(
    spec: EconomicsDiagramInput,
) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    axis_labels = {
        "x_axis": "Quantity of currency",
        "y_axis": "Exchange rate",
        **spec.labels,
    }
    elements, _ = _supply_demand(spec.model_copy(update={"labels": axis_labels}))
    for element in elements:
        if element.kind == "text" and element.text == "D":
            element.text = "D currency"
        elif element.kind == "text" and element.text == "S":
            element.text = "S currency"
    return elements, [
        DiagramLegendItem(label="Demand for currency", tone="primary"),
        DiagramLegendItem(label="Supply of currency", tone="secondary"),
    ]


def _labour_market(
    spec: EconomicsDiagramInput,
) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = _axes(_label(spec, "x_axis", "Employment"), _label(spec, "y_axis", "Wage rate"))
    elements.extend(
        [
            _element("path", d="M 125 90 C 245 135 365 235 505 305", emphasis=True, tone="primary"),
            _element(
                "path", d="M 125 300 C 245 250 365 150 505 80", emphasis=True, tone="secondary"
            ),
            _element("text", x=495, y=307, text="DL = MRP", tone="primary"),
            _element("text", x=495, y=82, text="SL", tone="secondary"),
        ]
    )
    return elements, [
        DiagramLegendItem(label="Demand for labour", tone="primary"),
        DiagramLegendItem(label="Supply of labour", tone="secondary"),
    ]


def _monopsony_labour(
    spec: EconomicsDiagramInput,
) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = _axes(
        _label(spec, "x_axis", "Employment"),
        _label(spec, "y_axis", "Wage / labour cost"),
    )
    elements.extend(
        [
            _element("line", x1=120, y1=300, x2=500, y2=80, emphasis=True, tone="secondary"),
            _element("line", x1=120, y1=300, x2=390, y2=55, emphasis=True, tone="tertiary"),
            _element("line", x1=120, y1=80, x2=500, y2=300, emphasis=True, tone="primary"),
            _element("text", x=500, y=79, text="ACL / SL", tone="secondary"),
            _element("text", x=389, y=53, text="MCL", tone="tertiary"),
            _element("text", x=500, y=300, text="MRP / DL", tone="primary"),
            _element("line", x1=268, y1=330, x2=268, y2=166, dashed=True, tone="tertiary"),
            _element("line", x1=80, y1=214, x2=268, y2=214, dashed=True, tone="tertiary"),
            _element("line", x1=310, y1=330, x2=310, y2=190, dashed=True, tone="muted"),
            _element("line", x1=80, y1=190, x2=310, y2=190, dashed=True, tone="muted"),
            _element("point", x=268, y=166, label="MCL = MRP", tone="tertiary"),
            _element("point", x=268, y=214, tone="tertiary"),
            _element("point", x=310, y=190, tone="muted"),
            _element("text", x=42, y=219, text="Wm", tone="tertiary"),
            _element("text", x=42, y=194, text="Wc", tone="muted"),
            _element("text", x=255, y=355, text="Qm", tone="tertiary"),
            _element("text", x=300, y=355, text="Qc", tone="muted"),
        ]
    )
    return elements, [
        DiagramLegendItem(label="Marginal revenue product of labour", tone="primary"),
        DiagramLegendItem(label="Average cost / labour supply", tone="secondary"),
        DiagramLegendItem(label="Marginal cost of labour", tone="tertiary"),
    ]


def _phillips(spec: EconomicsDiagramInput) -> tuple[list[DiagramElement], list[DiagramLegendItem]]:
    elements = _axes(
        _label(spec, "x_axis", "Unemployment rate"), _label(spec, "y_axis", "Inflation rate")
    )
    elements.extend(
        [
            _element("path", d="M 130 80 C 180 200 310 275 510 305", emphasis=True, tone="primary"),
            _element("line", x1=360, y1=315, x2=360, y2=70, emphasis=True, tone="secondary"),
            _element("text", x=475, y=300, text="SRPC", tone="primary"),
            _element("text", x=368, y=75, text="LRPC", tone="secondary"),
        ]
    )
    return elements, [
        DiagramLegendItem(label="Short-run Phillips curve", tone="primary"),
        DiagramLegendItem(label="Long-run Phillips curve", tone="secondary"),
    ]


_COMPILERS = {
    "supply_demand": _supply_demand,
    "ad_as": _ad_as,
    "ppc": _ppc,
    "lorenz_curve": _lorenz,
    "externality": _externality,
    "positive_externality": _positive_externality,
    "tariff": _tariff,
    "cost_revenue": _cost_revenue,
    "perfect_competition_exit": _perfect_competition_exit,
    "lrac": _lrac,
    "marginal_utility": _marginal_utility,
    "production_function": _production_function,
    "circular_flow": _circular_flow,
    "foreign_exchange": _foreign_exchange,
    "labour_market": _labour_market,
    "monopsony_labour": _monopsony_labour,
    "phillips_curve": _phillips,
}


def compile_economics_diagram(spec: EconomicsDiagramInput) -> AnswerDiagram:
    elements, legend = _COMPILERS[spec.template](spec)
    return AnswerDiagram(
        title=spec.title,
        caption=spec.caption,
        tool_name="economics_diagram",
        view_box=(0, 0, 600, 390),
        elements=elements,
        legend=legend,
    )


class EconomicsDiagramTool:
    name = "economics_diagram"

    def bind(self, context: AgentRunContext) -> BaseTool:
        async def economics_diagram(**kwargs: Any) -> str:
            """Create one validated standard economics diagram."""

            diagram = compile_economics_diagram(EconomicsDiagramInput.model_validate(kwargs))
            context.add_diagram(diagram)
            return (
                f"Economics diagram '{diagram.title}' accepted from the "
                f"{kwargs.get('template')} template with {len(diagram.elements)} elements."
            )

        return FunctionTool.from_defaults(
            async_fn=economics_diagram,
            name=self.name,
            fn_schema=EconomicsDiagramInput,
            description=(
                "Create and attach a validated OxfordAQA Economics diagram using a stable "
                "template: supply_demand, ad_as, ppc, lorenz_curve, externality, "
                "positive_externality, tariff, cost_revenue, perfect_competition_exit, lrac, "
                "marginal_utility, production_function, circular_flow, foreign_exchange, "
                "labour_market, monopsony_labour or phillips_curve. Use curve/change/policy to "
                "show the requested comparative static. Prefer this tool over hand-positioned "
                "math_diagram calls or image generation for every economics graph."
            ),
        )
