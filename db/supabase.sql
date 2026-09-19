-- second-brain :: Supabase inbox
--
-- The Shortcut calls capture() and the worker pending(), retry() and claim()
-- through the REST API:
--   POST https://<project>.supabase.co/rest/v1/rpc/<function>
--   header apikey: <publishable key>   ·   JSON body with the parameters
--
-- The table allows no direct reads or writes (RLS on, no policies). Each
-- function compares the sha256 of the token it receives with the one in
-- private.tokens, so tokens are never stored in clear. To register or rotate them:
--   insert into private.tokens values ('capture', '<sha256>'), ('worker', '<sha256>')
--   on conflict (name) do update set sha256 = excluded.sha256;

create extension if not exists pgcrypto with schema extensions;

create table if not exists public.inbox (
  id          bigint generated always as identity primary key,
  url         text not null unique,
  note        text,
  claimed_at  timestamptz,
  created_at  timestamptz not null default now()
);
alter table public.inbox enable row level security;

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create table if not exists private.tokens (
  name    text primary key check (name in ('capture', 'worker')),
  sha256  text not null
);

create or replace function private.token_ok(kind text, token text)
returns boolean
language sql stable security definer set search_path = ''
as $$
  select exists (
    select 1 from private.tokens t
    where t.name = kind
      and t.sha256 = encode(extensions.digest(coalesce(token, ''), 'sha256'), 'hex')
  )
$$;

-- Shortcut. Sharing the same URL again re-queues it with the new note.
create or replace function public.capture(url text, note text default null, token text default null)
returns json
language plpgsql security definer set search_path = ''
as $$
#variable_conflict use_variable
begin
  if not private.token_ok('capture', token) then
    raise exception 'unauthorized' using errcode = '42501';
  end if;
  if url !~* '^https?://' or length(url) > 2048 then
    raise exception 'invalid url' using errcode = '22023';
  end if;
  insert into public.inbox (url, note) values (url, nullif(trim(note), ''))
  on conflict on constraint inbox_url_key
  do update set note = excluded.note, claimed_at = null;
  return json_build_object('status', 'queued');
end
$$;

-- Worker: what's pending, in order of arrival.
create or replace function public.pending(token text)
returns table (id bigint, url text, note text)
language plpgsql stable security definer set search_path = ''
as $$
begin
  if not private.token_ok('worker', token) then
    raise exception 'unauthorized' using errcode = '42501';
  end if;
  return query
    select i.id, i.url, i.note from public.inbox i
    where i.claimed_at is null order by i.id limit 20;
end
$$;

-- Worker: confirmation after processing.
create or replace function public.claim(item_id bigint, token text)
returns json
language plpgsql security definer set search_path = ''
as $$
begin
  if not private.token_ok('worker', token) then
    raise exception 'unauthorized' using errcode = '42501';
  end if;
  update public.inbox i set claimed_at = now() where i.id = item_id;
  return json_build_object('status', 'claimed');
end
$$;

revoke execute on function private.token_ok(text, text) from public, anon, authenticated;
-- anon only (the publishable key): there are no users, so authenticated needs
-- nothing. Supabase warns that anon runs SECURITY DEFINER functions; that's
-- intended, because each one requires its token.
revoke execute on function public.capture(text, text, text), public.pending(text),
  public.claim(bigint, text) from public, authenticated;
grant execute on function public.capture(text, text, text), public.pending(text),
  public.claim(bigint, text) to anon;


-- 2. Worker on GitHub Actions: retries and a GitHub trigger when a capture arrives.
--
-- A transient failure (network, Ollama, rate limits) doesn't confirm the item:
-- retry() counts an attempt and leaves it pending; claim() closes it, with the
-- reason if it failed. When an item is inserted or re-queued, a trigger calls
-- repository_dispatch with a GitHub token stored in the Vault:
--   select vault.create_secret('<GitHub token>', 'github_dispatch_token');
-- Without that secret there's no trigger, and the workflow picks it up on its
-- scheduled run.

create extension if not exists pg_net with schema extensions;

alter table public.inbox add column if not exists attempts int not null default 0;
alter table public.inbox add column if not exists last_error text;

create or replace function public.capture(url text, note text default null, token text default null)
returns json
language plpgsql security definer set search_path = ''
as $$
#variable_conflict use_variable
begin
  if not private.token_ok('capture', token) then
    raise exception 'unauthorized' using errcode = '42501';
  end if;
  if url !~* '^https?://' or length(url) > 2048 then
    raise exception 'invalid url' using errcode = '22023';
  end if;
  insert into public.inbox (url, note) values (url, nullif(trim(note), ''))
  on conflict on constraint inbox_url_key
  do update set note = excluded.note, claimed_at = null, attempts = 0, last_error = null;
  return json_build_object('status', 'queued');
end
$$;

drop function if exists public.pending(text);
create function public.pending(token text)
returns table (id bigint, url text, note text, attempts int)
language plpgsql stable security definer set search_path = ''
as $$
begin
  if not private.token_ok('worker', token) then
    raise exception 'unauthorized' using errcode = '42501';
  end if;
  return query
    select i.id, i.url, i.note, i.attempts from public.inbox i
    where i.claimed_at is null order by i.id limit 20;
end
$$;

