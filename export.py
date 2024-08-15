import os
import pysqlite3

year = 2018

# Create SQLite database
conn = pysqlite3.connect(os.environ.get('SQLITE_PATH', f'{year}.sqlite'))
conn.row_factory = pysqlite3.Row

print("File date,Filing entity/person,Prop 1 vote,URL")
# Export each filing in CSV format
for row in conn.execute('SELECT * FROM filings ORDER BY cik, file_date'):
    file_date = row['file_date']
    cik = row['cik']
    display_name = row['display_name']
    prop1 = row['prop1']
    if prop1 is None:
        prop1 = "unknown"
    url = row['url']
    print(f'{file_date},"{display_name}",{prop1},"{url}"')
