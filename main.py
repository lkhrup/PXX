import requests
import os
from bs4 import BeautifulSoup
import pysqlite3

year = 2018

# Create SQLite database
conn = pysqlite3.connect(os.environ.get('SQLITE_PATH', f'{year}.sqlite'))
conn.row_factory = pysqlite3.Row
conn.execute("""
CREATE TABLE IF NOT EXISTS filings (
    cik TEXT PRIMARY KEY,
    display_name TEXT,
    filename TEXT
);
""")
conn.commit()

# Prepare directories
os.makedirs('pages', exist_ok=True)
os.makedirs('filings', exist_ok=True)
os.makedirs('blocks', exist_ok=True)

# Fetch search results and download filings
session = requests.Session()
headers = {
    'accept': 'application/json, text/javascript, */*; q=0.01',
    'accept-language': 'fr,en-US;q=0.9,en;q=0.8',
    'cache-control': 'no-cache',
    'origin': 'https://www.sec.gov',
    'pragma': 'no-cache',
    'priority': 'u=1, i',
    'referer': 'https://www.sec.gov/',
    'sec-ch-ua': '"Not/A)Brand";v="8", "Chromium";v="126"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Linux"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
    'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
}
# curl 'https://efts.sec.gov/LATEST/search-index?q=Tesla&dateRange=custom&category=custom&startdt=2018-08-15&enddt=2019-01-01&forms=N-PX&page=3&from=200'
page = 1
while True:
    print(f"Downloading page {page}")
    resp = session.get(
        f'https://efts.sec.gov/LATEST/search-index?q=Tesla&dateRange=custom&category=custom&startdt={year}-01-01&enddt={year+1}-01-01&forms=N-PX&page={page}&from={page*100}',
        headers=headers)
    data = resp.json()
    total_hits = data['hits']['total']['value']
    # Elasticsearch results format:
    # {
    #     "hits": {
    #         "total": {
    #             "value": 224,
    #             ...
    #         },
    #         ...,
    #         "hits": [
    #             {
    #                 "_id": "0001193125-18-261549:d611177dnpx.htm",
    #                 "_source": {
    #                     "ciks": [
    #                         "0000916620"
    #                     ],
    #                     ...
    #                 }
    #             },
    #             ...
    #         ]
    #     }
    # }
    # -> curl 'https://www.sec.gov/Archives/edgar/data/0000916620/000119312518261549/d611177dnpx.htm'
    for hit in data['hits']['hits']:
        display_names = ", ".join(hit['_source']['display_names'])
        cik = hit['_source']['ciks'][0]
        print(f"Hit: {display_names} (CIK={cik}, id={hit['_id']})")
        id = hit['_id']
        # 0001104659-18-053437:a18-15410_5npx.htm -> 000110465918053437/a18-15410_5npx.htm
        id1, id2 = id.split(':')
        id1 = id1.replace('-', '')
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{id1}/{id2}"
        filename = os.path.join("filings", f"{cik}-{id}".replace('/', '-'))
        conn.execute(
            "INSERT OR REPLACE INTO filings (cik, display_name, filename) VALUES (?, ?, ?)",
            (cik, display_names, filename)
        )
        if os.path.exists(filename):
            print(f"Skipping {filename}")
        else:
            print(f"Downloading {url} to {filename}")
            data = session.get(url, headers=headers)
            if data.status_code != 200:
                print(f"Failed to download {url}, status code: {data.status_code}")
                print(hit)
                continue
            with open(filename, 'wb') as f:
                f.write(data.content)
        if os.stat(filename).st_size < 400:
            print(f"File {filename} is too small, deleting it")
            os.remove(filename)
    if total_hits <= page*100:
        break
    page += 1
session.close()

# Convert filings to text
for filename in os.listdir('filings'):
    if filename.endswith('.htm'):
        with open(os.path.join('filings', filename), 'r') as f:
            data = f.read()
        txt_filename = filename.replace('.htm', '.txt')
        if os.path.exists(os.path.join('filings', txt_filename)):
            print(f"Skipping {txt_filename}")
            continue
        else:
            print(f"Converting {filename} to {txt_filename}")
            soup = BeautifulSoup(data, 'html.parser')
            data = soup.get_text()
            with open(os.path.join('data', txt_filename), 'w') as f:
                f.write(data)

# Extract blocks mentioning 'TESLA'
for filename in os.listdir('filings'):
    if filename.endswith('.txt'):
        with open(os.path.join('filings', filename), 'r') as f:
            data = f.read()
        # Get CIK before first '-' in filename
        cik = filename.split('-')[0]
        # Find blocks (delimited by lines starting with '---')
        blocks = []
        block = []
        for line in data.split('\n'):
            if line.startswith('---'):
                if block:
                    blocks.append(block)
                block = []
            else:
                block.append(line)
        if block:
            blocks.append(block)
        index = 1
        for block in blocks:
            block_text = '\n'.join(block)
            if 'TESLA' in block_text:
                with open(os.path.join('blocks', f"{cik}-{index}.txt"), 'w') as f:
                    f.write(block_text)
                index += 1

# TODO: analyze blocks
