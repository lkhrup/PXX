import os
import re
import unittest

from html_to_plain import html_to_plain


def ensure_text_filing(filename: str, filing: str) -> tuple[str, str]:
    filename = os.path.basename(filename)
    filing = filing.strip()
    first_line_end = filing.find('\n')
    first_line = filing[:first_line_end].lower()
    if first_line.startswith('<html>') or first_line.startswith('<!doctype html'):
        fmt = 'html'
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
    else:
        print("Using plain text filing")
        fmt = 'plain'
        plain_file = os.path.join('plain', filename)
        if not os.path.exists(plain_file):
            with open(plain_file, 'w', encoding="utf-8") as f:
                f.write(filing)
    return filing, fmt


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


def longest_common_substring(s1, s2):
    # Create a table to store lengths of longest common suffixes of substrings
    # dp[i][j] contains length of longest common suffix of s1[0..i-1] and s2[0..j-1]
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    # Initialize variables to store length of the longest common substring
    max_len = 0
    end_index_s1 = 0
    end_index_s2 = 0

    # Fill dp table and track the longest common substring length and its position
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:  # Check if characters match
                dp[i][j] = dp[i - 1][j - 1] + 1  # Extend the common substring length

                # Update the maximum length and positions if a longer substring is found
                if dp[i][j] > max_len:
                    max_len = dp[i][j]
                    end_index_s1 = i - 1  # Update the end index of the substring in s1
                    end_index_s2 = j - 1  # Update the end index of the substring in s2

    # The start index of the longest substring in s1 and s2
    start_index_s1 = end_index_s1 - max_len + 1
    start_index_s2 = end_index_s2 - max_len + 1

    # Return the length of the longest common substring and its positions in s1 and s2
    return max_len, start_index_s1, start_index_s2


class TestUtils(unittest.TestCase):

    def test_longest_common_substring(self):
        s1 = "abcdef"
        s2 = "zabcmno"
        length, position_s1, position_s2 = longest_common_substring(s1, s2)
        self.assertEqual(length, 3)
        self.assertEqual(s1[position_s1:position_s1 + length], "abc")
        self.assertEqual(s2[position_s2:position_s2 + length], "abc")


def align_texts(fund):
    """
    Align the `series_name` and `matched_text` based on the `method`.
    """
    method = fund['method']
    if 'common(' not in method:
        return (None, None)
    start = method.index('common(') + len('common(')
    end = method.index(')', start)
    args = method[start:end]
    length, l1, l2, r1, r2 = map(int, args.split(','))
    left = min(l1, l2)

    name_text = fund['series_name']
    matched_text = fund['fund_text']
    name_text_alphanum = re.sub(r'[^A-Z0-9]', '', name_text.upper())
    matched_text_alphanum = re.sub(r'[^A-Z0-9]', '', matched_text.upper())

    aligned_name = (
        ' ' * (l1 - left) + name_text_alphanum[:l2] +
        f"<b>{name_text_alphanum[l2:l2+length]}</b>" +
        name_text_alphanum[l2+length:]
    )
    aligned_matched = (
        ' ' * (l2 - left) + matched_text_alphanum[:l1] +
        f"<b>{matched_text_alphanum[l1:l1+length]}</b>" +
        matched_text_alphanum[l1+length:]
    )

    return aligned_name, aligned_matched
