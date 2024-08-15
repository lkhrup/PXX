import requests
import os
import html2text
import pysqlite3

year = 2018
offline = False

# Create SQLite database
conn = pysqlite3.connect(os.environ.get('SQLITE_PATH', f'{year}.sqlite'))
conn.row_factory = pysqlite3.Row
conn.execute("""
CREATE TABLE IF NOT EXISTS filings (
    url TEXT PRIMARY KEY,
    filename TEXT,
    file_date TEXT,
    cik TEXT,
    display_name TEXT,
    prop1 TEXT
);
""")
conn.commit()

# Prepare directories
os.makedirs('filings', exist_ok=True)
os.makedirs('blocks', exist_ok=True)

if not offline:
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
    cursor = 0
    while True:
        print(f"Downloading page {page}")
        resp = session.get(
            f'https://efts.sec.gov/LATEST/search-index?q=Tesla&dateRange=custom&category=custom&startdt={year}-01-01&enddt={year+1}-01-01&forms=N-PX&page={page}&from={cursor}',
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
            file_date = hit['_source']['file_date']
            print(f"Hit: {display_names} (CIK={cik}, id={hit['_id']})")
            id = hit['_id']
            # 0001104659-18-053437:a18-15410_5npx.htm -> 000110465918053437/a18-15410_5npx.htm
            id1, id2 = id.split(':')
            id1 = id1.replace('-', '')
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{id1}/{id2}"
            filename = f"{cik}-{id}".replace('/', '-')
            filepath = os.path.join("filings", filename)
            # Find the row by filename
            cu = conn.cursor()
            cu.execute("SELECT * FROM filings WHERE url = ?", (url,))
            if cu.fetchone():
                print(f"Updating {filename}")
                conn.execute(
                    "UPDATE filings SET filename = ?, cik = ?, display_name = ?, file_date = ? WHERE url = ?",
                    (filename, cik, display_names, file_date, url)
                )
            else:
                conn.execute(
                    "INSERT INTO filings (url, filename, cik, display_name, file_date) VALUES (?, ?, ?, ?, ?)",
                    (url, filename, cik, display_names, file_date)
                )
            cu.close()
            if not os.path.exists(filepath):
                print(f"Downloading {url} to {filepath}")
                data = session.get(url, headers=headers)
                if data.status_code != 200:
                    print(f"Failed to download {url}, status code: {data.status_code}")
                    print(hit)
                    continue
                with open(filepath, 'wb') as f:
                    f.write(data.content)
            if os.stat(filepath).st_size < 400:
                print(f"File {filepath} is too small, deleting it")
                os.remove(filepath)
        cursor += len(data['hits']['hits'])
        if cursor >= total_hits:
            break
        page += 1
    conn.commit()
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
            h = html2text.HTML2Text()
            data = h.handle(data)
            with open(os.path.join('filings', txt_filename), 'w') as f:
                f.write(data)


def split_blocks_separator(lines, separator):
    blocks = []
    block = []
    for line in lines:
        if separator in line:
            if block:
                blocks.append('\n'.join(block))
            block = [line]
        else:
            block.append(line)
    if block:
        blocks.append('\n'.join(block))
    return blocks


def split_block_double_separator(lines, separator):
    blocks = []
    block = []
    num_lines = len(lines)
    for index in range(1, num_lines):
        if index + 2 < num_lines and separator in lines[index] and separator in lines[index + 2]:
            if block:
                blocks.append('\n'.join(block))
            block = [lines[index]]
        else:
            block.append(lines[index])
    if block:
        blocks.append('\n'.join(block))
    return blocks


def split_blocks_indentation(lines):
    blocks = []
    block = []
    for line in lines:
        if line and line[0] != ' ':  # New block
            if block:
                blocks.append('\n'.join(block))
            block = [line]
        else:
            block.append(line)
    if block:
        blocks.append('\n'.join(block))
    return blocks


def split_blocks_rows(lines):
    key = lines[0].split('|')[0].strip()
    block = []
    for line in lines:
        if line.split('|')[0].strip() == key:
            block.append(line)
    return ['\n'.join(block)]


def split_blocks(lines):
    # Find the index of the first line mentioning TSLA or TESLA,
    # identify the section separator, and trim the start of the file.
    start = 0
    for line in lines:
        line_upper = line.upper()
        if 'TSLA' in line_upper or 'TESLA' in line_upper:
            break
        start += 1
    if start == 0:
        print("No lines mentioning TSLA or TESLA")
        return []
    if '| F | F' in lines[start]:
        return split_blocks_rows(lines[start:])
    if '---' in lines[start - 1] and '---' in lines[start + 1]:
        return split_block_double_separator(lines[start - 1:], '---')

    sep = None
    for distance in range(1, 25):
        line = lines[start - distance].strip()
        if not line:
            continue
        if '---' in line:
            lines = lines[start - distance:]
            sep = '---'
            break
        if '===' in line:
            lines = lines[start - distance:]
            sep = '==='
            break
        if '___' in line:
            lines = lines[start - distance:]
            sep = '___'
            break
    if sep is not None:
        return split_blocks_separator(lines, sep)

    lines = lines[start:]
    return split_blocks_indentation(lines)

# Extract blocks mentioning 'TESLA'
for filename in os.listdir('filings'):
    if filename.endswith('.txt'):

        # Get CIK before first '-' in filename
        cik = filename.split('-')[0]

        with open(os.path.join('filings', filename), 'r') as f:
            data = f.read()
        lines = data.split('\n')

        blocks = split_blocks(lines)

        index = 1
        for block in blocks:
            block_upper = block.upper()
            if 'TSLA' in block_upper or 'TESLA' in block_upper:
                with open(os.path.join('blocks', f"{cik}-{index}.txt"), 'w') as f:
                    f.write(block)
                index += 1
        if index == 1:
            print(f"Warning: no blocks found in {filename}")

# TODO: analyze blocks
