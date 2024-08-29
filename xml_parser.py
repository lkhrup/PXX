import io
import os
import re
from xml.etree import ElementTree
import traceback


def match_security(text: str) -> bool:
    # Case-insensitive, ignore non-alphanum
    text = text.upper()
    text = re.sub(r'[^A-Z0-9]', '', text)
    return text == "TESLAINC"

def match_vote(text: str) -> bool:
    """
    Return True if the vote is relevant, based on its description.
    We exclude irrelevant votes rather than attempting to match all relevant votes
    since there are many different formulations of the proposal.
    """
    return not re.search(
        r'stockholder proposal|shareholder proposal|s/h proposal|appointment|james murdoch|kimbal musk|non.*binding|delaware|metrics|director|harassment|electromagnetic|collective|non-interference|simple majority|sustainability|moratorium|miscellaneous|auditor',
        text, re.IGNORECASE)


def extract_text(element: ElementTree.Element) -> str:
    if element is None or element.text is None:
        return ""
    return element.text


def extract_number(element: ElementTree.Element) -> float | None:
    text = extract_text(element)
    if not text:
        return None
    # Remove thousands separator.
    # Parse as float, the filings have non-integer values.
    # TODO: 0001109228-0001420506-24-001838.txt contains "24696.540000|249.460000" as a value.
    return float(text.replace(',', ''))


def parse_proxy_vote_table(filename: str, root: ElementTree.Element):
    # XML namespace
    ns = {'inf': 'http://www.sec.gov/edgar/document/npxproxy/informationtable'}

    # Each vote is held in a proxyTable element
    for proxy_table in root.findall('inf:proxyTable', ns):
        # The issuerName element contains the security name
        issuer_name = proxy_table.find('inf:issuerName', ns)
        if issuer_name is None or not match_security(issuer_name.text):
            continue

        # The vote element contains the vote records
        vote = proxy_table.find('inf:vote', ns)
        if not vote:
            continue
        vote_records = vote.findall('inf:voteRecord', ns)
        if not vote_records:
            continue

        # Exclude votes from 2023-05-16
        meeting_date = proxy_table.find('inf:meetingDate', ns)
        if meeting_date.text == '05/16/2023':
            continue

        # Extract the number of shares voted, skip if 0
        shares_voted = extract_number(proxy_table.find('inf:sharesVoted', ns))
        if shares_voted is None or shares_voted == 0:
            continue

        # Initialize counters for FOR and AGAINST votes
        shares_for = 0
        shares_against = 0
        for vote_record in vote_records:
            how_voted = vote_record.find('inf:howVoted', ns)
            shares_voted_record = extract_number(vote_record.find('inf:sharesVoted', ns))
            if how_voted is not None and shares_voted_record is not None:
                if how_voted.text == "FOR":
                    shares_for += shares_voted_record
                elif how_voted.text == "AGAINST":
                    shares_against += shares_voted_record

        # Determine the final vote decision
        if shares_for > shares_against:
            final_vote = "FOR"
        else:
            final_vote = "AGAINST"

        # Build the vote description, collecting information for all the places that may contain it.
        vote_description = extract_text(proxy_table.find('inf:voteDescription', ns))
        vote_other_info = extract_text(proxy_table.find('inf:voteOtherInfo', ns))
        vote_categories = []
        for category in proxy_table.findall('inf:voteCategory', ns):
            vote_categories.append(extract_text(category))
        # Filter out unwanted votes
        all_text = " ".join([vote_description, vote_other_info] + vote_categories)
        if not match_vote(all_text):
            continue

        # Vote series is a key corresponding to the fund.
        # TODO: look up in the filing's edgarSubmission section.
        vote_series = proxy_table.find('inf:voteSeries', ns)

        # Ensure all elements are found before printing
        if vote_series is None or meeting_date is None or vote_description is None:
            # TODO: warn that some information is missing, we may want to investigate
            continue

        # TODO: proper CSV formatting
        print(f'{filename};{vote_series.text};{meeting_date.text};{shares_voted};{final_vote};"{all_text}"')


def process_filing(filename: str, file_path: str):

    # Read the file
    with open(file_path, 'r') as file:
        content = file.read()

    # Scan the file for <XML> and </XML> delimiters
    lines = content.split('\n')
    xml_ranges = []
    xml_start = None
    for i, line in enumerate(lines):
        if xml_start is None and line == '<XML>':
            xml_start = i
        elif xml_start is not None and line == '</XML>':
            xml_ranges.append((xml_start, i))
            xml_start = None

    # Parse the XML sections
    for start, end in xml_ranges:

        xml_start = start + 1  # Skip <XML> line
        source = "\n".join(lines[xml_start:end])

        # Fix a bad entity
        source = re.sub(r'&#2;', ' ', source)

        # Parse XML and dispatch based on root element
        tree = ElementTree.parse(io.StringIO(source))
        root = tree.getroot()
        if root.tag == '{http://www.sec.gov/edgar/npx}edgarSubmission':
            # TODO: parse_edgar_submission(root) to extract metadata
            continue
        elif root.tag == '{http://www.sec.gov/edgar/document/npxproxy/informationtable}proxyVoteTable':
            parse_proxy_vote_table(filename, root)
        else:
            print(f"warning: unknown element {root.tag}")


if __name__ == '__main__':
    for filename in os.listdir('filings'):
        if filename.endswith('.txt'):
            try:
                process_filing(filename, os.path.join('filings', filename))
            except Exception as e:
                print(f"Error processing {filename}: {e}")
                traceback.print_exception(None, e, e.__traceback__)
