CREATE TABLE IF NOT EXISTS students (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS papers (
    id SERIAL PRIMARY KEY,
    week INTEGER NOT NULL,
    paper_number INTEGER NOT NULL,
    paper_title TEXT NOT NULL,
    paper_link TEXT,
    active BOOLEAN DEFAULT TRUE,
    UNIQUE(week, paper_number)
);

CREATE TABLE IF NOT EXISTS nominations (
    id SERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id),
    paper_id INTEGER NOT NULL REFERENCES papers(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_id),
    UNIQUE(paper_id)
);
