"""kW-first TCO estimates for a solved CapacityPlan (spec §6.5, sub-project D task 9).

Reality check (verified against ``config/device-seed.yaml`` — grep it, don't
trust a comment): every datacenter-class device in the catalog (H100, H200,
B200, MI300X, the HGX/NVL nodes and clusters, ...) carries
``indicative_price_usd=None`` — vendors don't publish list prices for this
tier. Only a handful of consumer/workstation cards (RTX 4090, RTX 5090, RTX
6000 Ada) have a price on file. That means the ``$/Mtok`` figure is
electricity-only for essentially every real datacenter plan today, and the
honest headline metric is ``tokens_per_sec_per_kw`` — throughput per unit of
power, which needs no price data at all.

``estimate_tco`` resolves the device from ``plan.device_id`` (the same
string ``radar.capacity.solver.plan_capacity``/``max_workload`` recorded on
the plan) via ``radar.models_radar.devices.resolve_device`` — callers never
pass a ``DeviceProfile`` directly.

Math, given a solved ``CapacityPlan``:

- ``fleet_power_kw = n_gpus * device.tdp_watts / 1000`` (round 2) — GPU
  *board* TDP only. It does not include host CPUs, cooling, PSUs, or any
  other rack-level overhead, which the disclosed assumption note pegs at
  roughly +30-50% in a real datacenter.
- ``tokens_per_sec_per_kw = plan.throughput.aggregate_decode_tps /
  fleet_power_kw`` (round 1) — the headline efficiency number, always
  computable once TDP and a throughput estimate both exist.
- ``usd_per_million_tokens`` (round 4) sums two $/s terms, then divides by
  the fleet's tokens/sec (in millions):
  - electricity: ``fleet_power_kw * electricity_usd_per_kwh / 3600``.
  - hardware amortization: ``n_gpus * device.indicative_price_usd /
    (amortization_months * 30.44 * 86400)`` — 30.44 is the average days per
    month (365.25 / 12), the standard way to amortize a monthly figure
    against a per-second rate without picking a lucky/unlucky calendar
    month. This term is **0** (not counted, not skipped) when
    ``indicative_price_usd`` is ``None`` — the returned value is then
    electricity-only, and an assumption note says so explicitly rather than
    silently under-counting cost.

Returns ``None`` — the whole estimate, not a partial one — when either of
two things is missing: ``device.tdp_watts is None`` (no way to compute fleet
power at all) or ``plan.throughput is None`` (no tokens/sec means no
per-token metric is meaningful, memory-only plans included). Both
conditions are checked; either one alone is enough to bail out.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from radar.capacity.solver import CapacityPlan
from radar.capacity.types import AssumptionSheet
from radar.models_radar.devices import resolve_device


DEFAULT_ELECTRICITY_USD_PER_KWH = 0.12
DEFAULT_AMORTIZATION_MONTHS = 36

_AVG_DAYS_PER_MONTH = 30.44  # 365.25 / 12 — standard month-to-second amortization basis
_SECONDS_PER_DAY = 86400
_SECONDS_PER_HOUR = 3600


class TCOEstimate(BaseModel):
    """kW-first cost/efficiency estimate for one solved ``CapacityPlan``."""

    model_config = ConfigDict(frozen=True)

    fleet_power_kw: float
    tokens_per_sec_per_kw: float | None
    usd_per_million_tokens: float | None
    assumptions: AssumptionSheet


def estimate_tco(
    plan: CapacityPlan,
    *,
    electricity_usd_per_kwh: float = DEFAULT_ELECTRICITY_USD_PER_KWH,
    amortization_months: int = DEFAULT_AMORTIZATION_MONTHS,
) -> TCOEstimate | None:
    """kW-first TCO for a solved plan — see the module docstring for the math.

    ``None`` when ``resolve_device(plan.device_id).tdp_watts`` is ``None``
    (no published board TDP) or ``plan.throughput`` is ``None`` (no
    tokens/sec estimate to amortize cost or power against) — either
    condition alone is enough.
    """
    device = resolve_device(plan.device_id)
    if device.tdp_watts is None or plan.throughput is None:
        return None

    fleet_power_kw = round(plan.n_gpus * device.tdp_watts / 1000, 2)
    aggregate_tps = plan.throughput.aggregate_decode_tps

    tokens_per_sec_per_kw: float | None = None
    usd_per_million_tokens: float | None = None
    zero_power_note: str | None = None
    if fleet_power_kw > 0:
        tokens_per_sec_per_kw = round(aggregate_tps / fleet_power_kw, 1)

        electricity_usd_per_sec = fleet_power_kw * electricity_usd_per_kwh / _SECONDS_PER_HOUR
        price = device.indicative_price_usd
        hardware_usd_per_sec = (
            plan.n_gpus * price / (amortization_months * _AVG_DAYS_PER_MONTH * _SECONDS_PER_DAY)
            if price is not None else 0.0
        )
        total_usd_per_sec = electricity_usd_per_sec + hardware_usd_per_sec
        usd_per_million_tokens = round(total_usd_per_sec / (aggregate_tps / 1e6), 4)
    else:
        # Not observed in config/device-seed.yaml today (every published
        # tdp_watts is positive) — guarded rather than risking a
        # ZeroDivisionError if a future/custom entry ever records 0.
        zero_power_note = (
            f"fleet_power_kw computed as {fleet_power_kw} (n_gpus={plan.n_gpus} x "
            f"tdp_watts={device.tdp_watts}) — tokens/s/kW and $/Mtok are undefined at zero power"
        )

    assumptions = AssumptionSheet().plus(
        f"electricity rate ${electricity_usd_per_kwh:.2f}/kWh "
        f"(CLI default ${DEFAULT_ELECTRICITY_USD_PER_KWH:.2f}, override with --electricity-usd-kwh)",
        f"hardware amortized over {amortization_months} months "
        f"(CLI default {DEFAULT_AMORTIZATION_MONTHS}, override with --amortization-months), "
        f"basis {_AVG_DAYS_PER_MONTH} avg days/month",
        "fleet power is GPU board TDP only — excludes host CPUs, cooling, "
        "PSU overhead (~+30-50% at the rack)",
    )
    if device.indicative_price_usd is None:
        assumptions = assumptions.plus(
            f"$/Mtok excludes hardware capex: no public list price for {device.name}"
        )
    if zero_power_note is not None:
        assumptions = assumptions.plus(zero_power_note)

    return TCOEstimate(
        fleet_power_kw=fleet_power_kw,
        tokens_per_sec_per_kw=tokens_per_sec_per_kw,
        usd_per_million_tokens=usd_per_million_tokens,
        assumptions=assumptions,
    )
