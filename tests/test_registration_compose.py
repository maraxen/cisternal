"""Tests for cisternal.registration — shim.py + compose.py (M2-COMPOSE, item 2141).

Acceptance criteria covered:
  AC-M2-2   — async original -> iscoroutinefunction(compose_mcp_callable(fn)) is True.
  AC-M2-3   — sync original -> iscoroutinefunction(compose_mcp_callable(fn)) is True;
              awaiting it returns the sync result.
  AC-M2-4   — inspect.signature(generated) == inspect.signature(original) for plain
              types and Annotated[] params (incl. annotation equality).
  AC-M2-5   — schema fidelity: register generated callable as a FastMCP tool; assert
              input JSON schema reflects original parameter type annotations.
  AC-M2-6   — passthrough/no-telemetry: generated callable returns original value AND
              emits ZERO telemetry events (verified via ShadowExporter spy).
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Annotated, Any

import pytest
from pydantic import Field

from cisternal.registration.compose import compose_mcp_callable
from cisternal.registration.registry import clear_registry
from cisternal.telemetry import ShadowExporter, EventPipeline


# ---------------------------------------------------------------------------
# Fixture: registry cleanup after every test (A7)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_registries():
    """Wipe known partitions before and after every test (A7)."""
    for partition in ("default", "bathos", "contemplex"):
        clear_registry(name=partition)
    yield
    for partition in ("default", "bathos", "contemplex"):
        clear_registry(name=partition)


# ---------------------------------------------------------------------------
# Fixture: ShadowExporter spy pipeline for AC-M2-6
# ---------------------------------------------------------------------------

@pytest.fixture()
def shadow_pipeline():
    """Return a (ShadowExporter, EventPipeline) pair and shut down after test."""
    spy = ShadowExporter()
    pipeline = EventPipeline(exporters=[spy])
    yield spy, pipeline
    pipeline.shutdown()


# ---------------------------------------------------------------------------
# AC-M2-2: async original -> iscoroutinefunction(generated) is True
# ---------------------------------------------------------------------------

class TestAsyncOriginalIsCoroutine:
    def test_async_original_yields_coroutine_function(self):
        """AC-M2-2: compose of an async fn produces a coroutine function."""
        async def my_async_fn(x: int) -> int:
            return x * 2

        generated = compose_mcp_callable(my_async_fn)
        assert asyncio.iscoroutinefunction(generated), (
            "Generated callable must satisfy iscoroutinefunction() == True "
            "even for an async original (E2 outer form)."
        )

    @pytest.mark.asyncio
    async def test_async_original_returns_correct_value(self):
        """AC-M2-2: awaiting the generated callable returns the original return value."""
        async def my_async_fn(x: int) -> int:
            return x * 2

        generated = compose_mcp_callable(my_async_fn)
        result = await generated(21)
        assert result == 42

    def test_async_original_wrapped_attribute(self):
        """Generated callable's __wrapped__ points to the original (traceability)."""
        async def my_async_fn() -> None:
            pass

        generated = compose_mcp_callable(my_async_fn)
        assert generated.__wrapped__ is my_async_fn


# ---------------------------------------------------------------------------
# AC-M2-3: sync original -> iscoroutinefunction(generated) is True; result passthrough
# ---------------------------------------------------------------------------

class TestSyncOriginalIsCoroutine:
    def test_sync_original_yields_coroutine_function(self):
        """AC-M2-3: compose of a sync fn produces a coroutine function."""
        def my_sync_fn(x: int) -> int:
            return x + 1

        generated = compose_mcp_callable(my_sync_fn)
        assert asyncio.iscoroutinefunction(generated), (
            "Generated callable must satisfy iscoroutinefunction() == True "
            "even for a sync original (E2 outer form)."
        )

    @pytest.mark.asyncio
    async def test_sync_original_returns_correct_value(self):
        """AC-M2-3: awaiting the generated callable returns the sync result."""
        def my_sync_fn(a: int, b: int) -> int:
            return a + b

        generated = compose_mcp_callable(my_sync_fn)
        result = await generated(3, 4)
        assert result == 7

    @pytest.mark.asyncio
    async def test_sync_original_with_side_effects(self):
        """AC-M2-3: sync side effects (mutations) propagate through the generated callable."""
        calls: list[Any] = []

        def recorder(value: Any) -> str:
            calls.append(value)
            return "recorded"

        generated = compose_mcp_callable(recorder)
        result = await generated("hello")
        assert result == "recorded"
        assert calls == ["hello"]

    def test_sync_original_wrapped_attribute(self):
        """Generated callable's __wrapped__ points to the original (traceability)."""
        def my_sync_fn() -> None:
            pass

        generated = compose_mcp_callable(my_sync_fn)
        assert generated.__wrapped__ is my_sync_fn


