-- Valores manuales del panel agro de ARGO (un valor por clave, compartido).
-- Acceso solo desde el servidor con la secret key (service role): RLS activo y
-- sin policies para anon/authenticated.
create table if not exists public.argo_valores_manuales (
  clave text primary key,
  valor double precision not null,
  actualizado timestamptz not null default now()
);

alter table public.argo_valores_manuales enable row level security;
revoke all on public.argo_valores_manuales from anon, authenticated;
