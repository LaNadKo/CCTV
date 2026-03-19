-- Create dedicated database for the CCTV system (PostgreSQL 8.1)
-- Run this once while connected to the default "postgres" database.
-- Note: 8.1 has no "IF NOT EXISTS" for CREATE/DROP DATABASE.

CREATE DATABASE cctvdb
    WITH ENCODING 'UTF8'
    TEMPLATE template0;
