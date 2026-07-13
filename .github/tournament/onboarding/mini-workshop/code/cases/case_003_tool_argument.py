from __future__ import annotations

from time import perf_counter

from opik import track
from shared.models import CustomerQuestion, ToolResult


@track
def parse_refund_request(question: CustomerQuestion) -> dict[str, object]:
    return {
        "customer_id": question.customer_id,
        "requested_product": question.product,
        "region": question.region,
        "activated_seats": 2,
        "days_since_purchase": 18,
        "export_job_ran": False,
    }


@track
def calculate_refund_eligibility(
    *,
    product: str,
    region: str,
    activated_seats: int,
    days_since_purchase: int,
    export_job_ran: bool,
) -> ToolResult:
    started = perf_counter()
    if product == "pro" and region == "HK":
        eligible = days_since_purchase <= 30 and activated_seats < 3 and not export_job_ran
        reason = "HK Pro refund window is open."
    elif product == "starter" and region == "HK":
        eligible = False
        reason = "HK Starter activated seats are not refundable."
    else:
        eligible = days_since_purchase <= 7 and not export_job_ran
        reason = "Fallback seven day refund policy."

    return ToolResult(
        name="calculate_refund_eligibility",
        input={
            "product": product,
            "region": region,
            "activated_seats": activated_seats,
            "days_since_purchase": days_since_purchase,
            "export_job_ran": export_job_ran,
        },
        output={"eligible": eligible, "reason": reason},
        latency_ms=int((perf_counter() - started) * 1000),
    )


@track
def run_case(question: CustomerQuestion) -> str:
    request = parse_refund_request(question)
    tool = calculate_refund_eligibility(
        product="pro",
        region=str(request["region"]),
        activated_seats=int(request["activated_seats"]),
        days_since_purchase=int(request["days_since_purchase"]),
        export_job_ran=bool(request["export_job_ran"]),
    )
    status = "eligible" if tool.output["eligible"] else "not eligible"
    return f"The customer is {status}: {tool.output['reason']}"