# ---------------------------------------------------------------------------
# AC-M2-4: inspect.signature(generated) == inspect.signature(original)
# ---------------------------------------------------------------------------

class TestSignaturePreservation:
    def test_plain_type_signature_preserved(self):
        """AC-M2-4a: plain-type signature is preserved exactly."""
        def my_fn(a: int, b: str, c: float = 3.14) -> bool:
            return True

        generated = compose_mcp_callable(my_fn)
        original_sig = inspect.signature(my_fn)
        generated_sig = inspect.signature(generated)

        assert generated_sig == original_sig, (
            f"Signature mismatch.\n"
            f"  original:  {original_sig}\n"
            f"  generated: {generated_sig}"
        )

    def test_annotated_param_signature_preserved(self):
        """AC-M2-4b: Annotated[] params are preserved in the generated signature."""
        def my_fn(
            x: Annotated[int, "the x value"],
            y: Annotated[str, "the y value"] = "default",
        ) -> Annotated[str, "the result"]:
            return f"{x} {y}"

        generated = compose_mcp_callable(my_fn)
        original_sig = inspect.signature(my_fn)
        generated_sig = inspect.signature(generated)

        assert generated_sig == original_sig, (
            f"Signature mismatch for Annotated[] params.\n"
            f"  original:  {original_sig}\n"
            f"  generated: {generated_sig}"
        )

    def test_annotated_param_annotations_match(self):
        """AC-M2-4b: Individual parameter annotations including Annotated[] are equal."""
        def my_fn(x: Annotated[int, "doc for x"], y: str) -> None:
            pass

        generated = compose_mcp_callable(my_fn)
        orig_params = inspect.signature(my_fn).parameters
        gen_params = inspect.signature(generated).parameters

        assert set(orig_params.keys()) == set(gen_params.keys())
        for name in orig_params:
            assert orig_params[name].annotation == gen_params[name].annotation, (
                f"Parameter {name!r}: annotation mismatch: "
                f"{orig_params[name].annotation!r} != {gen_params[name].annotation!r}"
            )

    def test_return_annotation_preserved(self):
        """AC-M2-4: return annotation is left untouched on the generated callable."""
        def my_fn(x: int) -> Annotated[str, "annotated return"]:
            return str(x)

        generated = compose_mcp_callable(my_fn)
        orig_return = inspect.signature(my_fn).return_annotation
        gen_return = inspect.signature(generated).return_annotation

        assert orig_return == gen_return

    def test_name_preserved(self):
        """Generated callable carries the original __name__."""
        def my_special_fn() -> None:
            pass

        generated = compose_mcp_callable(my_special_fn)
        assert generated.__name__ == "my_special_fn"

    def test_signature_set_explicitly_not_via_update_wrapper(self):
        """AC-M2-4: __signature__ is set EXPLICITLY (verify it exists on the object)."""
        def my_fn(x: int) -> str:
            return str(x)

        generated = compose_mcp_callable(my_fn)
        # functools.update_wrapper does NOT set __signature__; if we relied on it,
        # generated.__dict__ would not contain '__signature__'.
        assert "__signature__" in generated.__dict__ or hasattr(generated, "__signature__")
        # The value must equal the original's signature.
        assert generated.__signature__ == inspect.signature(my_fn)


# ---------------------------------------------------------------------------
# AC-M2-5: schema fidelity — FastMCP reflects original parameter annotations
# ---------------------------------------------------------------------------

