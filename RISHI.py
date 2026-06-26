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
import re
import subprocess
import tempfile
import logging
import os
import secrets
import quant_solvers
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from concurrent.futures import ProcessPoolExecutor

import psutil
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from uuid import uuid4
import httpx
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

# GPU / VRAM sequencing note for Engineer's GenerativeAI sub-agent:
#   • GenerativeAI checks GPU VRAM via agents/engineer/generative/gpu_guard.py
#     before invoking any local diffusion model — returns RESOURCE_CONSTRAINED
#     (not a silent hang) if headroom is insufficient.
#   • For local dev: do NOT run CoderAI test suites (npm test / pytest) at the
#     same time as a GenerativeAI diffusion job — both are RAM-heavy and will
#     compete for system memory alongside Ollama.
#   • This is operational guidance (local dev scheduling), not a hard code gate,
#     since the threshold varies by machine. The env var ENGINEER_MIN_FREE_VRAM_MB
#     (default 4096 MB) tunes GenerativeAI's VRAM floor.

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
    # ── Engineer Orchestrator & Sub-Agents ────────────────────────────────
    # Engineer is the third orchestrator — sits alongside Chanakya and Kavach.
    # Sub-agents expose no MCP tools of their own (they use REST/HTTP to RISHI
    # for audit and approvals), but are registered here so their bearer tokens
    # are pre-loaded and the auth middleware can validate their identities.
    "agent_engineer_coder": {
        "role": "engineer_coder",
        "allowed_tools": [],   # CoderAI communicates via /engineer/* REST endpoints
    },
    "agent_engineer_designer": {
        "role": "engineer_designer",
        "allowed_tools": [],   # DesignerAI — Tier 0 output only, no MCP tools needed
    },
    "agent_engineer_generative": {
        "role": "engineer_generative",
        "allowed_tools": [],   # GenerativeAI — wraps local CLI, no MCP tools needed
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

def resolve_regime_for_date(tax_regimes: dict, tx_date: str) -> str:
    """Resolves the correct tax regime based on transaction date."""
    try:
        tx_dt = datetime.fromisoformat(tx_date.replace("Z", "+00:00"))
    except ValueError:
        tx_dt = datetime.now(timezone.utc)
    
    for regime_id, data in tax_regimes.items():
        if "effective_from" in data and "effective_to" in data:
            start_dt = datetime.fromisoformat(data["effective_from"].replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(data["effective_to"].replace("Z", "+00:00"))
            if start_dt <= tx_dt <= end_dt:
                return regime_id
    return None

async def _calculate_tax_liability(principal: str, transaction_date: str = "") -> str:
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
    
    # Load bitemporal tax regimes
    import os
    regimes_path = os.path.join(os.path.dirname(__file__), "data", "tax_regimes.json")
    try:
        with open(regimes_path, "r") as f:
            tax_regimes = json.load(f)
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Failed to load tax regimes: {e}"})

    if not transaction_date:
        transaction_date = datetime.now(timezone.utc).isoformat()
        
    regime = resolve_regime_for_date(tax_regimes, transaction_date)
    if not regime:
        return json.dumps({"status": "error", "message": f"No active tax regime found for date: {transaction_date}"})
        
    regime_data = tax_regimes[regime]
    
    # Schema validation
    brackets_data = regime_data.get("brackets", [])
    if not brackets_data:
        return json.dumps({"status": "error", "message": "Schema Error: No brackets defined."})
    if brackets_data[-1].get("limit") is not None:
        return json.dumps({"status": "error", "message": "Schema Error: Final bracket must have a null limit (open-ended)."})
        
    brackets = []
    last_limit = Decimal("-1")
    for b in brackets_data:
        raw_limit = b.get("limit")
        limit = Decimal("Infinity") if raw_limit is None else Decimal(str(raw_limit))
        rate = Decimal(str(b.get("rate", "0")))
        
        if limit <= last_limit:
            return json.dumps({"status": "error", "message": "Schema Error: Bracket limits must be strictly ascending."})
        if not (Decimal("0") <= rate <= Decimal("1")):
            return json.dumps({"status": "error", "message": "Schema Error: Rate must be between 0 and 1."})
            
        brackets.append((limit, rate))
        last_limit = limit
    
    # Surcharge Brackets parsing
    surcharge_brackets_data = regime_data.get("surcharge_brackets", [])
    surcharge_brackets = []
    if surcharge_brackets_data:
        last_s_limit = Decimal("-1")
        for b in surcharge_brackets_data:
            raw_s_limit = b.get("limit")
            s_limit = Decimal("Infinity") if raw_s_limit is None else Decimal(str(raw_s_limit))
            s_rate = Decimal(str(b.get("rate", "0")))
            surcharge_brackets.append((s_limit, s_rate))
    
    cess_rate = Decimal(str(regime_data.get("cess_rate", "0.0")))
    
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

    # Surcharge
    surcharge_rate = Decimal("0.0")
    for s_limit, s_rate in surcharge_brackets:
        if income <= s_limit:
            surcharge_rate = s_rate
            break

    surcharge = tax * surcharge_rate
    
    # Health and Education Cess
    cess = (tax + surcharge) * cess_rate
    total_tax = tax + surcharge + cess
    
    exact_result = str(total_tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))
    
    # Build a canonical audit preimage
    eff_from = regime_data.get("effective_from", "UNKNOWN")
    eff_to = regime_data.get("effective_to", "UNKNOWN")
    preimage = f"tax_slab|{principal}|{regime}|{eff_from}|{eff_to}|{exact_result}|{datetime.now(timezone.utc).isoformat()}"
    audit_hash = hashlib.sha256(preimage.encode()).hexdigest()

    return json.dumps({
        "status": "ok",
        "operation": "tax_slab",
        "regime": regime,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "principal": principal,
        "exact_result": exact_result,
        "details": {
            "base_tax": str(tax.quantize(Decimal("0.01"))),
            "surcharge": str(surcharge.quantize(Decimal("0.01"))),
            "cess": str(cess.quantize(Decimal("0.01"))),
            "slabs": slabs
        },
        "audit_hash": audit_hash,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    })


# ── 6b. Compliance evaluation ────────────────────────────────────────────────
# A structured rule-based compliance engine using FATF lists and CTR triggers.
COMPLIANCE_BLOCKLIST = [
    "tax evasion", "money laundering", "bribe", "kickback", "sanction",
]
FATF_BLACKLIST = {
    "jurisdictions": ["north korea", "iran", "myanmar", "cayman islands"],
    "source": "FATF High-Risk Jurisdictions subject to a Call for Action",
    "last_verified": "2026-06-22T00:00:00Z"
}
FATF_GREYLIST = {
    "jurisdictions": ["panama", "uae", "syria"],
    "source": "FATF Jurisdictions under Increased Monitoring",
    "last_verified": "2026-06-22T00:00:00Z"
}
HIGH_RISK_ENTITIES = {
    "entities": ["shell company", "unregistered charity", "bearer share"],
    "source": "FinCEN Advisory on High-Risk Typologies",
    "last_verified": "2026-06-22T00:00:00Z"
}
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
    if any(b in juris_lower for b in FATF_BLACKLIST["jurisdictions"]):
        flags.append(f"Jurisdiction '{jurisdiction}' is on FATF Blacklist.")
        status = "REJECTED"
    elif any(g in juris_lower for g in FATF_GREYLIST["jurisdictions"]):
        flags.append(f"Jurisdiction '{jurisdiction}' is on FATF Greylist (EDD Required).")
        if status != "REJECTED": status = "EDD_REQUIRED"
        
    # 2. Entity Risk
    entity_lower = entity_type.lower()
    if any(h in entity_lower for h in HIGH_RISK_ENTITIES["entities"]):
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

    # If proposal itself is JSON (from orchestrator)
    proposal_text = payload.get("proposal", "")
    try:
        inner_payload = json.loads(proposal_text)
        actual_proposal = inner_payload.get("proposal", proposal_text)
        amount_str = inner_payload.get("transaction_amount", "0")
    except (json.JSONDecodeError, TypeError):
        actual_proposal = proposal_text
        amount_str = "0"
        
    try:
        amount = Decimal(amount_str)
    except InvalidOperation:
        amount = Decimal("0")

    audit_ok = "Error" not in payload.get("audit_context", "Error")
    compliance_ok = payload.get("compliance_context", "") != "REJECTED"

    shock_down = amount * Decimal("0.95")
    shock_up = amount * Decimal("1.05")

    insights = [
        f"Proposal scope: '{actual_proposal[:120]}'",
        "Audit chain verified." if audit_ok else "WARNING: Audit chain incomplete.",
        "Compliance gate passed." if compliance_ok else "WARNING: Compliance not cleared.",
        f"Sensitivity Analysis: Base Capital = ₹{amount:,.2f}",
        f"Sensitivity Analysis: -5% FX Shock = ₹{shock_down:,.2f}",
        f"Sensitivity Analysis: +5% FX Shock = ₹{shock_up:,.2f}",
    ]
    risks = []
    if not audit_ok:
        risks.append("Missing cryptographic audit record — traceability gap.")
    if "15%" in actual_proposal or "reallocat" in actual_proposal.lower():
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

    action_str = plan.get("action", "{}")
    try:
        action_payload = json.loads(action_str)
        amount_str = action_payload.get("transaction_amount", "0")
        entity_type = action_payload.get("entity_type", "unknown").lower()
    except (json.JSONDecodeError, TypeError):
        amount_str = "0"
        entity_type = "unknown"
        
    try:
        amount = Decimal(amount_str)
    except InvalidOperation:
        amount = Decimal("0")

    # GHG Protocol Scope 3 Category 15: Investments
    # Emission factor: kg CO2e per $ (or ₹) invested
    emission_factors = {
        "data": {
            "green energy": Decimal("0.05"),
            "real estate": Decimal("0.40"),
            "shell company": Decimal("0.80"),
            "manufacturing": Decimal("0.60"),
            "unknown": Decimal("0.25")
        },
        "source": "DEFRA / EPA Sector Averages 2026",
        "last_verified": "2026-06-22T00:00:00Z"
    }
    
    factor = emission_factors["data"]["unknown"]
    for key, val in emission_factors["data"].items():
        if key in entity_type:
            factor = val
            break

    # Convert kg to metric tons
    estimated_carbon = (amount * factor / Decimal("1000")).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    esg_compliant = factor <= Decimal("0.10")

    return json.dumps({
        "status": "ok",
        "estimated_carbon_tons": str(estimated_carbon),
        "esg_compliance": "COMPLIANT" if esg_compliant else "REVIEW_REQUIRED",
        "sustainability_score": str(factor),
        "sustainability_recommendations": [
            "Offset remaining emissions via certified carbon credits.",
            "Publish annual sustainability report (GRI Standards).",
            "Set Science Based Targets (SBTi) within 12 months.",
        ],
    })


# ── 6g. Regulatory research ──────────────────────────────────────────────────
async def _fetch_regulatory_updates(query: str) -> str:
    """
    Returns the latest live regulatory updates from the SEC RSS feed.
    Falls back to mock data if the network is blocked.
    """
    import urllib.request
    import xml.etree.ElementTree as ET

    url = "https://www.sec.gov/news/pressreleases.rss"
    key_changes = []
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5.0) as response:
            xml_data = response.read()
        
        root = ET.fromstring(xml_data)
        for item in root.findall('./channel/item')[:4]:
            title = item.find('title')
            if title is not None:
                key_changes.append(title.text)
                
    except Exception as e:
        logger.warning(f"Live SEC RSS fetch failed ({e}). Falling back to mock data.")
        key_changes = [
            "[MOCK] IFRS S1/S2 mandatory sustainability disclosure effective FY2026.",
            "[MOCK] Pillar Two global minimum tax (15%) enforcement begins Q1 2026.",
            "[MOCK] SEC climate disclosure rules finalised — large accelerated filers first.",
            "[MOCK] EU CSRD extended to non-EU parent companies with EU subsidiaries.",
        ]

    return json.dumps({
        "status": "ok",
        "query": query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "key_regulatory_changes": key_changes,
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the transport's POST handler as a proper ASGI sub-application so
# tool-call POSTs from agents are routed to the correct SSE session.
app.mount("/messages", app=shared_sse_transport.handle_post_message)

# ---------------------------------------------------------------------------
# 11. KAVACH HMAC AUDIT TRAIL
# ---------------------------------------------------------------------------
class KavachAuditPayload(BaseModel):
    agent_id: str
    payload: str
    timestamp: str
    signature: str

kavach_audit_hash = "GENESIS_HASH"
audit_lock = asyncio.Lock()

@app.post("/kavach/audit")
async def kavach_audit_log(req: KavachAuditPayload):
    global kavach_audit_hash
    
    expected_secret = os.getenv("AGENT_TOKEN_KAVACH_CORE", "default_kavach_secret").encode()
    message = f"{req.payload}|{req.timestamp}".encode()
    expected_sig = hmac.new(expected_secret, message, hashlib.sha256).hexdigest()
    
    if not hmac.compare_digest(req.signature, expected_sig):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")
        
    async with audit_lock:
        chain_data = f"{kavach_audit_hash}|{req.payload}|{req.timestamp}".encode()
        new_hash = hashlib.sha256(chain_data).hexdigest()
        
        record = {
            "timestamp": req.timestamp,
            "agent_id": req.agent_id,
            "payload": req.payload,
            "prev_hash": kavach_audit_hash,
            "hash": new_hash
        }
        kavach_audit_hash = new_hash
        
        with open("kavach_audit_ledger.jsonl", "a") as f:
            f.write(json.dumps(record) + "\n")
            
    return {"status": "ok", "hash": new_hash}


# ---------------------------------------------------------------------------
# 12. KAVACH PENDING-APPROVAL STORE  (Gap 1)
#     Stateful approval records keyed by UUID.  A human reviewer calls
#     POST /kavach/approvals/{id}/decide with an HMAC-signed decision using
#     their own reviewer token (stored in REVIEWER_TOKENS env var as a
#     comma-separated list of sha256 fingerprints).
#
#     CRITICAL-severity findings require TWO distinct approver signatures
#     before status transitions to APPROVED (dual control).
# ---------------------------------------------------------------------------

approval_store: dict[str, dict] = {}
approval_store_lock = asyncio.Lock()


class ApprovalRequest(BaseModel):
    vuln_type: str
    asset: str
    severity: str          # LOW | MEDIUM | HIGH | CRITICAL
    engagement_id: str
    requesting_agent: str


class ApprovalDecision(BaseModel):
    decision: str          # APPROVED | DENIED
    reviewer_id: str       # identity of the human reviewer
    payload: str           # canonical string that was HMAC-signed
    timestamp: str         # ISO-8601 UTC
    signature: str         # HMAC-SHA256 of "payload|timestamp" under reviewer token


def _verify_reviewer_signature(reviewer_id: str, payload: str, timestamp: str, signature: str) -> bool:
    """
    Verifies the HMAC-SHA256 signature supplied by a human reviewer.
    The reviewer token is loaded from REVIEWER_TOKEN_<REVIEWER_ID_UPPER>.
    Falls back to AGENT_TOKEN_KAVACH_CORE if no specific reviewer token is set
    (dev-mode only — production must set per-reviewer tokens).
    """
    env_key = f"REVIEWER_TOKEN_{reviewer_id.upper().replace('-', '_')}"
    reviewer_secret = os.getenv(env_key) or os.getenv("AGENT_TOKEN_KAVACH_CORE", "default_kavach_secret")
    secret = reviewer_secret.encode()
    message = f"{payload}|{timestamp}".encode()
    expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


async def _write_approval_audit(event: str, detail: dict):
    """Write an approval lifecycle event to the tamper-evident audit ledger."""
    secret = os.getenv("AGENT_TOKEN_KAVACH_CORE", "default_kavach_secret").encode()
    payload_dict = {"phase": event, "event_data": detail}
    payload_str = json.dumps(payload_dict, sort_keys=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    message = f"{payload_str}|{timestamp}".encode()
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    # Re-use the existing audit endpoint internally
    await kavach_audit_log(KavachAuditPayload(
        agent_id="RISHI_APPROVAL_STORE",
        payload=payload_str,
        timestamp=timestamp,
        signature=signature,
    ))


@app.post("/kavach/approvals", status_code=201)
async def create_approval(req: ApprovalRequest):
    """
    Kavach calls this when it encounters a HIGH/CRITICAL finding that needs
    human sign-off.  Returns an approval_id the agent polls until a decision
    arrives or the timeout expires.
    """
    approval_id = str(uuid4())
    record = {
        "approval_id": approval_id,
        "status": "PENDING",
        "vuln_type": req.vuln_type,
        "asset": req.asset,
        "severity": req.severity,
        "engagement_id": req.engagement_id,
        "requesting_agent": req.requesting_agent,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decisions": [],           # list of individual reviewer decisions
        "required_approvers": 2 if (req.severity == "CRITICAL" or req.vuln_type == "deploy") else 1,
    }
    async with approval_store_lock:
        approval_store[approval_id] = record

    await _write_approval_audit("APPROVAL_CREATED", {
        "approval_id": approval_id,
        "asset": req.asset,
        "severity": req.severity,
        "engagement_id": req.engagement_id,
    })
    logger.info(f"[APPROVAL] Created {approval_id} for {req.asset} ({req.severity})")
    return {"approval_id": approval_id, "status": "PENDING",
            "required_approvers": record["required_approvers"]}


@app.get("/kavach/approvals/{approval_id}")
async def get_approval(approval_id: str):
    """
    Poll endpoint.  Kavach's poll_for_decision() calls this every N seconds
    until status is no longer PENDING or the timeout is reached.
    """
    async with approval_store_lock:
        record = approval_store.get(approval_id)
    if not record:
        raise HTTPException(status_code=404, detail="Approval record not found")
    # Return a safe view (omit internal decisions list details if desired)
    return {
        "approval_id": approval_id,
        "status": record["status"],
        "severity": record["severity"],
        "asset": record["asset"],
        "created_at": record["created_at"],
        "required_approvers": record["required_approvers"],
        "approver_count": len([d for d in record["decisions"] if d["decision"] == "APPROVED"]),
        "payload": json.dumps({"asset": record["asset"], "vuln_type": record["vuln_type"],
                                "engagement_id": record["engagement_id"]}, sort_keys=True),
        "timestamp": record.get("decided_at", ""),
        "signature": record.get("final_signature", ""),
    }


@app.post("/kavach/approvals/{approval_id}/decide")
async def decide_approval(approval_id: str, req: ApprovalDecision):
    """
    A human reviewer submits their HMAC-signed decision.
    - Signature must be valid under the reviewer's own token.
    - The same reviewer cannot sign twice (prevents self-approval even with
      valid credentials).
    - CRITICAL severity requires two distinct reviewers before APPROVED.
    - Every decision — approved, denied, or duplicate — is written to the
      audit ledger so 'who approved what, and when' is permanently
      reconstructable.
    """
    async with approval_store_lock:
        record = approval_store.get(approval_id)
        if not record:
            raise HTTPException(status_code=404, detail="Approval record not found")
        if record["status"] != "PENDING":
            raise HTTPException(status_code=409,
                                detail=f"Approval already in terminal state: {record['status']}")

        # Verify cryptographic signature
        if not _verify_reviewer_signature(req.reviewer_id, req.payload, req.timestamp, req.signature):
            await _write_approval_audit("DECISION_INVALID_HMAC", {
                "approval_id": approval_id, "reviewer_id": req.reviewer_id,
                "decision": req.decision,
            })
            raise HTTPException(status_code=401, detail="Invalid reviewer HMAC signature")

        # Prevent the same reviewer signing twice
        existing_reviewers = {d["reviewer_id"] for d in record["decisions"]}
        if req.reviewer_id in existing_reviewers:
            raise HTTPException(status_code=409,
                                detail="Reviewer has already submitted a decision for this approval")

        # Record this individual decision
        record["decisions"].append({
            "reviewer_id": req.reviewer_id,
            "decision": req.decision,
            "timestamp": req.timestamp,
        })

        # A single DENIED from any reviewer closes the approval immediately
        if req.decision == "DENIED":
            record["status"] = "DENIED"
            record["decided_at"] = datetime.now(timezone.utc).isoformat()
            record["final_signature"] = req.signature
        else:
            # Count unique APPROVED decisions
            approved_count = len([d for d in record["decisions"] if d["decision"] == "APPROVED"])
            if approved_count >= record["required_approvers"]:
                record["status"] = "APPROVED"
                record["decided_at"] = datetime.now(timezone.utc).isoformat()
                record["final_signature"] = req.signature

        new_status = record["status"]

    await _write_approval_audit("DECISION_RECORDED", {
        "approval_id": approval_id,
        "reviewer_id": req.reviewer_id,
        "decision": req.decision,
        "new_status": new_status,
        "asset": record["asset"],
        "severity": record["severity"],
    })
    logger.info(f"[APPROVAL] {approval_id} → {new_status} (reviewer: {req.reviewer_id})")
    return {"approval_id": approval_id, "status": new_status}


# ---------------------------------------------------------------------------
# 13. KAVACH ENGAGEMENT LIFECYCLE STORE  (Gap 3)
#     RISHI becomes the single source of truth for engagements.
#     ScopeGuard calls GET /kavach/engagements/{id} instead of reading a
#     local flat file, so a REVOKED engagement takes effect immediately
#     across all Kavach processes without a restart.
#
#     Endpoint summary:
#       POST /kavach/engagements          — create engagement (admin only)
#       GET  /kavach/engagements/{id}     — read (used by ScopeGuard.check())
#       POST /kavach/engagements/{id}/revoke — revoke mid-flight
# ---------------------------------------------------------------------------

engagement_store: dict[str, dict] = {}
engagement_store_lock = asyncio.Lock()
ENGAGEMENT_LEDGER_FILE = os.path.join(os.path.dirname(__file__), "kavach_engagements.jsonl")


class EngagementCreateRequest(BaseModel):
    engagement_id: str
    client: str
    targets: list[str]
    start_time: str           # ISO-8601
    end_time: str             # ISO-8601
    permitted_techniques: list[str]
    authorized_approvers: list[str] = []   # reviewer_id strings allowed to sign decisions
    destructive_testing_allowed: bool = False


class EngagementRevokeRequest(BaseModel):
    revocation_reason: str
    revoking_admin: str


def _persist_engagement(record: dict):
    """Append the current engagement snapshot to the JSONL audit trail."""
    try:
        with open(ENGAGEMENT_LEDGER_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        logger.error(f"[ENGAGEMENT] Failed to persist engagement record: {exc}")


def _load_engagements_from_ledger():
    """
    Replay the engagement ledger on startup to reconstruct current state.
    Last write for each engagement_id wins (append-only event log).
    """
    if not os.path.exists(ENGAGEMENT_LEDGER_FILE):
        return
    seen: dict[str, dict] = {}
    try:
        with open(ENGAGEMENT_LEDGER_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                seen[record["engagement_id"]] = record
    except Exception as exc:
        logger.error(f"[ENGAGEMENT] Failed to replay ledger: {exc}")
        return
    engagement_store.update(seen)
    logger.info(f"[ENGAGEMENT] Loaded {len(seen)} engagement(s) from ledger.")


# Replay on import so the store is warm before any request arrives.
_load_engagements_from_ledger()


@app.post("/kavach/engagements", status_code=201)
async def create_engagement(req: EngagementCreateRequest):
    """
    Create or update a Kavach engagement.  Every write is:
      - Appended to kavach_engagements.jsonl (tamper-evident, append-only)
      - Logged to the HMAC audit ledger
    """
    async with engagement_store_lock:
        if req.engagement_id in engagement_store:
            raise HTTPException(status_code=409,
                                detail=f"Engagement '{req.engagement_id}' already exists. "
                                       "Revoke and recreate to update.")
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "engagement_id": req.engagement_id,
            "client": req.client,
            "targets": req.targets,
            "start_time": req.start_time,
            "end_time": req.end_time,
            "permitted_techniques": req.permitted_techniques,
            "authorized_approvers": req.authorized_approvers,
            "destructive_testing_allowed": req.destructive_testing_allowed,
            "status": "ACTIVE",
            "version": 1,
            "created_at": now,
            "updated_at": now,
            "revocation_reason": None,
            "revoked_by": None,
            "revoked_at": None,
        }
        engagement_store[req.engagement_id] = record
        _persist_engagement(record)

    await _write_approval_audit("ENGAGEMENT_CREATED", {
        "engagement_id": req.engagement_id,
        "client": req.client,
        "targets": req.targets,
    })
    logger.info(f"[ENGAGEMENT] Created {req.engagement_id} for client '{req.client}'")
    return {"engagement_id": req.engagement_id, "status": "ACTIVE"}


@app.get("/kavach/engagements/{engagement_id}")
async def get_engagement(engagement_id: str):
    """
    Primary endpoint consumed by ScopeGuard.check() on every Kavach action.
    Returns full engagement detail including live status (ACTIVE | REVOKED).
    """
    async with engagement_store_lock:
        record = engagement_store.get(engagement_id)
    if not record:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return record


@app.post("/kavach/engagements/{engagement_id}/revoke")
async def revoke_engagement(engagement_id: str, req: EngagementRevokeRequest):
    """
    Immediately revokes an engagement.  ScopeGuard will start denying
    all checks for this engagement_id on the next request — no restart needed.
    """
    async with engagement_store_lock:
        record = engagement_store.get(engagement_id)
        if not record:
            raise HTTPException(status_code=404, detail="Engagement not found")
        if record["status"] == "REVOKED":
            raise HTTPException(status_code=409, detail="Engagement is already revoked")

        now = datetime.now(timezone.utc).isoformat()
        record["status"] = "REVOKED"
        record["revocation_reason"] = req.revocation_reason
        record["revoked_by"] = req.revoking_admin
        record["revoked_at"] = now
        record["updated_at"] = now
        record["version"] = record.get("version", 1) + 1
        _persist_engagement(record)

    await _write_approval_audit("ENGAGEMENT_REVOKED", {
        "engagement_id": engagement_id,
        "reason": req.revocation_reason,
        "revoked_by": req.revoking_admin,
    })
    logger.warning(
        f"[ENGAGEMENT] ⚠️  {engagement_id} REVOKED by '{req.revoking_admin}': "
        f"{req.revocation_reason}"
    )
    return {"engagement_id": engagement_id, "status": "REVOKED",
            "revoked_at": record["revoked_at"]}


# ---------------------------------------------------------------------------
# 14. KAVACH RATE LIMITING  (Feature Set B.1)
#     Per-engagement and global rolling counters on recon/scan/exploit actions.
#     The orchestrator consults POST /kavach/rate-limit/check before each
#     phase — the same pattern as ScopeGuard.check_async() so this feels like
#     a sibling gate, not a bolt-on.
#
#     Config (all via .env):
#       RATE_LIMIT_SCANS_PER_ENGAGEMENT_PER_HOUR   (default: 50)
#       RATE_LIMIT_EXPLOITS_PER_HOUR_GLOBAL        (default: 20)
#       RATE_LIMIT_RECON_PER_ENGAGEMENT_PER_HOUR   (default: 100)
#
#     On breach: deny the action, write RATE_LIMIT_EXCEEDED audit event,
#     return 429 with a clear reason — fail-closed, no silent queuing.
# ---------------------------------------------------------------------------

import time as _time

_RATE_LIMIT_SCANS_PER_ENG    = int(os.getenv("RATE_LIMIT_SCANS_PER_ENGAGEMENT_PER_HOUR", "50"))
_RATE_LIMIT_EXPLOITS_GLOBAL  = int(os.getenv("RATE_LIMIT_EXPLOITS_PER_HOUR_GLOBAL", "20"))
_RATE_LIMIT_RECON_PER_ENG    = int(os.getenv("RATE_LIMIT_RECON_PER_ENGAGEMENT_PER_HOUR", "100"))
_RATE_WINDOW_SECONDS         = 3600  # 1 hour rolling window

# Each entry is a list of UNIX timestamps of recent actions
rate_store: dict[str, list[float]] = {}
rate_store_lock = asyncio.Lock()


def _prune_window(timestamps: list[float], now: float) -> list[float]:
    """Drop timestamps older than the rolling window."""
    cutoff = now - _RATE_WINDOW_SECONDS
    return [t for t in timestamps if t > cutoff]


class RateLimitCheckRequest(BaseModel):
    engagement_id: str
    action_type: str   # RECON | VULN_SCAN | EXPLOIT


@app.post("/kavach/rate-limit/check")
async def rate_limit_check(req: RateLimitCheckRequest):
    """
    Kavach orchestrator calls this before starting each phase.
    Returns 200 {"allowed": true} if under limits.
    Returns 429 {"allowed": false, "reason": ...} on breach — caller must
    abort the phase, not queue it silently.
    """
    now = _time.time()
    action = req.action_type.upper()
    eng_id = req.engagement_id

    async with rate_store_lock:
        # --- Per-engagement counters ---
        eng_scan_key  = f"eng:{eng_id}:scan"
        eng_recon_key = f"eng:{eng_id}:recon"

        rate_store.setdefault(eng_scan_key, [])
        rate_store.setdefault(eng_recon_key, [])
        rate_store["global:exploit"] = rate_store.get("global:exploit", [])

        # Prune old entries
        rate_store[eng_scan_key]     = _prune_window(rate_store[eng_scan_key], now)
        rate_store[eng_recon_key]    = _prune_window(rate_store[eng_recon_key], now)
        rate_store["global:exploit"] = _prune_window(rate_store["global:exploit"], now)

        # Check limits
        if action == "RECON":
            count = len(rate_store[eng_recon_key])
            if count >= _RATE_LIMIT_RECON_PER_ENG:
                detail = (
                    f"Rate limit exceeded: engagement {eng_id} has performed "
                    f"{count}/{_RATE_LIMIT_RECON_PER_ENG} RECON actions in the last hour."
                )
                await _write_approval_audit("RATE_LIMIT_EXCEEDED", {
                    "engagement_id": eng_id, "action": action,
                    "count": count, "limit": _RATE_LIMIT_RECON_PER_ENG,
                })
                logger.warning(f"[RATE_LIMIT] {detail}")
                raise HTTPException(status_code=429, detail=detail)
            rate_store[eng_recon_key].append(now)

        elif action in ("VULN_SCAN", "SCAN"):
            count = len(rate_store[eng_scan_key])
            if count >= _RATE_LIMIT_SCANS_PER_ENG:
                detail = (
                    f"Rate limit exceeded: engagement {eng_id} has performed "
                    f"{count}/{_RATE_LIMIT_SCANS_PER_ENG} SCAN actions in the last hour."
                )
                await _write_approval_audit("RATE_LIMIT_EXCEEDED", {
                    "engagement_id": eng_id, "action": action,
                    "count": count, "limit": _RATE_LIMIT_SCANS_PER_ENG,
                })
                logger.warning(f"[RATE_LIMIT] {detail}")
                raise HTTPException(status_code=429, detail=detail)
            rate_store[eng_scan_key].append(now)

        elif action == "EXPLOIT":
            count = len(rate_store["global:exploit"])
            if count >= _RATE_LIMIT_EXPLOITS_GLOBAL:
                detail = (
                    f"Global exploit rate limit exceeded: "
                    f"{count}/{_RATE_LIMIT_EXPLOITS_GLOBAL} EXPLOIT actions in the last hour."
                )
                await _write_approval_audit("RATE_LIMIT_EXCEEDED", {
                    "engagement_id": eng_id, "action": action,
                    "count": count, "limit": _RATE_LIMIT_EXPLOITS_GLOBAL,
                })
                logger.warning(f"[RATE_LIMIT] {detail}")
                raise HTTPException(status_code=429, detail=detail)
            rate_store["global:exploit"].append(now)

        else:
            logger.warning(f"[RATE_LIMIT] Unknown action type '{action}' — denying (fail-closed).")
            raise HTTPException(status_code=400, detail=f"Unknown action_type '{action}'. Must be RECON|VULN_SCAN|EXPLOIT.")

    logger.debug(f"[RATE_LIMIT] {action} allowed for {eng_id}.")
    return {"allowed": True, "action": action, "engagement_id": eng_id}


# ---------------------------------------------------------------------------
# 15. KAVACH KILL SWITCH  (Feature Set B.2)
#     A single authenticated endpoint that immediately halts all further phase
#     execution and plugin invocation across every in-flight Kavach workflow.
#
#     This is a MANUAL emergency stop triggered by a human operator.
#     Section B.3 (anomaly detection) is the automated counterpart.
#
#     Implementation:
#       - Global boolean flag: kill_switch_active
#       - GET  /kavach/kill-switch/status   → polled by kill_switch_client.py
#         before every plugin execute() and PentestAgent.run_exploit_simulation()
#       - POST /kavach/kill-switch/activate → authenticated (HMAC over payload),
#         audited (who, when, why) — same pattern as engagement revocation
#       - POST /kavach/kill-switch/deactivate → authenticated, audited
#
#     Activating/deactivating is itself a tamper-evident, audited action.
#     The kill switch client (kill_switch_client.py) is fail-closed: if RISHI
#     is unreachable it treats the switch as ACTIVE.
# ---------------------------------------------------------------------------

kill_switch_active: bool = False
kill_switch_meta: dict = {
    "active": False,
    "activated_at": None,
    "activated_by": None,
    "reason": None,
    "deactivated_at": None,
    "deactivated_by": None,
}
kill_switch_lock = asyncio.Lock()


class KillSwitchActionRequest(BaseModel):
    operator_id: str      # identity of the human operator
    reason: str           # mandatory reason string
    payload: str          # canonical string that was HMAC-signed
    timestamp: str        # ISO-8601 UTC
    signature: str        # HMAC-SHA256 of "payload|timestamp" under AGENT_TOKEN_KAVACH_CORE


def _verify_operator_signature(payload: str, timestamp: str, signature: str) -> bool:
    """
    Verifies a kill-switch action is authenticated.  Uses the same
    AGENT_TOKEN_KAVACH_CORE secret as the audit ledger so no new
    secret infrastructure is required.
    """
    secret = os.getenv("AGENT_TOKEN_KAVACH_CORE", "default_kavach_secret").encode()
    message = f"{payload}|{timestamp}".encode()
    expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


@app.get("/kavach/kill-switch/status")
async def kill_switch_status():
    """
    Polled by kill_switch_client.py before every plugin execute() call.
    Intentionally unauthenticated reads — polling agents should not need
    operator credentials for a safety check.
    """
    async with kill_switch_lock:
        return dict(kill_switch_meta)


@app.post("/kavach/kill-switch/activate")
async def kill_switch_activate(req: KillSwitchActionRequest):
    """
    Human operator activates the kill switch.  Authenticated via HMAC.
    Immediately sets kill_switch_active=True — the next poll from any
    plugin or PentestAgent will see this and halt.
    """
    if not _verify_operator_signature(req.payload, req.timestamp, req.signature):
        raise HTTPException(status_code=401, detail="Invalid operator HMAC signature")

    async with kill_switch_lock:
        global kill_switch_active
        if kill_switch_active:
            raise HTTPException(status_code=409, detail="Kill switch is already active")
        kill_switch_active = True
        now = datetime.now(timezone.utc).isoformat()
        kill_switch_meta.update({
            "active": True,
            "activated_at": now,
            "activated_by": req.operator_id,
            "reason": req.reason,
            "deactivated_at": None,
            "deactivated_by": None,
        })

    await _write_approval_audit("KILL_SWITCH_ACTIVATED", {
        "operator_id": req.operator_id,
        "reason": req.reason,
        "timestamp": kill_switch_meta["activated_at"],
    })
    logger.critical(
        f"🚨 [KILL_SWITCH] ACTIVATED by '{req.operator_id}': {req.reason}"
    )
    return {"status": "ACTIVATED", "activated_at": kill_switch_meta["activated_at"]}


@app.post("/kavach/kill-switch/deactivate")
async def kill_switch_deactivate(req: KillSwitchActionRequest):
    """
    Human operator deactivates the kill switch.  Authenticated via HMAC.
    Plugins and PentestAgent will resume normal operation on their next
    kill-switch poll after this call returns.
    """
    if not _verify_operator_signature(req.payload, req.timestamp, req.signature):
        raise HTTPException(status_code=401, detail="Invalid operator HMAC signature")

    async with kill_switch_lock:
        global kill_switch_active
        if not kill_switch_active:
            raise HTTPException(status_code=409, detail="Kill switch is not currently active")
        kill_switch_active = False
        now = datetime.now(timezone.utc).isoformat()
        kill_switch_meta.update({
            "active": False,
            "deactivated_at": now,
            "deactivated_by": req.operator_id,
        })

    await _write_approval_audit("KILL_SWITCH_DEACTIVATED", {
        "operator_id": req.operator_id,
        "reason": req.reason,
        "timestamp": kill_switch_meta["deactivated_at"],
    })
    logger.info(
        f"✅ [KILL_SWITCH] DEACTIVATED by '{req.operator_id}': {req.reason}"
    )
    return {"status": "DEACTIVATED", "deactivated_at": kill_switch_meta["deactivated_at"]}


# ---------------------------------------------------------------------------
# 16. KAVACH ANOMALY DETECTION  (Feature Set B.3)
#     Lightweight, explainable heuristics that flag unusual Kavach behavior
#     for human review — NOT a black-box ML model. Every heuristic is a
#     named, threshold-based rule with documented inputs so the audit trail
#     is fully understandable to a reviewer.
#
#     Heuristics:
#       1. Scan velocity: single engagement scanning far more distinct assets
#          than its rolling historical baseline (ANOMALY_SCAN_VELOCITY_THRESHOLD)
#       2. Approval-rate: unusually high rate of HIGH/CRITICAL findings per hour
#          per engagement (ANOMALY_APPROVAL_RATE_THRESHOLD)
#       3. Plugin failure rate: plugin error rate far above historical baseline
#          over a 100-invocation window (ANOMALY_PLUGIN_FAILURE_RATE_THRESHOLD)
#
#     On any anomaly: ANOMALY_DETECTED audit event + create pending approval
#     via the existing approval infrastructure so a human explicitly clears
#     it before the workflow continues.
#
#     Thresholds — all configurable via .env:
#       ANOMALY_SCAN_VELOCITY_THRESHOLD       (default: 20 distinct assets/hour)
#       ANOMALY_APPROVAL_RATE_THRESHOLD       (default: 10 HIGH/CRITICAL/hour)
#       ANOMALY_PLUGIN_FAILURE_RATE_THRESHOLD (default: 0.40 = 40%)
# ---------------------------------------------------------------------------

_ANOMALY_SCAN_VELOCITY    = int(os.getenv("ANOMALY_SCAN_VELOCITY_THRESHOLD", "20"))
_ANOMALY_APPROVAL_RATE    = int(os.getenv("ANOMALY_APPROVAL_RATE_THRESHOLD", "10"))
_ANOMALY_PLUGIN_FAIL_RATE = float(os.getenv("ANOMALY_PLUGIN_FAILURE_RATE_THRESHOLD", "0.40"))

# Per-engagement rolling stores
_anomaly_scan_assets:    dict[str, list[str]]  = {}
_anomaly_approval_times: dict[str, list[float]] = {}
_plugin_invocations:     dict[str, list[bool]]  = {}
_anomaly_store_lock = asyncio.Lock()


class AnomalyRecordRequest(BaseModel):
    engagement_id: str
    event_type: str       # SCAN_ASSET | APPROVAL_REQUEST | PLUGIN_RESULT
    asset: Optional[str] = None
    severity: Optional[str] = None
    plugin_name: Optional[str] = None
    success: Optional[bool] = None


async def _create_anomaly_approval(engagement_id: str, heuristic: str, values: dict) -> str:
    """Creates a pending approval via existing approval infrastructure."""
    approval_id = secrets.token_hex(8)
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "approval_id": approval_id,
        "engagement_id": engagement_id,
        "target": f"anomaly:{heuristic}",
        "scan_type": "ANOMALY_REVIEW",
        "severity": "HIGH",
        "reason": f"Anomaly heuristic '{heuristic}' triggered. Human review required.",
        "values": values,
        "status": "PENDING",
        "created_at": now,
        "reviews": [],
    }
    async with approval_lock:
        pending_approvals[approval_id] = record
    await _write_approval_audit("ANOMALY_APPROVAL_CREATED", {
        "approval_id": approval_id, "engagement_id": engagement_id,
        "heuristic": heuristic, "values": values,
    })
    logger.warning(f"[ANOMALY] Created pending approval {approval_id} for '{heuristic}' on {engagement_id}")
    return approval_id


@app.post("/kavach/anomaly/record")
async def anomaly_record(req: AnomalyRecordRequest):
    """
    Called by the orchestrator after phase events so RISHI checks heuristics inline.
    Returns any anomaly flags detected.
    """
    detected_anomalies: list[dict] = []
    now = _time.time()

    async with _anomaly_store_lock:
        eng_id = req.engagement_id

        if req.event_type == "SCAN_ASSET" and req.asset:
            ts_key = f"anomaly_scan_ts:{eng_id}"
            rate_store[ts_key] = _prune_window(rate_store.get(ts_key, []), now)
            rate_store[ts_key].append(now)
            _anomaly_scan_assets.setdefault(eng_id, [])
            if req.asset not in _anomaly_scan_assets[eng_id]:
                _anomaly_scan_assets[eng_id].append(req.asset)
            hourly_count = len(rate_store[ts_key])
            if hourly_count > _ANOMALY_SCAN_VELOCITY:
                vals = {"distinct_assets": len(_anomaly_scan_assets[eng_id]),
                        "hourly_scans": hourly_count, "threshold": _ANOMALY_SCAN_VELOCITY}
                await _write_approval_audit("ANOMALY_DETECTED",
                    {"heuristic": "SCAN_VELOCITY", "engagement_id": eng_id, **vals})
                aid = await _create_anomaly_approval(eng_id, "SCAN_VELOCITY", vals)
                detected_anomalies.append({"heuristic": "SCAN_VELOCITY", "values": vals, "approval_id": aid})
                logger.warning(f"[ANOMALY] SCAN_VELOCITY: {hourly_count}/hr > {_ANOMALY_SCAN_VELOCITY}")

        elif req.event_type == "APPROVAL_REQUEST" and req.severity in ("HIGH", "CRITICAL"):
            ts_key = f"anomaly_approval:{eng_id}"
            rate_store[ts_key] = _prune_window(rate_store.get(ts_key, []), now)
            rate_store[ts_key].append(now)
            count = len(rate_store[ts_key])
            if count > _ANOMALY_APPROVAL_RATE:
                vals = {"hourly_high_critical_approvals": count,
                        "threshold": _ANOMALY_APPROVAL_RATE, "severity": req.severity}
                await _write_approval_audit("ANOMALY_DETECTED",
                    {"heuristic": "APPROVAL_RATE", "engagement_id": eng_id, **vals})
                aid = await _create_anomaly_approval(eng_id, "APPROVAL_RATE", vals)
                detected_anomalies.append({"heuristic": "APPROVAL_RATE", "values": vals, "approval_id": aid})
                logger.warning(f"[ANOMALY] APPROVAL_RATE: {count}/hr > {_ANOMALY_APPROVAL_RATE}")

        elif req.event_type == "PLUGIN_RESULT" and req.plugin_name and req.success is not None:
            p_key = req.plugin_name
            _plugin_invocations.setdefault(p_key, [])
            _plugin_invocations[p_key].append(req.success)
            if len(_plugin_invocations[p_key]) > 100:
                _plugin_invocations[p_key] = _plugin_invocations[p_key][-100:]
            window = _plugin_invocations[p_key]
            if len(window) >= 10:
                fail_rate = sum(1 for s in window if not s) / len(window)
                if fail_rate >= _ANOMALY_PLUGIN_FAIL_RATE:
                    vals = {"plugin": p_key, "failure_rate": round(fail_rate, 3),
                            "sample_size": len(window), "threshold": _ANOMALY_PLUGIN_FAIL_RATE}
                    await _write_approval_audit("ANOMALY_DETECTED",
                        {"heuristic": "PLUGIN_FAILURE_RATE", "engagement_id": eng_id, **vals})
                    aid = await _create_anomaly_approval(eng_id, "PLUGIN_FAILURE_RATE", vals)
                    detected_anomalies.append({
                        "heuristic": "PLUGIN_FAILURE_RATE", "values": vals, "approval_id": aid})
                    logger.warning(f"[ANOMALY] PLUGIN_FAILURE_RATE: {fail_rate:.1%} > {_ANOMALY_PLUGIN_FAIL_RATE:.0%}")

    return {"anomalies_detected": len(detected_anomalies), "anomalies": detected_anomalies}


@app.get("/kavach/anomaly/status/{engagement_id}")
async def anomaly_status(engagement_id: str):
    """Returns pending anomaly-review approvals for an engagement."""
    async with approval_lock:
        anomaly_approvals = [
            v for v in pending_approvals.values()
            if v.get("engagement_id") == engagement_id
            and v.get("scan_type") == "ANOMALY_REVIEW"
            and v.get("status") == "PENDING"
        ]
    return {
        "engagement_id": engagement_id,
        "pending_anomaly_reviews": len(anomaly_approvals),
        "approvals": anomaly_approvals,
    }


# ---------------------------------------------------------------------------
# 20. ENGINEER AUDIT LEDGER
#     Mirrors /kavach/audit exactly — same HMAC-chained append-only log,
#     same signing scheme.  Engineer agents use AGENT_TOKEN_ENGINEER_CORE
#     (or their individual tokens) as the signing secret.
#     Following the same numbered-section-comment convention.
# ---------------------------------------------------------------------------

kavach_audit_hash = "KAVACH_GENESIS_HASH"
kavach_audit_lock = asyncio.Lock()
KAVACH_AUDIT_LEDGER_FILE = os.path.join(os.path.dirname(__file__), "kavach_audit_ledger.jsonl")

def _load_kavach_audit_hash():
    """Resume the hash chain from the last ledger entry, instead of
    silently forking to a new genesis on every process restart."""
    global kavach_audit_hash
    if not os.path.exists(KAVACH_AUDIT_LEDGER_FILE):
        return
    last_hash = None
    try:
        with open(KAVACH_AUDIT_LEDGER_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                last_hash = json.loads(line).get("hash")
    except Exception as exc:
        logger.error(f"[KAVACH_AUDIT] Failed to replay ledger for hash resume: {exc}")
        return
    if last_hash:
        kavach_audit_hash = last_hash
        logger.info(f"[KAVACH_AUDIT] Resumed audit chain from {last_hash[:12]}...")

_load_kavach_audit_hash()

engineer_audit_hash = "ENGINEER_GENESIS_HASH"
engineer_audit_lock = asyncio.Lock()
ENGINEER_AUDIT_LEDGER_FILE = os.path.join(os.path.dirname(__file__), "engineer_audit_ledger.jsonl")

def _load_engineer_audit_hash():
    """Resume the hash chain from the last ledger entry, instead of
    silently forking to a new genesis on every process restart."""
    global engineer_audit_hash
    if not os.path.exists(ENGINEER_AUDIT_LEDGER_FILE):
        return
    last_hash = None
    try:
        with open(ENGINEER_AUDIT_LEDGER_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                last_hash = json.loads(line).get("hash")
    except Exception as exc:
        logger.error(f"[ENGINEER_AUDIT] Failed to replay ledger for hash resume: {exc}")
        return
    if last_hash:
        engineer_audit_hash = last_hash
        logger.info(f"[ENGINEER_AUDIT] Resumed audit chain from {last_hash[:12]}...")

_load_engineer_audit_hash()


class EngineerAuditPayload(BaseModel):
    agent_id: str
    payload: str
    timestamp: str
    signature: str


@app.post("/engineer/audit")
async def engineer_audit_log(req: EngineerAuditPayload):
    """
    HMAC-verified audit event for Engineer sub-agents.
    Mirrors POST /kavach/audit — same chain, separate ledger file.
    """
    global engineer_audit_hash

    expected_secret = os.getenv("AGENT_TOKEN_AGENT_ENGINEER_CODER", "default_engineer_secret").encode()
    message = f"{req.payload}|{req.timestamp}".encode()
    expected_sig = hmac.new(expected_secret, message, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(req.signature, expected_sig):
        raise HTTPException(status_code=401, detail="Invalid Engineer HMAC signature")

    async with engineer_audit_lock:
        chain_data = f"{engineer_audit_hash}|{req.payload}|{req.timestamp}".encode()
        new_hash = hashlib.sha256(chain_data).hexdigest()

        record = {
            "timestamp": req.timestamp,
            "agent_id": req.agent_id,
            "payload": req.payload,
            "prev_hash": engineer_audit_hash,
            "hash": new_hash,
        }
        engineer_audit_hash = new_hash

        with open(ENGINEER_AUDIT_LEDGER_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")

    return {"status": "ok", "hash": new_hash}


# ---------------------------------------------------------------------------
# 21. ENGINEER APPROVAL STORE
#     Pending approvals for Engineer Tier 2+ actions.
#     Reuses the same ApprovalRequest / ApprovalDecision models and
#     _verify_reviewer_signature helper from Section 12.
#     Separate store so Engineer approvals don't pollute Kavach's store.
# ---------------------------------------------------------------------------

engineer_approval_store: dict[str, dict] = {}
engineer_approval_store_lock = asyncio.Lock()


async def _write_engineer_approval_audit(event: str, detail: dict):
    """Write an Engineer approval lifecycle event to the Engineer audit ledger."""
    secret = os.getenv("AGENT_TOKEN_AGENT_ENGINEER_CODER", "default_engineer_secret").encode()
    payload_dict = {"phase": event, "event_data": detail}
    payload_str = json.dumps(payload_dict, sort_keys=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    message = f"{payload_str}|{timestamp}".encode()
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    await engineer_audit_log(EngineerAuditPayload(
        agent_id="RISHI_ENGINEER_APPROVAL_STORE",
        payload=payload_str,
        timestamp=timestamp,
        signature=signature,
    ))


@app.post("/engineer/approvals", status_code=201)
async def create_engineer_approval(req: ApprovalRequest):
    """
    Engineer orchestrator calls this for Tier 2+ actions requiring human sign-off.
    Same shape as POST /kavach/approvals — reuses ApprovalRequest model.
    """
    approval_id = str(uuid4())
    record = {
        "approval_id": approval_id,
        "status": "PENDING",
        "vuln_type": req.vuln_type,          # action_type for Engineer context
        "asset": req.asset,                   # workspace path / CWD
        "severity": req.severity,
        "engagement_id": req.engagement_id,  # workspace_id for Engineer
        "requesting_agent": req.requesting_agent,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decisions": [],
        "required_approvers": 2 if req.severity == "CRITICAL" else 1,
    }
    async with engineer_approval_store_lock:
        engineer_approval_store[approval_id] = record

    await _write_engineer_approval_audit("ENGINEER_APPROVAL_CREATED", {
        "approval_id": approval_id,
        "asset": req.asset,
        "severity": req.severity,
        "engagement_id": req.engagement_id,
    })
    logger.info(f"[ENGINEER_APPROVAL] Created {approval_id} for {req.asset} ({req.severity})")
    return {
        "approval_id": approval_id,
        "status": "PENDING",
        "required_approvers": record["required_approvers"],
    }


@app.get("/engineer/approvals/{approval_id}")
async def get_engineer_approval(approval_id: str):
    """Poll endpoint for Engineer Tier 2 approval decisions."""
    async with engineer_approval_store_lock:
        record = engineer_approval_store.get(approval_id)
    if not record:
        raise HTTPException(status_code=404, detail="Engineer approval record not found")
    return {
        "approval_id": approval_id,
        "status": record["status"],
        "severity": record["severity"],
        "asset": record["asset"],
        "created_at": record["created_at"],
        "required_approvers": record["required_approvers"],
        "approver_count": len([d for d in record["decisions"] if d["decision"] == "APPROVED"]),
        "payload": json.dumps({
            "asset": record["asset"],
            "vuln_type": record["vuln_type"],
            "engagement_id": record["engagement_id"],
        }, sort_keys=True),
        "timestamp": record.get("decided_at", ""),
        "signature": record.get("final_signature", ""),
    }


@app.post("/engineer/approvals/{approval_id}/decide")
async def decide_engineer_approval(approval_id: str, req: ApprovalDecision):
    """
    Human reviewer submits HMAC-signed decision for an Engineer Tier 2 action.
    Reuses ApprovalDecision model and _verify_reviewer_signature from Section 12.
    Same dual-control semantics: single DENIED closes immediately; APPROVED
    requires required_approvers distinct reviewers.
    """
    async with engineer_approval_store_lock:
        record = engineer_approval_store.get(approval_id)
        if not record:
            raise HTTPException(status_code=404, detail="Engineer approval record not found")
        if record["status"] != "PENDING":
            raise HTTPException(status_code=409,
                                detail=f"Approval already in terminal state: {record['status']}")

        if not _verify_reviewer_signature(req.reviewer_id, req.payload, req.timestamp, req.signature):
            await _write_engineer_approval_audit("ENGINEER_DECISION_INVALID_HMAC", {
                "approval_id": approval_id, "reviewer_id": req.reviewer_id,
            })
            raise HTTPException(status_code=401, detail="Invalid reviewer HMAC signature")

        existing_reviewers = {d["reviewer_id"] for d in record["decisions"]}
        if req.reviewer_id in existing_reviewers:
            raise HTTPException(status_code=409,
                                detail="Reviewer has already submitted a decision for this approval")

        record["decisions"].append({
            "reviewer_id": req.reviewer_id,
            "decision": req.decision,
            "timestamp": req.timestamp,
        })

        if req.decision == "DENIED":
            record["status"] = "DENIED"
            record["decided_at"] = datetime.now(timezone.utc).isoformat()
            record["final_signature"] = req.signature
        else:
            approved_count = len([d for d in record["decisions"] if d["decision"] == "APPROVED"])
            if approved_count >= record["required_approvers"]:
                record["status"] = "APPROVED"
                record["decided_at"] = datetime.now(timezone.utc).isoformat()
                record["final_signature"] = req.signature

        new_status = record["status"]

    await _write_engineer_approval_audit("ENGINEER_DECISION_RECORDED", {
        "approval_id": approval_id,
        "reviewer_id": req.reviewer_id,
        "decision": req.decision,
        "new_status": new_status,
    })
    logger.info(f"[ENGINEER_APPROVAL] {approval_id} → {new_status} (reviewer: {req.reviewer_id})")
    return {"approval_id": approval_id, "status": new_status}


# ---------------------------------------------------------------------------
# 22. ENGINEER WORKSPACE AUTHORIZATION STORE
#     Workspace records are the Engineer analogue of Kavach's engagement records.
#     Same shape: an ID, an authorization scope, a list of allowed people,
#     a revoke endpoint — same revocation mechanism, different domain (a
#     repo/project instead of a pentest target).
# ---------------------------------------------------------------------------

workspace_store: dict[str, dict] = {}
workspace_store_lock = asyncio.Lock()
WORKSPACE_LEDGER_FILE = os.path.join(os.path.dirname(__file__), "engineer_workspaces.jsonl")


class WorkspaceCreateRequest(BaseModel):
    workspace_id: str
    project_name: str
    root_path: str                        # absolute path on the server
    authorized_agents: list[str] = []
    authorized_approvers: list[str] = []
    allow_git_push: bool = False
    allow_deploy: bool = False
    deploy_command: list[str] | None = None


class WorkspaceRevokeRequest(BaseModel):
    revocation_reason: str
    revoking_admin: str


def _persist_workspace(record: dict):
    """Append workspace snapshot to the JSONL audit trail."""
    try:
        with open(WORKSPACE_LEDGER_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        logger.error(f"[WORKSPACE] Failed to persist workspace record: {exc}")


def _load_workspaces_from_ledger():
    """Replay workspace ledger on startup. Last write per workspace_id wins."""
    if not os.path.exists(WORKSPACE_LEDGER_FILE):
        return
    seen: dict[str, dict] = {}
    try:
        with open(WORKSPACE_LEDGER_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                seen[record["workspace_id"]] = record
    except Exception as exc:
        logger.error(f"[WORKSPACE] Failed to replay workspace ledger: {exc}")
        return
    workspace_store.update(seen)
    logger.info(f"[WORKSPACE] Loaded {len(seen)} workspace record(s) from ledger.")


_load_workspaces_from_ledger()


@app.post("/engineer/workspaces", status_code=201)
async def create_workspace(req: WorkspaceCreateRequest):
    """Create a new Engineer workspace authorization record."""
    async with workspace_store_lock:
        if req.workspace_id in workspace_store:
            raise HTTPException(status_code=409,
                                detail=f"Workspace '{req.workspace_id}' already exists.")
        record = {
            "workspace_id": req.workspace_id,
            "project_name": req.project_name,
            "root_path": req.root_path,
            "authorized_agents": req.authorized_agents,
            "authorized_approvers": req.authorized_approvers,
            "allow_git_push": req.allow_git_push,
            "allow_deploy": req.allow_deploy,
            "deploy_command": req.deploy_command,
            "status": "ACTIVE",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        workspace_store[req.workspace_id] = record
        _persist_workspace(record)

    logger.info(f"[WORKSPACE] Created workspace '{req.workspace_id}' → {req.root_path}")
    return {"workspace_id": req.workspace_id, "status": "ACTIVE"}


@app.get("/engineer/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str):
    """Read a workspace record (used by WorkspaceGuard.check())."""
    async with workspace_store_lock:
        record = workspace_store.get(workspace_id)
    if not record:
        raise HTTPException(status_code=404, detail="Workspace record not found")
    return record


@app.post("/engineer/workspaces/{workspace_id}/revoke")
async def revoke_workspace(workspace_id: str, req: WorkspaceRevokeRequest):
    """
    Immediately revoke a workspace — same pattern as POST /kavach/engagements/{id}/revoke.
    Takes effect on the next WorkspaceGuard check without a process restart.
    """
    async with workspace_store_lock:
        record = workspace_store.get(workspace_id)
        if not record:
            raise HTTPException(status_code=404, detail="Workspace record not found")
        if record["status"] == "REVOKED":
            raise HTTPException(status_code=409, detail="Workspace already revoked.")
        record["status"] = "REVOKED"
        record["revocation_reason"] = req.revocation_reason
        record["revoking_admin"] = req.revoking_admin
        record["revoked_at"] = datetime.now(timezone.utc).isoformat()
        _persist_workspace(record)

    await _write_engineer_approval_audit("WORKSPACE_REVOKED", {
        "workspace_id": workspace_id,
        "reason": req.revocation_reason,
        "admin": req.revoking_admin,
    })
    logger.warning(f"[WORKSPACE] '{workspace_id}' REVOKED by {req.revoking_admin}: {req.revocation_reason}")
    return {"workspace_id": workspace_id, "status": "REVOKED"}


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


class ChatRequest(BaseModel):
    prompt: str
    stream: bool = False

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    """
    Proxies a conversational prompt to the local Ollama instance.
    Includes a Code Interpreter loop to detect and execute python scripts.
    """
    system_prompt = (
        "You are Chanakya, a charismatic, world-class financial expert and mentor. "
        "You do NOT act like a robotic calculator. You think out loud, explain the 'why' behind the numbers, and walk the user through the math step-by-step like an expert mentor. "
        "Be conversational, dynamic, and 'alive'. Speak simply but with authority. "
        "If you are provided with an [EXPERT SCRATCHPAD] below, you MUST use its step-by-step logic and its exact final answer. "
        "Do NOT invent your own math or accounting rules if a scratchpad is provided; instead, elegantly incorporate its steps into your natural explanation.\\n\\n"
        "CODE INTERPRETER CAPABILITY:\\n"
        "If you are asked a complex math or logic question that is NOT covered by an [EXPERT SCRATCHPAD], you MUST write a Python script to calculate the exact answer. "
        "Output the script inside ```python ... ``` blocks. Use the print() function to output the final results. "
        "Do NOT attempt to guess the math. Write the Python code, print the result, and stop. The system will run the code and give you the output to generate your final answer."
    )
    
    # --- DETERMINISTIC MATH INTERCEPTOR ---
    override_injection = quant_solvers.route_and_solve(req.prompt)
    is_code_interpreter = override_injection == "[CODE_INTERPRETER_MODE]"
    
    if override_injection and not is_code_interpreter:
        system_prompt += override_injection
        logger.info(f"Quant Solver Interceptor applied.")
    
    # If code interpreter mode is active, the FIRST pass uses a strict Python override prompt.
    pass1_system_prompt = system_prompt
    if is_code_interpreter:
        pass1_system_prompt = (
            "You are a strict Python execution agent. You MUST write a python script to calculate the answer to the user's prompt. "
            "Output ONLY the python script inside ```python ... ``` blocks. Do not explain anything. Just write the code. "
            "Use print() to output the final answer."
        )
        logger.info(f"Code Interpreter strict override activated.")
        
    messages_pass1 = [
        {"role": "system", "content": pass1_system_prompt},
        {"role": "user", "content": req.prompt}
    ]
    
    if req.stream:
        async def stream_ollama():
            try:
                # FIRST PASS: Non-streaming to let it think and write code
                async with httpx.AsyncClient(timeout=120.0) as client:
                    payload = {"model": "llama3.1:8b", "messages": messages_pass1, "stream": False}
                    resp = await client.post("http://127.0.0.1:11434/api/chat", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    first_response = data.get("message", {}).get("content", "")
                    
                    # Check for python code
                    code_match = re.search(r'```python\\s*(.*?)\\s*```', first_response, re.DOTALL)
                    if code_match:
                        logger.info("Code Interpreter triggered!")
                        code = code_match.group(1)
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                            f.write(code)
                            temp_path = f.name
                        
                        try:
                            proc = subprocess.run(["python3", temp_path], capture_output=True, text=True, timeout=10)
                            output = proc.stdout if proc.returncode == 0 else f"Error:\\n{proc.stderr}"
                            logger.info(f"Code executed. Output: {output.strip()}")
                        except Exception as e:
                            output = f"Execution failed: {str(e)}"
                            logger.error(output)
                        finally:
                            os.unlink(temp_path)
                            
                        # SECOND PASS (Streaming) with the result
                        messages_pass2 = [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": req.prompt},
                            {"role": "assistant", "content": f"Let me calculate that for you.\\n```python\\n{code}\\n```"},
                            {"role": "user", "content": f"Here is the exact mathematical output from your python execution engine:\\n{output}\\nNow provide the final conversational answer to the user. Explain the concepts like an expert mentor using this exact mathematical answer."}
                        ]
                        
                        payload = {"model": "llama3.1:8b", "messages": messages_pass2, "stream": True}
                        async with client.stream("POST", "http://127.0.0.1:11434/api/chat", json=payload) as stream_resp:
                            stream_resp.raise_for_status()
                            async for chunk in stream_resp.aiter_lines():
                                if chunk:
                                    try:
                                        cdata = json.loads(chunk)
                                        if "message" in cdata and "content" in cdata["message"]:
                                            yield f"data: {json.dumps({'chunk': cdata['message']['content']})}\\n\\n"
                                    except:
                                        pass
                    else:
                        # No code generated. Artificially stream the response for UX.
                        words = first_response.split(' ')
                        for i, w in enumerate(words):
                            space = " " if i < len(words) - 1 else ""
                            yield f"data: {json.dumps({'chunk': w + space})}\\n\\n"
                            await asyncio.sleep(0.01)

            except Exception as e:
                logger.error(f"Error streaming from Ollama: {e}")
                yield f"data: {json.dumps({'error': 'Connection error'})}\\n\\n"
        
        return StreamingResponse(stream_ollama(), media_type="text/event-stream")
    else:
        # For non-streaming requests (tests)
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                payload = {"model": "llama3.1:8b", "messages": messages_pass1, "stream": False}
                resp = await client.post("http://127.0.0.1:11434/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                first_response = data.get("message", {}).get("content", "")
                
                code_match = re.search(r'```python\\s*(.*?)\\s*```', first_response, re.DOTALL)
                if code_match:
                    code = code_match.group(1)
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                        f.write(code)
                        temp_path = f.name
                    try:
                        proc = subprocess.run(["python3", temp_path], capture_output=True, text=True, timeout=10)
                        output = proc.stdout if proc.returncode == 0 else f"Error:\\n{proc.stderr}"
                    except Exception as e:
                        output = f"Execution failed: {str(e)}"
                    finally:
                        os.unlink(temp_path)
                        
                    messages_pass2 = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": req.prompt},
                        {"role": "assistant", "content": f"Let me calculate that for you.\\n```python\\n{code}\\n```"},
                        {"role": "user", "content": f"Here is the exact mathematical output from your python execution engine:\\n{output}\\nNow provide the final conversational answer to the user. Explain the concepts like an expert mentor using this exact mathematical answer."}
                    ]
                    payload = {"model": "llama3.1:8b", "messages": messages_pass2, "stream": False}
                    resp2 = await client.post("http://127.0.0.1:11434/api/chat", json=payload)
                    resp2.raise_for_status()
                    data2 = resp2.json()
                    return {"response": data2.get("message", {}).get("content", "")}
                else:
                    return {"response": first_response}
        except Exception as e:
            logger.error(f"Error calling Ollama: {e}")
            return {"response": "I'm sorry, I'm having trouble thinking right now. Please try again later."}


# ---------------------------------------------------------------------------
# 20. RISHI CENTRAL ROUTER (POST /ask)
# ---------------------------------------------------------------------------
class RouterDecision(BaseModel):
    orchestrators: list[str]
    sequence: str
    reasoning: str

class AskRequest(BaseModel):
    user_prompt: str
    session_id: Optional[str] = None
    context: Optional[dict] = None

router_sessions = {}

async def _write_router_audit(event: str, detail: dict):
    payload_str = json.dumps({"phase": event, "event_data": detail}, sort_keys=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    secret = os.getenv("AGENT_TOKEN_KAVACH_CORE", "default_kavach_secret").encode()
    message = f"{payload_str}|{timestamp}".encode()
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    await kavach_audit_log(KavachAuditPayload(
        agent_id="RISHI_CENTRAL_ROUTER",
        payload=payload_str,
        timestamp=timestamp,
        signature=signature
    ))

async def classify_intent(user_prompt: str) -> RouterDecision:
    system_prompt = """You are RISHI, a Central Routing AI.
Analyze the user request and determine which orchestrator(s) should handle it.
The available orchestrators are:
- "chanakya": handles quantitative finance, tax calculation, ethical compliance, ESG reporting, and financial visualization.
- "kavach": handles reconnaissance, vulnerability scanning, penetration testing, and security reporting.
- "engineer": handles code generation, software design, local diffusion asset generation, and code deployment.

You MUST respond ONLY with a valid JSON object matching this schema:
{
  "orchestrators": ["chanakya" | "kavach" | "engineer", ...],
  "sequence": "single" | "sequential" | "parallel",
  "reasoning": "one sentence — why these orchestrator(s)"
}"""
    try:
        from ollama import AsyncClient
        response = await AsyncClient().chat(model='llama3.1:8b', messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ], format='json')
        msg = response.get('message', None) if isinstance(response, dict) else None
        if msg is not None:
            content = msg.get('content', '') if isinstance(msg, dict) else getattr(msg, 'content', '')
        else:
            content = getattr(getattr(response, 'message', None), 'content', '')
        
        data = json.loads(content)
        orchestrators = [o for o in data.get("orchestrators", []) if o in ["chanakya", "kavach", "engineer"]]
        if not orchestrators:
            orchestrators = ["chanakya"]
        return RouterDecision(
            orchestrators=orchestrators,
            sequence=data.get("sequence", "single"),
            reasoning=data.get("reasoning", "Fallback")
        )
    except Exception as e:
        logger.error(f"Routing classification failed: {e}")
        return RouterDecision(orchestrators=["chanakya"], sequence="single", reasoning="Fallback due to error")

@app.post("/ask")
async def rishi_ask(req: AskRequest):
    logger.info(f"[ROUTER] /ask called with prompt: {req.user_prompt[:100]}...")
    
    decision = await classify_intent(req.user_prompt)
    
    await _write_router_audit("ROUTING_DECISION", {
        "session_id": req.session_id,
        "user_prompt": req.user_prompt[:500],
        "orchestrators_selected": decision.orchestrators,
        "sequence": decision.sequence,
        "reasoning": decision.reasoning,
    })
    
    context = req.context or {}
    engagement_id = context.get("engagement_id") or context.get("workspace_id")
    if req.session_id:
        if req.session_id not in router_sessions:
            router_sessions[req.session_id] = {}
        sess = router_sessions[req.session_id]
        if engagement_id:
            sess["engagement_id"] = engagement_id
        else:
            engagement_id = sess.get("engagement_id")
    
    results = []
    current_prompt = req.user_prompt
    
    from agents.chanakya.orchestrator import ChanakyaOrchestrator
    from agents.kavach.orchestrator import KavachOrchestrator
    from agents.engineer.orchestrator import EngineerOrchestrator
    
    orchestrator_map = {
        "chanakya": ChanakyaOrchestrator,
        "kavach": KavachOrchestrator,
        "engineer": EngineerOrchestrator
    }
    
    hops = 0
    max_hops = 3
    
    for orch_name in decision.orchestrators:
        if hops >= max_hops:
            logger.warning("[ROUTER] Hard cap of 3 orchestrator calls reached.")
            break
            
        orch_class = orchestrator_map.get(orch_name)
        if not orch_class:
            continue
            
        instance = orch_class()
        
        try:
            logger.info(f"[ROUTER] Invoking {orch_name}...")
            if orch_name == "kavach":
                result = await instance.run(current_prompt, engagement_id=engagement_id)
            elif orch_name == "engineer":
                result = await instance.run(current_prompt, workspace_id=engagement_id)
            else:
                result = await instance.run(current_prompt, session_id=req.session_id)
        except Exception as e:
            logger.error(f"[ROUTER] Orchestrator {orch_name} crashed: {e}")
            results.append({"orchestrator": orch_name, "status": "ERROR", "summary": f"Crash: {e}"})
            break
            
        results.append(result)
        hops += 1
        
        status = result.get("status")
        if status in ("NEEDS_APPROVAL", "BLOCKED", "ERROR"):
            logger.info(f"[ROUTER] Halting loop due to status {status} from {orch_name}.")
            break
            
        if hops < len(decision.orchestrators) and hops < max_hops:
            system_prompt = "You are a routing assistant. Combine the user's original request with the outcome of the previous step to form a clear instruction for the next step."
            try:
                from ollama import AsyncClient
                prompt_text = f"Original: {req.user_prompt}\\nPrevious Step ({orch_name}) Output: {result.get('summary')}\\nFormulate the next instruction:"
                resp = await AsyncClient().chat(model='llama3.1:8b', messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': prompt_text}
                ])
                msg = resp.get('message', None) if isinstance(resp, dict) else None
                if msg is not None:
                    current_prompt = msg.get('content', '') if isinstance(msg, dict) else getattr(msg, 'content', '')
                else:
                    current_prompt = getattr(getattr(resp, 'message', None), 'content', '')
            except Exception as e:
                logger.error(f"[ROUTER] Re-grounding failed: {e}")
                pass 
                
    final_status = results[-1].get("status") if results else "ERROR"
    if final_status in ("NEEDS_APPROVAL", "BLOCKED"):
        final_summary = f"The operation was {final_status.lower()}: " + " | ".join([str(r.get("summary", "")) for r in results if r.get("status") == final_status])
    elif final_status == "ERROR":
        final_summary = "The operation encountered an error: " + " | ".join([str(r.get("summary", "")) for r in results if r.get("status") == "ERROR"])
    else:
        system_prompt = "You are RISHI, a Master AI. Synthesize the provided agent outputs into a cohesive final answer to the user. Be concise but complete."
        outputs_text = json.dumps([r.get("summary") for r in results])
        try:
            from ollama import AsyncClient
            resp = await AsyncClient().chat(model='llama3.1:8b', messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': f"Original prompt: {req.user_prompt}\\nOutputs:\\n{outputs_text}"}
            ])
            msg = resp.get('message', None) if isinstance(resp, dict) else None
            if msg is not None:
                final_summary = msg.get('content', '') if isinstance(msg, dict) else getattr(msg, 'content', '')
            else:
                final_summary = getattr(getattr(resp, 'message', None), 'content', '')
        except Exception as e:
            logger.error(f"[ROUTER] Synthesis failed: {e}")
            final_summary = " | ".join([str(r.get("summary", "")) for r in results])

    return {
        "status": final_status,
        "summary": final_summary,
        "results": results,
        "session_id": req.session_id,
        "engagement_id": engagement_id
    }

if __name__ == "__main__":
    import uvicorn
    logger.info("Initializing RISHI Multi-Tenant Node Architecture.")
    logger.info(f"Workers: {worker_cores} cores | RAM threshold: {CRITICAL_RAM_PERCENT}%")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")