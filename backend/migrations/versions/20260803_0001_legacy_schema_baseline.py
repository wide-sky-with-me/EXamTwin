"""Create the initial ExamTwin relational schema.

Revision ID: 20260803_0001
Revises:
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260803_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the initial revision self-contained. Existing installations already
    # stamped at this revision are unchanged; fresh databases no longer depend
    # on application startup executing a second, unversioned schema definition.
    op.execute(
        """
        CREATE TABLE source_documents (
            id TEXT PRIMARY KEY,
            subject_code TEXT NOT NULL DEFAULT '9660',
            path TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            source_type TEXT NOT NULL,
            authority_tier TEXT NOT NULL DEFAULT 'supplementary',
            checksum TEXT NOT NULL,
            pair_key TEXT,
            unit_code TEXT,
            exam_year INTEGER,
            exam_session TEXT,
            page_count INTEGER,
            status TEXT NOT NULL DEFAULT 'discovered',
            markdown_path TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_source_type ON source_documents(source_type);
        CREATE INDEX idx_source_authority ON source_documents(authority_tier);
        CREATE INDEX idx_source_pair ON source_documents(pair_key);
        CREATE INDEX idx_source_status ON source_documents(status);

        CREATE TABLE knowledge_points (
            id TEXT PRIMARY KEY,
            subject_code TEXT NOT NULL DEFAULT '9660',
            code TEXT NOT NULL,
            title TEXT NOT NULL,
            unit_code TEXT NOT NULL,
            strand TEXT NOT NULL,
            parent_id TEXT REFERENCES knowledge_points(id),
            difficulty_score DOUBLE PRECISION NOT NULL,
            difficulty_label TEXT NOT NULL,
            difficulty_confidence DOUBLE PRECISION NOT NULL,
            evidence_level TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            features_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX idx_knowledge_subject_code
            ON knowledge_points(subject_code, code);

        CREATE TABLE knowledge_relations (
            id BIGSERIAL PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES knowledge_points(id),
            target_id TEXT NOT NULL REFERENCES knowledge_points(id),
            relation_type TEXT NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            source_ref TEXT NOT NULL,
            UNIQUE(source_id, target_id, relation_type)
        );

        CREATE TABLE knowledge_evidence (
            id BIGSERIAL PRIMARY KEY,
            knowledge_point_id TEXT NOT NULL REFERENCES knowledge_points(id) ON DELETE CASCADE,
            source_document_id TEXT REFERENCES source_documents(id) ON DELETE CASCADE,
            page INTEGER,
            section TEXT,
            section_path_json TEXT NOT NULL DEFAULT '[]',
            evidence_role TEXT NOT NULL,
            excerpt TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            source_ref TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(knowledge_point_id, source_document_id, page, section, content_hash)
        );
        CREATE INDEX idx_knowledge_evidence_point
            ON knowledge_evidence(knowledge_point_id);
        CREATE INDEX idx_knowledge_evidence_document
            ON knowledge_evidence(source_document_id, page);

        CREATE TABLE difficulty_evidence (
            id BIGSERIAL PRIMARY KEY,
            knowledge_point_id TEXT NOT NULL REFERENCES knowledge_points(id),
            question_ref TEXT,
            evidence_type TEXT NOT NULL,
            value DOUBLE PRECISION,
            evidence_level TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            run_id TEXT,
            method_key TEXT,
            model_name TEXT,
            input_hash TEXT,
            details_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE knowledge_build_runs (
            id TEXT PRIMARY KEY,
            subject_pack_id TEXT NOT NULL,
            subject_code TEXT NOT NULL,
            source_document_id TEXT REFERENCES source_documents(id) ON DELETE SET NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            pipeline_version TEXT NOT NULL,
            input_hash TEXT,
            ai_model TEXT,
            config_json TEXT NOT NULL DEFAULT '{}',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            artifact_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE INDEX idx_knowledge_build_subject
            ON knowledge_build_runs(subject_code, created_at DESC);

        CREATE TABLE question_difficulty (
            id BIGSERIAL PRIMARY KEY,
            source_document_id TEXT NOT NULL REFERENCES source_documents(id),
            question_ref TEXT NOT NULL,
            pair_key TEXT,
            question_number TEXT NOT NULL,
            difficulty_score DOUBLE PRECISION NOT NULL,
            difficulty_label TEXT NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            evidence_level TEXT NOT NULL,
            knowledge_codes_json TEXT NOT NULL DEFAULT '[]',
            evidence_json TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source_document_id, question_number)
        );
        CREATE INDEX idx_question_difficulty_pair ON question_difficulty(pair_key);

        CREATE TABLE assessments (
            id TEXT PRIMARY KEY,
            question_ref TEXT,
            answer_markdown TEXT NOT NULL,
            total_awarded DOUBLE PRECISION NOT NULL,
            total_available DOUBLE PRECISION NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            status TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE reviews (
            id BIGSERIAL PRIMARY KEY,
            assessment_id TEXT NOT NULL REFERENCES assessments(id),
            reviewer TEXT NOT NULL,
            decision TEXT NOT NULL,
            override_mark DOUBLE PRECISION,
            note TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE paper_jobs (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            suffix TEXT NOT NULL,
            unit_code TEXT,
            source_path TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            total_pages INTEGER NOT NULL DEFAULT 0,
            parsed_pages INTEGER NOT NULL DEFAULT 0,
            total_questions INTEGER NOT NULL DEFAULT 0,
            completed_questions INTEGER NOT NULL DEFAULT 0,
            failed_questions INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            lease_token TEXT,
            lease_expires_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT
        );
        CREATE INDEX idx_paper_jobs_claim
            ON paper_jobs(status, lease_expires_at, created_at);

        CREATE TABLE paper_job_chunks (
            id BIGSERIAL PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES paper_jobs(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            page_start INTEGER NOT NULL,
            page_end INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            markdown_path TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            started_at TEXT,
            completed_at TEXT,
            UNIQUE(job_id, chunk_index)
        );
        CREATE INDEX idx_paper_job_chunks_status
            ON paper_job_chunks(job_id, status, chunk_index);

        CREATE TABLE paper_job_questions (
            id BIGSERIAL PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES paper_jobs(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            number TEXT NOT NULL,
            question_markdown TEXT NOT NULL,
            source_pages_json TEXT NOT NULL DEFAULT '[]',
            requires_visual_context BOOLEAN,
            knowledge_codes_json TEXT NOT NULL DEFAULT '[]',
            requirements_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            answer_json TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            started_at TEXT,
            completed_at TEXT,
            UNIQUE(job_id, position)
        );
        CREATE INDEX idx_paper_job_questions_status
            ON paper_job_questions(job_id, status, position);

        CREATE TABLE paper_agent_steps (
            id BIGSERIAL PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES paper_jobs(id) ON DELETE CASCADE,
            question_position INTEGER NOT NULL,
            run_attempt INTEGER NOT NULL,
            sequence INTEGER NOT NULL,
            phase TEXT NOT NULL,
            status TEXT NOT NULL,
            tool_name TEXT,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(job_id, question_position, run_attempt, sequence)
        );
        CREATE INDEX idx_paper_agent_steps_question
            ON paper_agent_steps(job_id, question_position, run_attempt, sequence);

        CREATE FUNCTION notify_task_event() RETURNS trigger AS $$
        DECLARE
            resource_id TEXT;
        BEGIN
            IF TG_TABLE_NAME = 'paper_jobs' THEN
                resource_id := NEW.id;
            ELSE
                resource_id := NEW.job_id;
            END IF;
            PERFORM pg_notify(
                'examtwin_task_events',
                json_build_object('topic', 'paper_job', 'resource_id', resource_id)::TEXT
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER paper_jobs_task_event
        AFTER INSERT OR UPDATE ON paper_jobs
        FOR EACH ROW EXECUTE FUNCTION notify_task_event();
        CREATE TRIGGER paper_job_chunks_task_event
        AFTER INSERT OR UPDATE ON paper_job_chunks
        FOR EACH ROW EXECUTE FUNCTION notify_task_event();
        CREATE TRIGGER paper_job_questions_task_event
        AFTER INSERT OR UPDATE ON paper_job_questions
        FOR EACH ROW EXECUTE FUNCTION notify_task_event();
        CREATE TRIGGER paper_agent_steps_task_event
        AFTER INSERT OR UPDATE ON paper_agent_steps
        FOR EACH ROW EXECUTE FUNCTION notify_task_event();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS paper_agent_steps_task_event ON paper_agent_steps;
        DROP TRIGGER IF EXISTS paper_job_questions_task_event ON paper_job_questions;
        DROP TRIGGER IF EXISTS paper_job_chunks_task_event ON paper_job_chunks;
        DROP TRIGGER IF EXISTS paper_jobs_task_event ON paper_jobs;
        DROP FUNCTION IF EXISTS notify_task_event();
        DROP TABLE IF EXISTS paper_agent_steps;
        DROP TABLE IF EXISTS paper_job_questions;
        DROP TABLE IF EXISTS paper_job_chunks;
        DROP TABLE IF EXISTS paper_jobs;
        DROP TABLE IF EXISTS reviews;
        DROP TABLE IF EXISTS assessments;
        DROP TABLE IF EXISTS question_difficulty;
        DROP TABLE IF EXISTS difficulty_evidence;
        DROP TABLE IF EXISTS knowledge_evidence;
        DROP TABLE IF EXISTS knowledge_relations;
        DROP TABLE IF EXISTS knowledge_points;
        DROP TABLE IF EXISTS knowledge_build_runs;
        DROP TABLE IF EXISTS source_documents;
        """
    )
