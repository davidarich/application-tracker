# Application Tracker

Job application tracker written in Python using the Django framework.

## Features

### Jobs and applications

- **Dashboard** with an area chart of your jobs by status over the past two
  weeks.
- **Jobs page** with three views of the same jobs:
  - **Table:** search, filters, sorting and paging.
  - **List:** large cards with each job's details, skills and a collapsible
    description.
  - **Kanban:** a board with a column per open status. Change a job's status
    from the card's menu or by dragging the card by its handle, with Undo for
    each move.
- **Job pages** with the job's details, skills, description and full status
  history. Jobs track location, workplace type (in office, hybrid or remote),
  salary range, posting link and skills.
- **Hiring system detection:** a job's page shows which applicant tracking
  system its posting link belongs to, such as Greenhouse, Lever, Workday or
  Ashby.
- **Clean posting links:** links are saved without tracking parameters
  (`utm_source`, `gclid`, `ref` and the like). Anything that resembles an ID,
  such as `gh_jid` or `jobId`, is kept, and so are other parameters a hiring
  system may need. The rules are in `tracker/posting_urls.py`.
- **Statuses:** Applied, Responded, Interviewing, Offer, Closed and Ignored
  (for jobs you've decided not to pursue). The history of every status change
  is recorded.

### Companies and contacts

- **Companies list** with search and paging, and a page for each company with
  its details, mission statement, contacts and jobs.
- **Contacts** at each company, with email, phone and LinkedIn profile.

### Resume

- **Resume page** with a summary, work history, skills, education and
  certifications.
- **Career breaks:** work history entries without an employer, such as a
  sabbatical or medical leave.
- **In-progress education and certifications** with an expected completion
  date.
- **Fill in from resume:** upload a PDF and the summary, positions, skills,
  education and certifications are picked out with rules (no AI), including
  two-column layouts. Everything is shown on a review page to correct before
  anything is added. The uploaded PDF is kept with your resume, so you can
  download it later.

### Data and accounts

- **Private data:** each user sees only their own records.
- **Soft delete with Undo** for companies, jobs, resume entries and skills,
  plus **Recently deleted** pages to restore them later.
- **Shared skills list** managed by staff from the app's Admin section.
- **Accounts:** log in with your email address. Your profile includes a
  preferred name, phone number and profile photo.
- **Mock data:** a `seed` command creates realistic, fictional data for
  development.

### API

- **JSON REST API** to add, read and update jobs, companies and skills, with
  interactive docs. A job can name its company, which is created if it's new,
  and set its status, which is added to the status history.
- **OAuth 2.0 authentication** (the refresh token grant): refresh tokens
  are created and revoked on the API tokens page and exchanged for
  short-lived access tokens.
- **Runs on its own:** the API can be served by a separate container, sharing
  the database with the web app.
- **Creation source:** companies, jobs and skills record whether they were
  added in the app (Manual) or through the API, shown on each one's page.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py tailwind runserver
```

`createsuperuser` asks for your email address, name and phone number (with
its country code, e.g. `+1 555 123 4567`). Then open http://127.0.0.1:8000/ and
log in with that email address and password. You'll land on the dashboard. The
admin is at http://127.0.0.1:8000/admin/.

Users are an `accounts.User` model (see `accounts/models.py`): people log in
with their email address, which is matched ignoring case.

### Mock data

To fill the dashboard with realistic, entirely fictional data for development:

```powershell
python manage.py seed
```

This adds 60 jobs across 30 companies for a user, with contacts, applications,
cover letters and a status history spread over the past 30 days, so the chart
and job table have something to show. Running it again adds more jobs and
reuses that user's companies.

It also creates 40 shared skills (programming languages, frameworks, DevOps
tools and public cloud features) the first time it runs, and gives each seeded
job a mix of them. Skills belong to no user, so they're only created once and
`--clear` leaves them in place.

| Option         | Effect                                                                                                                                                   |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--user EMAIL` | The user to add data for (optional when there's only one user)                                                                                           |
| `--jobs N`     | Create N jobs (default 60)                                                                                                                               |
| `--days N`     | Spread activity over the past N days (default 30)                                                                                                        |
| `--seed N`     | Use a fixed random seed, for the same data every run                                                                                                     |
| `--clear`      | Delete that user's companies, contacts, jobs, applications and cover letters first; other users' data is kept (asks to confirm; add `--noinput` to skip) |
| `--force`      | Run even when `DEBUG` is off (refused by default, to protect production data)                                                                            |

### Users and data

Each user has their own private data. Companies and uploaded files belong to a
user (`user_owner`); contacts, jobs, applications, cover letters and status
history belong to whoever owns their company. Views get data only through
`tracker/ownership.py`, so the dashboard always shows just the logged-in user's
records, superusers included. In the admin, superusers see every user's records,
with a **User owner** column and filter.

Uploaded files are private too: they're stored as
`uploads/files/<user id>/<random id>.<ext>` and served only to their owner (or a
superuser), as downloads, never as public media.

### Styling

The app is styled with [Tailwind CSS](https://tailwindcss.com/) through
[django-tailwind-cli](https://django-tailwind-cli.rtfd.io/), which runs
Tailwind's standalone CLI, so Node.js isn't needed. The CLI is downloaded to
`.django_tailwind_cli/` on first use.

- `tailwind/app.css` holds the theme (colours, fonts) and shared form styles.
- `python manage.py tailwind runserver` starts the dev server and recompiles
  the CSS whenever a template or `tailwind/app.css` changes.
- `python manage.py tailwind build` compiles the CSS once, to
  `assets/css/tailwind.css`. That file is generated, so it isn't committed. The
  Docker build compiles it.

`requirements-dev.txt` installs the app's dependencies from `requirements.txt`
plus the development tools: [Ruff](https://docs.astral.sh/ruff/) for linting,
[basedpyright](https://docs.basedpyright.com/) for type checking and
[django-types](https://github.com/sbdchd/django-types) for Django type
information. To install only what the app needs to run, use
`pip install -r requirements.txt` instead.

### Checks

```powershell
ruff check .
ruff format --check .
basedpyright
python manage.py test
```

`pyrightconfig.json` points basedpyright at `.venv`, so editors that use
basedpyright or Pyright (such as Zed) find the same packages as the command line.

## API

The JSON API is at `/api/v1/`, built with
[Django Ninja](https://django-ninja.dev/) in the `api` app. Interactive docs
(which can send requests too) are at http://127.0.0.1:8000/api/v1/docs, and the
OpenAPI schema at `/api/v1/openapi.json`. In the docs, **Authorize** takes an
access token (see below), not a refresh token.

### Authentication (OAuth 2.0)

The API uses OAuth 2.0 with the refresh token grant
([RFC 6749](https://www.rfc-editor.org/rfc/rfc6749#section-6)) and bearer
access tokens ([RFC 6750](https://www.rfc-editor.org/rfc/rfc6750)):

1. On the **API tokens** page (under **Account** in the sidebar), give the
   token a name (what will use it) and select **Create token**. You get a **refresh token**
   (`rt_...`), shown once.
2. The program exchanges the refresh token at the token endpoint. It gets an
   **access token** (`at_...`) that lasts 15 minutes, and a **new refresh
   token**:

   ```powershell
   $tokens = Invoke-RestMethod http://127.0.0.1:8000/api/v1/oauth/token -Method Post `
     -Body @{ grant_type = "refresh_token"; refresh_token = "rt_..." }
   # $tokens: access_token, token_type ("Bearer"), expires_in (900), refresh_token
   ```

3. Every other request sends the access token:

   ```powershell
   $headers = @{ Authorization = "Bearer $($tokens.access_token)" }
   Invoke-RestMethod http://127.0.0.1:8000/api/v1/jobs -Headers $headers
   ```

4. Shortly before the access token expires (`expires_in` seconds after the
   exchange), or when a request gets a 401, the program exchanges its latest
   refresh token again.

An access token can be used for any number of requests, in parallel, until it
expires, so rapid requests need only one exchange every 15 minutes.

**How the tokens behave**

- **Each refresh token works once:** the program must keep the new one from
  each exchange. Sending a used refresh token again means it may have been
  copied, so that token's access is revoked: every token it led to stops
  working, and you create a new one on the API tokens page. There's no grace
  period, so this includes two exchanges of the same refresh token at the same
  moment.
- **Exchange one at a time:** a program that makes requests in parallel should
  let only one exchange run, with the other requests waiting for its result:

  ```js
  let refreshing = null
  async function accessToken() {
    if (tokens.expiresAt - Date.now() > 60_000) return tokens.access // refresh a minute early
    refreshing ??= refresh().finally(() => {
      refreshing = null
    }) // one exchange at a time
    return (await refreshing).access
  }
  ```

- **Refresh tokens expire** 90 days after they're issued, if not exchanged by
  then. Each exchange gives a new one, so a program that exchanges at least
  every 90 days never needs a new token from the API tokens page.
- **Requests send only the access token.** A refresh token sent as the bearer
  token is refused, with a message saying to exchange it.
- **Tokens are opaque and stored only as hashes.** Revoking access on the
  API tokens page, or deactivating a user, takes effect immediately. Staff can
  also revoke access in the admin, under **API grants**.
- **The token endpoint:**
  - takes form-encoded parameters (`application/x-www-form-urlencoded`), as
    OAuth requires.
  - needs no client ID: clients are public, and the refresh token is the
    credential.
  - answers errors in OAuth's format: `{"error": "invalid_grant",
"error_description": "..."}`, with `invalid_request`, `invalid_grant` or
    `unsupported_grant_type`.
- **No cookies or CSRF:** the API never uses the site's login cookie, so it
  needs no CSRF token.
- **Kept out of logs and error reports:** tokens are never accepted in URLs,
  pages and responses that show a token aren't cached, and server error
  reports leave out tokens.
- **Serve it over HTTPS:** OAuth 2.0 requires TLS, since anyone who can read the
  traffic can use the tokens. The app and its containers serve plain HTTP, so
  put them behind an HTTPS reverse proxy before using them anywhere but your
  own machine.

### Endpoints

| Method and path                       | What it does                                                                                                                                                                                                                                                                                                                       |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST /api/v1/oauth/token`            | Exchange a refresh token for an access token and a new refresh token (no access token needed)                                                                                                                                                                                                                                      |
| `GET /api/v1/companies`               | Your companies, by name. `q` searches names                                                                                                                                                                                                                                                                                        |
| `POST /api/v1/companies`              | Add a company                                                                                                                                                                                                                                                                                                                      |
| `GET`, `PATCH /api/v1/companies/{id}` | Read or change a company                                                                                                                                                                                                                                                                                                           |
| `GET /api/v1/jobs`                    | Your jobs, most recently updated first. Filters: `q` (title or company), `status` (`all` by default, `open`, `none` for not applied, or a status), `company` (an ID) and `posting_url` (the same posting as this link, e.g. to check whether a posting is already saved: copies that differ only in tracking parameters, http or https, `www.`, letter case, a trailing slash, parameter order or an `#anchor` match) |
| `POST /api/v1/jobs`                   | Add a job                                                                                                                                                                                                                                                                                                                          |
| `GET`, `PATCH /api/v1/jobs/{id}`      | Read or change a job, including its status                                                                                                                                                                                                                                                                                         |
| `GET /api/v1/skills`                  | The shared skills, by name. `q` searches names and descriptions                                                                                                                                                                                                                                                                    |
| `POST /api/v1/skills`                 | Add a skill (staff only)                                                                                                                                                                                                                                                                                                           |
| `GET`, `PATCH /api/v1/skills/{id}`    | Read or change (staff only) a skill                                                                                                                                                                                                                                                                                                |

Deleting isn't offered through the API yet.

- **Lists** take `limit` (default 25, at most 100) and `offset`, and return
  `{"count": <all matches>, "items": [...]}`.
- **PATCH** changes only the fields sent.
- **`creation_source`** in companies, jobs and skills is `manual` (added in the
  app or the admin) or `api` (added through the API, including a company
  created for a job's `company_name`). It's read-only: it's set when the record
  is created and ignored in request bodies.
- **`posting_url`** is saved without tracking parameters, as on the site.
- **`hiring_system`** in jobs is the applicant tracking system the posting link
  belongs to, such as `"Greenhouse"`, or `null` if there's no link or it isn't
  recognised. It's read-only.
- **Validation** is the same as the site's forms: unique company and skill
  names (ignoring case), valid URLs, and a minimum salary no higher than the
  maximum.
- **Other users' records** are answered with 404, as if they didn't exist.

Adding a job:

```powershell
$job = @{
  company_name = "Acme Robotics"   # or "company": "<one of your company IDs>"
  title = "Platform Engineer"
  workplace_type = "remote"        # "", "in_office", "hybrid" or "remote"
  salary_min = 140000
  salary_max = 170000
  skills = @("Python", "Kubernetes")
  status = "applied"               # leave out for a job you haven't applied to
} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/api/v1/jobs -Method Post `
  -Headers $headers -ContentType "application/json" -Body $job
```

- **`company_name`** is matched to one of your companies ignoring case. A new
  company is created if none matches, so a slightly different spelling makes a
  second company.
- **`skills`** are names (ignoring case) or IDs of existing skills. Unknown
  skills are refused, since only staff add skills.
- **`status`** is one of `applied`, `responded`, `interviewing`, `offer`,
  `closed` or `ignored`. Each change, on create or PATCH, is added to the job's
  status history, as on the site.

**Errors** are JSON with a `detail` message (the token endpoint uses OAuth's
format instead, described above):

| Status | Meaning                                                                                             |
| ------ | --------------------------------------------------------------------------------------------------- |
| 400    | The body isn't valid JSON                                                                           |
| 401    | No access token, or one that's wrong, expired or revoked (with a `WWW-Authenticate: Bearer` header) |
| 403    | Staff only (adding or changing skills)                                                              |
| 404    | No such record, or it isn't yours                                                                   |
| 409    | Clashed with a record saved at the same moment; try again                                           |
| 422    | Invalid fields: `errors` lists each field's messages, e.g. `{"title": ["Field required"]}`          |

### Running the API on its own

`DJANGO_ROLE` sets what a process serves:

- **`web`** (the default) serves the site with the API at `/api/v1/`.
- **`api`** serves only the API: no pages, admin, sessions or CSRF.

To try the API-only process locally, next to the site:

```powershell
$env:DJANGO_ROLE = "api"; python manage.py runserver 8001; Remove-Item Env:DJANGO_ROLE
```

Both processes can share the SQLite file: the database runs in WAL mode, so
one can read while the other writes, and writers wait their turn for up to 20
seconds. This works on one machine (not on a network drive). When the web app
and API move to separate machines, switch both to a database server such as
PostgreSQL.

## Docker

```powershell
docker build -t app-tracker .
docker run -d --name app-tracker -p 8000:8000 `
  -e DJANGO_SECRET_KEY="<a long random string>" `
  -v app-tracker-data:/app/data `
  app-tracker
docker exec -it app-tracker python manage.py createsuperuser
```

Then open http://localhost:8000/admin/. The SQLite database is stored in the
`app-tracker-data` volume, so it survives container rebuilds.

### Web app and API in separate containers

The Dockerfile has two targets: `web` (the default, the site with the API) and
`api` (only the API, without the site's stylesheet build). `compose.yaml` runs
both, sharing the `app-tracker-data` volume:

```powershell
$env:DJANGO_SECRET_KEY = "<a long random string>"
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

The site is at http://localhost:8000/ and the API-only container at
http://localhost:8001/api/v1/. Only `web` runs migrations. `api` starts once
`web` is healthy, and refuses to start while the database has migrations it
hasn't applied.

| Variable               | Default in container             | Purpose                                                      |
| ---------------------- | -------------------------------- | ------------------------------------------------------------ |
| `DJANGO_SECRET_KEY`    | insecure dev key                 | **Set this** for anything beyond local testing               |
| `DJANGO_DEBUG`         | `0`                              | `1` enables debug mode                                       |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1`            | Comma-separated hostnames the app will serve                 |
| `DJANGO_DB_PATH`       | `/app/data/db.sqlite3`           | SQLite database file location                                |
| `DJANGO_MEDIA_ROOT`    | `/app/data/uploads`              | Folder where uploaded files are stored                       |
| `DJANGO_ROLE`          | `web` (`api` in the `api` image) | `web` serves the site and the API; `api` serves only the API |
