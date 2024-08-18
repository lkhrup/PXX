import sys
import re

# lxml has a 10MB limit on text content; 0000814679-0000067590-18-001417 has 44MB of text
from lxml import html


class Text:
    """
    Text extraction from an HTML element.
    Preserves line breaks imposed by <div>, <p>, and <br> tags, but ignores '\n' and normalizes spaces.
    """

    def __init__(self, element):
        self.text_parts = []
        self.add_space = False
        self.add_newline = False
        self.traverse(element)

    def __str__(self):
        return ''.join(self.text_parts).strip()

    def traverse(self, element):
        if element.text:
            self.add_text(element.text)
        for child in element.iterchildren():
            self.traverse(child)
        if element.tag in ('div', 'p', 'br'):
            self.add_newline = True
            self.add_space = False
        if element.tail:
            self.add_text(element.tail)

    def add_text(self, text):
        text = text.replace('\n', ' ')
        text_s = text.strip()
        if not text_s:
            self.add_space = True
            return
        text = re.sub('[ \u00a0]+', ' ', text)
        if self.add_newline and text:
            text = '\n' + text
            self.add_space = False
            self.add_newline = False
        elif self.add_space:
            text = ' ' + text
            self.add_space = False
        self.text_parts.append(text)


class Table:

    def __init__(self, table):
        self.table = table
        self.table_data: list[list[tuple[int, str]]] = []
        self.col_widths: list[int] = []
        self.row_data: list[tuple[int, str]] = []
        self.col_index: int = 0
        self.extract()
        self.row_prefix = '  | '
        self.row_suffix = ' |'
        self.col_sep = ' | '
        # TODO: 0001120543-0000930413-18-002307 has headers only in the first table
        # 0000831114-0001398344-18-012865.json

    def write(self, buffer):

        # Detect 0-width columns
        zwc = [i for i, width in enumerate(self.col_widths) if width == 0]
        col_widths = [width for width in self.col_widths if width != 0]

        # Table start row indicating column widths
        table_cols = []
        for i, width in enumerate(col_widths):
            table_cols.append('-' * width)
        table_start_row = f"{self.row_prefix}{self.col_sep.join(table_cols)}{self.row_suffix}\n"
        buffer.write("\n" + table_start_row)

        # Table data rows
        for row in self.table_data:
            formatted_rows = [[]]
            formatted_end = [0]
            i = 0
            for colspan, cell in row:
                if i in zwc:  # Skip zero-width column
                    i += 1
                    continue
                # Calculate width of cell, taking into account colspan and skipping zero-width columns
                nz_col_widths = [width for width in self.col_widths[i:i + colspan] if width != 0]
                width = sum(nz_col_widths) + len(self.col_sep) * (len(nz_col_widths) - 1)
                # Split cell text into lines, and fill formatted rows
                cell_lines = cell.split('\n')
                for line_index, line in enumerate(cell_lines):
                    if line_index >= len(formatted_rows):
                        # Add a new formatted row
                        formatted_rows.append([])
                        formatted_end.append(0)
                    formatted_row = formatted_rows[line_index]
                    # Fill in empty cells up to the current column
                    j = formatted_end[line_index]
                    while j < i:
                        if j not in zwc:
                            formatted_row.append(' ' * self.col_widths[j])
                        j += 1
                    formatted_row.append(f"{line.ljust(width)}")
                    formatted_end[line_index] = i + colspan
                i += colspan
            for row_num, formatted_cells in enumerate(formatted_rows):
                # Complete row with empty cells, if necessary
                j = formatted_end[row_num]
                while j < len(self.col_widths):
                    if j not in zwc:
                        formatted_cells.append(' ' * self.col_widths[j])
                    j += 1
                formatted_row = self.col_sep.join(formatted_cells)
                buffer.write(f"{self.row_prefix}{formatted_row}{self.row_suffix}\n")

    def extract(self):
        for element in self.table.iterchildren():
            self.traverse(element)

    def traverse(self, element):
        if element.tag == 'tr':
            self.traverse_row(element)
        elif element.tag in ['th', 'td']:
            self.traverse_cell(element)
            self.flush()
        else:
            for child in element.iterchildren():
                self.traverse(child)

    def traverse_row(self, row):
        for cell in row.iterchildren():
            if cell.tag in ['th', 'td']:
                self.traverse_cell(cell)
        self.flush()

    def traverse_cell(self, cell):
        colspan = int(cell.get("colspan", 1))
        start_col = self.col_index
        for _ in range(colspan):
            if self.col_index >= len(self.col_widths):
                self.col_widths.append(0)
            self.col_index += 1
        cell_text = str(Text(cell))
        max_line_length = max(len(line) for line in cell_text.split("\n"))
        # Spread width of cell over the columns it spans
        length_per_col = (max_line_length + colspan - 1) // colspan
        for i in range(start_col, self.col_index):
            self.col_widths[i] = max(self.col_widths[i], length_per_col)
        self.row_data.append((colspan, cell_text))

    def flush(self):
        self.table_data.append(self.row_data)
        self.row_data = []
        self.col_index = 0


