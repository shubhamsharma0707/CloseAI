import re
import logging

logger = logging.getLogger(__name__)

def calculate_npv(initial_investment: float, cash_flows: list[float], discount_rate: float) -> str:
    """
    Calculates the Net Present Value of a series of cash flows.
    """
    npv = -initial_investment
    for t, cf in enumerate(cash_flows):
        npv += cf / ((1 + discount_rate) ** (t + 1))
    
    return (
        f"\\n\\n[EXPERT SCRATCHPAD - STRICT MATHEMATICAL CONTEXT]\\n"
        f"Step 1: Identify initial investment = ₹{initial_investment:,.2f}.\\n"
        f"Step 2: Calculate present value of each cash flow using formula CF / (1 + {discount_rate})^t.\\n"
        f"Step 3: Sum the present values and subtract the initial investment.\\n"
        f"Final NPV Calculation: ₹{npv:,.2f}\\n\\n"
        f"Instructions: Use this scratchpad to explain the math step-by-step to the user. "
        f"Do not invent your own math. Present the final NPV as exactly ₹{npv:,.2f}."
    )

def calculate_diluted_eps(net_income: float, existing_shares: float, bonds_value: float, 
                          bond_interest_rate: float, conv_shares: float, conv_bond_face_value: float, 
                          tax_rate: float) -> str:
    """
    Calculates the Diluted EPS deterministically.
    Assumes inputs are standardized (e.g. all in crores, or all raw numbers).
    """
    # Interest saved after tax
    interest_saved = (bonds_value * bond_interest_rate) * (1 - tax_rate)
    adjusted_earnings = net_income + interest_saved
    
    # New shares from conversion
    number_of_bonds = bonds_value / conv_bond_face_value
    new_shares = number_of_bonds * conv_shares
    
    total_shares = existing_shares + new_shares
    diluted_eps = adjusted_earnings / total_shares
    
    return (
        f"\\n\\n[EXPERT SCRATCHPAD - STRICT MATHEMATICAL CONTEXT]\\n"
        f"Step 1: Calculate Interest Saved After Tax.\\n"
        f"        Bonds ({bonds_value}) * Interest Rate ({bond_interest_rate}) * (1 - Tax Rate {tax_rate}) = {interest_saved:,.2f}.\\n"
        f"Step 2: Calculate Adjusted Earnings.\\n"
        f"        Net Income ({net_income}) + Interest Saved ({interest_saved:,.2f}) = {adjusted_earnings:,.2f}.\\n"
        f"Step 3: Calculate New Shares from Bonds.\\n"
        f"        (Bonds {bonds_value} / Face Value {conv_bond_face_value}) * Conversion Ratio {conv_shares} = {new_shares:,.2f} new shares.\\n"
        f"Step 4: Calculate Total Shares.\\n"
        f"        Existing Shares ({existing_shares}) + New Shares ({new_shares:,.2f}) = {total_shares:,.2f}.\\n"
        f"Step 5: Calculate Diluted EPS.\\n"
        f"        Adjusted Earnings ({adjusted_earnings:,.2f}) / Total Shares ({total_shares:,.2f}) = {diluted_eps:,.2f}.\\n"
        f"Final Diluted EPS Calculation: ₹{diluted_eps:,.2f}\\n\\n"
        f"Instructions: Use this scratchpad to explain the math step-by-step to the user conversationally. "
        f"Do not invent your own math. Present the final EPS as exactly ₹{diluted_eps:,.2f}."
    )

def calculate_operating_cash_flow(net_profit: float, depreciation: float, 
                                  inc_inventory: float, inc_receivables: float, 
                                  inc_payables: float) -> str:
    """
    Calculates Cash Flow from Operations (Indirect Method).
    """
    # Operating Cash Flow = Net Profit + Non-cash expenses (Depreciation) 
    # - Increase in Current Assets (Inventory, Receivables)
    # + Increase in Current Liabilities (Payables)
    ocf = net_profit + depreciation - inc_inventory - inc_receivables + inc_payables
    
    return (
        f"\\n\\n[EXPERT SCRATCHPAD - STRICT MATHEMATICAL CONTEXT]\\n"
        f"Step 1: Start with Net Profit = {net_profit}.\\n"
        f"Step 2: Add back non-cash expenses like Depreciation (+{depreciation}).\\n"
        f"Step 3: Adjust for working capital changes.\\n"
        f"        - Increase in Inventory is cash tied up, so subtract it (-{inc_inventory}).\\n"
        f"        - Increase in Receivables is cash not yet received, so subtract it (-{inc_receivables}).\\n"
        f"        - Increase in Payables is cash retained, so add it (+{inc_payables}).\\n"
        f"Step 4: Calculate total Operating Cash Flow.\\n"
        f"        {net_profit} + {depreciation} - {inc_inventory} - {inc_receivables} + {inc_payables} = {ocf:,.2f}.\\n"
        f"Final Cash Flow Calculation: ₹{ocf:,.2f}\\n\\n"
        f"Instructions: Use this scratchpad to explain the math step-by-step to the user conversationally. "
        f"Do not invent your own accounting rules. Present the final Cash Flow as exactly ₹{ocf:,.2f}."
    )

