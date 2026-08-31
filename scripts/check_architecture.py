from __future__ import annotations

import ast
import json
from collections.abc import Sequence
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "backend" / "src" / "examtwin"
SUBJECT_PACKS_ROOT = Path(__file__).resolve().parents[1] / "subject-packs"
FEATURES = frozenset({"subjects", "knowledge", "assessment"})
FEATURE_DEPENDENCIES = {
    "subjects": frozenset(),
    "knowledge": frozenset({"subjects"}),
    "assessment": frozenset({"subjects", "knowledge"}),
}
ALLOWED_TOP_LEVEL = frozenset({*FEATURES, "app", "platform", "contracts"})


def installed_subject_code_literals() -> frozenset[str]:
    codes: set[str] = set()
    for manifest_path in SUBJECT_PACKS_ROOT.glob("*/manifest.json"):
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        subject_code = payload.get("subject_code")
        if isinstance(subject_code, str) and subject_code:
            codes.add(subject_code)
    return frozenset(codes)


KNOWN_SUBJECT_CODE_LITERALS = installed_subject_code_literals()
LEGACY_TOP_LEVEL = frozenset(
    {
        "agent_harness",
        "api",
        "config",
        "config_contract",
        "local_storage",
        "observability",
        "persistence",
        "prompt_templates",
        "schemas",
        "services",
        "storage",
    }
)
THIN_ROUTE_FUNCTIONS: dict[tuple[str, ...], frozenset[str]] = {
    ("app", "api", "workspaces"): frozenset({"upload_workspace_document", "build_knowledge_base"}),
}
PERSISTENCE_FACTORY_CALLS = frozenset(
    {
        "build_corpus_ingestor",
        "build_object_store",
        "build_vector_index",
        "corpus_repository",
        "create_session_factory",
        "knowledge_repository",
        "vector_index_repository",
    }
)
CALLABLE_ARGUMENT_EXECUTORS = frozenset({"Depends", "guarded_api_call"})
MANAGED_ROUTE_DEPENDENCIES: dict[
    tuple[str, ...],
    dict[str, tuple[str, str]],
] = {
    ("app", "api", "workspaces"): {
        "upload_workspace_document": (
            "service",
            "examtwin.app.api.dependencies.get_corpus_workspace_service",
        ),
        "build_knowledge_base": (
            "service",
            "examtwin.app.api.dependencies.get_corpus_workspace_service",
        ),
    },
}


FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
CallableNode = FunctionNode | ast.Lambda
CallableTarget = str | CallableNode
CallableBinding = frozenset[CallableTarget] | None


def _assigned_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    nested_scopes = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.Lambda,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
    )

    def collect(child: ast.AST) -> None:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
            return
        if isinstance(child, nested_scopes):
            return
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])
            return
        for descendant in ast.iter_child_nodes(child):
            collect(descendant)

    collect(node)
    return names


def _parameter_names(function: CallableNode) -> set[str]:
    arguments = function.args
    parameters = [
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
    ]
    names = {parameter.arg for parameter in parameters}
    if arguments.vararg:
        names.add(arguments.vararg.arg)
    if arguments.kwarg:
        names.add(arguments.kwarg.arg)
    return names


