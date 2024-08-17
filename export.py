import os
import sqlite3

year = 2018

# Open SQLite database
conn = sqlite3.connect(os.environ.get('SQLITE_PATH', f'{year}.sqlite'))
conn.row_factory = sqlite3.Row

print("Doc #,Date filed,,Filing entity/person,Fund,Ticker symbols,Vote,URL")
# Export each filing in CSV format
for row in conn.execute("""
    SELECT * FROM votes v, filings f
    WHERE v.url = f.url ORDER BY num, file_date, fund, vote;
"""):
    num = row['num']
    cik = row['cik']
    display_name = row['display_name']
    file_date = row['file_date']
    fund = row['fund']
    vote = row['vote'].title()
    url = row['url']
    ticker_symbol = row['ticker_symbol']
    if ticker_symbol is None:
        ticker_symbol = ""
    print(f'{num},{file_date},,"{display_name}",{fund},"{ticker_symbol}",{vote},"{url}"')