def route_and_solve(prompt: str) -> str:
    """
    Examines the prompt, detects the quantitative finance intent, 
    extracts variables via regex, and returns the deterministic system override string.
    If no intent matches, returns an empty string.
    """
    prompt_upper = prompt.upper()
    
    # 1. NPV Routing
    if "NPV" in prompt_upper and "DISCOUNT RATE" in prompt_upper:
        try:
            rate_match = re.search(r'(\d+(?:\.\d+)?)\s*%', prompt)
            inv_match = re.search(r'investment of\s*₹?([\d,]+)', prompt, re.IGNORECASE)
            if rate_match and inv_match:
                rate = float(rate_match.group(1)) / 100.0
                initial = float(inv_match.group(1).replace(',', ''))
                
                cfs = []
                matches = re.finditer(r'(?:Year\s*)?([1-9])(?:[\s:]+)(?:₹\s*)?(-?[\d,]{4,})', prompt, re.IGNORECASE)
                for m in matches:
                    cf = float(m.group(2).replace(',', ''))
                    cfs.append(cf)
                
                if cfs:
                    return calculate_npv(initial, cfs, rate)
        except Exception as e:
            logger.error(f"NPV parsing error: {e}")
            
    # 2. Diluted EPS Routing
    if "DILUTED EPS" in prompt_upper and "CONVERTIBLE BONDS" in prompt_upper:
        try:
            ni_match = re.search(r'Net income:.*?(?:₹|Rs\.?)?\s*([\d,]+(?:.\d+)?)\s*(crore|lakh|million)?', prompt, re.IGNORECASE)
            shares_match = re.search(r'Existing shares:.*?([\d,]+(?:.\d+)?)\s*(crore|lakh|million)?', prompt, re.IGNORECASE)
            bonds_match = re.search(r'Convertible bonds:.*?(?:₹|Rs\.?)?\s*([\d,]+(?:.\d+)?)\s*(crore|lakh)?.*?(\d+(?:\.\d+)?)\s*%', prompt, re.IGNORECASE)
            conv_match = re.search(r'Conversion ratio:\s*(\d+)\s*shares per\s*(?:₹|Rs\.?)?\s*([\d,]+)', prompt, re.IGNORECASE)
            tax_match = re.search(r'Tax rate:\s*(\d+(?:\.\d+)?)\s*%', prompt, re.IGNORECASE)
            
            if ni_match and shares_match and bonds_match and conv_match and tax_match:
                ni = float(ni_match.group(1).replace(',', ''))
                shares = float(shares_match.group(1).replace(',', ''))
                bonds = float(bonds_match.group(1).replace(',', ''))
                interest = float(bonds_match.group(3)) / 100.0
                conv_shares = float(conv_match.group(1))
                conv_bond_face_value = float(conv_match.group(2).replace(',', ''))
                tax = float(tax_match.group(1)) / 100.0
                
                # Convert all to absolute numbers based on 'crore' (since the prompt mixes crore and absolute numbers for face value)
                # Let's dynamically apply the multiplier if 'crore' is found
                def get_multiplier(m):
                    unit = m.group(2).lower() if m.lastindex >= 2 and m.group(2) else ""
                    if unit == "crore": return 10000000.0
                    if unit == "lakh": return 100000.0
                    if unit == "million": return 1000000.0
                    return 1.0
                
                ni_abs = ni * get_multiplier(ni_match)
                shares_abs = shares * get_multiplier(shares_match)
                bonds_abs = bonds * get_multiplier(bonds_match)
                
                return calculate_diluted_eps(ni_abs, shares_abs, bonds_abs, interest, conv_shares, conv_bond_face_value, tax)
        except Exception as e:
            logger.error(f"Diluted EPS parsing error: {e}")
            
    # 3. Cash Flow from Operations Routing
    if "CASH FLOW FROM OPERATIONS" in prompt_upper and "DEPRECIATION" in prompt_upper:
        try:
            # We will use simple regex to find the numbers based on the standard question format
            profit_m = re.search(r'Net profit:.*?(?:₹|Rs\.?)?\s*([\d,]+(?:.\d+)?)', prompt, re.IGNORECASE)
            inv_m = re.search(r'Increase in inventory:.*?(?:₹|Rs\.?)?\s*([\d,]+(?:.\d+)?)', prompt, re.IGNORECASE)
            rec_m = re.search(r'Increase in receivables:.*?(?:₹|Rs\.?)?\s*([\d,]+(?:.\d+)?)', prompt, re.IGNORECASE)
            pay_m = re.search(r'Increase in payables:.*?(?:₹|Rs\.?)?\s*([\d,]+(?:.\d+)?)', prompt, re.IGNORECASE)
            dep_m = re.search(r'Depreciation:.*?(?:₹|Rs\.?)?\s*([\d,]+(?:.\d+)?)', prompt, re.IGNORECASE)
            
            if profit_m and inv_m and rec_m and pay_m and dep_m:
                profit = float(profit_m.group(1).replace(',', ''))
                inv = float(inv_m.group(1).replace(',', ''))
                rec = float(rec_m.group(1).replace(',', ''))
                pay = float(pay_m.group(1).replace(',', ''))
                dep = float(dep_m.group(1).replace(',', ''))
                
                return calculate_operating_cash_flow(profit, dep, inv, rec, pay)
        except Exception as e:
            logger.error(f"Cash Flow parsing error: {e}")

    return ""