class _RoutePersistenceAnalyzer:
    def __init__(self, tree: ast.Module) -> None:
        self.module_functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.module_callable_ids = {id(function) for function in self.module_functions.values()}
        self.module_bindings: dict[str, CallableBinding] = {}
        self.active_callables: set[int] = set()
        self.dependencies: list[str] = []
        self.reported: set[str] = set()
        self._build_module_bindings(tree.body)

    def _build_module_bindings(self, statements: Sequence[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                self._bind_import(statement, self.module_bindings)
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.module_bindings[statement.name] = frozenset({statement})
            elif isinstance(statement, ast.ClassDef):
                self.module_bindings[statement.name] = None
            elif isinstance(statement, ast.Assign):
                binding = self._resolve_callable(statement.value, self.module_bindings)
                self._record_module_callables(binding)
                for target in statement.targets:
                    self._bind_target(target, binding, self.module_bindings)
            elif isinstance(statement, ast.AnnAssign):
                binding = (
                    self._resolve_callable(statement.value, self.module_bindings)
                    if statement.value
                    else None
                )
                self._record_module_callables(binding)
                self._bind_target(statement.target, binding, self.module_bindings)
            elif isinstance(statement, (ast.AugAssign, ast.Delete)):
                for name in _assigned_names(statement):
                    self.module_bindings[name] = None
            else:
                for name in _assigned_names(statement):
                    self.module_bindings[name] = None

    def _record_module_callables(self, binding: CallableBinding) -> None:
        if binding:
            self.module_callable_ids.update(
                id(target) for target in binding if isinstance(target, ast.Lambda)
            )

    def inspect_route(self, route: str) -> list[str]:
        self.active_callables.clear()
        self.dependencies.clear()
        self.reported.clear()
        function = self.module_functions[route]
        self._inspect_function(function, self.module_bindings)
        return self.dependencies

    def _inspect_function(
        self,
        function: FunctionNode,
        enclosing_bindings: dict[str, CallableBinding],
    ) -> None:
        function_id = id(function)
        if function_id in self.active_callables:
            return
        self.active_callables.add(function_id)
        try:
            closure = (
                self.module_bindings
                if function_id in self.module_callable_ids
                else enclosing_bindings
            )
            self._inspect_function_definition(function, closure)
            bindings = dict(closure)
            local_names = set().union(*(_assigned_names(node) for node in function.body))
            local_names.update(_parameter_names(function))
            for name in local_names:
                bindings[name] = None
            self._inspect_statements(function.body, bindings)
        finally:
            self.active_callables.remove(function_id)

    def _inspect_lambda(
        self,
        function: ast.Lambda,
        enclosing_bindings: dict[str, CallableBinding],
    ) -> None:
        function_id = id(function)
        if function_id in self.active_callables:
            return
        self.active_callables.add(function_id)
        try:
            closure = (
                self.module_bindings
                if function_id in self.module_callable_ids
                else enclosing_bindings
            )
            bindings = dict(closure)
            local_names = _assigned_names(function.body)
            local_names.update(_parameter_names(function))
            for name in local_names:
                bindings[name] = None
            self._inspect_expression(function.body, bindings)
        finally:
            self.active_callables.remove(function_id)

    def _inspect_function_definition(
        self,
        function: FunctionNode,
        bindings: dict[str, CallableBinding],
    ) -> None:
        expressions = [
            *function.decorator_list,
            *function.args.defaults,
            *(default for default in function.args.kw_defaults if default is not None),
        ]
        for expression in expressions:
            self._inspect_expression(expression, bindings)

    def _inspect_statements(
        self,
        statements: Sequence[ast.stmt],
        bindings: dict[str, CallableBinding],
    ) -> bool:
        for statement in statements:
            if not self._inspect_statement(statement, bindings):
                return False
        return True

    def _inspect_statement(
        self,
        statement: ast.stmt,
        bindings: dict[str, CallableBinding],
    ) -> bool:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._inspect_function_definition(statement, bindings)
            bindings[statement.name] = frozenset({statement})
            return True
        if isinstance(statement, ast.ClassDef):
            for expression in [
                *statement.decorator_list,
                *statement.bases,
                *(keyword.value for keyword in statement.keywords),
            ]:
                self._inspect_expression(expression, bindings)
            bindings[statement.name] = None
            return True
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            self._bind_import(statement, bindings)
            return True
        if isinstance(statement, ast.Assign):
            self._inspect_expression(statement.value, bindings)
            binding = self._resolve_callable(statement.value, bindings)
            for target in statement.targets:
                self._bind_target(target, binding, bindings)
            return True
        if isinstance(statement, ast.AnnAssign):
            if statement.value:
                self._inspect_expression(statement.value, bindings)
            binding = self._resolve_callable(statement.value, bindings) if statement.value else None
            self._bind_target(statement.target, binding, bindings)
            return True
        if isinstance(statement, ast.AugAssign):
            self._inspect_expression(statement.value, bindings)
            self._bind_target(statement.target, None, bindings)
            return True
        if isinstance(statement, ast.If):
            self._inspect_expression(statement.test, bindings)
            return self._inspect_branches(
                bindings,
                (statement.body, statement.orelse or ()),
                include_unchanged=not statement.orelse,
            )
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            self._inspect_expression(statement.iter, bindings)
            loop_bindings = dict(bindings)
            self._bind_target(statement.target, None, loop_bindings)
            self._inspect_statements(statement.body, loop_bindings)
            self._merge_bindings(bindings, (dict(bindings), loop_bindings))
            self._inspect_statements(statement.orelse, bindings)
            return True
        if isinstance(statement, ast.While):
            self._inspect_expression(statement.test, bindings)
            loop_bindings = dict(bindings)
            self._inspect_statements(statement.body, loop_bindings)
            self._merge_bindings(bindings, (dict(bindings), loop_bindings))
            self._inspect_statements(statement.orelse, bindings)
            return True
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            for item in statement.items:
                self._inspect_expression(item.context_expr, bindings)
                if item.optional_vars:
                    self._bind_target(item.optional_vars, None, bindings)
            return self._inspect_statements(statement.body, bindings)
        if isinstance(statement, (ast.Try, ast.TryStar)):
            continuation_bindings: list[dict[str, CallableBinding]] = []
            normal_bindings = dict(bindings)
            if self._inspect_statements(statement.body, normal_bindings):
                if self._inspect_statements(statement.orelse, normal_bindings):
                    continuation_bindings.append(normal_bindings)
            for handler in statement.handlers:
                handler_bindings = dict(bindings)
                if self._inspect_statements(handler.body, handler_bindings):
                    continuation_bindings.append(handler_bindings)
            if continuation_bindings:
                self._merge_bindings(bindings, continuation_bindings)
            finally_falls_through = self._inspect_statements(statement.finalbody, bindings)
            return bool(continuation_bindings) and finally_falls_through
        if isinstance(statement, ast.Match):
            self._inspect_expression(statement.subject, bindings)
            return self._inspect_branches(
                bindings,
                [case.body for case in statement.cases],
                include_unchanged=True,
            )
        if isinstance(statement, ast.Return):
            if statement.value:
                self._inspect_expression(statement.value, bindings)
            return False
        if isinstance(statement, ast.Raise):
            if statement.exc:
                self._inspect_expression(statement.exc, bindings)
            if statement.cause:
                self._inspect_expression(statement.cause, bindings)
            return False
        if isinstance(statement, (ast.Break, ast.Continue)):
            return False

        for child in ast.iter_child_nodes(statement):
            if isinstance(child, ast.expr):
                self._inspect_expression(child, bindings)
            elif isinstance(child, ast.stmt):
                self._inspect_statement(child, bindings)
        for name in _assigned_names(statement):
            bindings[name] = None
        return True

    def _inspect_branches(
        self,
        bindings: dict[str, CallableBinding],
        branches: Sequence[Sequence[ast.stmt]],
        *,
        include_unchanged: bool,
    ) -> bool:
        branch_bindings: list[dict[str, CallableBinding]] = []
        if include_unchanged:
            branch_bindings.append(dict(bindings))
        for branch in branches:
            branch_scope = dict(bindings)
            if self._inspect_statements(branch, branch_scope):
                branch_bindings.append(branch_scope)
        if branch_bindings:
            self._merge_bindings(bindings, branch_bindings)
        return bool(branch_bindings)

    @staticmethod
    def _merge_bindings(
        bindings: dict[str, CallableBinding],
        branches: Sequence[dict[str, CallableBinding]],
    ) -> None:
        names = set().union(*(branch.keys() for branch in branches))
        for name in names:
            targets = frozenset(
                target for branch in branches for target in (branch.get(name) or ())
            )
            bindings[name] = targets or None

    def _inspect_expression(
        self,
        expression: ast.expr,
        bindings: dict[str, CallableBinding],
    ) -> None:
        if isinstance(expression, ast.Lambda):
            for default in [
                *expression.args.defaults,
                *(default for default in expression.args.kw_defaults if default is not None),
            ]:
                self._inspect_expression(default, bindings)
            return
        if isinstance(expression, ast.NamedExpr):
            self._inspect_expression(expression.value, bindings)
            self._bind_target(
                expression.target,
                self._resolve_callable(expression.value, bindings),
                bindings,
            )
            return
        if isinstance(expression, ast.Call):
            self._inspect_expression(expression.func, bindings)
            targets = self._resolve_callable(expression.func, bindings)
            self._inspect_callable_targets(targets, bindings)
            if self._is_callable_argument_executor(targets):
                for argument in expression.args:
                    self._inspect_callable_targets(
                        self._resolve_callable(argument, bindings),
                        bindings,
                    )
                for keyword in expression.keywords:
                    self._inspect_callable_targets(
                        self._resolve_callable(keyword.value, bindings),
                        bindings,
                    )
            for argument in expression.args:
                self._inspect_expression(argument, bindings)
            for keyword in expression.keywords:
                self._inspect_expression(keyword.value, bindings)
            return
        for child in ast.iter_child_nodes(expression):
            if isinstance(child, ast.expr):
                self._inspect_expression(child, bindings)

    def _inspect_callable_targets(
        self,
        targets: CallableBinding,
        bindings: dict[str, CallableBinding],
    ) -> None:
        if not targets:
            return
        for target in sorted(targets, key=self._target_sort_key):
            if isinstance(target, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._inspect_function(target, bindings)
            elif isinstance(target, ast.Lambda):
                self._inspect_lambda(target, bindings)
            elif target in PERSISTENCE_FACTORY_CALLS or target.endswith("Repository"):
                self._report(target)

    @staticmethod
    def _target_sort_key(target: CallableTarget) -> tuple[int, str, int, int]:
        if isinstance(target, str):
            return (0, target, 0, 0)
        return (1, type(target).__name__, target.lineno, target.col_offset)

    @staticmethod
    def _is_callable_argument_executor(targets: CallableBinding) -> bool:
        return bool(
            targets
            and any(
                isinstance(target, str) and target in CALLABLE_ARGUMENT_EXECUTORS
                for target in targets
            )
        )

    @staticmethod
    def _resolve_callable(
        expression: ast.expr,
        bindings: dict[str, CallableBinding],
    ) -> CallableBinding:
        if isinstance(expression, ast.Name):
            if expression.id in bindings:
                return bindings[expression.id]
            return frozenset({expression.id})
        if isinstance(expression, ast.Attribute):
            return frozenset({expression.attr})
        if isinstance(expression, ast.Lambda):
            return frozenset({expression})
        if isinstance(expression, ast.IfExp):
            targets = {
                target
                for branch in (expression.body, expression.orelse)
                for target in (_RoutePersistenceAnalyzer._resolve_callable(branch, bindings) or ())
            }
            return frozenset(targets) or None
        return None

    @staticmethod
    def _bind_import(
        statement: ast.Import | ast.ImportFrom,
        bindings: dict[str, CallableBinding],
    ) -> None:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                name = alias.asname or alias.name.split(".", 1)[0]
                bindings[name] = (
                    frozenset({alias.name.rsplit(".", 1)[-1]}) if alias.asname else None
                )
            return
        for alias in statement.names:
            if alias.name != "*":
                bindings[alias.asname or alias.name] = frozenset({alias.name.rsplit(".", 1)[-1]})

    @classmethod
    def _bind_target(
        cls,
        target: ast.expr,
        binding: CallableBinding,
        bindings: dict[str, CallableBinding],
    ) -> None:
        if isinstance(target, ast.Name):
            bindings[target.id] = binding
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                cls._bind_target(element, None, bindings)

    def _report(self, dependency: str) -> None:
        if dependency not in self.reported:
            self.reported.add(dependency)
            self.dependencies.append(dependency)


def route_persistence_calls(
    path: Path,
    names: frozenset[str],
) -> tuple[list[tuple[str, str]], list[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    analyzer = _RoutePersistenceAnalyzer(tree)
    violations: list[tuple[str, str]] = []
    missing_routes = sorted(names.difference(analyzer.module_functions))

    for route in sorted(names):
        if route in analyzer.module_functions:
            violations.extend((route, dependency) for dependency in analyzer.inspect_route(route))

    return violations, missing_routes


def _bind_qualified_import(
    path: Path,
    statement: ast.Import | ast.ImportFrom,
    bindings: dict[str, str | None],
) -> None:
    if isinstance(statement, ast.Import):
        for alias in statement.names:
            local_name = alias.asname or alias.name.split(".", 1)[0]
            bindings[local_name] = alias.name if alias.asname else local_name
        return

    modules = import_from_modules(path, statement)
    for alias in statement.names:
        if alias.name == "*":
            continue
        if statement.module:
            module = next(iter(modules), "")
            qualified = f"{module}.{alias.name}" if module else alias.name
        else:
            qualified = next(
                (module for module in modules if module.rsplit(".", 1)[-1] == alias.name),
                alias.name,
            )
        bindings[alias.asname or alias.name] = qualified


def _qualified_name(
    expression: ast.expr,
    bindings: dict[str, str | None],
) -> str | None:
    if isinstance(expression, ast.Name):
        return bindings.get(expression.id, expression.id)
    if isinstance(expression, ast.Attribute):
        parent = _qualified_name(expression.value, bindings)
        return f"{parent}.{expression.attr}" if parent else None
    return None


def _bind_qualified_target(
    target: ast.expr,
    binding: str | None,
    bindings: dict[str, str | None],
) -> None:
    if isinstance(target, ast.Name):
        bindings[target.id] = binding
        return
    for name in _assigned_names(target):
        bindings[name] = None


def _provider_binding_environments(
    path: Path,
    tree: ast.Module,
    route_names: set[str],
) -> dict[str, dict[str, str | None]]:
    bindings: dict[str, str | None] = {}
    environments: dict[str, dict[str, str | None]] = {}
    module_name = ".".join(("examtwin", *module_parts(path)))

    for statement in tree.body:
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            _bind_qualified_import(path, statement, bindings)
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if statement.name in route_names:
                environments[statement.name] = dict(bindings)
            bindings[statement.name] = f"{module_name}.{statement.name}"
        elif isinstance(statement, ast.ClassDef):
            bindings[statement.name] = f"{module_name}.{statement.name}"
        elif isinstance(statement, ast.Assign):
            binding = _qualified_name(statement.value, bindings)
            for target in statement.targets:
                _bind_qualified_target(target, binding, bindings)
        elif isinstance(statement, ast.AnnAssign):
            binding = (
                _qualified_name(statement.value, bindings) if statement.value is not None else None
            )
            _bind_qualified_target(statement.target, binding, bindings)
        else:
            for name in _assigned_names(statement):
                bindings[name] = None

    return environments


def _parameter_default(function: FunctionNode, parameter_name: str) -> ast.expr | None:
    positional = [*function.args.posonlyargs, *function.args.args]
    positional_defaults = {
        parameter.arg: default
        for parameter, default in zip(
            positional[len(positional) - len(function.args.defaults) :],
            function.args.defaults,
            strict=True,
        )
    }
    if parameter_name in positional_defaults:
        return positional_defaults[parameter_name]
    return next(
        (
            default
            for parameter, default in zip(
                function.args.kwonlyargs,
                function.args.kw_defaults,
                strict=True,
            )
            if parameter.arg == parameter_name
        ),
        None,
    )


def route_dependency_contract_violations(
    path: Path,
    contracts: dict[str, tuple[str, str]],
) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    provider_bindings = _provider_binding_environments(path, tree, set(contracts))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    violations: list[str] = []
    for route, (parameter_name, approved_provider) in sorted(contracts.items()):
        function = functions.get(route)
        if function is None:
            continue
        bindings = provider_bindings[route]
        default = _parameter_default(function, parameter_name)
        provider: ast.expr | None = None
        if (
            isinstance(default, ast.Call)
            and _qualified_name(default.func, bindings) == "fastapi.Depends"
        ):
            if len(default.args) == 1:
                provider = default.args[0]
            else:
                provider = next(
                    (keyword.value for keyword in default.keywords if keyword.arg == "dependency"),
                    None,
                )
        if provider is None or _qualified_name(provider, bindings) != approved_provider:
            violations.append(
                f"managed route dependency contract violated: {route}.{parameter_name} "
                f"must use {approved_provider}"
            )
    return violations


def import_from_modules(path: Path, node: ast.ImportFrom) -> set[str]:
    if node.level == 0:
        return {node.module} if node.module else set()

    package = ("examtwin", *module_parts(path)[:-1])
    if node.level > len(package):
        return set()
    keep = len(package) - node.level + 1
    base = package[:keep]
    if node.module:
        return {".".join((*base, *node.module.split(".")))}
    return {".".join((*base, alias.name)) for alias in node.names if alias.name != "*"}


def imported_modules(path: Path) -> tuple[set[str], list[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    errors: list[str] = []
    package_depth = len(("examtwin", *module_parts(path)[:-1]))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level > package_depth:
                errors.append(
                    f"relative import traverses above examtwin package: level {node.level}"
                )
                continue
            modules.update(import_from_modules(path, node))
    return modules, errors


def module_parts(path: Path) -> tuple[str, ...]:
    return path.relative_to(PACKAGE_ROOT).with_suffix("").parts


def known_subject_literal_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        (
            f"known subject code literal {node.value!r} is forbidden "
            f"in shared code at line {node.lineno}"
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value in KNOWN_SUBJECT_CODE_LITERALS
    ]


def check_file(path: Path) -> list[str]:
    parts = module_parts(path)
    top_level = parts[0]
    imports, import_errors = imported_modules(path)
    errors: list[str] = [*import_errors, *known_subject_literal_violations(path)]

    if top_level != "__init__" and top_level not in ALLOWED_TOP_LEVEL:
        errors.append(f"module must live in an explicit architecture boundary: {top_level}")
    if top_level in LEGACY_TOP_LEVEL:
        errors.append(f"legacy horizontal module is forbidden: {top_level}")

    if top_level == "platform":
        for imported in imports:
            if imported == "examtwin.app" or imported.startswith("examtwin.app."):
                errors.append(f"platform must not depend on app: {imported}")
            if any(
                imported == f"examtwin.{feature}" or imported.startswith(f"examtwin.{feature}.")
                for feature in FEATURES
            ):
                errors.append(f"platform must not depend on feature: {imported}")

    if top_level == "contracts":
        for imported in imports:
            if imported.startswith("examtwin.") and not (
                imported == "examtwin.contracts" or imported.startswith("examtwin.contracts.")
            ):
                errors.append(f"contracts must not depend on runtime modules: {imported}")

    if top_level in FEATURES:
        for imported in imports:
            if imported == "examtwin.app" or imported.startswith("examtwin.app."):
                errors.append(f"feature must not depend on app: {imported}")
            for feature in FEATURES - FEATURE_DEPENDENCIES[top_level] - {top_level}:
                if imported == f"examtwin.{feature}" or imported.startswith(f"examtwin.{feature}."):
                    errors.append(
                        f"{top_level} must not depend on downstream feature {feature}: {imported}"
                    )
            for feature in FEATURE_DEPENDENCIES[top_level]:
                prefix = f"examtwin.{feature}"
                if (imported == prefix or imported.startswith(f"{prefix}.")) and imported != (
                    f"{prefix}.public"
                ):
                    errors.append(f"cross-feature imports must use {feature}.public: {imported}")

    thin_routes = THIN_ROUTE_FUNCTIONS.get(parts)
    if thin_routes is not None:
        route_calls, missing_routes = route_persistence_calls(path, thin_routes)
        for route, dependency in route_calls:
            errors.append(
                f"route must delegate persistence orchestration to an application service: "
                f"{route} calls {dependency}"
            )
        for route in missing_routes:
            errors.append(f"configured managed route is missing: {route}")
        dependency_contracts = MANAGED_ROUTE_DEPENDENCIES.get(parts, {})
        errors.extend(route_dependency_contract_violations(path, dependency_contracts))
    if top_level != "app":
        for imported in imports:
            if imported == "fastapi" or imported.startswith("fastapi."):
                errors.append(f"FastAPI is restricted to the app boundary: {imported}")

    return [f"{path.relative_to(PACKAGE_ROOT.parent)}: {error}" for error in errors]


def main() -> int:
    errors = [
        error
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
        for error in check_file(path)
    ]
    if errors:
        print("Architecture dependency violations:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Architecture dependency rules passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
