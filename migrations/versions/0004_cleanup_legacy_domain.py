"""cleanup legacy homes/profiles embeddings and align reference data

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-01 18:30:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS last_name VARCHAR(100),
        ADD COLUMN IF NOT EXISTS first_name VARCHAR(100),
        ADD COLUMN IF NOT EXISTS middle_name VARCHAR(100)
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'profile_id'
            ) AND EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_name = 'profiles'
            ) THEN
                UPDATE users u
                SET
                    last_name = COALESCE(u.last_name, p.last_name),
                    first_name = COALESCE(u.first_name, p.first_name),
                    middle_name = COALESCE(u.middle_name, p.middle_name)
                FROM profiles p
                WHERE u.profile_id = p.profile_id;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS person_embeddings (
            person_embedding_id SERIAL PRIMARY KEY,
            person_id INTEGER NOT NULL REFERENCES persons(person_id) ON DELETE CASCADE,
            embedding BYTEA NOT NULL,
            source VARCHAR(50),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS person_embeddings_person_idx ON person_embeddings(person_id)")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'persons' AND column_name = 'embeddings'
            ) THEN
                INSERT INTO person_embeddings (person_id, embedding, source)
                SELECT p.person_id, p.embeddings, 'legacy_person_blob'
                FROM persons p
                WHERE p.embeddings IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM person_embeddings pe
                      WHERE pe.person_id = p.person_id
                  );
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        DECLARE
            system_admin_id integer;
            admin_id integer;
            user_role_id integer;
            viewer_role_id integer;
        BEGIN
            SELECT role_id INTO system_admin_id FROM roles WHERE name = 'system_admin' LIMIT 1;
            SELECT role_id INTO admin_id FROM roles WHERE name = 'admin' LIMIT 1;

            IF admin_id IS NULL AND system_admin_id IS NOT NULL THEN
                UPDATE roles SET name = 'admin' WHERE role_id = system_admin_id;
                admin_id := system_admin_id;
            ELSIF admin_id IS NOT NULL AND system_admin_id IS NOT NULL AND admin_id <> system_admin_id THEN
                UPDATE users SET role_id = admin_id WHERE role_id = system_admin_id;
                DELETE FROM roles WHERE role_id = system_admin_id;
            ELSIF admin_id IS NULL THEN
                INSERT INTO roles (role_id, name) VALUES (1, 'admin') ON CONFLICT (role_id) DO UPDATE SET name = EXCLUDED.name;
                SELECT role_id INTO admin_id FROM roles WHERE role_id = 1;
            END IF;

            SELECT role_id INTO user_role_id FROM roles WHERE name = 'user' LIMIT 1;
            IF user_role_id IS NULL THEN
                INSERT INTO roles (role_id, name) VALUES (2, 'user') ON CONFLICT (role_id) DO UPDATE SET name = EXCLUDED.name;
                user_role_id := 2;
            ELSIF user_role_id <> 2 THEN
                UPDATE users SET role_id = 2 WHERE role_id = user_role_id;
                INSERT INTO roles (role_id, name) VALUES (2, 'user') ON CONFLICT (role_id) DO NOTHING;
                DELETE FROM roles WHERE role_id = user_role_id AND role_id <> 2;
            END IF;

            SELECT role_id INTO viewer_role_id FROM roles WHERE name = 'viewer' LIMIT 1;
            IF viewer_role_id IS NULL THEN
                INSERT INTO roles (role_id, name) VALUES (3, 'viewer') ON CONFLICT (role_id) DO UPDATE SET name = EXCLUDED.name;
            ELSIF viewer_role_id <> 3 THEN
                UPDATE users SET role_id = 3 WHERE role_id = viewer_role_id;
                INSERT INTO roles (role_id, name) VALUES (3, 'viewer') ON CONFLICT (role_id) DO NOTHING;
                DELETE FROM roles WHERE role_id = viewer_role_id AND role_id <> 3;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        DECLARE
            legacy_motion_id integer;
            canonical_motion_id integer;
            legacy_person_id integer;
            canonical_person_id integer;
        BEGIN
            INSERT INTO event_types (event_type_id, name) VALUES (1, 'face_recognized') ON CONFLICT (event_type_id) DO NOTHING;
            INSERT INTO event_types (event_type_id, name) VALUES (2, 'face_unknown') ON CONFLICT (event_type_id) DO NOTHING;
            INSERT INTO event_types (event_type_id, name) VALUES (3, 'motion_detected') ON CONFLICT (event_type_id) DO NOTHING;
            INSERT INTO event_types (event_type_id, name) VALUES (4, 'person_detected') ON CONFLICT (event_type_id) DO NOTHING;
            INSERT INTO event_types (name) VALUES ('face_recognized') ON CONFLICT DO NOTHING;
            INSERT INTO event_types (name) VALUES ('face_unknown') ON CONFLICT DO NOTHING;
            INSERT INTO event_types (name) VALUES ('motion_detected') ON CONFLICT DO NOTHING;
            INSERT INTO event_types (name) VALUES ('person_detected') ON CONFLICT DO NOTHING;

            SELECT event_type_id INTO legacy_motion_id FROM event_types WHERE name = 'motion' LIMIT 1;
            SELECT event_type_id INTO canonical_motion_id FROM event_types WHERE name = 'motion_detected' LIMIT 1;
            IF legacy_motion_id IS NOT NULL AND canonical_motion_id IS NOT NULL AND legacy_motion_id <> canonical_motion_id THEN
                UPDATE events SET event_type_id = canonical_motion_id WHERE event_type_id = legacy_motion_id;
                DELETE FROM event_types WHERE event_type_id = legacy_motion_id;
            ELSIF legacy_motion_id IS NOT NULL THEN
                UPDATE event_types SET name = 'motion_detected' WHERE event_type_id = legacy_motion_id;
            END IF;

            SELECT event_type_id INTO legacy_person_id FROM event_types WHERE name = 'person_entered' LIMIT 1;
            SELECT event_type_id INTO canonical_person_id FROM event_types WHERE name = 'person_detected' LIMIT 1;
            IF legacy_person_id IS NOT NULL AND canonical_person_id IS NOT NULL AND legacy_person_id <> canonical_person_id THEN
                UPDATE events SET event_type_id = canonical_person_id WHERE event_type_id = legacy_person_id;
                DELETE FROM event_types WHERE event_type_id = legacy_person_id;
            ELSIF legacy_person_id IS NOT NULL THEN
                UPDATE event_types SET name = 'person_detected' WHERE event_type_id = legacy_person_id;
            END IF;
        END $$;
        """
    )

    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS profile_id CASCADE")
    op.execute("ALTER TABLE persons DROP COLUMN IF EXISTS embeddings CASCADE")
    op.execute("DROP INDEX IF EXISTS profiles_phone_unique_idx")
    op.execute("DROP TABLE IF EXISTS profiles CASCADE")

    op.execute("DROP TABLE IF EXISTS user_camera_permissions CASCADE")
    op.execute("DROP TABLE IF EXISTS group_camera_permissions CASCADE")
    op.execute("DROP TABLE IF EXISTS user_groups CASCADE")

    op.execute("DROP TABLE IF EXISTS home_activity_log CASCADE")
    op.execute("DROP TABLE IF EXISTS home_invitations CASCADE")
    op.execute("DROP TABLE IF EXISTS home_members CASCADE")
    op.execute("DROP TABLE IF EXISTS room_cameras CASCADE")
    op.execute("DROP TABLE IF EXISTS rooms CASCADE")
    op.execute("DROP TABLE IF EXISTS homes CASCADE")


def downgrade() -> None:
    raise NotImplementedError('Downgrade is not supported for legacy cleanup migration')
