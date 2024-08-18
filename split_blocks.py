import json
import os
import re
import sys

from html_to_plain import html_to_plain

os.makedirs('plain', exist_ok=True)
os.makedirs('blocks', exist_ok=True)


def custom_serializer(obj):
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not serializable")


def json_dumps(obj, **kwargs):
    return json.dumps(obj, **kwargs, default=custom_serializer)


class Fund:

    def __init__(self, original_name, ticker_symbols):
        self.original_name = original_name
        self.name = normalize_fund(original_name)
        self.ticker_symbols = ticker_symbols

    def to_dict(self):
        return {
            'name': self.name,
            'ticker_symbols': self.ticker_symbols,
        }

    def __str__(self):
        return self.original_name


class Block:

    def __init__(self, start, end, lines):
        self.start = start
        self.end = end
        self.lines = lines

    def to_dict(self):
        return {
            'start': self.start,
            'end': self.end,
            'lines': self.lines,
        }


def char_positions(line, char):
    return [i for i, c in enumerate(line) if c == char]


def normalize_fund(fund: str) -> str:
    fund = fund.upper()
    fund = fund.replace(',', '')
    fund = fund.replace('.', '')
    fund = fund.replace('*', '')
    fund = fund.replace('_', '')
    fund = fund.replace('=', '')
    fund = re.sub(' +', ' ', fund)
    fund = fund.replace(' & ', ' AND ')  # filings/0001331971-0001438934-18-000424.txt
    fund = fund.replace('(R)', '')  # filings/0001131042-0000894189-18-005019.txt
    # fund = fund.replace(' :', ':')
    fund = fund.strip()
    # Remove some common trailing patterns
    item_index = fund.find('ITEM ')
    if item_index > 0:
        fund = fund[:item_index]
    paren_index = fund.find('(')
    if paren_index > 0:
        fund = fund[:paren_index]
    subadviser_index = fund.find('- SUB-ADVISER:')
    if subadviser_index > 0:
        fund = fund[:subadviser_index]
    return fund.strip()


def match_fund(series: list[Fund], title: str) -> tuple[str, Fund] | None:
    """
    :param series: list of funds
    :param title: text to match
    :return: (method, fund) or None
    """
    if not title:
        return None
    for fund in series:
        if title == fund.name:
            return '1', fund
        if fund.name.startswith(title) and title + ' FUND' == fund.name:  # 0000814680-0000814680-18-000120.txt
            return '2', fund
        if title in fund.ticker_symbols:  # filings/0001551030-0001438934-18-000195.txt
            return '3', fund
    if '-' in title:
        parts = title.split('-')
        for part in parts:
            part_stripped = part.strip()
            for fund in series:
                if part_stripped == fund.name:
                    return '4-', fund
    if ':' in title:
        parts = title.split(':')
        for part in parts:
            part_stripped = part.strip()
            for fund in series:
                if part_stripped == fund.name:
                    return '4:', fund
    # Try dropping the first word of the title -- 0000711175-0000067590-18-001410.txt
    space_index = title.find(' ')
    if space_index > 0:
        title1 = title[space_index + 1:]
        for fund in series:
            if title1 == fund.name:
                return '5', fund
    # Try matching the start or end of the title
    for fund in series:
        if fund.name.endswith(' ' + title):
            return '6', fund
        if title.startswith(fund.name + ' '):
            return '7', fund  # This method may cause bad matches
    if len(title) == 30:  # Try matching 30 characters -- filings/0001567101-0000894189-18-004570.txt
        for fund in series:
            if fund.name[:30] == title:
                return '8', fund
    if title.endswith(' FUND') or title.endswith(' ETF') or title.endswith(' PORTFOLIO'):
        # Catches some funds for which there is no <SERIES-NAME> line,
        # but likely to cause erroneous matches.
        return '9', Fund(title, [])
    return None


