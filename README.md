# Personal Expense Tracker

A web-based personal finance management application developed using **Python Flask**, **SQLite**, **Pandas**, and **Matplotlib** with a custom high-fidelity **glassmorphism user interface** built on top of **Bootstrap 5**.

## Features

- **Dashboard Summary**: Monitor total income, total expenses, and net savings dynamically.
- **Glassmorphism UI**: Beautiful, interactive cards, toast notifications, responsive design, custom badges, and interactive elements.
- **CRUD Operations**: Record income and expense transactions with instant database updates.
- **Flexible Filters & Sorting**: Search description fields, select category, filter by transaction type, and sort data by date or amount instantly.
- **Dynamic Analysis (Pandas)**: Calculates real-time savings percentage and ranks category-wise spending.
- **Beautiful Visualizations (Matplotlib)**: Custom dark-themed charts displaying:
  1. Donut chart showing category-wise expense distribution.
  2. Line chart showing monthly expense trends.
  3. Grouped bar chart comparing month-over-month income vs expenses.
- **Safe Delete Modal**: Prevent accidental transaction deletions with double-check modal verification.

## Technology Stack

- **Frontend**: HTML5, CSS3 (Glassmorphism overrides), Bootstrap 5, FontAwesome 6
- **Backend**: Python 3.x, Flask
- **Database**: SQLite (`expense_tracker.db`)
- **Data Engine**: Pandas
- **Visualization**: Matplotlib

## Installation and Setup

1. **Clone or Navigate to the Directory**:
   ```bash
   cd "d:/python project/Expense Tracker Web App"
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the Application**:
   ```bash
   python app.py
   ```

4. **Access the App**:
   Open [http://localhost:5000](http://localhost:5000) in your web browser.

## Database Design (`transactions` Table)

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Primary Key (Autoincrement) |
| `date` | TEXT | Transaction date in `YYYY-MM-DD` |
| `type` | TEXT | `Income` or `Expense` |
| `category` | TEXT | E.g. Salary, Food, Travel, Shopping, Bills |
| `amount` | REAL | Numerical currency amount |
| `description` | TEXT | Optional transaction details |
