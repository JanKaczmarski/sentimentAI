CREATE TABLE user_accounts (
    user_id uuid PRIMARY KEY,
    email text NOT NULL UNIQUE,
    username text NOT NULL UNIQUE,
    api_key_digest char(64) NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE investment_theses (
    thesis_id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES user_accounts (user_id) ON DELETE CASCADE,
    risk_tolerance text NOT NULL CHECK (risk_tolerance IN ('low', 'medium', 'high')),
    investment_horizon text NOT NULL CHECK (investment_horizon IN ('short_term', 'long_term')),
    investment_style text NOT NULL CHECK (investment_style IN ('passive', 'active')),
    description text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX investment_theses_user_idx ON investment_theses (user_id, thesis_id);

CREATE TABLE investment_thesis_companies (
    thesis_id uuid NOT NULL REFERENCES investment_theses (thesis_id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    company text NOT NULL,
    PRIMARY KEY (thesis_id, ordinal)
);