def normalize_security(security):
    print("Literal: " + security)
    if security.startswith('| '):
        security = security[2:]
    security = security.strip().upper()
    tab_index = security.find('    ')
    if tab_index > 0:
        security = security[:tab_index]  # 0001217286-0001438934-18-000330.txt
    star_star_index = security.find('**')
    if star_star_index > 0:
        security = security[star_star_index + 2:]
    pipe_index = security.find('|')
    if pipe_index > 0:
        security = security[:pipe_index]  # 0001535538-0001535538-18-000053.txt
    company_name = security.find('COMPANY NAME:')
    if company_name > 0:
        security = security[company_name + 12:]
    meeting_date_index = security.find(' MEETING DATE:')
    if meeting_date_index > 0:
        security = security[:meeting_date_index]  # 0000814680-0000814680-18-000120.txt
    print("Normalized: " + security)
    return security


def compare_securities(security1, security2):
    print(f"Comparing {security1} and {security2}")
    if security1 == "ELI LILLY AND COMPANY" and security2[0] != 'E':
        security1 = "LILLY AND COMPANY"
        if security1 <= security2:  # 0000869365-0001193125-18-262109.txt
            return security1
    if security1 <= security2:
        return security1
    security1_norm = security1.replace('-', '').replace("'", '').replace('&', '').replace('`', ' ')
    security2_norm = security2.replace('-', '').replace("'", '').replace('&', '').replace('`', ' ')
    if security1_norm <= security2_norm:
        return security1
    security1_norm = security1_norm.replace(' ', '')
    security2_norm = security2_norm.replace(' ', '')
    if security1_norm <= security2_norm:
        return security1
    return None


def needle_found(line):
    line_upper = line.upper()
    tsla_index = line_upper.find('TSLA')
    if tsla_index >= 0:
        # Require next character to be non-alpha
        if tsla_index + 4 < len(line) and line[tsla_index + 4].isalpha():
            return False
        return True
    return 'TESLA' in line_upper


def split_blocks_separator(lines, separator):
    print(f"Splitting using separator {separator}")
    blocks = []
    start = 0
    for i, line in enumerate(lines):
        if separator in line:
            if i > start:
                blocks.append(Block(start, i, lines[start:i]))
            start = i
    if len(lines) > start:
        blocks.append(Block(start, len(lines), lines[start:]))
    return blocks


def split_block_double_separator(lines, separator):
    print(f"Splitting using double separator {separator}")
    # 0001579982-0001144204-18-042736
    blocks = []
    start = 0
    for i, line in enumerate(lines):
        if i + 2 < len(lines) and separator in lines[i] and separator in lines[i + 2]:
            if i > start:
                blocks.append(Block(start, i, lines[start:i]))
            start = i
    if start < len(lines):
        blocks.append(Block(start, len(lines), lines[start:]))
    return blocks


def split_blocks_indentation(lines):
    print(f"Splitting using indentation")
    # 0001432353-0001135428-18-000216
    blocks = []
    start = 0
    for i, line in enumerate(lines):
        if line and line[0] != ' ':  # New block
            if i > start:
                blocks.append(Block(start, i, lines[start:i]))
            start = i
    if start < len(lines):
        blocks.append(Block(start, len(lines), lines[start:]))
    return blocks


def split_blocks_marker(lines, marker, offset):
    # Split blocks `offset` lines before each occurrence of the marker.
    # 0000071516-0000051931-18-000837
    print("Using marker block split")
    blocks = []
    start = 0
    for i, line in enumerate(lines):
        if marker in line:
            blocks.append(Block(start, i - offset, lines[start:i - offset]))
            start = i - offset
    if start < len(lines):
        blocks.append(Block(start, len(lines), lines[start:]))
    return blocks


def split_blocks_huge_table(lines):
    # Examples include:
    # 0000355767-0001193125-18-240576.txt
    # 0000811161-0000897101-18-000869.txt
    # 0000811161-0000897101-18-000869.txt
    blocks = []
    index = 0

    line = ""
    while index < len(lines):

        # Locate a table start.
        while index < len(lines):
            line = lines[index]
            if line.startswith('  | -'):
                break
            index += 1
        if index == len(lines):
            break
        print("Begin new table")

        # Parse column width line, data fields are contiguous blocks of '-' characters.
        column_positions = []
        in_frame = True
        column_start = 0
        for i, c in enumerate(line):
            if in_frame:
                if c == '-':
                    in_frame = False
                    column_start = i
            else:
                if c != '-':
                    in_frame = True
                    column_positions.append((column_start, i + 1))

        # Assume the next line contains headers, split it into columns.
        header_line = lines[index + 1]
        headers = []
        for start, end in column_positions:
            headers.append(header_line[start:end].strip())
        # print(f"Headers: {headers}")
        index += 2  # Skip column widths and header lines

        # Collect data from subsequent rows, transposing the table
        while index < len(lines):
            line = lines[index]
            if not line.startswith('  |'):  # End of table
                break
            values = []
            for start, end in column_positions:
                values.append(line[start:end].strip())
            # Zip with headers
            block_lines = []
            print(f"Headers: {headers}")
            print(f"Values: {values}")
            for header, value in zip(headers, values):
                block_lines.append(f"{header}: {value}")
            blocks.append(Block(index, index + 1, block_lines))
            index += 1

    return blocks


