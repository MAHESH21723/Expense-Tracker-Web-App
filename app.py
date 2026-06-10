import os
import time
import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Import database methods
from database.models import (
    init_db,
    add_transaction,
    delete_transaction,
    get_all_transactions,
    get_summary,
    get_db_connection
)

app = Flask(__name__)
app.secret_key = 'super_secret_expense_tracker_key'

# Initialize database on startup
with app.app_context():
    init_db()

def generate_charts():
    """
    Query database via Pandas and dynamically generate Matplotlib
    reports, styled to match the dark glassmorphic UI.
    """
    charts_dir = os.path.join(app.static_folder, 'charts')
    os.makedirs(charts_dir, exist_ok=True)
    
    conn = get_db_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM transactions", conn)
    finally:
        conn.close()
        
    if df.empty:
        return False
        
    # Standardize data types
    df['amount'] = df['amount'].astype(float)
    df['date'] = pd.to_datetime(df['date'])
    
    has_expense = not df[df['type'] == 'Expense'].empty
    
    # Define color palette matching UI styles
    color_map = {
        'Food': '#fca5a5',
        'Transport': '#93c5fd',
        'Shopping': '#fbcfe8',
        'Bills': '#fbbf24',
        'Entertainment': '#d8b4fe',
        'Education': '#22d3ee',
        'Healthcare': '#5eead4',
        'Others': '#d1d5db'
    }
    
    # 1. Expense by Category (Pie Chart)
    if has_expense:
        expense_df = df[df['type'] == 'Expense']
        cat_grouped = expense_df.groupby('category')['amount'].sum().reset_index()
        cat_grouped = cat_grouped.sort_values(by='amount', ascending=False)
        
        fig, ax = plt.subplots(figsize=(6, 5), facecolor='none')
        ax.set_facecolor('none')
        
        colors = [color_map.get(cat, '#a78bfa') for cat in cat_grouped['category']]
        
        # Donut style pie chart
        wedges, texts, autotexts = ax.pie(
            cat_grouped['amount'], 
            labels=cat_grouped['category'], 
            autopct='%1.1f%%',
            startangle=140, 
            colors=colors,
            textprops=dict(color="#f3f4f6", fontsize=10),
            wedgeprops=dict(width=0.4, edgecolor='none')
        )
        
        # Make labels bold and stand out
        for autotext in autotexts:
            autotext.set_color('#111827')
            autotext.set_fontsize(9)
            autotext.set_weight('bold')
            
        ax.set_title('Expenses by Category', color='#ffffff', fontsize=14, pad=15, weight='bold')
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'category_pie.png'), transparent=True, dpi=150)
        plt.close(fig)
        
    # 2. Monthly Trend (Line Chart)
    if has_expense:
        expense_df = df[df['type'] == 'Expense'].copy()
        # Extract Year-Month
        expense_df['month'] = expense_df['date'].dt.to_period('M')
        monthly_expense = expense_df.groupby('month')['amount'].sum().reset_index()
        monthly_expense = monthly_expense.sort_values('month')
        monthly_expense['month_str'] = monthly_expense['month'].astype(str)
        
        fig, ax = plt.subplots(figsize=(6, 4.5), facecolor='none')
        ax.set_facecolor('none')
        
        ax.plot(
            monthly_expense['month_str'], 
            monthly_expense['amount'], 
            marker='o', 
            linewidth=3, 
            color='#8b5cf6', 
            markerfacecolor='#c084fc', 
            markeredgecolor='white', 
            markersize=8
        )
        
        ax.grid(color=(1.0, 1.0, 1.0, 0.08), linestyle='--', linewidth=0.8)
        ax.spines['bottom'].set_color((1.0, 1.0, 1.0, 0.2))
        ax.spines['left'].set_color((1.0, 1.0, 1.0, 0.2))
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        
        ax.tick_params(colors='#f3f4f6', labelsize=9)
        ax.set_title('Monthly Expense Trend', color='#ffffff', fontsize=14, pad=15, weight='bold')
        ax.set_ylabel('Amount (₹)', color='#9ca3af', fontsize=10)
        
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'monthly_trend.png'), transparent=True, dpi=150)
        plt.close(fig)
        
    # 3. Income vs Expense (Bar Chart)
    df['month'] = df['date'].dt.to_period('M')
    monthly_data = df.groupby(['month', 'type'])['amount'].sum().unstack(fill_value=0.0).reset_index()
    monthly_data = monthly_data.sort_values('month')
    monthly_data['month_str'] = monthly_data['month'].astype(str)
    
    if 'Income' not in monthly_data.columns:
        monthly_data['Income'] = 0.0
    if 'Expense' not in monthly_data.columns:
        monthly_data['Expense'] = 0.0
        
    fig, ax = plt.subplots(figsize=(6, 4.5), facecolor='none')
    ax.set_facecolor('none')
    
    x = range(len(monthly_data))
    width = 0.35
    
    ax.bar([i - width/2 for i in x], monthly_data['Income'], width, label='Income', color='#10b981', alpha=0.85)
    ax.bar([i + width/2 for i in x], monthly_data['Expense'], width, label='Expense', color='#f43f5e', alpha=0.85)
    
    ax.set_xticks(x)
    ax.set_xticklabels(monthly_data['month_str'])
    
    ax.grid(color=(1.0, 1.0, 1.0, 0.08), linestyle='--', linewidth=0.8)
    ax.spines['bottom'].set_color((1.0, 1.0, 1.0, 0.2))
    ax.spines['left'].set_color((1.0, 1.0, 1.0, 0.2))
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    ax.tick_params(colors='#f3f4f6', labelsize=9)
    ax.set_title('Monthly Income vs Expenses', color='#ffffff', fontsize=14, pad=15, weight='bold')
    ax.set_ylabel('Amount (₹)', color='#9ca3af', fontsize=10)
    
    legend = ax.legend(facecolor='#1e192d', edgecolor=(1.0, 1.0, 1.0, 0.1), loc='upper right')
    for text in legend.get_texts():
        text.set_color('#f3f4f6')
        
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'income_vs_expense.png'), transparent=True, dpi=150)
    plt.close(fig)
    
    return True

