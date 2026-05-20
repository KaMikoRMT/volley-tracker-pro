-- VolleyTracker Pro — Supabase 資料庫建置腳本
-- 在 Supabase SQL Editor 貼上並執行此腳本即可

-- ══════════════════════════════════════════════════════════════════════════════
-- 資料表
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.users (
    code       TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS public.matches (
    id          BIGSERIAL PRIMARY KEY,
    user_code   TEXT    NOT NULL REFERENCES public.users(code) ON DELETE CASCADE,
    match_name  TEXT    NOT NULL,
    players     JSONB   NOT NULL DEFAULT '[]',
    logs        JSONB   NOT NULL DEFAULT '[]',
    current_set INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_matches_user_code ON public.matches(user_code);

-- ══════════════════════════════════════════════════════════════════════════════
-- Row Level Security（RLS）
-- 使用 anon key 即可讀寫，透過 user_code 做應用層隔離
-- ══════════════════════════════════════════════════════════════════════════════

ALTER TABLE public.users  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.matches ENABLE ROW LEVEL SECURITY;

-- 開放 anon 角色完整存取（應用層自行驗證 user_code）
CREATE POLICY "anon_all_users"   ON public.users   FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "anon_all_matches" ON public.matches FOR ALL TO anon USING (true) WITH CHECK (true);