def split_blocks(lines: list[str]) -> tuple[str, list[Block]]:
    """ Find the index of the first line mentioning the relevant security,
        identify the block separator, and split the blocks accordingly.

        :returns: the separator type and the blocks.
    """
    needle_index = 0
    while needle_index < len(lines):
        line = lines[needle_index]
        if needle_found(line):
            break
        needle_index += 1
    if needle_index == len(lines):
        print("No lines mentioning relevant security")
        return 'none', []
    print("Line  : " + lines[needle_index])
    print("Line+1: " + lines[needle_index + 1])
    if 'Company Name: ' in lines[needle_index]:  # 0000917124-0001398344-18-012935
        return 'tabular, company name', split_blocks_marker(lines, 'Company Name: ', 0)
    if '| Security' in lines[needle_index + 1]:
        return 'tabular, security1', split_blocks_marker(lines, '| Security', 1)
    if '| Security: ' in lines[needle_index + 2]:
        return 'tabular, security2', split_blocks_marker(lines, '| Security: ', 2)
    if '---' in lines[needle_index - 1] and '---' in lines[needle_index + 1]:
        return 'double_sep, ---', split_block_double_separator(lines, '---')

    # If we can find 'FOR' or 'AGAINST' at and before or after the needle line, we have a huge table.
    needle_upper = lines[needle_index].upper()
    if 'FOR' in needle_upper or 'AGAINST' in needle_upper:
        around_upper = (lines[needle_index - 1] + " " + lines[needle_index + 1]).upper()
        if 'FOR' in around_upper or 'AGAINST' in around_upper:
            return 'huge_table', split_blocks_huge_table(lines)
    if '| F |' in needle_upper or '| N |' in needle_upper:
        around_upper = (lines[needle_index - 1] + " " + lines[needle_index + 1]).upper()
        if '| F |' in around_upper or '| N |' in around_upper:
            return 'huge_table', split_blocks_huge_table(lines)

    sep = None
    for distance in range(1, 25):
        line = lines[needle_index - distance].strip()
        if not line:
            continue
        if re.compile(r"\s*[=_-]{3,}\s*").match(line):
            sep = line
            break
        if '---' in line:
            sep = '---'
            break
        if '===' in line:
            sep = '==='
            break
        if '___' in line:
            sep = '___'
            break
    if sep is not None:
        return f'sep, {sep}', split_blocks_separator(lines, sep)

    return 'indentation', split_blocks_indentation(lines)


