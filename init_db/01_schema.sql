-- SAE System — PostgreSQL schema
-- Runs automatically on first container start via docker-entrypoint-initdb.d

-- Students with full auth fields
CREATE TABLE IF NOT EXISTS students (
    student_id    TEXT PRIMARY KEY,          -- UUID, e.g. "550e8400-e29b-41d4..."
    name          TEXT NOT NULL,             -- full display name
    username      TEXT UNIQUE NOT NULL,      -- unique handle
    email         TEXT UNIQUE NOT NULL,      -- login credential
    password_hash TEXT NOT NULL,             -- pbkdf2 hash:salt
    domain        TEXT DEFAULT '',           -- picked after login
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Roadmaps (JSON stored as JSONB for queryability)
CREATE TABLE IF NOT EXISTS roadmaps (
    id           SERIAL PRIMARY KEY,
    domain       TEXT NOT NULL UNIQUE,
    roadmap_json JSONB NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- Lessons per student + concept
CREATE TABLE IF NOT EXISTS lessons (
    id           SERIAL PRIMARY KEY,
    student_id   TEXT REFERENCES students(student_id) ON DELETE CASCADE,
    concept_id   TEXT NOT NULL,
    domain       TEXT NOT NULL,
    lesson_json  JSONB NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE (student_id, concept_id)
);

-- Test attempts
CREATE TABLE IF NOT EXISTS test_results (
    id              SERIAL PRIMARY KEY,
    student_id      TEXT REFERENCES students(student_id) ON DELETE CASCADE,
    concept_id      TEXT NOT NULL,
    domain          TEXT NOT NULL,
    total_marks     INT NOT NULL,
    earned_marks    INT NOT NULL,
    percentage      NUMERIC(5,2) NOT NULL,
    grade           CHAR(1) NOT NULL,
    passed          BOOLEAN NOT NULL,
    results_json    JSONB NOT NULL,
    attempted_at    TIMESTAMPTZ DEFAULT now()
);

-- Proof-of-learning hashes
CREATE TABLE IF NOT EXISTS proof_hashes (
    id           SERIAL PRIMARY KEY,
    student_id   TEXT REFERENCES students(student_id) ON DELETE CASCADE,
    concept_id   TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    score        NUMERIC(6,4) NOT NULL,
    proof_hash   TEXT NOT NULL UNIQUE,
    issued_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_students_email    ON students(email);
CREATE INDEX IF NOT EXISTS idx_students_username ON students(username);
CREATE INDEX IF NOT EXISTS idx_lessons_concept   ON lessons(concept_id);
CREATE INDEX IF NOT EXISTS idx_test_results_stud ON test_results(student_id);
CREATE INDEX IF NOT EXISTS idx_proof_student     ON proof_hashes(student_id);
