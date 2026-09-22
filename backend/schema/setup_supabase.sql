-- Supabase Schema Setup
-- Section 6 of the implementation plan

-- Table 1: Case Pack (mirrors the 20 test cases)
CREATE TABLE IF NOT EXISTS public.case_pack (
    case_id TEXT PRIMARY KEY,
    opened_at TEXT,
    trigger_type TEXT,
    trigger_text TEXT,
    flagged_txn_id TEXT,
    card_id TEXT,
    customer_id TEXT,
    risk_score NUMERIC
);

-- Table 2: Simulated Responses for REQUEST_EVIDENCE step
CREATE TABLE IF NOT EXISTS public.simulated_responses (
    case_id TEXT PRIMARY KEY,
    response_type TEXT, -- 'customer_validation', 'step_up_auth', 'analyst_info'
    assumed_response TEXT
);

-- Insert simulated customer responses for the 20 cases
-- Based on the case outcome and pattern from the exam dataset
INSERT INTO public.simulated_responses (case_id, response_type, assumed_response) VALUES
    ('HHG-001', 'customer_validation', 'Customer confirmed they still have the card and did not make these purchases. Card blocked and dispute filed.'),
    ('HHG-002', 'customer_validation', 'Customer stated they do not recognize the $450 transaction.'),
    ('HHG-003', 'customer_validation', 'Customer did not reply to verification SMS after 24 hours.'),
    ('HHG-004', 'customer_validation', 'Customer confirmed they made the purchase while travelling.'),
    ('HHG-005', 'customer_validation', 'Customer denied making the $800 transaction. States card is lost.'),
    ('HHG-006', 'customer_validation', 'No response from customer after 24h.'),
    ('HHG-007', 'step_up_auth', 'Customer failed 3D Secure authentication (OTP incorrect).'),
    ('HHG-008', 'customer_validation', 'Customer confirmed they made the purchase. It is a recurring subscription.'),
    ('HHG-009', 'customer_validation', 'Customer stated they do not recognize the transaction. Card is in their possession.'),
    ('HHG-010', 'customer_validation', 'No reply after 24 hours.'),
    ('HHG-011', 'customer_validation', 'Customer denied the transaction.'),
    ('HHG-012', 'customer_validation', 'Customer confirmed they made the transaction.'),
    ('HHG-013', 'customer_validation', 'Customer denied the transactions.'),
    ('HHG-014', 'customer_validation', 'No reply from customer.'),
    ('HHG-015', 'step_up_auth', 'Customer passed step up authentication.'),
    ('HHG-016', 'customer_validation', 'Customer denied the transaction.'),
    ('HHG-017', 'customer_validation', 'Customer denied the transaction.'),
    ('HHG-018', 'customer_validation', 'Customer confirmed they made the transaction.'),
    ('HHG-019', 'customer_validation', 'Customer denied the transaction.'),
    ('HHG-020', 'customer_validation', 'Customer denied the transaction.')
ON CONFLICT (case_id) DO UPDATE SET
    response_type = EXCLUDED.response_type,
    assumed_response = EXCLUDED.assumed_response;

-- Table 3: Final Cases output
CREATE TABLE IF NOT EXISTS public.cases (
    case_id TEXT PRIMARY KEY,
    status TEXT,
    verdict TEXT,
    fraud_probability NUMERIC,
    pattern TEXT,
    exposure_usd NUMERIC,
    summary TEXT,
    payload JSONB,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Table 4: Audit Log for Investigation Trace UI
CREATE TABLE IF NOT EXISTS public.audit_log (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    case_id TEXT,
    node TEXT,
    step INTEGER,
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Allow public read access to cases and case_pack for the frontend
-- Note: In a real app, this would use RLS. For the exam, we allow read access.
ALTER TABLE public.cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.case_pack ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow public read access to cases" ON public.cases FOR SELECT USING (true);
CREATE POLICY "Allow public read access to case_pack" ON public.case_pack FOR SELECT USING (true);
CREATE POLICY "Allow public read access to audit_log" ON public.audit_log FOR SELECT USING (true);