def find_fund_name_in_line(lines: list[str], index: int, series: list[Fund]) -> tuple[str, str, Fund] | None:
    """ Returns (text matched, method, fund), or None if no match.
    """
    line = lines[index]
    line_stripped = lines[index].strip()
    if not line_stripped:
        return None
    print(f"Fund? {line}")

    if line_stripped.startswith("="):
        # Title, potentially multi-lines
        line = line_stripped.replace('=', '').strip()
        title_start = index
        while title_start > 0:
            title_line = lines[title_start - 1].strip()
            if not title_line.startswith('='):
                break
            line = title_line.replace('=', '').strip() + " " + line
            title_start -= 1
        line_norm = normalize_fund(line)
        match = match_fund(series, line_norm)
        if match is not None:
            return '\n'.join(lines[title_start:index + 1]), match[0], match[1]
        return None

    # TODO: allow multiple candidates
    if line.startswith('  | '):
        line = line[4:]
        # There is a high risk we'd erroneously match fund mentioned in a proposal.
        # So we're very stric as to what we accept.
        # Patterns:
        #   "Registrant: FUND_NAME"
        #   "Fund Name: FUND_NAME"
        #   "Fund: FUND_NAME"
        #   "FUND_NAME" followed by empty columns
        line_upper = line.upper()
        if line_upper.startswith('REGISTRANT:'):
            line = line[11:]
        elif line.startswith('FUND NAME:'):
            line = line[10:]
        elif line.startswith('FUND:'):
            line = line[5:]
        cells = line_upper.split('|')
        rest = "".join(cells[1:]).strip().upper()
        if rest:
            # Junk after the first cell, probably a vote line.
            if 'ITEM' in rest and ('EXHIBIT' in rest or 'EX ' in rest):
                # Exception for 0001314414-0001580642-18-003578.txt,
                # where a cell contains "Item 1, Exhibit 17".
                pass
            if rest.startswith('FUND NAME'):
                # 0001355064-0001580642-18-004117.txt
                line = rest[9:].strip()
                if line.startswith('-'):
                    line = line[1:].strip()
                # TODO: 0001644419-0001580642-18-004201.txt
            else:
                return None
        line = line.split('|')[0].strip()

    print(f"  matching: {line}")
    match = match_fund(series, normalize_fund(line))
    if match is not None:
        return lines[index], match[0], match[1]

    return None


def find_fund_name_in_lines(lines: list[str], start_index: int, series: list[Fund]) -> tuple[str, str, Fund]:

    if '|' in lines[start_index]:
        # Look for the fund name in the first cell of a table (0001479599-0001144204-18-046418.txt)
        cells = lines[start_index].split('|')
        match = match_fund(series, normalize_fund(cells[1]))
        if match is not None:
            return lines[start_index], match[0], match[1]

    index = start_index - 1
    while index >= 0:
        line_upper = lines[index].upper()
        if "NO PROXY VOTING ACTIVITY" in line_upper:
            break
        if "NOT CAST ANY PROXY VOTES" in line_upper:
            break
        match = find_fund_name_in_line(lines, index, series)
        if match is not None:
            return match
        index -= 1

    # If we reach the start of the file and there is a single fund, assume it is it.
    if len(series) == 1:
        return '0', '', series[0]

    print(f"Fatal: fund not identified")
    exit(1)


def split_sections(series: list[Fund], filing: str):
    lines = filing.split('\n')
    split_method, blocks = split_blocks(lines)
    print(f"Found {len(blocks)} blocks by method {split_method}")
    # print(json_dumps(blocks, indent=2))
    sections = []
    section_start = 0
    while section_start < len(blocks):
        block = blocks[section_start]
        # Find the line index of the first line mentioning TSLA or TESLA
        needle_index = None
        for line_index in range(block.start, block.end):
            if needle_found(lines[line_index]):
                needle_index = line_index
                break
        section_end = section_start + 1
        if needle_index is not None:
            print(f"Needle found in block {section_start}, line {needle_index}")
            # Walk forward to find the end of the section
            while section_end < len(blocks):
                next_block = blocks[section_end]
                found = False
                for line_index in range(next_block.start, next_block.end):
                    if needle_found(lines[line_index]):
                        found = True
                        break
                if not found:
                    break
                section_end += 1
            # Find the fund name, going backward from the needle line.
            # Working line by line simplifies detection as the fund may occur inside a block.
            fund_text_matched, fund_method, fund = find_fund_name_in_lines(lines, needle_index, series)
            print(f"Fund: <{fund}>")
            print(f"Matched: {fund_text_matched}")
            print(f"Method: {fund_method}")
            section_blocks = blocks[section_start:section_end]
            print(f"Section: blocks {section_start}-{section_end}")
            print(json_dumps(section_blocks, indent=2))
            sections.append({
                'fund': fund,
                'blocks': section_blocks,
                'fund_text_matched': fund_text_matched,
                'split_method': split_method,
                'fund_method': fund_method,
            })
        section_start = section_end
    return sections


