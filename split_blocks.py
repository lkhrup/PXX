import argparse
import json
import os
import re
import sys
import unittest

from utils import ensure_text_filing

os.makedirs('plain', exist_ok=True)
os.makedirs('blocks', exist_ok=True)


def custom_serializer(obj):
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not serializable")


def json_dumps(obj, **kwargs):
    return json.dumps(obj, **kwargs, default=custom_serializer)


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


class FundLine:
    #     id SERIAL PRIMARY KEY,
    #     cik TEXT,
    #     ordinal TEXT,
    #     series_name TEXT,
    #     ticker_symbol TEXT,
    #     method TEXT,
    #     fund_name TEXT,
    #     fund_text TEXT

    def __init__(self, cik, ordinal, series_name, ticker_symbol, method, fund_name, fund_text):
        self.cik = cik
        self.ordinal = ordinal
        self.series_name = series_name
        self.ticker_symbol = ticker_symbol
        self.method = method
        self.fund_name = fund_name
        self.fund_text = fund_text


def find_fund_line(index: int, fund_lines: list[FundLine]) -> int:
    # Dichotomy search to find the fund line at or immediately before index
    if not fund_lines:
        return -1
    left = 0  # 0
    right = len(fund_lines)
    print(f"Searching for {index} in [{left},{right})")
    while left < right:
        print(f"left={left} right={right}")
        mid = (left + right) // 2
        if fund_lines[mid][0] <= index:
            print(f"after {mid}, {fund_lines[mid][0]} < {index}")
            left = mid + 1
        else:
            print(f"before {mid}, {fund_lines[mid][0]} >= {index}")
            right = mid
    result = max(0, left - 1)
    if fund_lines[result][0] > index:
        return -1
    return result


def test_fund_line(name):
    return FundLine('CIK', '1', name, 'TICKER', 'METHOD', 'FUND NAME', 'FUND TEXT')


class TestFindFundLine(unittest.TestCase):

    def test_find_fund_line(self):
        fund_lines = [
            (0, test_fund_line('FUND A'),
            (5, test_fund_line('FUND B')),
            (10, test_fund_line('FUND C')),
        ]
        assert find_fund_line(0, []) == -1
        assert find_fund_line(0, fund_lines) == 0
        assert find_fund_line(1, fund_lines) == 0
        assert find_fund_line(4, fund_lines) == 0
        assert find_fund_line(5, fund_lines) == 1
        assert find_fund_line(6, fund_lines) == 1
        assert find_fund_line(9, fund_lines) == 1
        assert find_fund_line(10, fund_lines) == 2
        assert find_fund_line(11, fund_lines) == 2
        assert find_fund_line(15, fund_lines) == 2
        fund_lines = [
            (1650, test_fund_line('ARK Industrial Innovation ETF')),
            (3475, test_fund_line('ARK Innovation ETF')),
            (7338, test_fund_line('ARK Web x.0 ETF')),
            (8723, test_fund_line('The 3D Printing ETF')),
        ]
        assert find_fund_line(3252, fund_lines) == 0

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



def split_sections(series: list[Fund], filing: str):
    lines = filing.split('\n')

    # Do a first pass on the file to identify lines that are likely to contain fund names.
    fund_lines = []
    for i in range(len(lines)):
        match = find_fund_name_in_line(lines, i, series)
        if match is not None:
            fund_lines.append((i, match))
    print(f"Found {len(fund_lines)} potential fund lines")
    for i, match in fund_lines:
        print(f"{str(i).rjust(8)}: {match}")

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
            section_blocks = blocks[section_start:section_end]
            print(f"Section: blocks {section_start}-{section_end}")
            print(json_dumps(section_blocks, indent=2))
            # Find the fund name.
            fund_line_index = find_fund_line(needle_index, fund_lines)
            if fund_line_index >= 0:
                print(f"Fund line index: {fund_line_index}")
                line, match = fund_lines[fund_line_index]
                print(f"Line number in filing: {line}")
                fund_text_matched, fund_method, fund = match
                print(f"Fund: <{fund}>")
                print(f"Matched: {fund_text_matched}")
                print(f"Method: {fund_method}")
                sections.append({
                    'fund': fund,
                    'blocks': section_blocks,
                    'fund_text_matched': fund_text_matched,
                    'split_method': split_method,
                    'fund_method': fund_method,
                })
            else:
                print("WARNING: fund line not identified")
                sections.append({
                    'fund_method': '0',
                    'blocks': section_blocks,
                    'split_method': split_method,
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
    parser = argparse.ArgumentParser(
        prog='split_blocks',
        description='Split blocks from filings')
    parser.add_argument('-c', '--clear', action='store_true')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('-t', '--test', action='store_true')
    parser.add_argument('filings', metavar='FILING', type=str, nargs='*',
                        help='names of the filings to split (no path, with ext)')
    args = parser.parse_args()

    if args.test:
        sys.argv = sys.argv[:1]  # unittest.main() will not recognize the --test argument
        unittest.main()
        exit(0)

    if args.clear:
        for filename in os.listdir('blocks'):
            if filename.endswith('.json'):
                os.remove(os.path.join('blocks', filename))

    if args.filings:
        for filename in args.filings:
            output_filename = os.path.join('blocks', filename)
            output_filename = output_filename.replace('.txt', '.json')
            split_filing(filename, output_filename)
    else:
        split_filings()
    exit(0)
