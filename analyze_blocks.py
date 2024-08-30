import argparse
import json
import os
import sqlite3

from openai import OpenAI

year = 2018
model = "gpt-4o-mini"
conn = sqlite3.connect(os.environ.get('SQLITE_PATH', f'{year}.sqlite'))
conn.row_factory = sqlite3.Row
conn.execute("""
CREATE TABLE IF NOT EXISTS votes (
    id SERIAL PRIMARY KEY,
    filing_url TEXT,
    block_start INTEGER,
    block_end INTEGER,
    block_text TEXT,
    vote TEXT
);
""")
conn.commit()

prompt_prefix = """
Instructions:
From the input, extract the vote cast on TESLA, INC (ticker TSLA) issue/proposal number 1 at the 21-Mar-18 special meeting.
Issue 1 can be identified with one of these phrasings or variations thereof:
- Approval of Performance Stock Option Agreement;
- Approve Grant of Performance-Based Stock Option Award;
- Approve Stock Option Grant to Elon Musk.
Consider only the meeting and issue mentioned, disregard other meetings and issues in the input.
Consider only the actual vote, ignore the Management Recommendation (which is For on this issue).
For example, if the input contains "Mgt Rec Vote Cast" then "For Against" on the next line would mean Mgt Rec = For, Vote Cast = Against.
If the input says management recommendation is Against, then columns might be reversed.
The text may be preformatted so keeping track of column alignments may help. Columns may also be separated with the '|' character.
Your response must be "None" if the input does not include a definite vote on the relevant issue (Did Not Vote, incorrect meeting date, irrelevant security).
Otherwise, your response must be a single word, "For" or "Against".
Do not explain your reasoning.

Input:
""".strip()
prompt_suffix = """
""".strip()

client = OpenAI()


def analyze_blocks(row):
    filing_url = row['url']
    filename = row['filename']
    filename = filename.replace('.htm', '.txt')
    filename = filename.replace('.txt', '.json')
    filename = os.path.join('blocks', filename)
    print(f"{row['cik']} {row['display_name']}")
    with open(filename, 'r', encoding="utf-8") as f:
        filing = json.loads(f.read())
    for block in filing['blocks']:
        block_start = block['start']
        block_end = block['end']
        block_text = "\n".join(block['lines'])
        # block_text = re.sub(' +', ' ', block_text)  # Reduce LLM input size, it will match on pipes.
        content = prompt_prefix + "\n" + block_text + "\n" + prompt_suffix
        # print(block_text)
        # print(f"  prompt size: {len(content)}")
        completion = client.chat.completions.create(model=model, messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant."
            },
            {
                'role': 'user',
                'content': content,
            },
        ])
        vote = completion.choices[0].message.content
        # Store vote
        conn.execute("""
            INSERT INTO votes (
                filing_url, block_start, block_end, block_text, vote
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            filing_url, block_start, block_end, block_text, vote
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
