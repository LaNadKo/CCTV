"""add onvif camera metadata and backfill endpoints

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-01 21:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cameras
        ADD COLUMN IF NOT EXISTS connection_kind VARCHAR(20) NOT NULL DEFAULT 'manual',
        ADD COLUMN IF NOT EXISTS supports_ptz BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS onvif_profile_token VARCHAR(255),
        ADD COLUMN IF NOT EXISTS device_metadata TEXT
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'cameras_connection_kind_chk'
            ) THEN
                ALTER TABLE cameras
                ADD CONSTRAINT cameras_connection_kind_chk
                CHECK (connection_kind IN ('manual', 'onvif', 'rtsp', 'http'));
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        INSERT INTO camera_endpoints (camera_id, endpoint_kind, endpoint_url, is_primary)
        SELECT c.camera_id,
               CASE
                   WHEN c.stream_url ILIKE 'rtsp://%' THEN 'rtsp'
                   WHEN c.stream_url ILIKE 'http://%' OR c.stream_url ILIKE 'https://%' THEN 'http'
                   ELSE 'rtsp'
               END,
               c.stream_url,
               TRUE
        FROM cameras c
        WHERE c.stream_url IS NOT NULL
          AND c.stream_url <> ''
          AND c.stream_url NOT LIKE 'local%'
          AND NOT EXISTS (
              SELECT 1
              FROM camera_endpoints ep
              WHERE ep.camera_id = c.camera_id
                AND ep.endpoint_url = c.stream_url
          );
        """
    )

    op.execute(
        """
        UPDATE cameras
        SET connection_kind = CASE
            WHEN EXISTS (
                SELECT 1 FROM camera_endpoints ep
                WHERE ep.camera_id = cameras.camera_id AND ep.endpoint_kind = 'onvif'
            ) THEN 'onvif'
            WHEN EXISTS (
                SELECT 1 FROM camera_endpoints ep
                WHERE ep.camera_id = cameras.camera_id AND ep.endpoint_kind = 'rtsp'
            ) THEN 'rtsp'
            WHEN EXISTS (
                SELECT 1 FROM camera_endpoints ep
                WHERE ep.camera_id = cameras.camera_id AND ep.endpoint_kind = 'http'
            ) THEN 'http'
            WHEN stream_url ILIKE 'rtsp://%' THEN 'rtsp'
            WHEN stream_url ILIKE 'http://%' OR stream_url ILIKE 'https://%' THEN 'http'
            ELSE 'manual'
        END;
        """
    )


def downgrade() -> None:
    raise NotImplementedError('Downgrade is not supported for ONVIF camera migration')