class Document:

    def __init__(self, root, pre_blocks):
        self.root = root
        self.add_space = False
        self.add_newline = False
        self.pre_blocks = pre_blocks

    def write(self, buffer):
        self.traverse(self.root, 0, buffer)

    def traverse(self, element, depth, buffer):
        if isinstance(element, html.HtmlComment):
            return
        # print(f">{' ' * depth}{element.tag}")
        if element.tag == 'table':
            Table(element).write(buffer)
            self.add_newline = True
            self.add_space = False
            # ignore element.tail, it'll likely contain junk inside the table
        elif element.tag == 'pre':
            if element.text:
                # Look up the pre block by index
                buffer.write(self.pre_blocks[int(element.text)])
            self.add_newline = True
            self.add_space = False
            if element.tail:
                self.add_text(element.tail, buffer)
        else:
            if element.tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                buffer.write(f"{'#' * int(element.tag[1:])} f{Text(element)}\n")
            else:
                if element.text:
                    self.add_text(element.text, buffer)
                for child in element.iterchildren():
                    self.traverse(child, depth + 1, buffer)
            if element.tag in ['html', 'body', 'div', 'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                self.add_newline = True
                self.add_space = False
            if element.tail:
                self.add_text(element.tail, buffer)

    def add_text(self, text, buffer):
        text = text.replace('\n', ' ')
        text_s = text.strip()
        if not text_s:
            self.add_space = True
            return
        text = re.sub('[ \u00a0]+', ' ', text)
        if self.add_newline and text:
            text = '\n' + text
            self.add_space = False
            self.add_newline = False
        elif self.add_space:
            text = ' ' + text
            self.add_space = False
        buffer.write(text)


def html_to_plain(html_content, buffer):

    # Extract <PRE></PRE> blocks manipulating the string.
    # PRE blocks may exceed the 10MB limit per text node of lxml.
    # We replace the content with an index in an array, and then replace the index with the content.
    pre_blocks = []
    pre_block_index = 0
    pre_start_re = re.compile(r'<pre[^>]*>', re.IGNORECASE)
    pre_end_re = re.compile(r'</pre>', re.IGNORECASE)
    start_pos = 0
    while True:
        start_match = pre_start_re.search(html_content, start_pos)
        if not start_match:
            break
        pre_text_start = start_match.end()
        end_match = pre_end_re.search(html_content, pre_text_start)
        if not end_match:
            break
        pre_text_end = end_match.start()
        pre_blocks.append(html_content[pre_text_start:pre_text_end])
        html_content = f"{html_content[:pre_text_start]}{pre_block_index}{html_content[pre_text_end:]}"
        start_pos = start_match.end() + 1
        pre_block_index += 1

    Document(html.fromstring(html_content), pre_blocks).write(buffer)


if __name__ == '__main__':
    with open('input.html', 'r', encoding='utf-8') as f:
        input_content = f.read()

    html_to_plain(input_content, sys.stdout)
