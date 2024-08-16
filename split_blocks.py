import json
import os
import sys

import html2text


os.makedirs('temp', exist_ok=True)


def normalize_fund(fund):
    fund = fund.upper()
    fund = fund.replace(',', '')
    fund = fund.replace('.', '')
    fund = fund.replace('*', '')
    fund = fund.replace('_', '')
    fund = fund.replace('=', '')
    fund = fund.replace('  ', ' ')
    fund = fund.replace(' & ', ' AND ')  # filings/0001331971-0001438934-18-000424.txt
    fund = fund.replace('(R)', '')  # filings/0001131042-0000894189-18-005019.txt
    fund = fund.replace(' :', ':')
    fund = fund.strip()
    if fund.startswith("FUND:"):
        fund = fund[5:].strip()
    if fund.startswith("FUND NAME:"):
        fund = fund[10:].strip()
    if fund.startswith("THE "):
        fund = fund[4:]
    paren_index = fund.find('(')
    if paren_index > 0:
        fund = fund[:paren_index]
    subadviser_index = fund.find('- SUB-ADVISER:')
    if subadviser_index > 0:
        fund = fund[:subadviser_index]
    return fund.strip()


def match_fund(series, title):
    print(f"Match fund: {title}")
    if title.startswith('REGISTRANT:'):
        title = title[11:].strip()
    item_index = title.find('ITEM ')
    if item_index > 0: # filings/0001123460-0001580642-18-003631.txt
        title = title[:item_index].strip()
    if title.endswith(' FUND') or title.endswith(' ETF') or title.endswith(' PORTFOLIO'):
        # Fast path, also catches some funds for which there is no <SERIES-NAME> line
        return title
    for fund, ticker_symbol in series:
        if title == fund:
            return fund
        if fund.startswith(title) and title+' FUND' == fund:  # 0000814680-0000814680-18-000120.txt
            return fund
        if title == ticker_symbol:  # filings/0001551030-0001438934-18-000195.txt
            return fund
    if '-' in title:
        parts = title.split('-')
        for part in parts:
            part_stripped = part.strip()
            for fund, _ in series:
                if part_stripped == fund:
                    return part_stripped
    # Try dropping the first word of the title -- 0000711175-0000067590-18-001410.txt
    space_index = title.find(' ')
    if space_index > 0:
        title1 = title[space_index + 1:]
        for fund, _ in series:
            if title1 == fund:
                return title
    # Try matching the start or end of the title
    for fund, _ in series:
        if fund.endswith(' ' + title):
            return fund
        if title.startswith(fund + ' '):
            return fund
    if len(title) == 30:  # Try matching 30 characters -- filings/0001567101-0000894189-18-004570.txt
        for fund, _ in series:
            if fund[:30] == title:
                return fund
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


# ZHEJIANG EXPRESSWAY CO., LTD.


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
    block = []
    for line in lines:
        if separator in line:
            if block:
                blocks.append(block)
            block = []
        else:
            block.append(line)
    if block:
        blocks.append(block)
    return blocks


def split_block_double_separator(lines, separator):
    print(f"Splitting using double separator {separator}")
    blocks = []
    block = []
    num_lines = len(lines)
    for index in range(1, num_lines):
        if index + 2 < num_lines and separator in lines[index] and separator in lines[index + 2]:
            if block:
                blocks.append(block)
            block = [lines[index]]
        else:
            block.append(lines[index])
    if block:
        blocks.append(block)
    return blocks


def split_blocks_indentation(lines):
    print(f"Splitting using indentation")
    blocks = []
    block = []
    for line in lines:
        if line and line[0] != ' ':  # New block
            if block:
                blocks.append(block)
            block = [line]
        else:
            block.append(line)
    if block:
        blocks.append(block)
    return blocks


def split_blocks_tabular(lines, marker):
    # Split blocks a line before each occurrence of '| **Security**'
    print("Using tabular block split")
    blocks = []
    block_start = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if marker in line:
            blocks.append(lines[block_start:index - 1])
            block_start = index - 1
        index += 1
    blocks.append(lines[block_start:])
    return blocks


