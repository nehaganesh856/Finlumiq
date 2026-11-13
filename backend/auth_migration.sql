-- ============================================================
-- Auth Upgrade Migration — Finlumiq
-- Run this in phpMyAdmin: select expense_tracker → SQL tab → Go
-- SAFE: uses ALTER ... IF NOT EXISTS / IF EXISTS patterns
-- Does NOT drop or truncate any existing table.
-- ============================================================

USE expense_tracker;

-- -------------------------------------------------------
-- 1. Add new columns to users table (safe ALTER)
-- -------------------------------------------------------

-- email_verified: 0 = unverified, 1 = verified
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS email_verified   TINYINT(1)   NOT NULL DEFAULT 0 AFTER password_hash,
  ADD COLUMN IF NOT EXISTS google_id        VARCHAR(100) DEFAULT NULL AFTER email_verified,
  ADD COLUMN IF NOT EXISTS updated_at       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
                                            ON UPDATE CURRENT_TIMESTAMP AFTER created_at;

-- -------------------------------------------------------
-- 2. Auto-verify ALL existing users
--    (they registered before email verification existed,
--     so we trust them and prevent lock-out)
-- -------------------------------------------------------
UPDATE users SET email_verified = 1 WHERE email_verified = 0;

-- -------------------------------------------------------
-- 3. Create auth_tokens table for email verify + pw reset
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS auth_tokens (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  user_id     INT          NOT NULL,
  token_hash  VARCHAR(64)  NOT NULL UNIQUE COMMENT 'SHA-256 hex of the raw token',
  purpose     ENUM('email_verify','password_reset') NOT NULL,
  expires_at  DATETIME     NOT NULL,
  used_at     DATETIME     DEFAULT NULL COMMENT 'Set when token is consumed',
  created_at  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_auth_tokens_user
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_token_hash    (token_hash),
  INDEX idx_user_purpose  (user_id, purpose),
  INDEX idx_expires_at    (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -------------------------------------------------------
-- 4. Verification: show results
-- -------------------------------------------------------
SELECT 'users table columns:' AS info;
DESCRIBE users;

SELECT 'auth_tokens table created:' AS info;
DESCRIBE auth_tokens;

SELECT CONCAT('Total users: ', COUNT(*), ' | Verified: ', SUM(email_verified)) AS summary
FROM users;
