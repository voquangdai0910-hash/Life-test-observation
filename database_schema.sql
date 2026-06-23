-- Users Table (using direct PostgreSQL, no Supabase Auth dependency)
CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    full_name TEXT,
    password_hash TEXT,
    role TEXT CHECK (role IN ('operator', 'access_person', 'admin')) DEFAULT 'operator',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Data Uploads Table
CREATE TABLE IF NOT EXISTS public.data_uploads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    test_name TEXT NOT NULL,
    description TEXT,
    data JSONB,
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    file_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Testing Sessions Table
CREATE TABLE IF NOT EXISTS public.testing_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    test_name TEXT NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP WITH TIME ZONE,
    status TEXT CHECK (status IN ('running', 'completed', 'paused', 'cancelled')) DEFAULT 'running',
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Upload Configuration Table
CREATE TABLE IF NOT EXISTS public.upload_config (
    id INTEGER PRIMARY KEY DEFAULT 1,
    interval_minutes INTEGER DEFAULT 240,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_by UUID REFERENCES public.users(id),
    CONSTRAINT single_row CHECK (id = 1)
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_data_uploads_operator_id ON public.data_uploads(operator_id);
CREATE INDEX IF NOT EXISTS idx_data_uploads_uploaded_at ON public.data_uploads(uploaded_at);
CREATE INDEX IF NOT EXISTS idx_testing_sessions_operator_id ON public.testing_sessions(operator_id);
CREATE INDEX IF NOT EXISTS idx_testing_sessions_status ON public.testing_sessions(status);
CREATE INDEX IF NOT EXISTS idx_users_role ON public.users(role);

-- Enable RLS (Row Level Security)
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.data_uploads ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.testing_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.upload_config ENABLE ROW LEVEL SECURITY;

-- RLS Policies for users table
CREATE POLICY "Users can view their own profile" ON public.users
    FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Users can update their own profile" ON public.users
    FOR UPDATE USING (auth.uid() = id);

-- RLS Policies for data_uploads table
CREATE POLICY "Operators can view their own uploads" ON public.data_uploads
    FOR SELECT USING (
        operator_id = auth.uid() OR
        EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND role IN ('access_person', 'admin'))
    );

CREATE POLICY "Operators can insert their own uploads" ON public.data_uploads
    FOR INSERT WITH CHECK (operator_id = auth.uid());

CREATE POLICY "Access persons can view all uploads" ON public.data_uploads
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND role IN ('access_person', 'admin'))
    );

-- RLS Policies for testing_sessions table
CREATE POLICY "Operators can view their own sessions" ON public.testing_sessions
    FOR SELECT USING (
        operator_id = auth.uid() OR
        EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND role IN ('access_person', 'admin'))
    );

CREATE POLICY "Operators can insert their own sessions" ON public.testing_sessions
    FOR INSERT WITH CHECK (operator_id = auth.uid());

CREATE POLICY "Operators can update their own sessions" ON public.testing_sessions
    FOR UPDATE USING (operator_id = auth.uid());

-- RLS Policies for upload_config table
CREATE POLICY "Anyone can view upload config" ON public.upload_config
    FOR SELECT USING (true);

CREATE POLICY "Only admins can update upload config" ON public.upload_config
    FOR UPDATE USING (
        EXISTS (SELECT 1 FROM public.users WHERE id = auth.uid() AND role = 'admin')
    );

-- Insert default upload config
INSERT INTO public.upload_config (id, interval_minutes) VALUES (1, 240)
ON CONFLICT (id) DO NOTHING;