def split_blocks(lines):
    # Find the index of the first line mentioning TSLA or TESLA,
    # identify the block separator, and split the blocks.
    needle_index = 0
    while needle_index < len(lines):
        line = lines[needle_index]
        if needle_found(line):
            break
        needle_index += 1
    if needle_index == len(lines):
        print("No lines mentioning TSLA or TESLA")
        return []
    print("Line  : " + lines[needle_index])
    print("Line+1: " + lines[needle_index + 1])
    if '|  Security' in lines[needle_index + 1]:
        return split_blocks_tabular(lines, '|  Security')
    if '| **Security**' in lines[needle_index + 1]:
        return split_blocks_tabular(lines, '| **Security**')
    if '---' in lines[needle_index - 1] and '---' in lines[needle_index + 1]:
        return split_block_double_separator(lines, '---')
    if lines[needle_index - 2].startswith('| ** **'):
        return split_blocks_separator(lines, '| ** **')
    if '| F | F' in lines[needle_index]:  # XXX This may be broken due pad_tables=True
        return lines

    sep = None
    for distance in range(1, 25):
        line = lines[needle_index - distance].strip()
        if not line:
            continue
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
        return split_blocks_separator(lines, sep)

    return split_blocks_indentation(lines)


def find_fund_name_in_block(block, series):
    title_index = len(block) - 1
    title_lines = []
    detect_title_lines = True
    while title_index >= 0:
        line = block[title_index].strip()
        print(f"Line {title_index}: {line}")
        if line:
            if detect_title_lines:
                if line.startswith("="):
                    title_lines.append(line.replace('=', '').strip())
                elif len(title_lines) > 0:
                    # Only collect adjacent lines
                    detect_title_lines = False
            if '|' in line:
                fields = line.split('|')
            else:
                fields = [line]
            stop = False
            for field in fields:
                field_norm = normalize_fund(field)
                if "NO PROXY VOTING ACTIVITY" in field_norm:
                    stop = True
                    break
                if "NOT CAST ANY PROXY VOTES" in field_norm:
                    stop = True
                    break
                fund = match_fund(series, field_norm)
                if fund is not None:
                    return fund, line
            if stop:
                break
            print(f"Skipping noise: {line}")
        title_index -= 1
    if title_lines:
        title_lines.reverse()
        line = " ".join(title_lines)
        print(f"Detected title lines: {line}")
        line_norm = normalize_fund(line)
        fund = match_fund(series, line_norm)
        if fund is not None:
            return fund, line
    if len(series) == 1:
        return series[0], None  # filings/0001030979-0001162044-18-000535.txt
    return None, None


def find_fund_name(blocks, start_index, series):
    index = start_index
    while index >= 0:
        print(f"Looking for fund name in block {index}")
        fund, ticker_symbol = find_fund_name_in_block(blocks[index], series)
        if fund is not None:
            return fund, ticker_symbol
        index -= 1
    print(f"Fatal: fund not identified")
    exit(1)


def split_sections(series, filing):
    lines = filing.split('\n')
    blocks = split_blocks(lines)
    print(f"Found {len(blocks)} blocks")
    print(json.dumps(blocks, indent=2))
    sections = []
    section_end = -1
    for block_index in range(len(blocks)):
        if block_index <= section_end:
            # Skip blocks already processed
            continue
        block = blocks[block_index]
        # Find the line index of the first line mentioning TSLA or TESLA
        needle_index = None
        for line_index in range(len(block)):
            if needle_found(block[line_index]):
                needle_index = line_index
                break
        if needle_index is not None:
            print(f"Needle found in block {block_index}, line {needle_index}")
            # Walk back to find the start of the section,
            # assuming the security is on the same line in each block, and securities are listed alphabetically.
            section_start = block_index
            current_security = normalize_security(blocks[section_start][needle_index])
            print(f"security: {current_security}")
            was_page = False
            while section_start > 0:
                section_start -= 1
                prev_block = blocks[section_start]
                if needle_index >= len(prev_block):
                    print(f"Short block, assuming fund section start")
                    break
                prev_security = normalize_security(prev_block[needle_index])
                if prev_security == '<PAGE>':
                    was_page = True
                    continue  # Skip, 0001573386-0001135428-18-000263.txt
                if prev_security.startswith('('):  # 0000067160-0001144204-18-047049.txt
                    break
                print(f"prev security: {prev_security}")
                current_security = compare_securities(prev_security, current_security)
                print(f"next security: {current_security}")
                if current_security is None:
                    break
            if was_page and section_start > 0:  # first <PAGE> -- filings/0000869365-0001193125-18-262109.txt
                section_start += 1  # 0001573386-0001135428-18-000263.txt
            # Walk forward to find the end of the section
            section_end = block_index
            while section_end < len(blocks) - 2:
                next_block = blocks[section_end + 1]
                print(f"Next block: {next_block}")
                print(f"Needle index: {needle_index}")
                if needle_index > len(next_block):
                    break  # 0001314414-0001580642-18-003578.txt
                if not needle_found(next_block[needle_index]):
                    break
                section_end += 1
            print(f"Section: {section_start}-{block_index}-{section_end}")
            # Find the fund name
            fund, fund_line = find_fund_name(blocks, section_start, series)
            print(f"Fund: <{fund}>")
            print(f"Fund line: {fund_line}")
            section_blocks = blocks[block_index:section_end + 1]
            print(json.dumps(section_blocks, indent=2))
            sections.append({'fund': fund, 'blocks': section_blocks})
    return sections


