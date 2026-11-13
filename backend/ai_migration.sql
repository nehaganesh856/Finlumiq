-- Finlumiq Phase 6: AI Assistant conversation storage
-- Select the existing expense_tracker database before running this script.
-- This migration only creates new AI tables; it does not modify financial records.

USE expense_tracker;

CREATE TABLE IF NOT EXISTS ai_conversations (
    id BIGINT NOT NULL AUTO_INCREMENT,
    user_id INT NOT NULL,
    title VARCHAR(120) NOT NULL DEFAULT 'New conversation',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_ai_conversations_user_updated (user_id, updated_at),
    CONSTRAINT fk_ai_conversations_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ai_messages (
    id BIGINT NOT NULL AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    user_id INT NOT NULL,
    role ENUM('user', 'assistant') NOT NULL,
    content MEDIUMTEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_ai_messages_conversation (conversation_id, id),
    KEY idx_ai_messages_user (user_id),
    CONSTRAINT fk_ai_messages_conversation
        FOREIGN KEY (conversation_id) REFERENCES ai_conversations(id) ON DELETE CASCADE,
    CONSTRAINT fk_ai_messages_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SELECT 'Phase 6 AI tables are ready.' AS status;
