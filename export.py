import os
import sqlite3

year = 2018

# Open SQLite database
conn = sqlite3.connect(os.environ.get('SQLITE_PATH', f'{year}.sqlite'))
conn.row_factory = sqlite3.Row

print("CIK,Filing entity,Doc,Date filed,Series name,Ticker symbols,Vote")
# Export each filing in CSV format
for row in conn.execute("""
    SELECT filings.cik, filings.display_name, filings.num, filings.file_date,
           funds.series_name, coalesce(funds.ticker_symbol, '') AS ticker_symbol,
           votes.vote
      FROM votes
     LEFT OUTER JOIN filings ON
        filings.url = votes.filing_url
     LEFT OUTER JOIN funds ON
        funds.filing_url = votes.filing_url AND
        votes.block_start BETWEEN funds.first_line AND funds.last_line 
     WHERE vote <> 'None'
    ORDER BY num, block_start;
"""):
    cik = row['cik']
    display_name = row['display_name']
    num = row['num']
    file_date = row['file_date']
    series_name = row['series_name']
    ticker_symbol = row['ticker_symbol']
    vote = row['vote']
    print(f'"{cik}","{display_name}",{num},{file_date},"{series_name}","{ticker_symbol}","{vote}"')
