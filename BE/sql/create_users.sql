CREATE TABLE public.users (
    id         bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kakao_id   bigint      NOT NULL UNIQUE,
    nickname   text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.users FROM PUBLIC, anon, authenticated;
