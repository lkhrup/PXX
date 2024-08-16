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
Consider only the issue mentioned, disregard any other issues in the input.
Consider only the actual vote, ignore the Management Recommendation (which is For in this case). If you see "Mgt Rec Vote Cast" in the input, then pick the second vote mentioned (so "For Against" would be Against, not For). The text is preformatted, so keeping track of column alignments may help.
Your response imperatively must always be a single word, do not explain your reasoning.
Your response must be "None" if the input does not include a vote on the specific issue mentioned.
Otherwise, it must be either "For" or "Against".

Input:
""".strip()
prompt_suffix = """
""".strip()

client = Client(host=os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434'))

def analyze_blocks(row):
    url = row['url']
    cik = row['cik']
    filename = row['filename']
    filename = filename.replace('.htm', '.txt')
    filename = filename.replace('.txt', '.json')
    with open(f'blocks/{filename}') as f:
        blocks = json.loads(f.read())
    print(filename)
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
        if len(vote) > 7:
            vote = 'confused'
        # Validate and store vote
        if vote in ['for', 'against', 'none']:
            conn.execute("""
                INSERT OR REPLACE INTO votes (key, url, fund, ticker_symbol, fund_line, block_text, vote)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (f"{cik} {fund}", url, fund, ticker_symbol, fund_line, block_text, vote))
            conn.commit()


# For every filing in sqlite:
for row in conn.execute('SELECT * FROM filings'):
    try:
        analyze_blocks(row)
    except FileNotFoundError:
        print(f"Warning: no blocks for {row['url']}")
