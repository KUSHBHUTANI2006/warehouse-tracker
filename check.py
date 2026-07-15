import sqlite3
conn = sqlite3.connect('warehouse.db')
c = conn.cursor()
c.execute("SELECT * FROM products")
c.execute("SELECT * FROM batches")
print(c.fetchall())
print(c.fetchall())
conn.close()