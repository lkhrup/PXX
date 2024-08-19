import argparse
import json
import os
import sqlite3
from ollama import Client

year = 2018
model = 'llama3:70b'
# model = 'mixtral:8x7b' # much worse than llama3:70b
conn = sqlite3.connect(os.environ.get('SQLITE_PATH', f'{year}.sqlite'))
conn.row_factory = sqlite3.Row
conn.execute("""
CREATE TABLE IF NOT EXISTS votes (
    id SERIAL PRIMARY KEY,
    url TEXT,
    
    split_method TEXT,
    block_start TEXT,
    block_text TEXT,
    
    fund_method TEXT,
    fund_name TEXT,
    ticker_symbol TEXT,
    fund_line TEXT,
    
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
The text may be preformatted and keeping track of column alignments may help. Columns may be separated with the '|' character.
Your response must be "None" if the input does not include a definite vote on the relevant issue (Did Not Vote, incorrect meeting date, irrelevant security).
Otherwise, your response must be a single word, "For" or "Against".
Do not explain your reasoning.

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
    for fund_block in blocks:

        # Fund information (if available)
        fund = fund_block.get('fund', None)
        if fund is not None:
            fund_name = fund['name']
            ticker_symbols = fund['ticker_symbols']
            fund_method = fund_block['fund_method']
            fund_text_matched = fund_block['fund_text_matched']
        else:
            fund_name = None
            ticker_symbols = []
            fund_method = None
            fund_text_matched = None

        # Block information
        split_method = fund_block['split_method']
        text_blocks = fund_block['blocks']
        for block in text_blocks:
            block_start = block['start']
            block_text = "\n".join(block['lines'])
            # block_text = re.sub(' +', ' ', block_text)  # Reduce LLM input size, it will match on pipes.
            content = prompt_prefix + "\n" + block_text + "\n" + prompt_suffix
            # print(block_text)
            # print(f"  prompt size: {len(content)}")
            response = client.chat(model=model, messages=[
                {
                    'role': 'user',
                    'content': content,
                },
            ])
            vote = response['message']['content']
            print(f"{fund_name}: {vote}")
            vote = vote.lower().strip()
            # Validate and store vote
            if vote in ['for', 'against']:
                conn.execute("""
                    INSERT INTO votes (
                        url,
                        split_method, block_start, block_text,
                        fund_method, fund_name, ticker_symbol, fund_line,
                        vote
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    url,
                    split_method, block_start, block_text,
                    fund_method, fund_name, ", ".join(ticker_symbols), fund_text_matched,
                    vote
                ))
                conn.commit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='split_blocks',
        description='Split blocks from filings')
    parser.add_argument('-c', '--clear', action='store_true')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('filings', metavar='FILING', type=str, nargs='*',
                        help='names of the filings to split (no path, with ext)')
    args = parser.parse_args()

    if args.clear:
        # Clear votes
        conn.execute("DELETE FROM votes")

    if args.filings:
        for row in conn.execute('SELECT * FROM filings WHERE filename IN ({})'.format(
                ','.join('?' * len(args.filings))), args.filings):
            analyze_blocks(row)
    else:
        for row in conn.execute('SELECT * FROM filings'):
            try:
                analyze_blocks(row)
            except FileNotFoundError:
                print(f"Warning: no blocks for {row['url']}")

    exit(0)
