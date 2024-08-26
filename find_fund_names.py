import argparse
import os
import re
import sqlite3
import sys
import unittest

from utils import ensure_text_filing, longest_common_substring

year = 2018
conn = sqlite3.connect(os.environ.get('SQLITE_PATH', f'{year}.sqlite'))
conn.row_factory = sqlite3.Row


os.makedirs('plain', exist_ok=True)


class Fund:

    def __init__(self, original_name, ticker_symbols):
        self.original_name = original_name
        self.name = normalize_fund(original_name)
        self.alphanum = re.sub('[^A-Z0-9]', '', self.name)
        self.alphanum_set = set(self.alphanum)
        self.ticker_symbols = sorted(ticker_symbols)

    def to_dict(self):
        return {
            'name': self.name,
            'ticker_symbols': self.ticker_symbols,
        }

    def __str__(self):
        return self.original_name


class FundMatch:

    def __init__(self, fund: Fund, method: list[str]):
        self.fund = fund
        self.text = None
        self.method = method
        self.start_line = None
        self.end_line = None

    def __str__(self):
        return f"L{self.start_line} {self.fund.name} ({';'.join(self.method)})"

    def add_tweaks(self, tweaks):
        if tweaks:
            self.method = self.method + tweaks


def normalize_fund(fund: str) -> str:
    # Fund should match "^[^A-Za-z0-9 '&%/.,:+*\$|()-]+$"
    fund = fund.upper()
    # "'", "*" can just be removed
    fund = re.sub(r"['*]", '', fund)
    # '/', '|', ',', ':', '$', are replaced by ' '
    fund = re.sub(r'[/|,:$]', ' ', fund)
    # Normalize 'and' to ' & '
    fund = re.sub(r'\bAND\b', ' & ', fund)
    # Get rid of (R) and (TM) and (SM)
    fund = re.sub(r'\(R\)|<SUP>R</SUP>|\(TM\)|<SUP>TM</SUP>|\(SM\)|<SUP>SM</SUP>', '', fund)
    # '%', '.', '+', '-' can be left alone
    # Normalize whitespace
    fund = re.sub(' +', ' ', fund)
    fund = fund.strip()
    return fund


def levenshtein_distance(str1, str2):
    # Create a matrix to store distances
    m, n = len(str1), len(str2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    # Initialize the matrix
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    # Fill the matrix
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if str1[i - 1] == str2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]  # No change needed
            else:
                dp[i][j] = min(dp[i - 1][j] + 1,  # Deletion
                               dp[i][j - 1] + 1,  # Insertion
                               dp[i - 1][j - 1] + 1)  # Substitution

    return dp[m][n]


