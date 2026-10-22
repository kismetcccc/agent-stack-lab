-- Frozen v1 schema from the accepted baseline. Never import current Base metadata here.
-- Used only after CI fixture opt-in and an empty-database assertion.

CREATE TABLE attempts (
	id VARCHAR(36) NOT NULL, 
	task_id VARCHAR(36) NOT NULL, 
	fence INTEGER NOT NULL, 
	started_at DOUBLE NOT NULL, 
	finished_at DOUBLE, 
	outcome VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_attempts_task_id ON attempts (task_id);

CREATE TABLE inbox (
	event_id VARCHAR(36) NOT NULL, 
	received_at DOUBLE NOT NULL, 
	PRIMARY KEY (event_id)
);

CREATE TABLE outbox (
	id VARCHAR(36) NOT NULL, 
	task_id VARCHAR(36) NOT NULL, 
	event_type VARCHAR(40) NOT NULL, 
	payload TEXT NOT NULL, 
	sent_at DOUBLE, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_outbox_sent_at ON outbox (sent_at);

CREATE TABLE schema_version (
	version INTEGER NOT NULL AUTO_INCREMENT, 
	PRIMARY KEY (version)
);

CREATE TABLE sessions (
	token_hash VARCHAR(64) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	csrf_hash VARCHAR(64) NOT NULL, 
	expires_at DOUBLE NOT NULL, 
	PRIMARY KEY (token_hash)
);

CREATE INDEX ix_sessions_user_id ON sessions (user_id);

CREATE TABLE task_events (
	id VARCHAR(36) NOT NULL, 
	task_id VARCHAR(36) NOT NULL, 
	trace_id VARCHAR(36) NOT NULL, 
	component VARCHAR(40) NOT NULL, 
	kind VARCHAR(40) NOT NULL, 
	content VARCHAR(256) NOT NULL, 
	created_at DOUBLE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_event_task_time ON task_events (task_id, created_at);

CREATE TABLE tasks (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36) NOT NULL, 
	idempotency_key VARCHAR(128) COLLATE utf8mb4_bin NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	prompt TEXT NOT NULL, 
	trace_id VARCHAR(36) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	attempt_count INTEGER NOT NULL, 
	fence INTEGER NOT NULL, 
	attempt_id VARCHAR(36), 
	lease_until DOUBLE NOT NULL, 
	next_attempt_at DOUBLE NOT NULL, 
	result_id VARCHAR(100), 
	error_code VARCHAR(80), 
	created_at DOUBLE NOT NULL, 
	updated_at DOUBLE NOT NULL, 
	model_mode VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (owner_id, idempotency_key)
);

CREATE INDEX ix_task_owner_created ON tasks (owner_id, created_at);

CREATE INDEX ix_task_queue ON tasks (status, next_attempt_at);

CREATE TABLE users (
	id VARCHAR(36) NOT NULL, 
	username VARCHAR(80) NOT NULL, 
	password_hash VARCHAR(256) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (username)
);
