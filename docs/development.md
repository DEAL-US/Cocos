# Development

Cocos sends the assembly and annotation jobs to a separate bio service, which lives in the [Cocos-deployment](https://github.com/DEAL-US/Cocos-deployment) repository together with a mock of it. The easiest way to develop is to clone that repository, which includes this one as a submodule, and start everything with its `deploy.py`:

```bash
git clone --recurse-submodules https://github.com/DEAL-US/Cocos-deployment.git
cd Cocos-deployment
python deploy.py --mock
```

This starts the mock of the bio service and the development stack of Cocos described below, at `http://localhost:8080`. See the README of Cocos-deployment for the other options, such as the real bio service.

## Setup

From the `cocos` folder run:

```bash
python scripts/setup_dev.py
```

This sets up:

- `.env`, copied from `.env.example` if it does not exist yet
- Python dependencies from `requirements.txt`
- Frontend dependencies (`tailwindcss` + `daisyui`, `cytoscape` + `cytoscape-dagre`) from `app/package.json`
- Compiled CSS output at `app/static/css/tailwind.css` and the JavaScript libraries in `app/static/vendor/` (`npm run build`)

## Development Stack

`docker/docker-compose.yml` is the Docker Compose project `cocos-dev`:

| Container            | What                                                                                     |
| -------------------- | ---------------------------------------------------------------------------------------- |
| `cocos-dev-web`      | Django development server, at `http://localhost:8080`                                    |
| `cocos-dev-worker`   | Celery worker                                                                            |
| `cocos-dev-postgres` | PostgreSQL, published on `127.0.0.1:5432`                                                |
| `cocos-dev-redis`    | Redis, the Celery broker                                                                 |
| `cocos-dev-frontend` | Compiles the CSS and copies the JavaScript libraries, and compiles the CSS again on changes |

`deploy.py` starts it, but it can also be started on its own. It joins the Docker network `cocos-network`, which it shares with the bio service, so that network has to exist first:

```bash
docker network create cocos-network
cd docker
docker compose up
```

Without the bio service (or its mock) the web interface works, but assembly and annotation jobs fail.

The stack mounts the application source code into the containers, so changes to the code, the templates and the Tailwind classes are reflected without rebuilding the image. The frontend container installs the npm dependencies, copies the JavaScript libraries to `app/static/vendor/` and compiles `app/static/css/tailwind.css`, then compiles the CSS again whenever a template, Python or JavaScript file changes (it checks every 2 seconds, since Docker on Windows does not report changes in mounted folders).

PostgreSQL is published on `127.0.0.1:5432`, so tests and `runserver` on the host can reach it but other machines cannot. Management commands can also run in the web container, e.g. `docker exec cocos-dev-web python manage.py check`.

The first build can take a while, because of the large machine learning dependencies (`torch`). Later builds reuse the Docker layer cache while `requirements.txt` does not change.

## Environment Variables

`.env` is not committed: `.env.example` is its template. Its values work as they are for development, and the commented ones are optional.

- `DB_HOST=localhost` is for Django running on the host (tests, `runserver`); the containers get `cocos-dev-postgres` from the compose file.
- `MOCK=true` sends the jobs to the mock of the bio service (`MOCK_ANNOTATION_BASE`) instead of the real one (`ANNOTATION_BASE`).
- With `DJANGO_DEBUG=1`, emails are printed to the console, and `DJANGO_SECRET_KEY` and `DB_PASSWORD` have development defaults.

## Testing

Dependencies are split in two files:

- `requirements.txt` - what the application needs to run (installed in the Docker image).
- `requirements-dev.txt` - test tools (`coverage`, `responses`, and `roc-validator`, which checks the RO-Crates of the predictions). It includes `requirements.txt`, so a single command installs everything:

```bash
pip install -r requirements-dev.txt
```

The tests need the PostgreSQL database configured in `.env`. The bio service is mocked at HTTP level and Celery tasks run synchronously, so neither the bio service nor Redis/Celery workers have to be running.

From the `app` folder, run all tests:

```bash
python manage.py test
```

Run tests for specific app:

```bash
python manage.py test notifications
```

Measure test coverage:

```bash
python -m coverage run --source=. --omit="*/migrations/*,*/tests/*,manage.py,app/wsgi.py,app/asgi.py,core/testing.py" manage.py test
python -m coverage report
```
