# Production

The production stack of Cocos (`docker/docker-compose.prod.yml`) is:

                         Nginx
                           │
                           ▼
                       Gunicorn
                           │
                           ▼
                         Django
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
          PostgreSQL      Redis       Celery

| Container        | What                    |
| ---------------- | ----------------------- |
| `cocos-nginx`    | Nginx reverse proxy     |
| `cocos-web`      | Django + Gunicorn       |
| `cocos-worker`   | Celery worker           |
| `cocos-postgres` | PostgreSQL              |
| `cocos-redis`    | Redis, the Celery broker |

Nginx is the public entry point, on ports 80 and 443, and acts as a reverse proxy for the Django application; the Django/Gunicorn container is not exposed to the host. The application data and uploaded files are stored in Docker volumes. The web and worker containers run as the unprivileged user `app`, not as root. The image compiles the CSS and copies the JavaScript libraries when it is built.

Cocos reaches the bio service (assembly and annotation) at `ANNOTATION_BASE`, `http://bio-assembly-api:8000` by default, through the `cocos-network` Docker network. The bio service has no authentication and publishes no ports, so users only reach it through Cocos. It lives in the [Cocos-deployment](https://github.com/DEAL-US/Cocos-deployment) repository, whose README explains how to start it.

## Configuration

The configuration is in `.env.prod`, which is not committed. The setup script prepares it. From the `cocos` folder run:

```bash
python scripts/setup_prod.py
```

It creates `.env.prod` from `.env.prod.example` if needed, generates the Django secret key and the database password while they still have their example values, and lists the values you still have to fill in. Values that are already set are never overwritten.

To do it by hand instead, copy `.env.prod.example` to `.env.prod` and replace its example values:

| Variable                                                      | Value                                                                       |
| ------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `DJANGO_SECRET_KEY`                                           | A long random key (see below)                                               |
| `DJANGO_ALLOWED_HOSTS`                                        | The domain of the deployment, e.g. `cocos.example.com`                      |
| `DJANGO_CSRF_TRUSTED_ORIGINS`                                 | Its HTTPS origin, e.g. `https://cocos.example.com`                          |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`           | The database the PostgreSQL container creates, with a strong password       |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`                           | The same values as `POSTGRES_*`: Django connects to that database           |
| `DB_HOST`                                                     | `cocos-postgres`, the PostgreSQL container                                  |
| `SENDGRID_API_KEY`, `DEFAULT_FROM_EMAIL`                      | For email notifications                                                     |

Generate a Django secret key with:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

With `DJANGO_DEBUG=0`, Django refuses to start (`ImproperlyConfigured`) if `DJANGO_SECRET_KEY` or `DB_PASSWORD` is not set: they have defaults only in development.

## Start

From [Cocos-deployment](https://github.com/DEAL-US/Cocos-deployment), `python deploy.py --prod` starts the bio service and this stack, after running `setup_prod.py` on `.env.prod`.

To start only this stack, when `setup_prod.py` reports that `.env.prod` is ready, run:

```bash
python scripts/setup_prod.py --start
```

or by hand, from the `cocos/docker` folder:

```bash
docker compose --env-file ../.env.prod -f docker-compose.prod.yml -p cocos-prod up --build -d
```

Cocos is then at `http://localhost` (port 80), or at its domain.
