from __future__ import annotations

from typing import Any, Callable, Optional
import json

from ..client import MondayClient


def enable_graphql_trace(
    client: MondayClient,
    *,
    print_success: bool = False,
    print_response: bool = False,
    response_max_chars: int = 2000,
    logger: Optional[Callable[[str], None]] = None,
) -> None:
    """Print all GraphQL queries/mutations, variables, and optionally responses.

    Parameters
    ----------
    print_success:
        When True, emit an [OK] line after successful calls.
    print_response:
        When True, pretty-print the JSON 'data' returned by GraphQL.
    response_max_chars:
        Clamp the printed response to this many characters (after pretty-print).
    logger:
        Optional logging function. Defaults to print().
    """

    orig_query = client.query
    orig_mutation = client.mutation

    def traced_query(q: str, v: Optional[dict] = None):
        _log = logger or print
        _log("\n[TRACE] QUERY:\n" + str(q))
        _log("[TRACE] Vars: " + (json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, dict) else str(v)))
        try:
            res = orig_query(q, v)
            if print_response:
                try:
                    body = json.dumps(res, ensure_ascii=False, indent=2, sort_keys=True)
                except Exception:
                    body = str(res)
                if response_max_chars and len(body) > int(response_max_chars):
                    body = body[: int(response_max_chars)] + " …(truncated)"
                _log("[TRACE] RESPONSE:\n" + body)
            if print_success:
                _log("[TRACE] OK")
            return res
        except Exception as e:
            _log("[TRACE] ERROR: " + str(e))
            raise

    def traced_mutation(m: str, v: Optional[dict] = None):
        _log = logger or print
        _log("\n[TRACE] MUTATION:\n" + str(m))
        _log("[TRACE] Vars: " + (json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, dict) else str(v)))
        try:
            res = orig_mutation(m, v)
            if print_response:
                try:
                    body = json.dumps(res, ensure_ascii=False, indent=2, sort_keys=True)
                except Exception:
                    body = str(res)
                if response_max_chars and len(body) > int(response_max_chars):
                    body = body[: int(response_max_chars)] + " …(truncated)"
                _log("[TRACE] RESPONSE:\n" + body)
            if print_success:
                _log("[TRACE] OK")
            return res
        except Exception as e:
            _log("[TRACE] ERROR: " + str(e))
            raise

    client.query = traced_query  # type: ignore[assignment]
    client.mutation = traced_mutation  # type: ignore[assignment]


__all__ = [
    "enable_graphql_trace",
]


