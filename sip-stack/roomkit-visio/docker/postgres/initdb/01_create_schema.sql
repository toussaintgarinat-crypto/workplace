-- ============================================================
-- Kamailio Database Schema Creation Script
-- Tables: version, subscriber, dispatcher, rtpengine, address, trusted
-- Target: PostgreSQL
-- ============================================================

-- Version tracking table (required by Kamailio modules)
CREATE TABLE IF NOT EXISTS version (
    id SERIAL PRIMARY KEY NOT NULL,
    table_name VARCHAR(32) NOT NULL,
    table_version INTEGER DEFAULT 0 NOT NULL,
    CONSTRAINT version_table_name_idx UNIQUE (table_name)
);

-- Subscriber table (auth_db module - version 7)
CREATE TABLE IF NOT EXISTS subscriber (
    id SERIAL PRIMARY KEY NOT NULL,
    username VARCHAR(64) DEFAULT '' NOT NULL,
    domain VARCHAR(64) DEFAULT '' NOT NULL,
    password VARCHAR(64) DEFAULT '' NOT NULL,
    ha1 VARCHAR(128) DEFAULT '' NOT NULL,
    ha1b VARCHAR(128) DEFAULT '' NOT NULL,
    rpid VARCHAR(64) DEFAULT NULL,
    CONSTRAINT subscriber_account_idx UNIQUE (username, domain)
);

-- Dispatcher table (dispatcher module - version 4)
CREATE TABLE IF NOT EXISTS dispatcher (
    id SERIAL PRIMARY KEY NOT NULL,
    setid INTEGER DEFAULT 0 NOT NULL,
    destination VARCHAR(192) DEFAULT '' NOT NULL,
    flags INTEGER DEFAULT 0 NOT NULL,
    priority INTEGER DEFAULT 0 NOT NULL,
    attrs VARCHAR(128) DEFAULT '' NOT NULL,
    description VARCHAR(64) DEFAULT '' NOT NULL
);

-- RTPEngine table (rtpengine module - version 1)
CREATE TABLE IF NOT EXISTS rtpengine (
    id SERIAL PRIMARY KEY NOT NULL,
    setid INTEGER DEFAULT 0 NOT NULL,
    url VARCHAR(64) DEFAULT '' NOT NULL,
    weight INTEGER DEFAULT 1 NOT NULL,
    disabled INTEGER DEFAULT 0 NOT NULL,
    stamp TIMESTAMP WITHOUT TIME ZONE DEFAULT '1900-01-01 00:00:01' NOT NULL,
    external_ip VARCHAR(45)
);

-- Address table (permissions module - version 6)
-- IP whitelist for SIP device access (hot reload with kamcmd permissions.addressReload)
CREATE TABLE IF NOT EXISTS address (
    id SERIAL PRIMARY KEY,
    grp INTEGER NOT NULL DEFAULT 1,
    ip_addr VARCHAR(50) NOT NULL,
    mask INTEGER NOT NULL DEFAULT 32,
    port SMALLINT NOT NULL DEFAULT 0,
    tag VARCHAR(64)
);

-- Trusted table (permissions module - version 6)
-- Required by permissions module even if not used directly
CREATE TABLE IF NOT EXISTS trusted (
    id SERIAL PRIMARY KEY NOT NULL,
    src_ip VARCHAR(50) NOT NULL,
    proto VARCHAR(4) NOT NULL,
    from_pattern VARCHAR(64) DEFAULT NULL,
    ruri_pattern VARCHAR(64) DEFAULT NULL,
    tag VARCHAR(64),
    priority INTEGER DEFAULT 0 NOT NULL
);
CREATE INDEX IF NOT EXISTS trusted_peer_idx ON trusted (src_ip);

-- UAC Registration table (uac module - version 5)
-- SIP trunk registrations to external SIP servers (e.g., OVH)
CREATE TABLE IF NOT EXISTS uacreg (
    id SERIAL PRIMARY KEY NOT NULL,
    l_uuid VARCHAR(64) DEFAULT '' NOT NULL,
    l_username VARCHAR(64) DEFAULT '' NOT NULL,
    l_domain VARCHAR(64) DEFAULT '' NOT NULL,
    r_username VARCHAR(64) DEFAULT '' NOT NULL,
    r_domain VARCHAR(64) DEFAULT '' NOT NULL,
    realm VARCHAR(64) DEFAULT '' NOT NULL,
    auth_username VARCHAR(64) DEFAULT '' NOT NULL,
    auth_password VARCHAR(64) DEFAULT '' NOT NULL,
    auth_ha1 VARCHAR(128) DEFAULT '' NOT NULL,
    auth_proxy VARCHAR(255) DEFAULT '' NOT NULL,
    expires INTEGER DEFAULT 0 NOT NULL,
    flags INTEGER DEFAULT 0 NOT NULL,
    reg_delay INTEGER DEFAULT 0 NOT NULL,
    contact_addr VARCHAR(255) DEFAULT '' NOT NULL,
    socket VARCHAR(128) DEFAULT '' NOT NULL,
    CONSTRAINT uacreg_l_uuid_idx UNIQUE (l_uuid)
);