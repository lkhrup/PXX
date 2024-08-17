import os
import json
from ollama import Client
import pysqlite3

year = 2018
model = 'llama3:70b'
# model = 'mixtral:8x7b' # much worse than llama3:70b
conn = pysqlite3.connect(os.environ.get('SQLITE_PATH', f'{year}.sqlite'))
conn.row_factory = pysqlite3.Row
conn.execute("""
CREATE TABLE IF NOT EXISTS votes (
    id SERIAL PRIMARY KEY,
    url TEXT,
    fund TEXT,
    ticker_symbol TEXT,
    fund_strategy TEXT,
    fund_line TEXT,
    block_text TEXT,
    vote TEXT
);
""")
conn.commit()

prompt_prefix = """
Instructions:
From the input, extract the vote cast on TESLA, INC (ticker TSLA) issue/proposal number 1 at the 21-Mar-18 special meeting.
Issue 1 can be identified with one of these phrasings (or variations thereof):
- Approval of Performance Stock Option Agreement,
- Approve Grant of Performance-Based Stock Option Award,
- Approve Stock Option Grant to Elon Musk.
Consider only the issue mentioned, disregard any other issues in the input.
Consider only the actual vote, ignore the Management Recommendation (which is For on this issue).
For example, if you see "Mgt Rec Vote Cast" in the input, then "For Against" on the next line would mean Mgt Rec = For, Vote Cast = Against.
The text may be preformatted, so keeping track of column alignments may help.
Your response must be a single word, do not explain your reasoning. I will ask for details if needed.
Your response must be "None" if the input does not include a vote on the specific issue mentioned (Did Not Vote, incorrect meeting date, security not mentioned).
If you are certain you identify the vote correctly, then say "For" or "Against" accordingly.

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
    with open(f'blocks/{filename}', 'r', encoding="utf-8") as f:
        blocks = json.loads(f.read())
    print(filename)
    for block in blocks:
        fund = block['fund']
        # If fund is an array (not a string), it is an array (fund, ticker_symbol)
        fund_strategy = None
        ticker_symbol = None
        if isinstance(fund, list):
            if len(fund) == 2:
                fund, ticker_symbol = fund
            elif len(fund) == 3:
                fund_strategy, fund, ticker_symbol = fund
            else:
                print(f"Warning: unexpected fund format {fund}")
        fund_line = block['fund_line']
        text_blocks = block['blocks']  # Array of array of lines
        for lines in text_blocks:
            block_text = "\n".join(lines)
            content = prompt_prefix + "\n" + block_text + "\n" + prompt_suffix
            response = client.chat(model=model, messages=[
                {
                    'role': 'user',
                    'content': content,
                },
            ])
            vote = response['message']['content']
            print(f"{fund}: {vote}")
            if '.' in vote:
                vote = vote.split('.')[0]
            vote = vote.lower().strip()
            # Validate and store vote
            if vote in ['for', 'against']:
                conn.execute("""
                    INSERT INTO votes (url, fund, fund_strategy, ticker_symbol, fund_line, block_text, vote)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (url, fund, fund_strategy, ticker_symbol, fund_line, block_text, vote))
                conn.commit()


# For every filing in sqlite:
for row in conn.execute('SELECT * FROM filings'):
    try:
        analyze_blocks(row)
    except FileNotFoundError:
        print(f"Warning: no blocks for {row['url']}")
