-- Created by Redgate Data Modeler (https://datamodeler.redgate-platform.com)
-- Last modification date: 2026-08-16 12:44:42.092

-- tables
-- Table: chunks
CREATE TABLE chunks (
    report_id int  NOT NULL,
    chunk_number int  NOT NULL,
    chunk_link varchar(500)  NOT NULL,
    CONSTRAINT pk_chunks PRIMARY KEY (report_id,chunk_number)
);

-- Table: companies
CREATE TABLE companies (
    company_id int  NOT NULL,
    company_name varchar(255)  NOT NULL,
    cik char(10)  NULL,
    CONSTRAINT pk_companies PRIMARY KEY (company_id)
);

-- Table: past_predictions
CREATE TABLE past_predictions (
    prediction_id int  NOT NULL,
    user_id int  NOT NULL,
    doc_link varchar(500)  NOT NULL,
    created_at timestamp  NULL,
    CONSTRAINT pk_past_predictions PRIMARY KEY (prediction_id)
);

-- Table: reports
CREATE TABLE reports (
    report_id int  NOT NULL,
    company_id int  NOT NULL,
    report_date date  NOT NULL,
    CONSTRAINT uq_reports_report_id UNIQUE (report_id) NOT DEFERRABLE  INITIALLY IMMEDIATE,
    CONSTRAINT pk_reports PRIMARY KEY (report_id,company_id)
);

-- Table: stock_pricing
CREATE TABLE stock_pricing (
    company_id int  NOT NULL,
    price_date date  NOT NULL,
    price decimal(15,4)  NOT NULL,
    CONSTRAINT pk_stock_pricing PRIMARY KEY (company_id,price_date)
);

-- Table: strategies
CREATE TABLE strategies (
    strategy_name varchar(100)  NOT NULL,
    description text  NULL,
    CONSTRAINT pk_strategies PRIMARY KEY (strategy_name)
);

-- Table: subscriptions
CREATE TABLE subscriptions (
    user_id int  NOT NULL,
    company_id int  NOT NULL,
    strategy_name varchar(100)  NOT NULL,
    CONSTRAINT pk_subscriptions PRIMARY KEY (user_id,company_id)
);

-- Table: users
CREATE TABLE users (
    user_id int  NOT NULL,
    username varchar(100)  NOT NULL,
    email varchar(255)  NOT NULL,
    CONSTRAINT uq_users_username UNIQUE (username) NOT DEFERRABLE  INITIALLY IMMEDIATE,
    CONSTRAINT uq_users_email UNIQUE (email) NOT DEFERRABLE  INITIALLY IMMEDIATE,
    CONSTRAINT pk_users PRIMARY KEY (user_id)
);

-- foreign keys
-- Reference: fk_chunks_report (table: chunks)
ALTER TABLE chunks ADD CONSTRAINT fk_chunks_report
    FOREIGN KEY (report_id)
    REFERENCES reports (report_id)  
    NOT DEFERRABLE 
    INITIALLY IMMEDIATE
;

-- Reference: fk_past_predictions_user (table: past_predictions)
ALTER TABLE past_predictions ADD CONSTRAINT fk_past_predictions_user
    FOREIGN KEY (user_id)
    REFERENCES users (user_id)  
    NOT DEFERRABLE 
    INITIALLY IMMEDIATE
;

-- Reference: fk_reports_company (table: reports)
ALTER TABLE reports ADD CONSTRAINT fk_reports_company
    FOREIGN KEY (company_id)
    REFERENCES companies (company_id)  
    NOT DEFERRABLE 
    INITIALLY IMMEDIATE
;

-- Reference: fk_stock_pricing_company (table: stock_pricing)
ALTER TABLE stock_pricing ADD CONSTRAINT fk_stock_pricing_company
    FOREIGN KEY (company_id)
    REFERENCES companies (company_id)  
    NOT DEFERRABLE 
    INITIALLY IMMEDIATE
;

-- Reference: fk_subscriptions_company (table: subscriptions)
ALTER TABLE subscriptions ADD CONSTRAINT fk_subscriptions_company
    FOREIGN KEY (company_id)
    REFERENCES companies (company_id)  
    NOT DEFERRABLE 
    INITIALLY IMMEDIATE
;

-- Reference: fk_subscriptions_strategy (table: subscriptions)
ALTER TABLE subscriptions ADD CONSTRAINT fk_subscriptions_strategy
    FOREIGN KEY (strategy_name)
    REFERENCES strategies (strategy_name)  
    NOT DEFERRABLE 
    INITIALLY IMMEDIATE
;

-- Reference: fk_subscriptions_user (table: subscriptions)
ALTER TABLE subscriptions ADD CONSTRAINT fk_subscriptions_user
    FOREIGN KEY (user_id)
    REFERENCES users (user_id)  
    NOT DEFERRABLE 
    INITIALLY IMMEDIATE
;

-- End of file.

