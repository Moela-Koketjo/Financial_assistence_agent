PARSE_STATEMENT_PROMPT: str = """
Extract all transactions from this bank statement image.
Return a JSON array ONLY. No explanation, no markdown, just the raw array.
Each item must have exactly these fields:
{
  "date": "DD Mon YYYY",
  "description": "full description text as shown",
  "service_fee": 0.00,
  "amount": 500.00,
  "direction": "DR",
  "balance": 6746.17
}
Rules:
- amount is always positive
- direction is exactly "DR" or "CR"
- service_fee is 0 if the column is blank
- date format is like "09 Feb 2026"
"""

CATEGORIZE_TRANSACTION_PROMPT: str = """
Categorize this bank transaction. Return JSON only, no other text, no markdown.
Description: "{description}"
Amount: R{amount}
Direction: {direction} (DR = money going out, CR = money coming in)

Return exactly:
{{
  "category": "<one of: Groceries | Airtime & Data | Food & Takeout | Transport | Bank Fees | Utilities | Personal Transfer | Income | Shopping | Other>",
  "confidence": <0.0 to 1.0>,
  "reasoning": "<one sentence>"
}}
"""

NL_TO_SQL_PROMPT: str = """
You are a MySQL expert for a personal finance app.

Database schema:
{schema}

Write a single SELECT SQL query to answer: "{question}"

Rules:
- Return SQL only — no explanation, no markdown, no backticks
- Must start with SELECT
- No DROP, DELETE, UPDATE, INSERT, ALTER, CREATE
- Add LIMIT 100 if no limit specified
- Join category table when you need category names
"""

TOOL_SYSTEM_PROMPT: str = """
You are a personal finance assistant for a single user.
Transactions are stored in a MySQL database.
Use tools to look up real data. Always include specific rand amounts.
Be concise. Current context: month={month}, year={year}
"""

FORMAT_TOOL_RESULT_PROMPT: str = """
The tool returned: {result}
Answer the user's question in plain friendly English using this data.
Include specific amounts. Keep to 2-3 sentences.
"""
