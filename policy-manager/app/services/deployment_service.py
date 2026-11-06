"""SDN side effects, verification and compensation; no ORM or HTTP concerns.

Not an atomic multi-switch transaction. Ambiguous/partially compensated states
MUST remain unresolved until a later reconciliation, never reported successful.
"""
from dataclasses import dataclass
import time
from typing import Callable

from app.adapters import ryu_adapter as ryu


@dataclass(frozen=True)
class DeploymentResult:
    status: str  # succeeded | failed | unresolved
    error_code: str | None = None
    detail: str | None = None
    compensated: bool | None = None
    attempted_network_change: bool = False


def _verify_all(flows: list[dict], *, should_exist: bool, adapter, sleep: Callable, attempts: int = 6) -> bool:
    if not flows:
        return True
    # Every expected flow is checked against the switch, not just the REST HTTP status.
    for n in range(attempts):
        result = [adapter.flow_present(f) for f in flows]
        if all(result) if should_exist else not any(result):
            return True
        if n + 1 < attempts:
            sleep(0.25)
    return False


def apply_change(*, old_flows: list[dict], new_flows: list[dict],
                 is_active_before: bool, adapter=ryu,
                 sleep: Callable = time.sleep,
                 on_verifying: Callable[[], None] | None = None) -> DeploymentResult:
    """Converge to new set, compensating toward the observed pre-change set.

    old_flows are the *claimed* current deployment. For replacement, all must
    be observed first, otherwise we must not pretend that rollback can be safe.
    """
    involved = old_flows + new_flows
    if not involved:
        return DeploymentResult('succeeded')
    try:
        connected = adapter.switches()
        missing = sorted({int(f['dpid']) for f in involved} - set(connected))
        if missing:
            return DeploymentResult('failed', 'SWITCH_DISCONNECTED', f'Missing switch DPIDs: {missing}', False)
        if old_flows and new_flows and is_active_before:
            if not _verify_all(old_flows, should_exist=True, adapter=adapter, sleep=sleep):
                return DeploymentResult('unresolved', 'PRIOR_STATE_DRIFT', 'Old flows not all present before replacement')
    except Exception as exc:
        return DeploymentResult('failed', 'PREFLIGHT_FAILED', str(exc)[:1000], False)

    changed = False
    try:
        # New first minimizes a gap in a default-allow network. OF1.3 multi-
        # switch atomicity is NOT asserted; the transition may temporarily overblock.
        for flow in new_flows:
            changed = True
            adapter.add_flow(flow)
        if on_verifying:
            on_verifying()
        if not _verify_all(new_flows, should_exist=True, adapter=adapter, sleep=sleep):
            raise RuntimeError('New flows not verified after installation')
        for flow in old_flows:
            changed = True
            adapter.delete_flow(flow)
        if not _verify_all(old_flows, should_exist=False, adapter=adapter, sleep=sleep):
            raise RuntimeError('Old flows not absent after removal')
        # Strict delete must not remove new-cookie flows (including identical match).
        if not _verify_all(new_flows, should_exist=True, adapter=adapter, sleep=sleep):
            raise RuntimeError('New flows disappeared during replacement')
        return DeploymentResult('succeeded', compensated=None, attempted_network_change=changed)
    except Exception as exc:
        cause = str(exc)[:1000]
        if not changed:
            return DeploymentResult('failed', 'DEPLOY_FAILED', cause, False)
        # Best effort, but success of REST delete isn't proof of rollback.
        try:
            for flow in new_flows:
                adapter.delete_flow(flow)
            for flow in old_flows:
                if is_active_before:
                    adapter.add_flow(flow)
            new_absent = _verify_all(new_flows, should_exist=False, adapter=adapter, sleep=sleep)
            old_restored = (not is_active_before or
                            _verify_all(old_flows, should_exist=True, adapter=adapter, sleep=sleep))
            if new_absent and old_restored:
                return DeploymentResult('failed', 'DEPLOY_COMPENSATED', cause, True, True)
            return DeploymentResult('unresolved', 'COMPENSATION_NOT_VERIFIED', cause, False, True)
        except Exception as cleanup_exc:
            return DeploymentResult('unresolved', 'COMPENSATION_UNAVAILABLE',
                                    f'{cause}; cleanup: {cleanup_exc}'[:1200], False, True)