drop function if exists public.claim(bigint, text);
create function public.claim(item_id bigint, token text, reason text default null)
returns json
language plpgsql security definer set search_path = ''
as $$
begin
  if not private.token_ok('worker', token) then
    raise exception 'unauthorized' using errcode = '42501';
  end if;
  update public.inbox i set claimed_at = now(), last_error = reason where i.id = item_id;
  return json_build_object('status', 'claimed');
end
$$;

create or replace function public.retry(item_id bigint, token text, reason text default null)
returns json
language plpgsql security definer set search_path = ''
as $$
begin
  if not private.token_ok('worker', token) then
    raise exception 'unauthorized' using errcode = '42501';
  end if;
  update public.inbox i set attempts = i.attempts + 1, last_error = reason where i.id = item_id;
  return json_build_object('status', 'retry');
end
$$;

-- Launches the capture workflow of the private wiki repository as soon as a
-- capture arrives. Both values live in the Vault (without them, nothing is sent
-- and the workflow's schedule picks captures up):
--   select vault.create_secret('<fine-grained token>', 'github_dispatch_token');
--   select vault.create_secret('<owner>/second-brain-wiki', 'github_dispatch_repo');
create or replace function private.dispatch_capture()
returns trigger
language plpgsql security definer set search_path = ''
as $$
declare
  gh_token text := (select s.decrypted_secret from vault.decrypted_secrets s
                    where s.name = 'github_dispatch_token');
  gh_repo text := (select s.decrypted_secret from vault.decrypted_secrets s
                   where s.name = 'github_dispatch_repo');
begin
  if gh_token is not null and gh_repo is not null then
    perform net.http_post(
      url := 'https://api.github.com/repos/' || gh_repo || '/dispatches',
      headers := jsonb_build_object(
        'Authorization', 'Bearer ' || gh_token,
        'Accept', 'application/vnd.github+json',
        'X-GitHub-Api-Version', '2022-11-28',
        'User-Agent', 'second-brain-supabase'),
      body := jsonb_build_object('event_type', 'capture'));
  end if;
  return new;
end
$$;

drop trigger if exists inbox_dispatch on public.inbox;
create trigger inbox_dispatch
  after insert or update of claimed_at on public.inbox
  for each row when (new.claimed_at is null)
  execute function private.dispatch_capture();

revoke execute on function private.dispatch_capture() from public, anon, authenticated;
revoke execute on function public.pending(text), public.claim(bigint, text, text),
  public.retry(bigint, text, text) from public, authenticated;
grant execute on function public.pending(text), public.claim(bigint, text, text),
  public.retry(bigint, text, text) to anon;


-- 3. Image captures: a shared screenshot or photo has no URL, only its bytes.
--
-- The Shortcut calls capture_image() with the image base64-encoded; the worker
-- keys it by its content hash, so the same image shared twice isn't filed twice.
-- url becomes nullable (a row is either a URL or an image), and the base64 lives
-- in the row but stays out of pending(): the worker pulls it with fetch_image()
-- only for the capture it's about to file, so a poll doesn't drag every image.

alter table public.inbox alter column url drop not null;
alter table public.inbox add column if not exists image text;  -- base64
alter table public.inbox add column if not exists mime text;
alter table public.inbox drop constraint if exists inbox_has_content;
alter table public.inbox add constraint inbox_has_content check (url is not null or image is not null);

create or replace function public.capture_image(image text, mime text, note text default null,
                                                token text default null)
returns json
language plpgsql security definer set search_path = ''
as $$
#variable_conflict use_variable
begin
  if not private.token_ok('capture', token) then
    raise exception 'unauthorized' using errcode = '42501';
  end if;
  if mime is null or mime not in ('image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif') then
    raise exception 'unsupported image type' using errcode = '22023';
  end if;
  if image is null or length(image) < 64 or length(image) > 12000000 then  -- ~9 MB of image
    raise exception 'invalid image' using errcode = '22023';
  end if;
  insert into public.inbox (mime, image, note) values (mime, image, nullif(trim(note), ''));
  return json_build_object('status', 'queued');
end
$$;

drop function if exists public.pending(text);
create function public.pending(token text)
returns table (id bigint, url text, note text, mime text, attempts int)
language plpgsql stable security definer set search_path = ''
as $$
begin
  if not private.token_ok('worker', token) then
    raise exception 'unauthorized' using errcode = '42501';
  end if;
  return query
    select i.id, i.url, i.note, i.mime, i.attempts from public.inbox i
    where i.claimed_at is null order by i.id limit 20;
end
$$;

-- Worker: the base64 image of one row, only when it's the row being filed.
create or replace function public.fetch_image(item_id bigint, token text)
returns text
language plpgsql stable security definer set search_path = ''
as $$
declare data text;
begin
  if not private.token_ok('worker', token) then
    raise exception 'unauthorized' using errcode = '42501';
  end if;
  select i.image into data from public.inbox i where i.id = item_id;
  return data;
end
$$;

revoke execute on function public.capture_image(text, text, text, text),
  public.fetch_image(bigint, text), public.pending(text) from public, authenticated;
grant execute on function public.capture_image(text, text, text, text) to anon;  -- capture token
grant execute on function public.fetch_image(bigint, text), public.pending(text) to anon;  -- worker token
