-- Finlumiq Performance Indexes Migration
-- Run once against the TiDB Cloud database (expense_tracker_fixed).
-- Uses IF NOT EXISTS / CREATE INDEX ... IF NOT EXISTS (TiDB supports this).
-- Safe to re-run: each statement only adds the index if it does not already exist.

-- expenses: cover the most common access pattern (user + date range)
-- This eliminates the full table scan that causes the 16-second /api/expenses response.
CREATE INDEX IF NOT EXISTS idx_expenses_user_date
  ON expenses (user_id, expense_date DESC);

-- income: same pattern
CREATE INDEX IF NOT EXISTS idx_income_user_date
  ON income (user_id, income_date DESC);

-- categories: speed up the WHERE user_id IS NULL OR user_id = ? lookup
-- (Already has user_id in the base schema; this composite adds grp for ORDER BY)
CREATE INDEX IF NOT EXISTS idx_categories_user_grp
  ON categories (user_id, grp, name);

-- college_fees: due_date range queries used by /api/dashboard and /api/reminders
CREATE INDEX IF NOT EXISTS idx_fees_user_due
  ON college_fees (user_id, due_date ASC);

-- savings_goals: status + target_date ordering
CREATE INDEX IF NOT EXISTS idx_goals_user_status
  ON savings_goals (user_id, status, target_date ASC);

-- scholarships: deadline ordering
CREATE INDEX IF NOT EXISTS idx_scholarships_user_deadline
  ON scholarships (user_id, application_deadline ASC);

-- ai_messages: conversation listing is ORDER BY id DESC
CREATE INDEX IF NOT EXISTS idx_ai_messages_conv_user
  ON ai_messages (conversation_id, user_id, id DESC);

-- ai_conversations: listing is ORDER BY updated_at DESC
CREATE INDEX IF NOT EXISTS idx_ai_conversations_user_updated
  ON ai_conversations (user_id, updated_at DESC);