class FundMatcher:

    def __init__(self, series: list[Fund], lines: list[str]):
        self.series = series
        self.lines = lines
        self.blacklist = ["FUND", "TRUST FUND", "PROPOSED FUND", 'END NPX REPORT']
        self.verbose = False
        self.max_series_length = max(len(fund.name) for fund in series)
        self.cache = {}

    def match_strict(self, title: str) -> FundMatch | None:
        for fund in self.series:

            if fund.name == title:
                return FundMatch(fund, ["exact"])
            if fund.name[:len(title)] == title and len(title) >= 30:
                return FundMatch(fund, [f"prefix({len(title)})"])
            if title in fund.ticker_symbols:  # filings/0001551030-0001438934-18-000195.txt
                return FundMatch(fund, ["ticker symbol"])
            if fund.name.startswith(title) and title + ' FUND' == fund.name:  # 0000814680-0000814680-18-000120.txt
                return FundMatch(fund, ["suffix(FUND)"])
            if fund.name.startswith(
                    title) and title + ' EQUITY FUND' == fund.name:  # 0000814680-0000814680-18-000120.txt
                return FundMatch(fund, ["suffix(EQUITY FUND)"])

        return None

    def match_common_substring(self, title: str) -> FundMatch | None:
        alphanum = re.sub('[^A-Z0-9]', '', title)
        if self.verbose:
            print(f"T Trying common substring match for {title} as {alphanum}")
        low_threshold = min(5., len(alphanum) * 0.8)  # empirical
        penalty_threshold = max(12, len(alphanum))  # empirical
        alphanum_set = set(alphanum)
        best_score = (0, 0, 0, 0)
        best_match = None
        for fund in self.series:
            if len(alphanum_set.intersection(fund.alphanum_set)) < 3:
                continue
            if self.verbose:
                print(f"T   against {fund.alphanum} ({fund.name})")

            length, pos1, pos2 = longest_common_substring(alphanum, fund.alphanum)

            # heads and tails penalize the score
            penalty = pos1 + pos2 + len(alphanum) - (pos1 + length) + len(fund.alphanum) - (pos2 + length)
            score = length - penalty / 4
            if penalty > penalty_threshold or score < low_threshold:
                continue

            if self.verbose:
                print(f"T   lcs: {length} ({pos1},{pos2}), score={score}")

            if score > best_score[0]:
                best_score = (score, length, pos1, pos2)
                best_match = fund
        if best_match is None:
            return None
        score, length, pos1, pos2 = best_score
        if score < 5:
            return None
        # Compute end positions
        pos3 = len(alphanum) - (pos1 + length)
        pos4 = len(best_match.alphanum) - (pos2 + length)
        if self.verbose:
            print(f"T   {pos1, len(alphanum), pos3} {pos2, len(best_match.alphanum), pos4}")
        return FundMatch(best_match, [f"common{(length, pos1, pos2, pos3, pos4)}"])

    def match(self, text: str, important: bool) -> FundMatch | None:
        original_text = text
        text = normalize_fund(text)
        if self.verbose:
            print("T Matching:", text)

        # Exclude some common lines that can not be fund names
        if not text:
            return None
        if text in self.blacklist:
            return None
        if (text.endswith('INC.') or text.endswith('INCORPORATED') or text.endswith('CORP.')
                or text.endswith('CO.') or text.endswith('COMPANY')) or text.endswith('LTD'):
            return None
        if 'INSTITUTIONAL CLIENT' in text or 'WHETHER FUND' in text or 'C/O ' in text:
            return None

        # Fast exact match
        fm = self.match_strict(text)
        if fm is not None:
            fm.text = original_text
            return fm

        # Slower outer match
        fm = self.match_common_substring(text)
        if fm is not None:
            fm.text = original_text
            return fm

        if important and self.verbose:
            print(f"W match expected but not found in: {text}")

        return None

    def find_at(self, index: int) -> FundMatch | None:
        """ Returns (text matched, method, fund), or None if no match.
        """
        line = self.lines[index]

        line_stripped = line.strip()
        if not line_stripped:
            return None

        # print(f'T {index}: {self.lines[index]}')

        tweaks = []
        candidates = []
        if line_stripped.startswith("="):
            # Title, potentially multi-lines
            line = line_stripped.replace('=', '').strip()
            title_start = index
            while title_start > 0:
                title_line = self.lines[title_start - 1].strip()
                if not title_line.startswith('='):
                    break
                line = title_line.replace('=', '').strip() + " " + line
                title_start -= 1
            candidates.append(line)
            tweaks.append("title")
        elif line.startswith('  | '):
            tweaks.append("row")
            if self.verbose:
                print(f"T row")
            line = line[4:]
            # There is a high risk we'd erroneously match a fund mentioned in a proposal.
            # So we're very strict as to what we accept.
            cells = line.split('|')
            rest = "".join(cells[1:]).strip().upper()
            if rest:
                has_junk = True
                # Junk after the first cell, probably a vote line.
                if 'ITEM' in rest and ('EXHIBIT' in rest or 'EX ' in rest):
                    # Exception for 0001314414-0001580642-18-003578.txt,
                    # where a cell contains "Item 1, Exhibit 17".
                    tweaks.append("trailing(itemex)")
                    has_junk = False
                elif rest.startswith('FUND NAME'):
                    # 0001355064-0001580642-18-004117.txt
                    tweaks.append("trailing(fund name)")
                    line = rest[9:].strip()
                    if line.startswith('-'):
                        line = line[1:].strip()
                    has_junk = False
                pvr_index = rest.find('PROXY VOTING RECORD')
                if pvr_index >= 0:
                    tweaks.append("trailing(pvr)")
                    line = rest[:pvr_index].strip()
                    has_junk = False
                if has_junk:
                    for cell in cells[1:]:
                        text = cell.strip()
                        if text:
                            candidates.append(text)
            line = line.split('|')[0].strip()
            candidates.append(line)
        else:
            candidates.append(line)
        # print(f"T candidates: {candidates}")

        # Split at '- ' to add more candidates.
        # We don't split at '-' because fund names may contain '-'.
        # We don't split at ' - ' because the first space may be missing.
        for i in range(len(candidates)):
            if '- ' in candidates[i]:
                parts = candidates[i].split('- ')
                for j, part in enumerate(parts):
                    candidates.append(part)

        # Sort candidates, longest first
        candidates.sort(key=lambda x: len(x), reverse=True)
        if self.verbose:
            print(f"Candidates: {candidates}")

        for text in candidates:

            # Skip over very long lines
            if len(text) > self.max_series_length + 20:
                continue

            text_upper = text.upper()
            tweaks2 = tweaks.copy()
            important = False

            m = re.search("\s*-?\s*SUB-?ADVIS[OE]R", text_upper)
            if m is not None:
                if self.verbose:
                    print(f"T   matched 'sub-adviser' in {text}")
                important = True
                text = text[:m.start()].strip()
                tweaks2.append("trailing(subadvisor)")

            # Identify some common leading patterns
            m = re.match('REGISTRANT\s*:\s*', text_upper)
            if m is not None:
                if self.verbose:
                    print(f"T   matched 'Registrant:' in {text}")
                important = True
                text = text[m.end():]
                tweaks2.append("leading(registrant)")
            m = re.match('FUND(\s+NAME)?\s*:\s*', text_upper)
            if m is not None:
                if self.verbose:
                    print(f"T   matched 'fund name:' in {text}")
                important = True
                text = text[m.end():]
                tweaks2.append("leading(fund name)")

            # Remove some common trailing patterns
            m = re.search(r'-?\s*CLASS\b', text_upper)
            if m is not None:
                if self.verbose:
                    print(f"T   matched 'class' in {text}")
                text = text[:m.start()].strip()
                tweaks2.append("trailing '- class'")
            m = re.search(r'\bEFFECTIVE\b', text_upper)
            if m is not None:
                if self.verbose:
                    print(f"T   matched 'effective' in {text}")
                text = text[:m.start()].strip()
                tweaks2.append("trailing(effective)")
            m = re.search(r'\bITEM\b', text_upper)
            if m is not None:
                if self.verbose:
                    print(f"T   matched 'item' in {text}")
                text = text[:m.start()].strip()
                tweaks2.append("trailing(item)")
            paren_index = text.find('(')
            if paren_index > 0:
                text = text[:paren_index].strip()

            fm = self.match(text, important)
            if fm is not None:
                fm.start_line = index
                fm.text = text
                fm.add_tweaks(tweaks2)
                return fm

        return None


