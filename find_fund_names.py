import argparse
import os
import re
import sqlite3
import sys
import time
import unittest
from multiprocessing import Pool

from utils import ensure_text_filing, longest_common_substring, levenshtein_distance

year = 2018

def likely_security(text):
    return re.search(r'\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LIMITED|LTD|LLC|PLC)\.?$', text) is not None

def likely_fund(text):
    return re.search(r'equity|fund|portfolio', text, re.IGNORECASE) is not None

class Fund:

    def __init__(self, original_name, ticker_symbols=None):
        self.original_name = original_name
        self.name = normalize_fund(original_name.upper())
        self.alphanum = re.sub('[^A-Z0-9]', '', self.name)
        self.alphanum_set = set(self.alphanum)
        if ticker_symbols is None:
            self.ticker_symbols = []
        else:
            self.ticker_symbols = sorted(ticker_symbols)

    def to_dict(self):
        return {
            'name': self.name,
            'ticker_symbols': self.ticker_symbols,
        }

    def __str__(self):
        return self.original_name

    def __eq__(self, other):
        return self.original_name == other.original_name


class FundMatch:

    def __init__(self, fund: Fund, tweaks: list[str]):
        self.fund = fund
        self.text = None
        self.method = tweaks
        self.first_line = None
        self.last_line = None

    def __str__(self):
        return f"L{self.first_line} {self.fund.name} ({';'.join(self.method)})"

    def add_tweaks(self, tweaks):
        if tweaks:
            self.method = self.method + tweaks


def normalize_fund(fund: str) -> str:
    # Fund should match "^[^A-Za-z0-9 '&%/.,:+*\$|()-]+$"
    # "'", "*" can just be removed
    fund = re.sub(r"['*]", '', fund)
    # Get rid of (R) entirely.
    fund = re.sub(r'&reg;|\(R\)|\[R]|<SUP>R</SUP>', '', fund, flags=re.IGNORECASE)
    # Remove parentheses and superscript around TM, SM.
    fund = re.sub(r'\(TM\)|<SUP>TM</SUP>', 'TM', fund, flags=re.IGNORECASE)
    fund = re.sub(r'\(SM\)|<SUP>SM</SUP>', 'SM', fund, flags=re.IGNORECASE)
    # '/', '|', ',', ':', '$', are replaced by ' '
    # Some patterns above match on '/', so be sure to keep this one last.
    fund = re.sub(r'[/|,:$]', ' ', fund)
    # Normalize 'and' to ' & '
    fund = re.sub(r'&amp;', '&', fund, flags=re.IGNORECASE)
    fund = re.sub(r'\bAND\b', ' & ', fund, flags=re.IGNORECASE)
    # '%', '.', '+', '-' can be left alone
    # Normalize U.S. to US
    fund = re.sub(r'\bU\.S\.\b', 'US', fund)
    # Remove numeric entities
    fund = re.sub('&#[0-9]+;', ' ', fund)
    # Normalize whitespace
    fund = re.sub(' +', ' ', fund)
    fund = fund.strip()
    return fund


