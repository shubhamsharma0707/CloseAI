import requests

prompts = [
    """
    1. NPV vs IRR Conflict
    A project requires an initial investment of 1,00,00,000 and generates the following cash flows:
    Year 1: 80,00,000
    Year 2: 70,00,000
    Year 3: -30,00,000
    The discount rate is 12%.
    Calculate the NPV.
    """,
    """
    4. Working Capital Trap
    A company reports:
    - Net profit: ₹80 lakh
    - Increase in inventory: ₹40 lakh
    - Increase in receivables: ₹30 lakh
    - Increase in payables: ₹10 lakh
    - Depreciation: ₹15 lakh
    Question: Calculate cash flow from operations.
    """,
    """
    A company has:
    - Net income: ₹50 crore
    - Existing shares: 10 crore
    - Convertible bonds: ₹100 crore at 5% interest
    - Conversion ratio: 20 shares per ₹1,000 bond
    - Tax rate: 30%
    Question: Calculate diluted EPS.
    """
]

for p in prompts:
    print(f"--- Prompt ---")
    res = requests.post("http://127.0.0.1:8000/chat", json={"prompt": p})
    if res.status_code == 200:
        print(res.json()["response"])
    else:
        print("Error", res.status_code)
    print("\n")