@app.route('/')
def dashboard():
    # Capture GET query params for filter / search
    search = request.args.get('search')
    category = request.args.get('category')
    trans_type = request.args.get('type')
    sort_by = request.args.get('sort_by', 'date')
    sort_order = request.args.get('sort_order', 'desc')
    
    # Get filtered transactions
    transactions = get_all_transactions(
        search=search,
        category=category,
        trans_type=trans_type,
        sort_by=sort_by,
        sort_order=sort_order
    )
    
    summary = get_summary()
    
    # Retain filter params in input fields
    filters = {
        'search': search,
        'category': category,
        'type': trans_type,
        'sort_by': sort_by,
        'sort_order': sort_order
    }
    
    return render_template(
        'index.html', 
        transactions=transactions, 
        summary=summary, 
        filters=filters,
        active_page='dashboard'
    )

@app.route('/add-income', methods=['GET', 'POST'])
def add_income():
    if request.method == 'POST':
        date = request.form.get('date')
        category = request.form.get('category')
        amount = request.form.get('amount')
        description = request.form.get('description')
        
        # Validation checks
        if not date or not category or not amount:
            flash("All fields except description are required.", "danger")
            return render_template('add_income.html', active_page='add_income')
            
        try:
            amt = float(amount)
            if amt <= 0:
                flash("Invalid Amount: Amount must be greater than zero.", "danger")
                return render_template('add_income.html', active_page='add_income')
        except ValueError:
            flash("Invalid Amount: Amount must be a valid number.", "danger")
            return render_template('add_income.html', active_page='add_income')
            
        try:
            datetime.datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            flash("Invalid Date: Must be a valid date.", "danger")
            return render_template('add_income.html', active_page='add_income')
            
        add_transaction(date, 'Income', category, amt, description)
        flash("Income Added Successfully!", "success")
        return redirect(url_for('dashboard'))
        
    return render_template('add_income.html', active_page='add_income')

@app.route('/add-expense', methods=['GET', 'POST'])
def add_expense():
    if request.method == 'POST':
        date = request.form.get('date')
        category = request.form.get('category')
        amount = request.form.get('amount')
        description = request.form.get('description')
        
        # Validation checks
        if not date or not category or not amount:
            flash("All fields except description are required.", "danger")
            return render_template('add_expense.html', active_page='add_expense')
            
        try:
            amt = float(amount)
            if amt <= 0:
                flash("Invalid Amount: Amount must be greater than zero.", "danger")
                return render_template('add_expense.html', active_page='add_expense')
        except ValueError:
            flash("Invalid Amount: Amount must be a valid number.", "danger")
            return render_template('add_expense.html', active_page='add_expense')
            
        try:
            datetime.datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            flash("Invalid Date: Must be a valid date.", "danger")
            return render_template('add_expense.html', active_page='add_expense')
            
        add_transaction(date, 'Expense', category, amt, description)
        flash("Expense Added Successfully!", "success")
        return redirect(url_for('dashboard'))
        
    return render_template('add_expense.html', active_page='add_expense')

@app.route('/delete/<int:transaction_id>', methods=['POST'])
def delete(transaction_id):
    delete_transaction(transaction_id)
    flash("Transaction Deleted Successfully!", "success")
    return redirect(url_for('dashboard'))

@app.route('/reports')
def reports():
    conn = get_db_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM transactions", conn)
    finally:
        conn.close()
        
    summary = get_summary()
    
    # Calculate savings percentage
    total_inc = summary['total_income']
    total_exp = summary['total_expense']
    
    if total_inc > 0:
        savings_pct = (summary['savings'] / total_inc) * 100
    else:
        # If no income but has expenses, savings pct is 0. If no transactions at all, it's 0.
        savings_pct = 0.0
        
    # Cap between 0 and 100 for presentation
    summary['savings_percentage'] = max(0.0, min(100.0, savings_pct))
    
    # Process Category-wise data for expenses using Pandas
    category_data = []
    has_data = not df.empty
    
    if has_data:
        expense_df = df[df['type'] == 'Expense'].copy()
        if not expense_df.empty:
            expense_df['amount'] = expense_df['amount'].astype(float)
            cat_totals = expense_df.groupby('category')['amount'].sum().reset_index()
            cat_totals = cat_totals.sort_values(by='amount', ascending=False)
            total_expense_amount = cat_totals['amount'].sum()
            
            for _, row in cat_totals.iterrows():
                percentage = (row['amount'] / total_expense_amount * 100) if total_expense_amount > 0 else 0.0
                category_data.append({
                    'category': row['category'],
                    'amount': row['amount'],
                    'percentage': percentage
                })
                
        # Generate chart images in static/charts
        generate_charts()
        
    timestamp = int(time.time())
    
    return render_template(
        'reports.html', 
        summary=summary, 
        category_data=category_data, 
        has_data=has_data,
        timestamp=timestamp,
        active_page='reports'
    )

if __name__ == '__main__':
    app.run(debug=True, port=5000)