def split_filing(filename, output_filename):
    print(f"\n\n\n---------- {filename} ----------\n")
    with open(os.path.join('filings', filename), 'r') as f:
        filing = f.read()
    # Split at the "<TEXT>" line
    parts = filing.split('<TEXT>\n')
    preamble = parts[0]
    filing = parts[1]
    if len(parts) > 2:
        print("Warning: multiple <TEXT> sections")
    # From the preample, extract <SERIES-NAME> lines
    series = []
    preamble_lines = preamble.split('\n')
    fund = None
    ticker_symbol = None
    for line in preamble_lines:
        if line.startswith('<SERIES-NAME>'):
            fund = normalize_fund(line[13:])
        if 'TICKER-SYMBOL>' in line:
            ticker_symbol = line.split('>')[1].strip()
        if line.startswith('</SERIES>'):
            series.append((fund, ticker_symbol))
            fund = None
            ticker_symbol = None
    if not series:
        for line in preamble_lines:
            if "COMPANY CONFORMED NAME:" in line:  # 0001298699-0001193125-18-252336.txt
                fund = line.split(':')[1].strip()
                series.append((normalize_fund(fund), None))
    if ('SPROTT GOLD MINERS ETF', 'SGDM') in series:
        fund = 'Sprott Buzz Social Media Insights ETF'  # Not in preamble, 0001414040-0001387131-18-003632.txt
        series.append((normalize_fund(fund), None))
    if ('SPDR MSCI WORLD STRATEGICFACTORS ETF', 'QWLD') in series:
        fund = 'SPDR MSCI ACWI IMI ETF'  # Not in preamble, 0001168164-0001193125-18-263578.txt
        series.append((normalize_fund(fund), None))

    print("Series:")
    for s in series:
        print(f"  {s}")

    # Detect html filing and convert to text
    filing = filing.strip()
    first_line_end = filing.find('\n')
    first_line = filing[:first_line_end].lower()
    if first_line.startswith('<html>') or first_line.startswith('<!doctype html'):
        temp_file = os.path.join('temp', filename)
        if os.path.exists(temp_file):
            print("Using cached HTML conversion")
            with open(temp_file, 'r') as f:
                filing = f.read()
        else:
            print("Converting HTML filing")
            h = html2text.HTML2Text()
            h.body_width = 0  # Disable line wrapping -- 0001314414-0001580642-18-003578.txt
            h.pad_tables = True  # Enable table padding -- 0001314414-0001580642-18-003578.txt
            filing = h.handle(filing)
            # Write to a temporary file
            with open(temp_file, 'w') as f:
                f.write(filing)

    sections = split_sections(series, filing)
    if len(sections) == 0:
        print(f"Warning: no relevant blocks found in {filename}")
        exit(1)
    with open(output_filename, 'w') as f:
        f.write(json.dumps(sections, indent=2))


def split_filings():
    for filename in os.listdir('filings'):
        if filename == "0001432353-0001135428-18-000216.txt":
            # Bad block splitting
            continue
        if filename.endswith('.txt'):
            output_filename = os.path.join('blocks', filename)
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