def extract_series(preamble: str) -> list[Fund]:
    # From the preample, extract <SERIES-NAME> lines
    series = []

    preamble_lines = preamble.split('\n')
    name = None
    normalized_names = []
    ticker_symbols = []
    for line in preamble_lines:
        if line.startswith('<SERIES-NAME>'):
            name = line[13:]
        if line.startswith('<CLASS-CONTRACT-TICKER-SYMBOL>'):
            ticker_symbols.append(line.split('>')[1].strip())
        if line.startswith('</SERIES>'):
            if name is not None:
                fund = Fund(name, ticker_symbols)
                series.append(fund)
                normalized_names.append(fund.name)  # normalized name
            name = None
            ticker_symbols = []

    if not series:
        for line in preamble_lines:
            if "COMPANY CONFORMED NAME:" in line:  # 0001298699-0001193125-18-252336.txt
                name = line.split(':')[1].strip()
                series.append(Fund(name, []))

    if 'SPROTT GOLD MINERS ETF' in normalized_names:
        name = 'Sprott Buzz Social Media Insights ETF'  # Not in preamble, 0001414040-0001387131-18-003632.txt
        series.append(Fund(name, []))
    if 'SPDR MSCI WORLD STRATEGICFACTORS ETF' in normalized_names:
        name = 'SPDR MSCI ACWI IMI ETF'  # Not in preamble, 0001168164-0001193125-18-263578.txt
        series.append(Fund(name, []))

    # Sort series by decreasing length. This will make more specific matches first.
    series.sort(key=lambda x: len(x.name), reverse=True)

    return series


def ensure_text_filing(filename: str, filing: str) -> str:
    filing = filing.strip()
    first_line_end = filing.find('\n')
    first_line = filing[:first_line_end].lower()
    if first_line.startswith('<html>') or first_line.startswith('<!doctype html'):
        plain_file = os.path.join('plain', filename)
        if os.path.exists(plain_file):
            print("Using cached HTML conversion")
        else:
            print("Converting HTML filing")
            # Using html2text (unsatisfactory, table layout is sometimes broken):
            #   h = html2text.HTML2Text()
            #   h.body_width = 0  # Disable line wrapping -- 0001314414-0001580642-18-003578.txt
            #   h.pad_tables = True  # Enable table padding -- 0001314414-0001580642-18-003578.txt
            #   filing = h.handle(filing)
            #
            # Using pandoc (unsatisfactory, no support for multiple table header rows):
            #   with tempfile.NamedTemporaryFile(suffix=".html", mode='w', encoding='utf-8') as temp_html_file:
            #       temp_html_file.write(filing)
            #       temp_html_path = temp_html_file.name
            #       subprocess.run(["pandoc", temp_html_path, "-f", "html", "-t", "plain", "-o", plain_file])
            with open(plain_file, 'w', encoding="utf-8") as f:
                html_to_plain(filing, f)
        with open(plain_file, 'r', encoding="utf-8") as f:
            filing = f.read()
    return filing


def split_filing(filename, output_filename):
    print(f"\n\n\n---------- {filename} ----------\n")
    with open(os.path.join('filings', filename), 'r', encoding="utf-8") as f:
        filing = f.read()

    # Split at the "<TEXT>" line
    parts = filing.split('<TEXT>\n')
    preamble = parts[0]
    filing = parts[1].split('</TEXT>\n')[0]
    if len(parts) > 2:
        print("Warning: multiple <TEXT> sections")

    # Extract series from preamble
    series = extract_series(preamble)
    print("Series:")
    for s in series:
        print(f"  {s}")

    # Detect html filing and convert to text
    filing = ensure_text_filing(filename, filing)

    # Split filing into sections, write out blocks as JSON
    sections = split_sections(series, filing)
    if len(sections) == 0:
        print(f"Warning: no relevant blocks found in {filename}")
        exit(1)
    with open(output_filename, 'w', encoding="utf-8") as f:
        f.write(json_dumps(sections, indent=2))


def split_filings():
    for filename in os.listdir('filings'):
        if filename == "0001066241-0001162044-18-000507.txt":
            # Bad block splitting, tabular
            continue
        if filename.endswith('.txt'):
            output_filename = os.path.join('blocks', filename)
            output_filename = output_filename.replace('.txt', '.json')
            if os.path.exists(output_filename):
                print(f"Skipping {filename}")
            else:
                split_filing(filename, output_filename)


# main
if __name__ == '__main__':
    if len(sys.argv) < 2:
        split_filings()
    else:
        split_filing(sys.argv[1], "/dev/stdout")
