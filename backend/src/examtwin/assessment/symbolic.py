from __future__ import annotations

import re
from typing import Any

from sympy import (
    Abs,
    Float,
    Function,
    Integer,
    Symbol,
    binomial,
    cos,
    exp,
    factorial,
    log,
    pi,
    sin,
    sqrt,
    tan,
)
from sympy.parsing.sympy_parser import (
    convert_xor,
    parse_expr,
    standard_transformations,
)

SAFE_EXPRESSION = re.compile(r"^[0-9A-Za-z_+\-*/^().,\s=]+$")
TRANSFORMATIONS = standard_transformations + (convert_xor,)
SAFE_GLOBALS = {
    "__builtins__": {},
    "Symbol": Symbol,
    "Integer": Integer,
    "Float": Float,
    "Function": Function,
    "sin": sin,
    "cos": cos,
    "tan": tan,
    "exp": exp,
    "log": log,
    "sqrt": sqrt,
    "binomial": binomial,
    "binom": binomial,
    "factorial": factorial,
    "Abs": Abs,
    "abs": Abs,
    "pi": pi,
}


def parse_safe_expression(expression: str, variable: str | None = None) -> Any:
    if len(expression) > 500 or not SAFE_EXPRESSION.fullmatch(expression):
        raise ValueError("Expression contains unsupported characters")
    if "__" in expression:
        raise ValueError("Dunder names are not allowed")
    identifiers = set(re.findall(r"\b[A-Za-z][A-Za-z0-9_]*\b", expression))
    function_names = {
        "sin",
        "cos",
        "tan",
        "exp",
        "log",
        "sqrt",
        "binomial",
        "binom",
        "factorial",
        "Abs",
        "abs",
        "pi",
    }
    local_dict = {name: Symbol(name) for name in identifiers if name not in function_names}
    if variable:
        local_dict[variable] = Symbol(variable)
    return parse_expr(
        expression,
        local_dict=local_dict,
        global_dict=SAFE_GLOBALS,
        transformations=TRANSFORMATIONS,
        evaluate=True,
    )
