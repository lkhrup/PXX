import os
import json
import pysqlite3

year = 2018

# Open SQLite database
conn = pysqlite3.connect(os.environ.get('SQLITE_PATH', f'{year}.sqlite'))
conn.row_factory = pysqlite3.Row

# Load the the cik -> num map.
with open(f'{year}-nums.json', 'r', encoding="utf-8") as f:
    num_dict = json.loads(f.read())

# Update each filing's num.
for row in conn.execute('SELECT * FROM filings'):
    cik = row['cik']
    num = num_dict.get(cik)
    if num is not None:
        conn.execute('UPDATE filings SET num = ? WHERE cik = ?', (num, cik))
        conn.commit()
        print(f"Updated {cik} to {num}")
    else:
        print(f"Warning: no num for {cik}")
