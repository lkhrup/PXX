from flask import Flask, render_template, request, redirect, url_for
import sqlite3

app = Flask(__name__)

DATABASE = '2018.sqlite'  # Path to your SQLite database file


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


@app.route('/')
def filings_list():
    conn = get_db_connection()
    filings = conn.execute('SELECT DISTINCT cik, display_name FROM filings').fetchall()
    conn.close()
    return render_template('filings.html', filings=filings)


@app.route('/filing/<string:cik>')
def filing_funds(cik):
    conn = get_db_connection()

    # Fetch the specific filing info
    filing = conn.execute('SELECT * FROM filings WHERE cik = ?', (cik,)).fetchone()

    # Fetch funds related to the selected filing's CIK
    funds = conn.execute('SELECT * FROM funds WHERE cik = ?', (cik,)).fetchall()

    # Fetch the previous and next CIKs
    previous_filing = conn.execute(
        'SELECT * FROM filings WHERE cik < ? ORDER BY cik DESC LIMIT 1', (cik,)
    ).fetchone()
    next_filing = conn.execute(
        'SELECT * FROM filings WHERE cik > ? ORDER BY cik ASC LIMIT 1', (cik,)
    ).fetchone()

    conn.close()
    return render_template('funds.html', funds=funds, filing=filing,
                           previous_filing=previous_filing, next_filing=next_filing)


@app.route('/toggle_fund', methods=['POST'])
def toggle_fund():
    data = request.get_json()
    fund_id = data['id']
    cik = data['cik']

    conn = get_db_connection()

    # Get the current value of the disabled flag for the specified fund
    fund = conn.execute('SELECT disabled FROM funds WHERE id = ? AND cik = ?', (fund_id, cik)).fetchone()

    # Toggle the disabled flag
    new_disabled_value = not fund['disabled']

    # Update the database
    conn.execute('UPDATE funds SET disabled = ? WHERE id = ?', (new_disabled_value, fund_id))
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

    # Fetch the current status of the first fund in the range to determine the action (enable/disable)
    first_fund = conn.execute('SELECT disabled FROM funds WHERE id = ? AND cik = ?', (first_id, cik)).fetchone()
    new_disabled_value = not first_fund['disabled']  # Toggle all to the opposite of the first one

    # Update all funds in the specified range
    conn.execute('UPDATE funds SET disabled = ? WHERE id BETWEEN ? AND ? AND cik = ?',
                 (new_disabled_value, first_id, last_id, cik))
    conn.commit()
    conn.close()

    return '', 204  # No Content response


if __name__ == '__main__':
    app.run(debug=True)
