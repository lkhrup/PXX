import os
import pysqlite3

year = 2018

# Create SQLite database
conn = pysqlite3.connect(os.environ.get('SQLITE_PATH', f'{year}.sqlite'))
conn.row_factory = pysqlite3.Row

print("File date,Filing entity/person,Fund,Ticker,Vote,URL")
# Export each filing in CSV format
for row in conn.execute("""
    SELECT * FROM votes v, filings f
    WHERE v.url = f.url ORDER BY vote, cik, file_date, fund;
"""):
    cik = row['cik']
    display_name = row['display_name']
    file_date = row['file_date']
    fund = row['fund']
    vote = row['vote']
    url = row['url']
    ticker_symbol = row['ticker_symbol']
    print(f'{file_date},"{display_name}",{fund},{ticker_symbol},{vote},"{url}"')
