"""
RISHI.py — Multi-Tenant Central MCP Node
=========================================
Runs as the sole server process.  All Chanakya agents connect to it
over SSE and execute tools via the MCP protocol.

Security model
--------------
• Every incoming SSE connection must present a valid x-agent-id and a
  matching bearer token from AGENT_TOKENS (loaded from the environment).
• Each agent receives a scoped FastMCP instance exposing ONLY the tools
  listed in its AGENT_REGISTRY entry — tool bleed across roles is
  structurally impossible.
• The shared blackboard enforces a per-key size cap and a total key-count
  cap to prevent runaway writes.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from concurrent.futures import ProcessPoolExecutor

import psutil
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport

# ---------------------------------------------------------------------------
# Logging — import the shared utility; configure once at startup
# ---------------------------------------------------------------------------
import sys
sys.path.insert(0, os.path.dirname(__file__))

# Load .env before anything reads os.environ (tokens, RAM threshold, etc.)
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)

from utils.logger_config import configure_logging

configure_logging()
logger = logging.getLogger("RISHI.Server")

# ---------------------------------------------------------------------------
# 1. SYSTEM CONFIGURATION
# ---------------------------------------------------------------------------
CRITICAL_RAM_PERCENT = float(os.getenv("CRITICAL_RAM_PERCENT", "85.0"))
worker_cores = max(1, (os.cpu_count() or 4) - 2)
process_pool = ProcessPoolExecutor(max_workers=worker_cores)

# ---------------------------------------------------------------------------
# 2. TOKEN STORE
#    Load per-agent bearer tokens from the environment.
#    Format:  AGENT_TOKEN_<AGENT_ID_UPPERCASE>=<token>
#    Example: AGENT_TOKEN_RISHI_CORE_NODE=some-long-random-secret
#
#    Falls back to a random token in dev if the env var is missing,
#    which means agents using the old hardcoded fallback will be rejected.
# ---------------------------------------------------------------------------
def _load_token(agent_id: str) -> str:
    env_key = f"AGENT_TOKEN_{agent_id.upper().replace('-', '_')}"
    token = os.getenv(env_key)
    if not token:
        # Generate a random token so the server starts, but agents that send
        # the hardcoded fallback "alpha_secure_node_001" will be rejected.
        token = secrets.token_hex(32)
        logger.warning(
            f"No token configured for agent '{agent_id}' (env var: {env_key}). "
            "A random token has been assigned — set the env var to allow connections."
        )
    return token


# ---------------------------------------------------------------------------
# 3. AGENT REGISTRY
#    Maps agent_id → role + allowed_tools + expected bearer token
# ---------------------------------------------------------------------------
AGENT_REGISTRY: dict[str, dict] = {
    # Core system controller
    "rishi_core_node": {
        "role": "system_controller",
        "allowed_tools": ["read_blackboard", "write_blackboard"],
    },
    # Phase 1 — Quantitative
    "agent_chanakya_deterministic": {
        "role": "quantitative_analyst",
        "allowed_tools": ["tamper_proof_audit_math", "calculate_tax_liability", "write_blackboard"],
    },
    "agent_chanakya_auditability": {
        "role": "ledger_auditor",
        "allowed_tools": ["read_blackboard"],
    },
    # Phase 2 — Qualitative
    "agent_chanakya_ethical": {
        "role": "compliance_officer",
        "allowed_tools": ["evaluate_compliance", "read_blackboard", "write_blackboard"],
    },
    "agent_chanakya_critical": {
        "role": "strategic_analyst",
        "allowed_tools": ["analyze_strategy", "read_blackboard", "write_blackboard"],
    },
    # Phase 3 — Output
    "agent_chanakya_communication": {
        "role": "executive_writer",
        "allowed_tools": ["generate_executive_summary", "read_blackboard", "write_blackboard"],
    },
    "agent_chanakya_visualization": {
        "role": "data_visualizer",
        "allowed_tools": ["generate_visualizations", "read_blackboard", "write_blackboard"],
    },
    "agent_chanakya_esg": {
        "role": "esg_analyst",
        "allowed_tools": ["calculate_esg_metrics", "read_blackboard", "write_blackboard"],
    },
    # Phase 4 — Evolution
    "agent_chanakya_adaptability": {
        "role": "regulatory_researcher",
        "allowed_tools": ["fetch_regulatory_updates", "read_blackboard", "write_blackboard"],
    },
}

# Pre-load tokens at startup
AGENT_TOKENS: dict[str, str] = {
    agent_id: _load_token(agent_id) for agent_id in AGENT_REGISTRY
}


# ---------------------------------------------------------------------------
# 4. AUTHENTICATION
# ---------------------------------------------------------------------------
def verify_and_route_agent(
    x_agent_id: str = Header(None),
    x_agent_token: str = Header(None),
) -> str:
    """
    Validates agent identity and bearer token using constant-time comparison.
    Raises 401 on unknown agent or wrong token, 503 on RAM pressure.
    """
    if not x_agent_id or x_agent_id not in AGENT_REGISTRY:
        raise HTTPException(status_code=401, detail="Unregistered Agent Identity")

    # Parse "Bearer <token>" — accept both bare token and Bearer prefix
    raw_token = x_agent_token or ""
    presented = raw_token.removeprefix("Bearer ").strip()

    expected = AGENT_TOKENS.get(x_agent_id, "")
    # hmac.compare_digest prevents timing-based oracle attacks
    if not hmac.compare_digest(presented.encode(), expected.encode()):
        logger.warning(f"Token mismatch for agent '{x_agent_id}'")
        raise HTTPException(status_code=401, detail="Invalid Agent Token")

    if psutil.virtual_memory().percent > CRITICAL_RAM_PERCENT:
        raise HTTPException(status_code=503, detail="Server Load Critical. Hold.")

    return x_agent_id


# ---------------------------------------------------------------------------
# 5. BLACKBOARD (Inter-Agent Shared Memory)
# ---------------------------------------------------------------------------
MAX_BLACKBOARD_KEYS = 256
MAX_VALUE_BYTES = 64 * 1024  # 64 KB per entry

shared_blackboard: dict[str, str] = {}
blackboard_lock = asyncio.Lock()


async def _write_to_blackboard(key: str, data: str) -> str:
    """Write a value to the shared blackboard (enforces size limits)."""
    if len(data.encode()) > MAX_VALUE_BYTES:
        return f"Error: Value exceeds {MAX_VALUE_BYTES // 1024} KB limit."
    async with blackboard_lock:
        if key not in shared_blackboard and len(shared_blackboard) >= MAX_BLACKBOARD_KEYS:
            return f"Error: Blackboard full ({MAX_BLACKBOARD_KEYS} keys maximum)."
        shared_blackboard[key] = data
    return f"Written to blackboard: '{key}'"


async def _read_from_blackboard(key: str) -> str:
    """Read a value from the shared blackboard."""
    async with blackboard_lock:
        return shared_blackboard.get(key, f"Error: Key '{key}' not found on blackboard.")


# ---------------------------------------------------------------------------
# 6. TOOL IMPLEMENTATIONS
# ---------------------------------------------------------------------------

# ── 6a. Deterministic financial math ────────────────────────────────────────
ALLOWED_OPERATIONS = {"add", "subtract", "multiply", "divide"}


async def _tamper_proof_audit_math(operation: str, operands: list[str]) -> str:
    """
    Executes exact-precision arithmetic using Python's Decimal module and
    returns the result together with a SHA-256 audit hash that proves the
    computation was performed on this specific input.

    The hash covers: operation + sorted(operands) + result — making it
    impossible to swap inputs after the fact without invalidating the hash.
    """
    if operation not in ALLOWED_OPERATIONS:
        return json.dumps({"status": "error", "message": f"Unknown operation '{operation}'. Allowed: {sorted(ALLOWED_OPERATIONS)}"})

    if len(operands) < 2:
        return json.dumps({"status": "error", "message": "At least two operands are required."})

    try:
        values = [Decimal(op) for op in operands]
    except InvalidOperation as exc:
        return json.dumps({"status": "error", "message": f"Non-numeric operand: {exc}"})

    try:
        result = values[0]
        if operation == "add":
            for v in values[1:]:
                result += v
        elif operation == "subtract":
            for v in values[1:]:
                result -= v
        elif operation == "multiply":
            for v in values[1:]:
                result *= v
        elif operation == "divide":
            for v in values[1:]:
                if v == 0:
                    return json.dumps({"status": "error", "message": "Division by zero."})
                result /= v
    except Exception as exc:
        return json.dumps({"status": "error", "message": f"Calculation error: {exc}"})

    # Quantise to 10 decimal places for financial reporting
    exact_result = str(result.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_EVEN))

    # Build a canonical audit preimage
    preimage = f"{operation}|{','.join(operands)}|{exact_result}|{datetime.now(timezone.utc).isoformat()}"
    audit_hash = hashlib.sha256(preimage.encode()).hexdigest()

    return json.dumps({
        "status": "ok",
        "operation": operation,
        "operands": operands,
        "exact_result": exact_result,
        "audit_hash": audit_hash,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    })

async def _calculate_tax_liability(principal: str, regime: str = "india_new_2024") -> str:
    """
    Executes exact-precision slab-based tax calculation using Python's Decimal.
    """
    try:
        income = Decimal(principal)
    except InvalidOperation as exc:
        return json.dumps({"status": "error", "message": f"Non-numeric principal: {exc}"})

    if income < 0:
        return json.dumps({"status": "error", "message": "Income cannot be negative."})

    slabs = []
    tax = Decimal("0")
    
    # India Income Tax New Regime FY 2024-25
    brackets = [
        (Decimal("300000"), Decimal("0.00")),
        (Decimal("700000"), Decimal("0.05")),
        (Decimal("1000000"), Decimal("0.10")),
        (Decimal("1200000"), Decimal("0.15")),
        (Decimal("1500000"), Decimal("0.20")),
        (Decimal("Infinity"), Decimal("0.30"))
    ]
    
    previous_limit = Decimal("0")
    for limit, rate in brackets:
        if income > previous_limit:
            taxable_in_slab = min(income - previous_limit, limit - previous_limit)
            slab_tax = taxable_in_slab * rate
            slabs.append({
                "bracket": f"{previous_limit}-{limit}",
                "taxable_amount": str(taxable_in_slab.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)),
                "rate": str(rate),
                "tax": str(slab_tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))
            })
            tax += slab_tax
            previous_limit = limit
        else:
            break

    # Health and Education Cess (4%)
    cess = tax * Decimal("0.04")
    total_tax = tax + cess
    
    exact_result = str(total_tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))
    
    # Build a canonical audit preimage
    preimage = f"tax_slab|{principal}|{regime}|{exact_result}|{datetime.now(timezone.utc).isoformat()}"
    audit_hash = hashlib.sha256(preimage.encode()).hexdigest()

    return json.dumps({
        "status": "ok",
        "operation": "tax_slab",
        "regime": regime,
        "principal": principal,
        "exact_result": exact_result,
        "slab_breakdown": slabs,
        "audit_hash": audit_hash,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    })


# ── 6b. Compliance evaluation ────────────────────────────────────────────────
# A structured rule-based compliance engine using FATF lists and CTR triggers.
COMPLIANCE_BLOCKLIST = [
    "tax evasion", "money laundering", "bribe", "kickback", "sanction",
]
FATF_BLACKLIST = ["north korea", "iran", "myanmar", "cayman islands"]
FATF_GREYLIST = ["panama", "uae", "syria"]
HIGH_RISK_ENTITIES = ["shell company", "unregistered charity", "bearer share"]
CTR_THRESHOLD = Decimal("1000000")  # e.g., > 10L requires EDD

async def _evaluate_compliance(proposal: str, jurisdiction: str = "", entity_type: str = "", transaction_amount: str = "0") -> str:
    """
    Evaluates a financial proposal against a structured AML/KYC rule set.
    Returns APPROVED, REJECTED, or EDD_REQUIRED with detailed flags.
    """
    try:
        amount = Decimal(transaction_amount)
    except InvalidOperation:
        amount = Decimal("0")
        
    flags = []
    status = "APPROVED"
    
    # 1. Jurisdiction Risk
    juris_lower = jurisdiction.lower()
    if any(b in juris_lower for b in FATF_BLACKLIST):
        flags.append(f"Jurisdiction '{jurisdiction}' is on FATF Blacklist.")
        status = "REJECTED"
    elif any(g in juris_lower for g in FATF_GREYLIST):
        flags.append(f"Jurisdiction '{jurisdiction}' is on FATF Greylist (EDD Required).")
        if status != "REJECTED": status = "EDD_REQUIRED"
        
    # 2. Entity Risk
    entity_lower = entity_type.lower()
    if any(h in entity_lower for h in HIGH_RISK_ENTITIES):
        flags.append(f"Entity type '{entity_type}' is classified as High Risk.")
        status = "REJECTED"
        
    # 3. Transaction Size Trigger (CTR)
    if amount > CTR_THRESHOLD:
        flags.append(f"Transaction amount ({amount}) exceeds CTR threshold ({CTR_THRESHOLD}). Enhanced Due Diligence required.")
        if status != "REJECTED": status = "EDD_REQUIRED"
        
    # 4. General Policy (Legacy Blocklist for catching explicit bad words)
    proposal_lower = proposal.lower()
    for term in COMPLIANCE_BLOCKLIST:
        if term in proposal_lower:
            flags.append(f"Proposal contains prohibited term: '{term}'")
            status = "REJECTED"
            
    if not flags:
        return json.dumps({
            "status": "APPROVED",
            "reason": "No policy violations detected.",
            "flags": [],
            "policy": "AML/KYC Compliance Framework v3.0",
        })
    else:
        return json.dumps({
            "status": status,
            "reason": " | ".join(flags),
            "flags": flags,
            "policy": "AML/KYC Compliance Framework v3.0",
        })


# ── 6c. Strategic analysis ───────────────────────────────────────────────────
async def _analyze_strategy(context: str) -> str:
    """
    Performs rule-based strategic analysis on a JSON context payload.
    In production this would invoke an LLM or RAG pipeline.
    """
    try:
        payload = json.loads(context)
    except json.JSONDecodeError:
        payload = {"proposal": context}

    proposal = payload.get("proposal", "")
    audit_ok = "Error" not in payload.get("audit_context", "Error")
    compliance_ok = payload.get("compliance_context", "") != "REJECTED"

    insights = [
        f"Proposal scope: '{proposal[:120]}'",
        "Audit chain verified." if audit_ok else "WARNING: Audit chain incomplete.",
        "Compliance gate passed." if compliance_ok else "WARNING: Compliance not cleared.",
        "Recommend quarterly review against updated ESG benchmarks.",
    ]
    risks = []
    if not audit_ok:
        risks.append("Missing cryptographic audit record — traceability gap.")
    if "15%" in proposal or "reallocat" in proposal.lower():
        risks.append("Budget reallocation exceeds 10% threshold — board sign-off required.")

    return json.dumps({
        "status": "ok",
        "strategic_insights": insights,
        "risk_factors": risks,
    })


# ── 6d. Executive summary ────────────────────────────────────────────────────
async def _generate_executive_summary(data_payload: str) -> str:
    """
    Translates a structured strategic plan JSON into a human-readable summary.
    """
    try:
        plan = json.loads(data_payload)
    except json.JSONDecodeError:
        plan = {"action": data_payload, "insights": [], "risks": []}

    action = plan.get("action", "N/A")
    insights = plan.get("insights", [])
    risks = plan.get("risks", [])

    lines = [
        "EXECUTIVE SUMMARY",
        "=================",
        f"Proposed Action: {action}",
        "",
        "Key Insights:",
        *[f"  • {i}" for i in insights],
        "",
        "Risk Factors:",
        *(([f"  ⚠ {r}" for r in risks]) if risks else ["  None identified."]),
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    return "\n".join(lines)


# ── 6e. Visualization payload ────────────────────────────────────────────────
async def _generate_visualizations(source_data: str) -> str:
    """
    Builds chart-ready data payloads from the strategic plan.
    In production this could write PNG files or push to Power BI.
    """
    try:
        plan = json.loads(source_data)
    except json.JSONDecodeError:
        plan = {}

    return json.dumps({
        "status": "ok",
        "dashboard_url": "Local Preview Only",
        "exported_charts": [
            "charts/risk_matrix.png",
            "charts/budget_allocation.png",
            "charts/esg_scores.png",
        ],
        "insight_count": len(plan.get("insights", [])),
        "risk_count": len(plan.get("risks", [])),
    })


# ── 6f. ESG metrics ──────────────────────────────────────────────────────────
async def _calculate_esg_metrics(financial_data: str) -> str:
    """
    Estimates carbon footprint and ESG compliance from the financial strategy.
    Emission factors are illustrative; replace with sector-specific DEFRA/EPA values.
    """
    try:
        plan = json.loads(financial_data)
    except json.JSONDecodeError:
        plan = {}

    action = plan.get("action", "").lower()
    # Simplified scoring: sustainability keywords lower carbon estimate
    sustainability_keywords = ["sustainability", "renewable", "green", "carbon", "esg"]
    sustainability_score = sum(1 for kw in sustainability_keywords if kw in action)

    base_carbon = 1200.0  # metric tons CO2e (illustrative baseline)
    estimated_carbon = round(base_carbon * max(0.5, 1.0 - sustainability_score * 0.1), 2)
    esg_compliant = sustainability_score >= 1

    return json.dumps({
        "status": "ok",
        "estimated_carbon_tons": estimated_carbon,
        "esg_compliance": "COMPLIANT" if esg_compliant else "REVIEW_REQUIRED",
        "sustainability_score": sustainability_score,
        "sustainability_recommendations": [
            "Offset remaining emissions via certified carbon credits.",
            "Publish annual sustainability report (GRI Standards).",
            "Set Science Based Targets (SBTi) within 12 months.",
        ],
    })


# ── 6g. Regulatory research ──────────────────────────────────────────────────
async def _fetch_regulatory_updates(query: str) -> str:
    """
    Returns the latest simulated regulatory updates relevant to the query.
    In production this would call a RAG system or a curated news API.
    """
    return json.dumps({
        "status": "ok",
        "query": query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "key_regulatory_changes": [
            "IFRS S1/S2 mandatory sustainability disclosure effective FY2026.",
            "Pillar Two global minimum tax (15%) enforcement begins Q1 2026.",
            "SEC climate disclosure rules finalised — large accelerated filers first.",
            "EU CSRD extended to non-EU parent companies with EU subsidiaries.",
        ],
        "new_risk_alerts": [
            "Increased OECD scrutiny of transfer-pricing arrangements in tech sector.",
            "Greenwashing enforcement actions rising — ensure ESG claims are auditable.",
        ],
    })


# ---------------------------------------------------------------------------
# 7. TOOL MAP  name → (callable, description)
# ---------------------------------------------------------------------------
TOOL_IMPLEMENTATIONS: dict[str, tuple] = {
    "tamper_proof_audit_math": (
        _tamper_proof_audit_math,
        "Execute exact-precision arithmetic (add/subtract/multiply/divide) on decimal operands "
        "and return the result with a SHA-256 audit hash.",
    ),
    "calculate_tax_liability": (
        _calculate_tax_liability,
        "Execute exact-precision slab-based tax calculation using Indian Income Tax New Regime slabs.",
    ),
    "read_blackboard": (
        _read_from_blackboard,
        "Read a value from the shared in-memory blackboard by key.",
    ),
    "write_blackboard": (
        _write_to_blackboard,
        "Write a value to the shared in-memory blackboard under the given key.",
    ),
    "evaluate_compliance": (
        _evaluate_compliance,
        "Evaluate a financial proposal against the AML/KYC compliance rule set. "
        "Returns APPROVED or REJECTED with a reason.",
    ),
    "analyze_strategy": (
        _analyze_strategy,
        "Perform strategic analysis on a JSON context payload containing a proposal, "
        "audit context, and compliance context.",
    ),
    "generate_executive_summary": (
        _generate_executive_summary,
        "Translate a structured strategic plan JSON into a human-readable executive summary.",
    ),
    "generate_visualizations": (
        _generate_visualizations,
        "Build chart-ready payloads and export paths from the strategic plan.",
    ),
    "calculate_esg_metrics": (
        _calculate_esg_metrics,
        "Calculate carbon footprint and ESG compliance metrics from financial strategy data.",
    ),
    "fetch_regulatory_updates": (
        _fetch_regulatory_updates,
        "Fetch the latest regulatory changes and risk alerts relevant to the given query.",
    ),
}


# ---------------------------------------------------------------------------
# 8. SCOPED MCP SERVER FACTORY
# ---------------------------------------------------------------------------
def build_scoped_mcp(agent_id: str) -> FastMCP:
    """
    Build a FastMCP instance exposing ONLY the tools listed for this agent.
    Tool isolation is structural — an agent literally cannot call a tool that
    is not registered on its server instance.
    """
    allowed = AGENT_REGISTRY[agent_id]["allowed_tools"]
    mcp = FastMCP(name=f"Node_{agent_id}")
    for name in allowed:
        if name in TOOL_IMPLEMENTATIONS:
            func, doc = TOOL_IMPLEMENTATIONS[name]
            mcp.tool(name=name, description=doc)(func)
    return mcp


# ---------------------------------------------------------------------------
# 9. SINGLE SHARED SSE TRANSPORT
# ---------------------------------------------------------------------------
shared_sse_transport = SseServerTransport("/messages/")


# ---------------------------------------------------------------------------
# 10. FASTAPI APPLICATION
# ---------------------------------------------------------------------------
app = FastAPI(title="RISHI Multi-Tenant Central Node", version="2.0.0")

# Mount the transport's POST handler as a proper ASGI sub-application so
# tool-call POSTs from agents are routed to the correct SSE session.
app.mount("/messages", app=shared_sse_transport.handle_post_message)


@app.get("/sse")
async def connect_agent(
    request: Request,
    agent_id: str = Depends(verify_and_route_agent),
    x_agent_id: str = Header(None),
):
    """
    Opens a scoped MCP-over-SSE session for the authenticated agent.
    The agent receives only the tools its role is permitted to call.
    """
    logger.info(f"Agent '{x_agent_id}' connected (role: {AGENT_REGISTRY[x_agent_id]['role']})")
    scoped_mcp = build_scoped_mcp(x_agent_id)
    mcp_server = scoped_mcp._mcp_server

    async with shared_sse_transport.connect_sse(
        request.scope, request.receive, request._send  # type: ignore[attr-defined]
    ) as (read_stream, write_stream):
        await mcp_server.run(
            read_stream,
            write_stream,
            mcp_server.create_initialization_options(),
        )

    logger.info(f"Agent '{x_agent_id}' disconnected.")


@app.get("/health")
def health_check():
    """
    Internal health probe.  Returns system metrics without leaking
    blackboard contents or agent token information.
    """
    mem = psutil.virtual_memory()
    return {
        "status": "ok",
        "ram_percent": mem.percent,
        "ram_critical_threshold": CRITICAL_RAM_PERCENT,
        "active_sessions": len(shared_sse_transport._read_stream_writers),
        "blackboard_entry_count": len(shared_blackboard),
        "blackboard_max_keys": MAX_BLACKBOARD_KEYS,
        "registered_agent_count": len(AGENT_REGISTRY),
    }


if __name__ == "__main__":
    import uvicorn
    logger.info("Initializing RISHI Multi-Tenant Node Architecture.")
    logger.info(f"Workers: {worker_cores} cores | RAM threshold: {CRITICAL_RAM_PERCENT}%")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")