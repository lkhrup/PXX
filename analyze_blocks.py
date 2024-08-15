import os
from ollama import Client
import pysqlite3

year = 2018
conn = pysqlite3.connect(os.environ.get('SQLITE_PATH', f'{year}.sqlite'))
conn.row_factory = pysqlite3.Row

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

# For every filing in sqlite:
for row in conn.execute('SELECT * FROM filings WHERE prop1 is NULL'):
    print(f"{row['prop1']}: {row['url']}")
    if row['prop1'] is not None:
        break
    url = row['url']
    filename = row['filename'].replace('.htm', '.txt')
    with open(f'blocks/{filename}') as f:
        content = f.read()
    content = prompt_prefix + "\n" + content + "\n" + prompt_suffix
    response = client.chat(model='llama3:70b', messages=[
        {
            'role': 'user',
            'content': content,
        },
    ])
    vote = response['message']['content']
    print(f"{filename}: {vote}")
    vote = vote.lower().strip()
    # Validate and store vote
    if vote in ['for', 'against', 'none']:
        conn.execute('UPDATE filings SET prop1 = ? WHERE url = ?', (vote, url))
        conn.commit()
