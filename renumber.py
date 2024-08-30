import sqlite3

# Connect to the SQLite database (replace 'your_database.db' with your database file)
conn = sqlite3.connect('2018-final.sqlite')
cursor = conn.cursor()

# Fetch all unique cik values
cursor.execute("SELECT DISTINCT cik FROM funds")
cik_values = cursor.fetchall()

# Loop through each cik group
for (cik,) in cik_values:
    # Fetch all rows for the current cik, ordered by first_line
    cursor.execute("SELECT id FROM funds WHERE cik = ? ORDER BY first_line", (cik,))
    rows = cursor.fetchall()
    
    # Renumber ordinals
    for ordinal, (row_id,) in enumerate(rows, start=1):
        cursor.execute("UPDATE funds SET ordinal = ? WHERE id = ?", (ordinal, row_id))

# Commit changes and close the connection
conn.commit()
conn.close()