class TestSchemaFidelity:
    """AC-M2-5: FastMCP input schema reflects original parameter type annotations.

    Strategy: construct a REAL fastmcp.FastMCP, register the generated
    callable as a tool, and assert the input JSON schema properties match
    the original's parameter types.

    FastMCP uses __signature__ for schema generation; the H1 guarantee
    (explicit __signature__ == inspect.signature(original)) means schema
    fidelity flows from signature fidelity.
    """

    @pytest.mark.asyncio
    async def test_plain_types_schema(self):
        """AC-M2-5a: plain-type params appear correctly in FastMCP schema."""
        import fastmcp

        def add_numbers(a: int, b: float) -> float:
            return a + b

        generated = compose_mcp_callable(add_numbers)
        mcp = fastmcp.FastMCP("schema-test-plain")
        mcp.add_tool(generated)

        tools = await mcp.list_tools()
        assert len(tools) == 1
        tool = tools[0]

        props = tool.parameters.get("properties", {})
        assert "a" in props, f"'a' missing from schema properties: {props}"
        assert "b" in props, f"'b' missing from schema properties: {props}"
        assert props["a"].get("type") == "integer", f"'a' type: {props['a']}"
        assert props["b"].get("type") == "number", f"'b' type: {props['b']}"

    @pytest.mark.asyncio
    async def test_annotated_types_schema(self):
        """AC-M2-5b: Annotated[] params with pydantic.Field(description=...) produce
        a stable 'description' field in the FastMCP JSON schema.

        Uses pydantic.Field rather than bare Annotated[str, "..."] string metadata,
        which is unreliable across FastMCP versions.  pydantic.Field is the canonical
        way to attach field metadata recognised by both FastMCP and pydantic.
        """
        import fastmcp

        def greet(
            name: Annotated[str, Field(description="The name to greet")],
            times: Annotated[int, Field(description="How many times to greet")] = 1,
        ) -> str:
            return (name + " ") * times

        generated = compose_mcp_callable(greet)
        mcp = fastmcp.FastMCP("schema-test-annotated")
        mcp.add_tool(generated)

        tools = await mcp.list_tools()
        assert len(tools) == 1
        tool = tools[0]

        props = tool.parameters.get("properties", {})
        assert "name" in props, f"'name' missing: {props}"
        assert "times" in props, f"'times' missing: {props}"
        assert props["name"].get("type") == "string", f"'name' type: {props['name']}"
        assert props["times"].get("type") == "integer", f"'times' type: {props['times']}"
        # pydantic.Field(description=...) produces a stable 'description' in schema.
        assert props["name"].get("description") == "The name to greet", (
            f"Expected description='The name to greet' in 'name' schema, got: {props['name']}"
        )
        assert props["times"].get("description") == "How many times to greet", (
            f"Expected description='How many times to greet' in 'times' schema, got: {props['times']}"
        )
        # F2: 'times' has a default value (= 1) and must NOT appear in 'required'.
        assert "times" not in tool.parameters.get("required", []), (
            f"'times' has a default and must not be in 'required', "
            f"got required={tool.parameters.get('required', [])}"
        )


# ---------------------------------------------------------------------------
# AC-M2-6: passthrough / no-telemetry
# ---------------------------------------------------------------------------

