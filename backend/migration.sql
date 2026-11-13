-- ============================================================
-- Smart Student Expense Tracker — Full Database Migration
-- Run this in phpMyAdmin: select expense_tracker database,
-- then paste into the SQL tab and click Go.
-- ============================================================

USE expense_tracker;

-- -------------------------------------------------------
-- Ensure base tables exist (safe to run on existing DB)
-- -------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(80) NOT NULL,
  email VARCHAR(120) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT DEFAULT NULL,
  name VARCHAR(40) NOT NULL,
  grp VARCHAR(20) NOT NULL,
  icon VARCHAR(8) NOT NULL DEFAULT '🏷️',
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_categories_user (user_id)
);

-- Fix expenses table: add category_id if it still uses old category VARCHAR column
-- Check first: if category_id column does not exist, add it
SET @col_exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = 'expense_tracker'
  AND TABLE_NAME = 'expenses'
  AND COLUMN_NAME = 'category_id'
);

-- Only add category_id if it doesn't exist (safe migration)
-- Since MySQL doesn't support IF in plain SQL outside procedures,
-- we use CREATE TABLE IF NOT EXISTS approach for new tables only.
-- For expenses, run this ALTER manually if needed:
--
-- ALTER TABLE expenses ADD COLUMN category_id INT NOT NULL AFTER amount;
-- ALTER TABLE expenses ADD FOREIGN KEY (category_id) REFERENCES categories(id);
-- ALTER TABLE expenses DROP COLUMN category;
--
-- If your expenses table already has category_id, skip the above.

CREATE TABLE IF NOT EXISTS expenses (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  title VARCHAR(100) NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  category_id INT NOT NULL,
  expense_date DATE NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (category_id) REFERENCES categories(id),
  INDEX idx_expenses_user (user_id),
  INDEX idx_expenses_date (expense_date)
);

CREATE TABLE IF NOT EXISTS income (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  source VARCHAR(50) NOT NULL,
  income_date DATE NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_income_user (user_id)
);

