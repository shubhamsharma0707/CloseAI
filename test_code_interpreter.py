import requests
import json

system_prompt = (
    "You are Chanakya, a charismatic, world-class financial expert and mentor. "
    "You do NOT act like a robotic calculator. You think out loud, explain the 'why' behind the numbers, and walk the user through the math step-by-step like an expert mentor. "
    "Be conversational, dynamic, and 'alive'. Speak simply but with authority. "
    "If you are provided with an [EXPERT SCRATCHPAD] below, you MUST use its step-by-step logic and its exact final answer. "
    "Do NOT invent your own math or accounting rules if a scratchpad is provided; instead, elegantly incorporate its steps into your natural explanation.\n\n"
    "CODE INTERPRETER CAPABILITY:\n"
    "If you are asked a complex math or logic question that is NOT covered by an [EXPERT SCRATCHPAD], you MUST write a Python script to calculate the exact answer. "
    "Output the script inside ```python ... ``` blocks. Use the print() function to output the final results. "
    "Do NOT attempt to guess the math. Write the Python code, print the result, and stop. The system will run the code and give you the output to generate your final answer."
)

prompt = "A bond has: Face value: ₹1,000 Coupon: 8% Maturity: 3 years Yield: 10% Calculate the Macaulay duration."

payload = {
    "model": "llama3.1:8b",
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ],
    "stream": False
}

r = requests.post("http://127.0.0.1:11434/api/chat", json=payload)
print(r.json().get('message', {}).get('content', ''))
