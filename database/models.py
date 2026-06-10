import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'expense_tracker.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_transaction(date, trans_type, category, amount, description):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO transactions (date, type, category, amount, description)
        VALUES (?, ?, ?, ?, ?)
    ''', (date, trans_type, category, amount, description))
    conn.commit()
    conn.close()

def delete_transaction(transaction_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM transactions WHERE id = ?', (transaction_id,))
    conn.commit()
    conn.close()

def get_all_transactions(search=None, category=None, trans_type=None, sort_by='date', sort_order='desc'):
    conn = get_db_connection()
    query = 'SELECT * FROM transactions WHERE 1=1'
    params = []
    
    if search:
        query += ' AND (description LIKE ? OR category LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%'])
        
    if category:
        query += ' AND category = ?'
        params.append(category)
        
    if trans_type:
        query += ' AND type = ?'
        params.append(trans_type)
        
    # Safe validation for sorting to prevent SQL injection
    allowed_sort_cols = ['date', 'amount', 'category', 'type', 'id']
    if sort_by not in allowed_sort_cols:
        sort_by = 'date'
        
    if sort_order.lower() not in ['asc', 'desc']:
        sort_order = 'desc'
        
    query += f' ORDER BY {sort_by} {sort_order}'
    
    cursor = conn.cursor()
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_summary():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='Income'")
    total_income = cursor.fetchone()[0] or 0.0
    
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='Expense'")
    total_expense = cursor.fetchone()[0] or 0.0
    
    conn.close()
    
    savings = total_income - total_expense
    return {
        'total_income': total_income,
        'total_expense': total_expense,
        'savings': savings
    }