CREATE TABLE IF NOT EXISTS user_budget (
  user_id INT PRIMARY KEY,
  amount DECIMAL(10,2) NOT NULL DEFAULT 0,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS group_budgets (
  user_id INT NOT NULL,
  grp VARCHAR(20) NOT NULL,
  amount DECIMAL(10,2) NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, grp),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- -------------------------------------------------------
-- Seed default categories (only if categories table is empty)
-- -------------------------------------------------------
INSERT IGNORE INTO categories (id, user_id, name, grp, icon) VALUES
(1,  NULL, 'Canteen',          'Food',      '🍽'),
(2,  NULL, 'Restaurant',       'Food',      '🍜'),
(3,  NULL, 'Groceries',        'Food',      '🛒'),
(4,  NULL, 'Snacks',           'Food',      '🍿'),
(5,  NULL, 'Clothes',          'Shopping',  '👕'),
(6,  NULL, 'Stationery',       'Shopping',  '📚'),
(7,  NULL, 'Electronics',      'Shopping',  '💻'),
(8,  NULL, 'Books',            'College',   '📖'),
(9,  NULL, 'Lab Fees',         'College',   '🔬'),
(10, NULL, 'Tuition',          'College',   '🎓'),
(11, NULL, 'Bus / Auto',       'Transport', '🚌'),
(12, NULL, 'Fuel',             'Transport', '⛽'),
(13, NULL, 'Train / Metro',    'Transport', '🚇'),
(14, NULL, 'Rent',             'Living',    '🏠'),
(15, NULL, 'Utilities',        'Living',    '💡'),
(16, NULL, 'Mobile Recharge',  'Bills',     '📱'),
(17, NULL, 'Internet',         'Bills',     '🌐'),
(18, NULL, 'Movies',           'Fun',       '🎬'),
(19, NULL, 'Games',            'Fun',       '🎮'),
(20, NULL, 'Sports',           'Fun',       '⚽'),
(21, NULL, 'Doctor',           'Health',    '🏥'),
(22, NULL, 'Medicines',        'Health',    '💊'),
(23, NULL, 'Miscellaneous',    'Other',     '📦');

-- -------------------------------------------------------
-- PHASE 3 — Semester Management
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS semesters (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  semester_name VARCHAR(100) NOT NULL,
  semester_number INT NOT NULL,
  academic_year VARCHAR(20) NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  budget DECIMAL(12,2) NOT NULL DEFAULT 0,
  description TEXT,
  status ENUM('Upcoming','Active','Completed') NOT NULL DEFAULT 'Upcoming',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_semesters_user (user_id),
  INDEX idx_semesters_status (status)
);

-- -------------------------------------------------------
-- PHASE 3 — College Fees
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS college_fees (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  semester_id INT DEFAULT NULL,
  fee_title VARCHAR(150) NOT NULL,
  fee_category ENUM('Tuition','Examination','Hostel','Transport','Library','Laboratory','Admission','Other') NOT NULL,
  total_amount DECIMAL(12,2) NOT NULL,
  due_date DATE NOT NULL,
  description TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (semester_id) REFERENCES semesters(id) ON DELETE SET NULL,
  INDEX idx_fees_user (user_id),
  INDEX idx_fees_due (due_date)
);

-- -------------------------------------------------------
-- PHASE 3 — Fee Payments
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS fee_payments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  fee_id INT NOT NULL,
  user_id INT NOT NULL,
  amount_paid DECIMAL(12,2) NOT NULL,
  payment_date DATE NOT NULL,
  payment_method ENUM('Cash','UPI','Bank Transfer','Card','Other') NOT NULL DEFAULT 'Cash',
  transaction_reference VARCHAR(100) DEFAULT NULL,
  remarks TEXT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (fee_id) REFERENCES college_fees(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_payments_fee (fee_id)
);

-- -------------------------------------------------------
-- PHASE 4 — Savings Goals
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS savings_goals (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  goal_title VARCHAR(150) NOT NULL,
  goal_category VARCHAR(80) NOT NULL DEFAULT 'General',
  target_amount DECIMAL(12,2) NOT NULL,
  current_saved_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  start_date DATE NOT NULL,
  target_date DATE DEFAULT NULL,
  description TEXT DEFAULT NULL,
  status ENUM('Active','Completed','Paused','Cancelled') NOT NULL DEFAULT 'Active',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_goals_user (user_id),
  INDEX idx_goals_status (status)
);

-- -------------------------------------------------------
-- PHASE 4 — Savings Transactions
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS savings_transactions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  goal_id INT NOT NULL,
  user_id INT NOT NULL,
  transaction_type ENUM('Deposit','Withdrawal','Correction') NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  transaction_date DATE NOT NULL,
  remarks TEXT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (goal_id) REFERENCES savings_goals(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_txn_goal (goal_id)
);

-- -------------------------------------------------------
-- PHASE 4 — Scholarships
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS scholarships (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  scholarship_name VARCHAR(200) NOT NULL,
  provider VARCHAR(150) DEFAULT NULL,
  category VARCHAR(100) DEFAULT NULL,
  application_date DATE DEFAULT NULL,
  application_deadline DATE DEFAULT NULL,
  expected_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  awarded_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  expected_payment_date DATE DEFAULT NULL,
  status ENUM('Not Applied','Applied','Under Review','Approved','Rejected','Payment Pending','Partially Received','Received') NOT NULL DEFAULT 'Not Applied',
  description TEXT DEFAULT NULL,
  reference_number VARCHAR(100) DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_scholarships_user (user_id),
  INDEX idx_scholarships_deadline (application_deadline)
);

-- -------------------------------------------------------
-- PHASE 4 — Scholarship Payments
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS scholarship_payments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  scholarship_id INT NOT NULL,
  user_id INT NOT NULL,
  amount_received DECIMAL(12,2) NOT NULL,
  payment_date DATE NOT NULL,
  transaction_reference VARCHAR(100) DEFAULT NULL,
  remarks TEXT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (scholarship_id) REFERENCES scholarships(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_schol_payments (scholarship_id)
);

-- -------------------------------------------------------
-- Done! All tables created successfully.
-- -------------------------------------------------------
SELECT 'Migration complete!' AS status;
