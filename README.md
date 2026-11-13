
# Finlumiq

AI-powered student financial management platform that helps students track expenses, manage budgets, monitor college fees, set savings goals, and make smarter financial decisions.
## Features

- Register, log in and log out (passwords are hashed, never stored as plain text)
- Add, view, edit and delete expenses (full CRUD)
- Monthly budget with a progress bar and an 80% warning
- Category pie chart and monthly trend line (Chart.js)
- Filter by month and download expenses as CSV
- Dark mode and a responsive layout for phones

## Tech stack

- **Frontend:** HTML, CSS, JavaScript (no framework)
- **Backend:** Python, Flask
- **Database:** MySQL / MariaDB

## Setup

### 1. Requirements

Python 3.10+ and MySQL (for example XAMPP).

### 2. Database

Start MySQL, then run `backend/schema.sql` in phpMyAdmin (SQL tab) or MySQL Workbench.

### 3. Backend

```powershell
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Open `backend/.env`, set your database details, and create a secret key:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Paste the result as `SECRET_KEY`, then start the API:

```powershell
python app.py
```

It runs at `http://127.0.0.1:5000`.

### 4. Frontend

In a second terminal, from the project's main folder:

```powershell
python -m http.server 8000 --bind 127.0.0.1
```

Open `http://127.0.0.1:8000` (use `127.0.0.1`, not `localhost`).

## API overview

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/auth/register` | Create an account |
| POST | `/api/auth/login` | Log in |
| POST | `/api/auth/logout` | Log out |
| GET | `/api/auth/me` | Current user |
| GET/POST | `/api/expenses` | List / add expenses |
| PUT/DELETE | `/api/expenses/<id>` | Edit / delete an expense |
| GET/PUT | `/api/budget` | Read / save the monthly budget |

## Limitations

This is a learning project for local use. A public deployment would also need HTTPS, secure cookies, rate limiting on login, password reset, and a production server instead of Flask's debug server.

# Finlumiq
AI-powered student financial management platform