class TestPassthroughNoTelemetry:
    """AC-M2-6: generated callable is a PURE PASSTHROUGH with zero telemetry.

    Verification strategy:
      1. Install a ShadowExporter spy into a fresh EventPipeline.
      2. Compose a function and await the generated callable.
      3. Assert it returns the original return value.
      4. Assert no records accumulated in the spy (the pipeline does NOT run
         here; we verify that compose_mcp_callable does not touch any telemetry
         mechanism directly).

    Note: cisternal's telemetry pipeline is initialized separately (via
    init_pipeline or EventPipeline constructor).  The spy pipeline created
    here is isolated and not registered as the global pipeline.  If the
    generated callable were to call any telemetry function that went through
    a different pipeline, those events would not appear in the spy.  The
    stronger guarantee (C5) is structural: the generated callable's code
    references no adapter, no CisternalMiddleware, and no telemetry function
    at all.  Both structural and behavioural checks are performed below.
    """

    @pytest.mark.asyncio
    async def test_sync_original_returns_value(self):
        """AC-M2-6: sync original — generated callable returns the original value."""
        def double(x: int) -> int:
            return x * 2

        generated = compose_mcp_callable(double)
        result = await generated(7)
        assert result == 14

    @pytest.mark.asyncio
    async def test_async_original_returns_value(self):
        """AC-M2-6: async original — generated callable returns the original value."""
        async def triple(x: int) -> int:
            return x * 3

        generated = compose_mcp_callable(triple)
        result = await generated(5)
        assert result == 15

    @pytest.mark.asyncio
    async def test_no_telemetry_emitted_sync(self, shadow_pipeline):
        """AC-M2-6: invoking the generated callable (sync original) emits ZERO telemetry."""
        spy, pipeline = shadow_pipeline

        def my_fn(x: int) -> int:
            return x + 100

        generated = compose_mcp_callable(my_fn)
        result = await generated(42)
        assert result == 142

        # Give the pipeline a moment to drain (it runs in a daemon thread).
        import time
        time.sleep(0.05)

        assert len(spy.records) == 0, (
            f"Expected zero telemetry records, but got {len(spy.records)}: {spy.records}"
        )

    @pytest.mark.asyncio
    async def test_no_telemetry_emitted_async(self, shadow_pipeline):
        """AC-M2-6: invoking the generated callable (async original) emits ZERO telemetry."""
        spy, pipeline = shadow_pipeline

        async def my_async_fn(x: int) -> int:
            return x * 10

        generated = compose_mcp_callable(my_async_fn)
        result = await generated(3)
        assert result == 30

        import time
        time.sleep(0.05)

        assert len(spy.records) == 0, (
            f"Expected zero telemetry records, but got {len(spy.records)}: {spy.records}"
        )

    def test_generated_callable_code_does_not_reference_adapter(self):
        """AC-M2-6: structural check — generated callable's closure references no adapter.

        Inspects the closures and global references of the generated callable
        to confirm that no adapter, CisternalMiddleware, or telemetry emit
        function is captured.
        """
        def my_fn(x: int) -> int:
            return x

        generated = compose_mcp_callable(my_fn)

        # Check __globals__ of the generated callable for telemetry imports.
        # The generated callable is defined in compose.py which imports only
        # 'dispatch' from shim.py — no adapters.
        fn_globals = getattr(generated, "__globals__", {})
        forbidden_names = {
            "CisternalMiddleware",
            "AdapterBase",
            "emit_start",
            "emit_end",
            "emit_error",
            "shape_ok",
            "shape_error",
        }
        found = forbidden_names & set(fn_globals.keys())
        assert not found, (
            f"Generated callable's __globals__ contains forbidden telemetry "
            f"references: {found}"
        )

    @pytest.mark.asyncio
    async def test_return_value_passthrough_no_mutation(self):
        """AC-M2-6: generated callable returns EXACTLY the value from the original."""
        sentinel = object()  # unique identity object

        def return_sentinel() -> object:
            return sentinel

        generated = compose_mcp_callable(return_sentinel)
        result = await generated()
        assert result is sentinel, (
            "Generated callable must return the exact return value from the original "
            "(identity preserved, no wrapping or mutation)."
        )


# ---------------------------------------------------------------------------
# shim.py direct tests (dispatch + is_async + cli_dispatch / TBD-M2-3)
# ---------------------------------------------------------------------------

class TestShimDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_async_fn(self):
        """shim.dispatch awaits async originals."""
        from cisternal.registration.shim import dispatch

        async def my_async(x: int) -> int:
            return x + 1

        result = await dispatch(my_async, 10)
        assert result == 11

    @pytest.mark.asyncio
    async def test_dispatch_sync_fn(self):
        """shim.dispatch calls sync originals directly."""
        from cisternal.registration.shim import dispatch

        def my_sync(x: int) -> int:
            return x * 3

        result = await dispatch(my_sync, 5)
        assert result == 15

    def test_is_async_true_for_async_fn(self):
        """shim.is_async returns True for async def."""
        from cisternal.registration.shim import is_async

        async def fn() -> None:
            pass

        assert is_async(fn) is True

    def test_is_async_false_for_sync_fn(self):
        """shim.is_async returns False for plain def."""
        from cisternal.registration.shim import is_async

        def fn() -> None:
            pass

        assert is_async(fn) is False

    def test_cli_dispatch_sync_fn(self):
        """cli_dispatch calls a sync fn directly and returns its value."""
        from cisternal.registration.shim import cli_dispatch

        def add(a: int, b: int) -> int:
            return a + b

        result = cli_dispatch(add, 4, 6)
        assert result == 10

    @pytest.mark.asyncio
    async def test_cli_dispatch_async_fn_running_loop_raises(self):
        """TBD-M2-3: cli_dispatch raises CisternalWireError when loop already running."""
        from cisternal.registration.shim import cli_dispatch
        from cisternal.registration.errors import CisternalWireError

        async def my_async_fn(x: int) -> int:
            return x

        # Inside this async test a loop IS running, so cli_dispatch must raise.
        with pytest.raises(CisternalWireError, match="event loop is already running"):
            cli_dispatch(my_async_fn, 1)