class FundMatcher:
    """
    Match fund names in a list of lines.
    Stateless: can be used concurrently on multiple ranges of lines.
    """

    def __init__(self, series: list[Fund], lines: list[str]):

        self.series = series
        # Compute the set of distinct words in the series names;
        # irrelevant lines won't contain any of these words.
        # We remove common words likely to be part of the fund name because
        # they do not, by themselves, make a line relevant.
        series_words = set()
        for fund in series:
            for word in fund.name.split():
                series_words.add(word)
        for word in ['FUND', 'PORTFOLIO', 'TRUST']:
            if word in series_words:
                series_words.remove(word)
        self.series_words = series_words
        self.max_series_length = max(len(fund.name) for fund in series)

        self.lines = lines

        self.verbose = False

    def process_lines(self, first_line, last_line) -> list[FundMatch]:
        """ Match fund names in the range [first_line, last_line].
        """
        if self.verbose:
            print(f"I Range: {first_line}-{last_line}")
        matches = []

        # Keep track of the last match, ignore subsequent matches for the same fund.
        last_fund = None
        i = first_line
        while i < last_line:
            i = self.skip_irrelevant_lines(i, last_line)
            if i >= last_line:
                break
            match = self.find_at(i)
            if match is not None and match.fund is not last_fund:
                matches.append(match)
                last_fund = match.fund
            i += 1

        return matches

    def skip_irrelevant_lines(self, i, last_line) -> int:
        """
        Attempt to skip efficiently over most irrelevant items.

        :param i: current line index
        :param last_line: maximum line index
        :return: the line index of the next relevant line
        """
        while i < last_line:

            # If the line contains "equity", "fund", "portfolio", it is likely to be relevant.
            # Performing this check early help avoid skipping over relevant lines.
            if likely_fund(self.lines[i]):
                return i

            # Lines that begin with a number are probably votes and should be skipped.
            # "361 Domestic Long/Short Equity Fund" is a counter-example (caught by test above).
            # Subsequent indented lines can also safely be skipped.
            m = re.match(r'\s*\|?\s*([A-Z](.\d)?|\d+|\d+[A-Za-z].?|CMMT)\b', self.lines[i])
            if m is not None:
                i += 1
                ws = ' ' * len(m.group())
                while i < last_line and self.lines[i].startswith(ws):
                    i += 1
                continue

            # Skip lines that are empty or just a series of dashes, equal signs, or underscores
            if re.match(r'[-=_]*\s*$', self.lines[i]):
                i += 1
                continue

            # Skip common pattern that never occur on the same line as a fund name,
            # but would be likely to cause a false positive.
            m = re.search(
                r'Ticker|Voted|Meeting|Annual|Issue No|Mgmt|Proposal|ISIN|Type|Record Date|no proxy voting|during the reporting|SECURITY ID:|Security:|Please|Agenda Number:',
                self.lines[i])
            if m is not None:
                i += 1
                continue

            # If no word in the line is part of a fund name, skip it
            words = set(re.findall(r'\b\w+\b', self.lines[i].upper()))
            if not words.intersection(self.series_words):
                i += 1
                continue

            # Convert to uppercase for looser matching
            text = self.lines[i].upper().strip()

            # Exclude some common lines that can not be fund names
            if not text or text in ["FUND", "TRUST FUND", "PROPOSED FUND"]:
                i += 1
                continue
            if likely_security(text):
                i += 1
                continue
            if re.search(r'(INSTITUTIONAL CLIENT|WHETHER FUND|C/O)', text):
                i += 1
                continue

            break

        return i

    def find_at(self, index: int) -> FundMatch | None:
        """ Find a fund name in the line at index.
            Subsequent lines may be used if the line is part of a multi-line title.
        """
        line = self.lines[index]
        line_stripped = line.strip()
        if not line_stripped:
            return None

        tweaks = []
        candidates = []
        if line_stripped.startswith("="):
            tweaks.append("title")
            self.process_title(candidates, index, line_stripped)
        elif line.startswith('  | '):
            tweaks.append("row")
            self.process_row(candidates, line, tweaks)
        else:
            candidates.append(line)

        # Split at '- ', ' -', ',' to add more candidates.
        # We try the longest candidates first, so it does not matter if a fund name is split.
        for i in range(len(candidates)):
            candidate = candidates[i]
            if '-' in candidate:
                for part in re.split(r'-\s|\s-|,', candidate):
                    candidates.append(part.strip())

        # Sort candidates, longest first
        candidates.sort(key=lambda x: len(x), reverse=True)
        if self.verbose:
            print(f"Candidates: {candidates}")

        best_score = -1
        best_candidate = None
        for text in candidates:

            # Skip over very long lines
            if len(text) > self.max_series_length + 40:
                continue

            fm, score = self.process_candidate(index, text, tweaks)
            if fm is not None and score > best_score:
                best_score = score
                best_candidate = fm

        return best_candidate

    def process_title(self, candidates, index, line_stripped):
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

    def process_row(self, candidates, line, tweaks):
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

    def process_candidate(self, index: int, text: str, tweaks: list[str]) -> tuple[FundMatch | None, int]:
        text_upper = text.upper()
        if likely_security(text_upper) and not likely_fund(text_upper):
            # Prevent candidates that look like security names from being matched.
            return None, 0
        extra_tweaks = []
        likely = False
        m = re.search("\s*-?\s*SUB-?ADVIS[OE]R", text_upper)
        if m is not None:
            if self.verbose:
                print(f"T   matched 'sub-adviser' in {text}")
            likely = True
            text = text[:m.start()].strip()
            extra_tweaks.append("trailing(subadvisor)")
        # Identify some common leading patterns
        m = re.match('REGISTRANT\s*:\s*', text_upper)
        if m is not None:
            if self.verbose:
                print(f"T   matched 'Registrant:' in {text}")
            likely = True
            text = text[m.end():]
            extra_tweaks.append("leading(registrant)")
        m = re.match('FUND(\s+NAME)?\s*:\s*', text_upper)
        if m is not None:
            if self.verbose:
                print(f"T   matched 'fund name:' in {text}")
            likely = True
            text = text[m.end():]
            extra_tweaks.append("leading(fund name)")
        # Remove some common trailing patterns
        m = re.search(r'-?\s*CLASS\b', text_upper)
        if m is not None:
            if self.verbose:
                print(f"T   matched 'class' in {text}")
            text = text[:m.start()].strip()
            extra_tweaks.append("trailing '- class'")
        m = re.search(r'\bEFFECTIVE\b', text_upper)
        if m is not None:
            if self.verbose:
                print(f"T   matched 'effective' in {text}")
            text = text[:m.start()].strip()
            extra_tweaks.append("trailing(effective)")
        m = re.search(r'\bITEM\b', text_upper)
        if m is not None:
            if self.verbose:
                print(f"T   matched 'item' in {text}")
            text = text[:m.start()].strip()
            extra_tweaks.append("trailing(item)")
        # Look for a parenthesis, and remove the content.
        # Ignore (R), (SM), (TM) as they are likely to be part of a security name.
        paren_match = re.search(r'\([^)]{3}', text)
        if paren_match is not None:
            text = text[:paren_match.start()].strip()
        fm, score = self.match_fund(text)
        if fm is None:
            if likely and self.verbose:
                print(f"W match expected but not found in: {text}")
            return None, 0
        # Fill-in the FundMatch object with the context
        fm.first_line = index
        fm.text = text.strip()
        fm.add_tweaks(tweaks)
        fm.add_tweaks(extra_tweaks)
        return fm, score

    def match_fund(self, text: str) -> tuple[FundMatch | None, int]:

        text_norm = normalize_fund(text.upper())
        if self.verbose:
            print(f"Matching {text} as {text_norm}")

        # Fast exact match
        fm = self.match_strict(text_norm)
        if fm is not None:
            return fm, len(text_norm)

        # Slower common substring match
        fm, score = self.match_common_substring(text_norm)
        if fm is not None:
            return fm, score

        return None, 0

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

    def match_common_substring(self, title: str) -> tuple[FundMatch | None, int]:
        # TODO: ignore matches limited to FUND, PORTFOLIO, TRUST; also INTERNATIONAL
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

            length, pos1, pos2 = longest_common_substring(alphanum, fund.alphanum)

            # Skip common words that do not help identify the fund
            common = alphanum[pos1:pos1 + length]
            if common in ["FUND", "PORTFOLIO", "TRUST", "EQUITY"]:
                continue

            # heads and tails penalize the score
            penalty = pos1 + pos2 + len(alphanum) - (pos1 + length) + len(fund.alphanum) - (pos2 + length)
            score = max(1, length - penalty / 4)
            if penalty > penalty_threshold or score < low_threshold:
                if self.verbose:
                    print(f"T not {fund.alphanum} -- {penalty} > {penalty_threshold} or {score} < {low_threshold}")
                continue

            if self.verbose:
                print(f"T   lcs: {length} ({pos1},{pos2}), score={score}")

            if score > best_score[0]:
                best_score = (score, length, pos1, pos2)
                best_match = fund
        if best_match is None:
            return None, 0
        score, length, pos1, pos2 = best_score
        if score < 5:
            return None, 0
        # Compute end positions
        pos3 = len(alphanum) - (pos1 + length)
        pos4 = len(best_match.alphanum) - (pos2 + length)
        if self.verbose:
            print(f"T   {pos1, len(alphanum), pos3} {pos2, len(best_match.alphanum), pos4}")
        ld = levenshtein_distance(best_match.name, title)
        tweaks = [f"common{(length, pos1, pos2, pos3, pos4)}", f"levenshtein({ld})"]
        return FundMatch(best_match, tweaks), max(1, length - ld)


