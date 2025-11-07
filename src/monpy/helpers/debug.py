from __future__ import annotations

from typing import Any, Callable, Optional

from ..client import MondayClient


def enable_graphql_trace(client: MondayClient, *, print_success: bool = False) -> None:
    """Print all GraphQL queries/mutations and variables during runtime.

    - When print_success is False, all calls are printed but only errors include an [ERROR] line.
    - When True, successful calls log an [OK] line as well.
    """

    orig_query = client.query
    orig_mutation = client.mutation

    def traced_query(q: str, v: Optional[dict] = None):
        print("\n[TRACE] QUERY:\n", q, sep="")
        print("[TRACE] Vars:", v)
        try:
            res = orig_query(q, v)
            if print_success:
                print("[TRACE] OK")
            return res
        except Exception as e:
            print("[TRACE] ERROR:", e)
            raise

    def traced_mutation(m: str, v: Optional[dict] = None):
        print("\n[TRACE] MUTATION:\n", m, sep="")
        print("[TRACE] Vars:", v)
        try:
            res = orig_mutation(m, v)
            if print_success:
                print("[TRACE] OK")
            return res
        except Exception as e:
            print("[TRACE] ERROR:", e)
            raise

    client.query = traced_query  # type: ignore[assignment]
    client.mutation = traced_mutation  # type: ignore[assignment]


__all__ = [
    "enable_graphql_trace",
]


