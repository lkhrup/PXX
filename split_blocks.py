import argparse
import json
import os
import re
import sys
import unittest

from utils import ensure_text_filing


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
        self.needle = None
        self.lines = lines

    def to_dict(self):
        return {
            'start': self.start,
            'end': self.end,
            'lines': self.lines,
        }


def needle_found(line):
    return re.search(r'\b(TSLA|TESLA)\b', line, re.IGNORECASE) is not None


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


def split_filing(filename: str, output_filename: str):
    print(f"\n\n\n---------- {filename} ----------\n")
    with open(os.path.join('filings', filename), 'r', encoding="utf-8") as f:
        filing = f.read()

    # Split at the "<TEXT>" line
    parts = filing.split('<TEXT>\n')
    filing = parts[1].split('</TEXT>\n')[0]
    if len(parts) > 2:
        print("Warning: multiple <TEXT> sections")

    # Detect html filing and convert to text
    filing, fmt = ensure_text_filing(filename, filing)
    lines = filing.split('\n')

    # Extract vote blocks from the filing and write them out as JSON
    split_method, blocks = split_blocks(lines)
    print(f"Found {len(blocks)} blocks by method {split_method}")

    # Filter out blocks that do not mention TSLA or TESLA
    relevant_blocks = []
    for block in blocks:
        # Find the line index of the first line mentioning TSLA or TESLA
        for line_index in range(block.start, block.end):
            if needle_found(lines[line_index]):
                block.needle = line_index
                relevant_blocks.append(block)
                break

    with open(output_filename, 'w', encoding="utf-8") as f:
        f.write(json_dumps({
            'filename': filename,
            'format': fmt,
            'split_method': split_method,
            'blocks': relevant_blocks,
        }, indent=2))


def split_filings():
    for filename in os.listdir('filings'):
        if filename.endswith('.txt'):
            output_filename = os.path.join('blocks', filename)
            output_filename = output_filename.replace('.txt', '.json')
            if os.path.exists(output_filename):
                print(f"Skipping {filename}")
            else:
                split_filing(filename, output_filename)


def main():
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

    os.makedirs('plain', exist_ok=True)
    os.makedirs('blocks', exist_ok=True)

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


# main
if __name__ == '__main__':
    main()