class TestFundMatcher(unittest.TestCase):

    def test_0000804239_easy(self):
        fund = Fund("SIMT CORE FIXED INCOME FUND")
        lines = ["Fund Name : CORE FIXED INCOME FUND"]
        matcher = FundMatcher([fund], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0000804239_hard(self):
        fund = Fund("SIMT High Yield Bond Fund - Class G")
        lines = ["Fund Name : HIGH YIELD BOND FUND"]
        matcher = FundMatcher([fund], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0000804239_enhanced(self):
        fund = Fund("SIMT ENHANCED INCOME FUND")
        lines = ["Fund Name : Enhanced Income"]
        matcher = FundMatcher([fund], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0000741350(self):
        fund = Fund("PGIM Emerging Markets Debt Hard Currency Fund")
        lines = ["PGIM Emerging Markets Debt Hard Currency Fund - Sub-Advisor: PGIM Fixed Income"]
        matcher = FundMatcher([fund], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0000711175(self):
        fund = Fund("CONSERVATIVE BALANCED PORTFOLIO")
        lines = ["PSF Conservative Balanced Portfolio - Equity Sleeve - Sub-Adviser: QMA"]
        matcher = FundMatcher([fund], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0000875186(self):
        fund = Fund("Small-Mid Cap Equity Fund")
        lines = ["=========== Consulting Group Capital Markets Funds - Small-Mid Cap  ============"]
        matcher = FundMatcher([fund], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0000819118(self):
        fund = Fund("Fidelity International Index Fund")
        lines = ["EDISON INTERNATIONAL"]
        matcher = FundMatcher([fund], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNone(match)

    def test_0001174610(self):
        fund = Fund("ProShares Short 7-10 Year Treasury")
        lines = ["  | <U+0095> | Short 7-10 Year Treasury |"]
        matcher = FundMatcher([fund], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0001046292(self):
        fund = Fund("Goldman Sachs Mid Cap Value Fund")
        lines = ["========= Goldman Sachs Variable Insurance Trust - Goldman Sachs Mid  ==========",
                 "=========                       Cap Value Fund                        =========="]
        matcher = FundMatcher([fund], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0001318342(self):
        fund = Fund("361 Domestic Long/Short Equity Fund")
        lines = ["361 Domestic Long/Short Equity Fund"]
        matcher = FundMatcher([fund], lines)
        matcher.verbose = True
        self.assertEqual(0, matcher.skip_irrelevant_lines(0, 1))
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0001015965(self):
        fund = Fund("Voya RussellTM Large Cap Growth Index Portfolio")
        lines = ["Voya Russell<sup>TM</sup> Large Cap Growth Index Portfolio"]
        self.assertEqual(fund.original_name, normalize_fund(lines[0]))
        matcher = FundMatcher([fund], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)
        self.assertEqual(match.method, ["exact"])

    def test_0001261788(self):
        fund = Fund("Zevenbergen Growth Fund")
        lines = ["  | Zevenbergen Growth Fund Investment Company Report |"]
        matcher = FundMatcher([fund], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        self.assertIsNotNone(match)

    def test_0000934563(self):
        fund = Fund("The ESG Growth Portfolio")
        lines = ["Portfolio"]
        matcher = FundMatcher([fund], lines)
        matcher.verbose = True
        match = matcher.find_at(0)
        print(match)
        self.assertIsNone(match)


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


def process_range(series, lines, start, end, verbose):
    matcher = FundMatcher(series, lines)
    matcher.verbose = verbose
    return matcher.process_lines(start, end)


def process_filing(conn, cik, filename, verbose=False):
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

    # Detect html filing and convert to text
    text_filing, fmt = ensure_text_filing(filename, filing)

    # Identify lines that are likely to contain fund names.
    lines = text_filing.split('\n')
    num_lines = len(lines)

    # Update filing with format, num_lines
    conn.execute("UPDATE filings SET format = ?, num_lines = ? WHERE cik = ? AND filename = ?",
                 (fmt, num_lines, cik, filename))
    conn.execute("COMMIT")

    # Look in the 200 first lines for a line that looks like
    # ******************************* FORM N-Px REPORT *******************************
    # and adjust the first_line to skip the header, which may contain fund names.
    first_line = 0
    for i in range(min(200, len(lines))):
        if re.match(r'^\*+\s*FORM N-P[Xx] REPORT\s*\*+$', lines[i]):
            first_line = i + 1
            break

    # Split line ranges between CPUs
    num_cpus = os.cpu_count()
    actual_num_lines = num_lines - first_line
    chunk_size = actual_num_lines // num_cpus
    line_ranges = [(first_line + i * chunk_size, first_line + (i + 1) * chunk_size) for i in range(num_cpus)]
    line_ranges[-1] = (line_ranges[-1][0], num_lines)

    start_time = time.time()
    matches = []
    with Pool(num_cpus) as pool:
        for ms in pool.starmap(process_range, [(series, lines, start, end, verbose) for (start, end) in line_ranges]):
            matches.extend(ms)
    time_elapsed = time.time() - start_time
    print(f"Processed {num_lines} lines in {time_elapsed:.2f}s")

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
            m = FundMatch(series[0], ["default"])
            m.first_line = first_line
            matches.append(m)
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
            print(f"I [{match.first_line},{';'.join(match.method)}] found {match.fund} as {match.text}")

    # Sort matches by first_line
    matches.sort(key=lambda x: x.first_line)

    # Remove consecutive matches for the same fund
    i = 0
    while i < len(matches) - 1:
        if matches[i].fund == matches[i + 1].fund:
            m = matches[i]
            m.last_line = matches[i + 1].last_line
            matches[i + 1] = m
            del matches[i]
        else:
            i += 1

    # Map tweaks to matches
    tweak_matches = {}
    for match in matches:
        for tweak in match.method:
            if tweak not in tweak_matches:
                tweak_matches[tweak] = []
            tweak_matches[tweak].append(match)
    # Sort by number of matches for each tweak.
    sorted_tweaks = list(sorted(tweak_matches.items(), key=lambda x: len(x[1]), reverse=True))
    if verbose:
        for tweak, tweak_matches in sorted_tweaks:
            print(f"I tweak {tweak}: {len(tweak_matches)} matches")
    mostly_exact = False
    levenshtein_threshold = 7
    require_tweaks = []
    if sorted_tweaks:
        for tweak in sorted_tweaks:
            is_majority = len(tweak[1]) > len(matches) / 2
            if tweak[0] == 'exact':
                mostly_exact = True
                continue
            if tweak[0] in ['title', 'row', 'leading(fund name)'] and is_majority:
                require_tweaks.append(tweak[0])
            m = re.match('levenshtein\((\d+)\)', tweak[0])
            if m and is_majority:
                levenshtein_threshold = max(levenshtein_threshold, int(m.group(1)) + 5)

    # Remove previous matches and insert new ones
    conn.execute("BEGIN")
    conn.execute("DELETE FROM funds WHERE cik = ?", (cik,))
    for i, match in enumerate(matches):
        if i + 1 < len(matches):
            match.last_line = matches[i + 1].first_line - 1
        else:
            match.last_line = num_lines - 1
        span = match.last_line - match.first_line
        state = "KEEP"
        flagged = False
        if mostly_exact:
            for tweak in match.method:
                m = re.match('levenshtein\((\d+)\)', tweak)
                if m is not None and int(m.group(1)) > levenshtein_threshold:
                    state = "SKIP"
                    if span >= min(1000., actual_num_lines / 10):
                        flagged = True
                    break
        if require_tweaks:
            for tweak in require_tweaks:
                if tweak not in match.method:
                    state = "SKIP"
                    if span >= actual_num_lines / 10:
                        flagged = True
                    break
        # Create new row in funds table
        conn.execute("""
            INSERT INTO funds (cik, ordinal, series_name, ticker_symbol, method, first_line, last_line, fund_name, fund_text, state, flagged)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cik,
            i + 1,
            match.fund.original_name,
            ",".join(match.fund.ticker_symbols),
            ";".join(match.method),
            match.first_line,
            match.last_line,
            match.fund.name,
            match.text,
            state,
            flagged))
    conn.execute("COMMIT")


def process_filings(conn, filings, verbose=False):
    for filename in filings:
        cik = os.path.basename(filename).split('-')[0]
        process_filing(conn, cik, filename, verbose)


def process_all_filings(conn, verbose=False):
    for filename in os.listdir('filings'):
        if filename.endswith('.txt'):
            cik = filename.split('-')[0]
            process_filing(conn, cik, os.path.join('filings', filename), verbose)


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

    conn = sqlite3.connect(os.environ.get('SQLITE_PATH', f'{year}.sqlite'))
    conn.row_factory = sqlite3.Row
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
        state TEXT DEFAULT 'KEEP',
        flagged BOOLEAN DEFAULT FALSE
    );
    """)
    if args.clear:
        conn.execute("DELETE FROM funds")
    conn.commit()

    if args.filings:
        process_filings(conn, args.filings, verbose=args.verbose)
    else:
        process_all_filings(conn, verbose=args.verbose)
    exit(0)


# main
if __name__ == '__main__':
    os.makedirs('plain', exist_ok=True)
    main()
