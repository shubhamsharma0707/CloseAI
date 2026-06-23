import asyncio
from ollama import AsyncClient

async def test():
    def calculate_npv(initial_investment: float, year1: float, year2: float, year3: float, discount_rate: float) -> str:
        """Calculates Net Present Value for a 3-year project."""
        npv = (year1 / (1 + discount_rate)) + (year2 / ((1 + discount_rate)**2)) + (year3 / ((1 + discount_rate)**3)) - initial_investment
        return f"Exact NPV is {npv}"

    client = AsyncClient()
    response = await client.chat(
        model='llama3.1:8b',
        messages=[{'role': 'user', 'content': 'A project requires an initial investment of 1,00,00,000 and generates the following cash flows: Year 1: 80,00,000. Year 2: 70,00,000. Year 3: -30,00,000. The discount rate is 12%. Calculate NPV.'}],
        tools=[calculate_npv]
    )
    print("Response:", response)
    
asyncio.run(test())
