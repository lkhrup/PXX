import os
import json
from ollama import Client
import pysqlite3

year = 2018
conn = pysqlite3.connect(os.environ.get('SQLITE_PATH', f'{year}.sqlite'))
conn.row_factory = pysqlite3.Row
conn.execute("""
CREATE TABLE IF NOT EXISTS votes (
    key TEXT PRIMARY KEY,
    url TEXT,
    fund TEXT,
    ticker_symbol TEXT,
    fund_line TEXT,
    block_text TEXT,
    vote TEXT
);
""")
conn.commit()

prompt_prefix = """
Instruction:
From the SEC filing input, extract the vote cast on TESLA, INC (ticker TSLA) issue/proposal number 1 on the 21-Mar-18 special meeting.
Issue 1 is titled "Approve Grant of Performance-Based Stock Option Award" but another phrasing such as "Approve Stock Option Grant to Elon Musk" or "Approval of Performance Stock Option Agreement" may be used.
Consider only the issue mentioned, disregard any other issues/proposals in the input.
Consider only the actual vote, ignore any Management Recommendation.
Your response must be a single word, do not explain your reasoning.
Your response must be "For" or "Against", or "None" if no vote was cast on the specific proposal mentioned, "Multiple" if the input contains multiple instances of the same meeting dates and proposals, or "Absent" if the input is not relevant.

Input:
""".strip()
prompt_suffix = """
""".strip()

client = Client(host=os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434'))

def analyze_blocks(row):
    print(row['url'])
    url = row['url']
    cik = row['cik']
    filename = row['filename']
    filename = filename.replace('.htm', '.txt')
    filename = filename.replace('.txt', '.json')
    with open(f'blocks/{filename}') as f:
        blocks = json.loads(f.read())
    for block in blocks:
        fund = block['fund']
        # If fund is an array (not a string), it is an array (fund, ticker_symbol)
        ticker_symbol = None
        if isinstance(fund, list):
            fund, ticker_symbol = fund
        fund_line = block['fund_line']
        text_blocks = block['blocks']  # Array of array of lines
        block_text = "\n".join(["\n".join(lines) for lines in text_blocks])
        content = prompt_prefix + "\n" + block_text + "\n" + prompt_suffix
        response = client.chat(model='llama3:70b', messages=[
            {
                'role': 'user',
                'content': content,
            },
        ])
        vote = response['message']['content']
        print(f"{fund}: {vote}")
        vote = vote.lower().strip()
        # Validate and store vote
        if vote in ['for', 'against', 'none']:
            conn.execute("""
                INSERT OR REPLACE INTO votes (key, url, fund, ticker_symbol, fund_line, block_text, vote)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (f"{cik} {fund}", url, fund, ticker_symbol, fund_line, block_text, vote))


# For every filing in sqlite:
for row in conn.execute('SELECT * FROM filings'):
    try:
        analyze_blocks(row)
    except FileNotFoundError:
        print(f"Warning: no blocks for {row['url']}")
