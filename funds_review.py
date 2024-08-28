import os
import sqlite3

from flask import Flask, render_template, make_response, redirect, url_for
from flask import request
from unpoly.up import Unpoly

import find_fund_names
from flask_adapter import FlaskAdapter
from utils import align_texts

DATABASE = '2018.sqlite'  # Path to your SQLite database file


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


app = Flask(__name__)


@app.before_request
def before_request():
    # Initialize Unpoly with the FlaskAdapter for each request
    adapter = FlaskAdapter()
    request.up = Unpoly(adapter)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/update-content')
def load_partial():
    content = render_template('partials/content.html')
    response = make_response(content)
    response.headers['X-Up-Target'] = 'up-main'  # Specify the update target
    return response


@app.route('/filings/<string:cik>')
def filing_funds(cik):
    conn = get_db_connection()

    # Fetch the specific filing info
    filing = conn.execute('SELECT * FROM filings WHERE cik = ?', (cik,)).fetchone()

    # Fetch funds related to the selected filing's CIK
    funds = conn.execute('SELECT * FROM funds WHERE cik = ? ORDER BY first_line', (cik,)).fetchall()

    # Fetch the previous and next CIKs
    previous_filing = conn.execute(
        'SELECT * FROM filings WHERE cik < ? ORDER BY cik DESC LIMIT 1', (cik,)
    ).fetchone()
    next_filing = conn.execute(
        'SELECT * FROM filings WHERE cik > ? ORDER BY cik ASC LIMIT 1', (cik,)
    ).fetchone()

    conn.close()

    # Process text alignment in Python
    processed_funds = []
    for fund in funds:
        name, matched = align_texts(fund)
        processed_fund = dict(fund)
        processed_fund['aligned_name'] = name
        processed_fund['aligned_matched'] = matched
        processed_fund['method'] = fund['method'].replace(';', '\n')
        processed_funds.append(processed_fund)

    return render_template(
        'funds.html',
        funds=processed_funds,
        filing=filing,
        previous_filing=previous_filing,
        next_filing=next_filing,
        processed=request.args.get('processed')
    )


@app.route('/filings/<string:cik>/process')
def process_filing(cik):
    conn = get_db_connection()
    filing = conn.execute('SELECT * FROM filings WHERE cik = ?', (cik,)).fetchone()
    conn.execute('DELETE FROM funds WHERE cik = ?', (cik,))
    filename = os.path.join('filings', filing['filename'])
    find_fund_names.process_filing(conn, cik, filename, False)
    conn.close()
    return redirect(url_for('filing_funds', cik=cik, processed=True))


@app.route('/filings')
def filings_list():
    conn = get_db_connection()
    # Get filings (CIK, display name) and count SKIP, KEEP, and flagged funds
    filings = conn.execute("""
        SELECT filings.cik, display_name, skip_count, keep_count, flagged_count
          FROM filings, (
            SELECT cik,
                   COUNT(CASE WHEN state = 'SKIP' THEN 1 END) AS skip_count,
                   COUNT(CASE WHEN state = 'KEEP' THEN 1 END) AS keep_count,
                   COUNT(CASE WHEN flagged THEN 1 END) AS flagged_count
              FROM funds
              GROUP BY cik
          ) AS fund_counts
          WHERE filings.cik = fund_counts.cik
          ORDER BY filings.cik
        """).fetchall()
    conn.close()
    return render_template('filings.html', filings=filings)


@app.route('/toggle_fund_state', methods=['POST'])
def toggle_fund_state():
    data = request.get_json()
    fund_id = data['id']

    conn = get_db_connection()
    conn.execute("""
        UPDATE funds SET state = (
            CASE WHEN state = 'KEEP' THEN 'SKIP'
                 WHEN state = 'SKIP' THEN 'KEEP'
                 ELSE state
            END)
        WHERE id = ?
        """, (fund_id,))
    conn.commit()
    conn.close()

    return '', 204  # No Content response


@app.route('/toggle_fund_flagged', methods=['POST'])
def toggle_fund_flagged():
    data = request.get_json()
    fund_id = data['id']
    value = data['value']

    conn = get_db_connection()
    conn.execute("""
        UPDATE funds SET flagged = NOT flagged WHERE id = ? AND flagged = ?
        """, (fund_id, value))
    conn.commit()
    conn.close()

    return '', 204  # No Content response


@app.route('/toggle_range', methods=['POST'])
def toggle_range():
    data = request.get_json()
    cik = data['cik']
    first_id = data['first_id']
    last_id = data['last_id']

    conn = get_db_connection()

    # Identify the affected line range
    first = conn.execute('SELECT first_line AS line FROM funds WHERE id = ? AND cik = ?', (first_id, cik)).fetchone()
    last = conn.execute('SELECT last_line AS line FROM funds WHERE id = ? AND cik = ?', (last_id, cik)).fetchone()

    # Update all funds in the specified range
    conn.execute("""
        UPDATE funds
        SET state = (
            CASE WHEN state = 'KEEP' THEN 'SKIP'
                 WHEN state = 'SKIP' THEN 'KEEP'
                 ELSE state
            END)
        WHERE cik = ? AND first_line BETWEEN ? AND ?""",
                 (cik, first['line'], last['line']))
    conn.commit()
    conn.close()

    return '', 204  # No Content response

@app.route('/skip_range', methods=['POST'])
def skip_range():
    data = request.get_json()
    cik = data['cik']
    first_id = data['first_id']
    last_id = data['last_id']

    conn = get_db_connection()

    # Identify the affected line range
    first = conn.execute('SELECT first_line AS line FROM funds WHERE id = ? AND cik = ?', (first_id, cik)).fetchone()
    last = conn.execute('SELECT last_line AS line FROM funds WHERE id = ? AND cik = ?', (last_id, cik)).fetchone()

    # Update all funds in the specified range
    conn.execute("""
        UPDATE funds
        SET state = 'SKIP'
        WHERE cik = ? AND first_line BETWEEN ? AND ?""",
                 (cik, first['line'], last['line']))
    conn.commit()
    conn.close()

    return '', 204

@app.route('/keep_range', methods=['POST'])
def keep_range():
    data = request.get_json()
    cik = data['cik']
    first_id = data['first_id']
    last_id = data['last_id']

    conn = get_db_connection()

    # Identify the affected line range
    first = conn.execute('SELECT first_line AS line FROM funds WHERE id = ? AND cik = ?', (first_id, cik)).fetchone()
    last = conn.execute('SELECT last_line AS line FROM funds WHERE id = ? AND cik = ?', (last_id, cik)).fetchone()

    # Update all funds in the specified range
    conn.execute("""
        UPDATE funds
        SET state = 'KEEP'
        WHERE cik = ? AND first_line BETWEEN ? AND ?""",
                 (cik, first['line'], last['line']))
    conn.commit()
    conn.close()

    return '', 204


if __name__ == '__main__':
    app.run(debug=True)