class TestFundMatcher(unittest.TestCase):

    def test_0000804239_easy(self):
        series_name = "SIMT CORE FIXED INCOME FUND"
        lines = ["Fund Name : CORE FIXED INCOME FUND"]
        matcher = FundMatcher([Fund(series_name, [])], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0000804239_hard(self):
        series_name = "SIMT High Yield Bond Fund - Class G"
        self.assertEqual("SIMT HIGH YIELD BOND FUND", normalize_fund(series_name))
        lines = ["Fund Name : HIGH YIELD BOND FUND"]
        matcher = FundMatcher([Fund(series_name, [])], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0000804239_enhanced(self):
        series_name = "SIMT ENHANCED INCOME FUND"
        lines = ["Fund Name : Enhanced Income"]
        matcher = FundMatcher([Fund(series_name, [])], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0000741350(self):
        series_name = "PGIM Emerging Markets Debt Hard Currency Fund"
        lines = ["PGIM Emerging Markets Debt Hard Currency Fund - Sub-Advisor: PGIM Fixed Income"]
        matcher = FundMatcher([Fund(series_name, [])], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0000711175(self):
        series_name = "CONSERVATIVE BALANCED PORTFOLIO"
        lines = ["PSF Conservative Balanced Portfolio - Equity Sleeve - Sub-Adviser: QMA"]
        matcher = FundMatcher([Fund(series_name, [])], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0000875186(self):
        series_name = "Small-Mid Cap Equity Fund"
        lines = ["=========== Consulting Group Capital Markets Funds - Small-Mid Cap  ============"]
        matcher = FundMatcher([Fund(series_name, [])], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0000819118(self):
        series_name = "Fidelity International Index Fund"
        lines = ["EDISON INTERNATIONAL"]
        matcher = FundMatcher([Fund(series_name, [])], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        print(match)
        self.assertIsNone(match)

    def test_0001174610(self):
        series_name = "ProShares Short 7-10 Year Treasury"
        lines = ["  | <U+0095> | Short 7-10 Year Treasury |"]
        matcher = FundMatcher([Fund(series_name, [])], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0001046292(self):
        series_name = "Goldman Sachs Mid Cap Value Fund"
        lines = ["========= Goldman Sachs Variable Insurance Trust - Goldman Sachs Mid  ==========",
                 "=========                       Cap Value Fund                        =========="]
        matcher = FundMatcher([Fund(series_name, [])], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)
        print(match)


def extract_series(preamble: str) -> list[Fund]:
    # From the preample, extract <SERIES-NAME> lines
    series = []

    preamble_lines = preamble.split('\n')
    name = None
    normalized_names = []
    ticker_symbols = []
    for line in preamble_lines:
        if line.startswith('<SERIES-NAME>'):
            # Allowed characters: [^A-Za-z0-9 '&%/.,:+*\$|()-]
            name = line[13:]
            name = re.sub('&#[0-9]+;', ' ', name)
            name = name.replace('&reg;', '(R)')
            name = name.replace('&amp;', '&')
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


def process_filing(cik, filename, verbose=False):
    if verbose:
        print(f"\n\n\n---------- {filename} ----------\n")
    with open(filename, 'r', encoding="utf-8") as f:
        filing = f.read()

    # Split at the "<TEXT>" line
    parts = filing.split('<TEXT>\n')
    preamble = parts[0]
    filing = parts[1].split('</TEXT>\n')[0]
    if verbose and len(parts) > 2:
        print("W Multiple <TEXT> sections")

    # Extract series from preamble
    series = extract_series(preamble)
    series_words = set()
    for fund in series:
        for word in fund.name.split():
            series_words.add(word)
    for word in ['FUND', 'PORTFOLIO', 'TRUST']:
        if word in series_words:
            series_words.remove(word)

    # Detect html filing and convert to text
    text_filing = ensure_text_filing(filename, filing)

    # Identify lines that are likely to contain fund names.
    lines = text_filing.split('\n')
    start_line = 0
    num_lines = len(lines)

    # Look in the 200 first lines for a line that looks like
    # ******************************* FORM N-Px REPORT *******************************
    # and adjust the start_line to skip the header, which may contain fund names.
    for i in range(min(200, len(lines))):
        if re.match(r'^\*+\s*FORM N-P[Xx] REPORT\s*\*+$', lines[i]):
            start_line = i + 1
            break

    matcher = FundMatcher(series, lines)
    matcher.verbose = verbose
    matches = []
    if verbose:
        print(f"I Range: {start_line}-{num_lines}")

    # Keep track of the last match.
    # If the next match is the same, skip it.
    # After each new match (and at the end), update the last_line of the previous match.
    last_fund = None
    last_fund_id = None

    def add_match(line_no: int, match: FundMatch):
        nonlocal last_fund, last_fund_id

        # Update last_fund.last_line if needed
        if last_fund_id is not None:
            conn.execute("UPDATE funds SET last_line = ? WHERE id = ?", (line_no - 1, last_fund_id))

        if match is not None:
            matches.append(match)
            # Create new row in funds table
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO funds (cik, ordinal, series_name, ticker_symbol, method, first_line, fund_name, fund_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cik,
                len(matches),
                match.fund.original_name,
                ",".join(match.fund.ticker_symbols),
                ";".join(match.method),
                line_no,
                match.fund.name,
                match.text))
            last_fund = match.fund
            last_fund_id = cursor.lastrowid

    i = start_line
    while i < num_lines:

        # We attempt to skip over most irrelevant items.
        # Lines that begin with a number are probably votes and should be skipped.
        # Subsequent indented lines can also safely be skipped.
        m = re.match(r'\s*\|?\s*([A-Z](.\d)?|\d+|\d+[A-Za-z].?|CMMT)\b', lines[i])
        if m is not None:
            i += 1
            ws = ' ' * len(m.group())
            while i < num_lines and lines[i].startswith(ws):
                i += 1
            continue
        # Skip lines that are empty or just a series of dashes, equal signs, or underscores
        if re.match(r'[-=_]*\s*$', lines[i]):
            i += 1
            continue
        # Skip common words that won't be part of fund names
        m = re.search(
            r'Ticker|Voted|Meeting|Annual|Issue No|Mgmt|Proposal|ISIN|Type|Record Date|no proxy voting|during the reporting|SECURITY ID:|Security:|Please|Agenda Number:',
            lines[i])
        if m is not None:
            i += 1
            continue
        # If no word in the line is part of a fund name, skip it
        words = set(re.findall(r'\b\w+\b', lines[i].upper()))
        if not words.intersection(series_words):
            i += 1
            continue

        match = matcher.find_at(i)
        if match is not None and match.fund is not last_fund:
            add_match(i, match)

        i += 1

    if verbose and len(matches) > 100:
        print(f"W {filename}: too many funds found, {len(matches)} lines")

    if verbose and len(matches) == len(series):
        print(f"I Found all funds")

    # prune matches
    # 1. If most have tweak "title" then remove the others
    # 2. If most have tweak "leading" then remove the others

    if not matches:
        if len(series) == 1:
            if verbose:
                print("I No fund line found, defaulting to single series")
            add_match(0, FundMatch(series[0], "default"))
        else:
            if verbose:
                print(f"W {filename}: no funds found, {len(series)} series")

    if verbose:
        print(f"I {len(matches)} matches founds")
    for fund in series:
        found = False
        for match in matches:
            if match.fund == fund:
                found = True
                break
        if not found and verbose:
            print(f"W {filename}: fund not found: {fund.original_name} ({fund.name})")
    if verbose:
        for match in matches:
            print(f"I [{match.start_line},{';'.join(match.method)}] found {match.fund} as {match.text}")

    # Update filing with num_lines
    conn.execute("UPDATE filings SET num_lines = ? WHERE cik = ? AND filename = ?", (num_lines, cik, filename))

    if matches:
        add_match(i, None)  # Update last_line of the last match
        conn.execute("COMMIT")


def process_filings(filings, verbose=False):
    for filename in filings:
        cik = os.path.basename(filename).split('-')[0]
        process_filing(cik, filename, verbose)


def process_all_filings(verbose=False):
    for filename in os.listdir('filings'):
        if filename.endswith('.txt'):
            cik = filename.split('-')[0]
            process_filing(cik, os.path.join('filings', filename), verbose)


def main():
    parser = argparse.ArgumentParser(
        prog='find_fund_names',
        description='Identify fund names in SEC filings')
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

    conn.execute("""
    CREATE TABLE IF NOT EXISTS funds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cik TEXT,
        ordinal TEXT,
        series_name TEXT,
        ticker_symbol TEXT,
        first_line INTEGER,
        last_line INTEGER,
        method TEXT,
        fund_name TEXT,
        fund_text TEXT,
        disabled boolean DEFAULT FALSE
    );
    """)
    conn.commit()

    if args.clear:
        conn.execute("DELETE FROM funds")

    if args.filings:
        process_filings(args.filings, verbose=args.verbose)
    else:
        process_all_filings(verbose=args.verbose)
    exit(0)


# main
if __name__ == '__main__':
    main()
