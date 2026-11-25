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

| Option | Effect |
|---|---|
| `--user EMAIL` | The user to add data for (optional when there's only one user) |
| `--jobs N` | Create N jobs (default 60) |
| `--days N` | Spread activity over the past N days (default 30) |
| `--seed N` | Use a fixed random seed, for the same data every run |
| `--clear` | Delete that user's companies, contacts, jobs, applications and cover letters first; other users' data is kept (asks to confirm; add `--noinput` to skip) |
| `--force` | Run even when `DEBUG` is off (refused by default, to protect production data) |

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

| Variable | Default in container | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | insecure dev key | **Set this** for anything beyond local testing |
| `DJANGO_DEBUG` | `0` | `1` enables debug mode |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hostnames the app will serve |
| `DJANGO_DB_PATH` | `/app/data/db.sqlite3` | SQLite database file location |
| `DJANGO_MEDIA_ROOT` | `/app/data/uploads` | Folder where uploaded files are stored |
