# cocos

Framework for integrating and deploying antibiotic resistance prediction models in genomic analysis workflows.

COCOS provides a web interface that allows users to process genomic data and obtain antibiotic resistance predictions from multiple registered prediction models. The framework is designed to facilitate the use of research models by users without requiring direct interaction with the underlying machine learning implementations.

---

## Quick Start

### Development Setup

From the `cocos` folder run:

```powershell
python scripts/setup_dev.py
```

This sets up:

- `.env`, copied from `.env.example` if it does not exist yet
- Python dependencies from `requirements.txt`
- Frontend dependencies (`tailwindcss` + `daisyui`) from `app/package.json`
- Compiled CSS output at `app/static/css/tailwind.css`

Then start the dev server:

```bash
cd docker
docker compose -f docker-compose.yml up
```

The development environment includes:

- Django development server
- PostgreSQL
- Redis
- Celery worker

Access at: `http://localhost:8080`

The development environment mounts the application source code into the containers, so changes to the code are reflected without rebuilding the image.

### Production Deployment

The production environment uses:

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

Nginx is the public entry point and acts as a reverse proxy for the Django application.

The Django/Gunicorn container is not directly exposed to the host.

The setup script prepares `.env.prod` and starts the stack. From the `cocos` folder run:

```bash
python scripts/setup_prod.py
```

It creates `.env.prod` from `.env.prod.example` if needed, generates the Django secret key and the database password while they still have their example values, and lists the values you still have to fill in (e.g. the domain). Values that are already set are never overwritten. When it reports that `.env.prod` is ready, start the stack with:

```bash
python scripts/setup_prod.py --start
```

To do it by hand instead, from the `cocos/docker` folder:

```bash
# Configure environment (copy template and fill with real values)
cp ../.env.prod.example ../.env.prod
```

Then edit `.env.prod` and configure the required values. At minimum, production requires:

```
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=<strong-secret-key>

DB_NAME=<database-name>
DB_USER=<database-user>
DB_PASSWORD=<strong-password>
DB_HOST=postgres
DB_PORT=5432

POSTGRES_DB=<database-name>
POSTGRES_USER=<database-user>
POSTGRES_PASSWORD=<strong-password>
```

Generate a Django secret key with:

```
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

If email notifications are enabled, configure:

```
SENDGRID_API_KEY=<api-key>
```

The production domain is configured through environment variables:

```
DJANGO_ALLOWED_HOSTS=<domain>
DJANGO_CSRF_TRUSTED_ORIGINS=https://<domain>
```

For example:

```
DJANGO_ALLOWED_HOSTS=cocos.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://cocos.example.com
```

These values depend on the domain assigned to the deployment.

To start the production environment, run:

```
docker compose --env-file ../.env.prod -f docker-compose.prod.yml -p cocos-prod up --build -d
```

The production stack contains:

- `cocos-web` - Django + Gunicorn
- `cocos-worker` - Celery worker
- `cocos-nginx` - Nginx reverse proxy
- `cocos-postgres` - PostgreSQL
- `cocos-redis` - Redis

The application data and uploaded files are stored in Docker volumes.

Access at: `http://localhost` (port 80)

---

## Environment Configuration

Environment files are not committed. `.env.example` and `.env.prod.example` are templates: copy them to `.env` and `.env.prod` (the setup scripts do it for you) and fill in the values.

### Development (`.env`)

- `DB_HOST=localhost` (PostgreSQL on host)
- `DJANGO_DEBUG=1`

### Production (`.env.prod`)

- `DB_HOST=cocos-postgres` (Docker service name)
- `DJANGO_DEBUG=0`
- **MUST SET SECURELY:**
  - `DJANGO_SECRET_KEY` - Generate with: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
  - `POSTGRES_PASSWORD` - Strong, random password
  - `DB_PASSWORD` - Same as POSTGRES_PASSWORD
  - `SENDGRID_API_KEY` - If using email notifications

---

## Database & Docker

**Environment variables:**

- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_CONN_MAX_AGE`
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (Docker postgres service)

**First build** can take time due to large ML dependencies (`torch`, etc.). Subsequent runs use Docker layer cache.

---

## Extending COCOS

Prediction models and annotation parsers are plug-ins: each one is a folder that COCOS discovers when it starts, so adding one does not require changing the rest of the code.

| To add | Create | Becomes the step |
|---|---|---|
| A prediction model | `app/ai_models/<model_name>/` | `predict_<model_name>` |
| An annotation parser | `app/parsers/<parser_name>/` | `extract_<parser_name>` |

### Add New Prediction Models

Add a folder under `app/ai_models/` with this structure:

```
app/ai_models/<model_name>/
├── weights/
│   ├── <antibiotic>.pt      # model weights per antibiotic
│   └── ...
└── model_classes.py         # model definition & adapter
```

**Rules:**

- Weight files must be named after the antibiotic (e.g. `amikacin.pt`). The antibiotics a model supports are the names of its weight files.
- The adapter registered with `@register_model("<model_name>")` uses the folder name, so its weights are found.
- The adapter must accept an `antibiotic` argument in `__init__` and implement `load()` and `predict(file)`, where `file` is a Bakta JSON `File` whose genes have been extracted. `predict` returns the probability of resistance.
- `supported_organisms` declares the organisms the model was built for: `ANY_ORGANISM` (the default) or NCBI Taxonomy CURIEs with their names. The organisms offered to users come from these declarations: the organism field of the upload forms only appears once some model declares specific organisms.

```python
from prediction.adapters import ANY_ORGANISM, ModelInterface, get_model_weights_path, presence_from_list, register_model


@register_model("my_model")
class MyAdapter(ModelInterface):
    supported_organisms = ANY_ORGANISM  # or {'NCBITaxon:562': 'Escherichia coli'}

    def __init__(self, antibiotic: str):
        self.antibiotic = antibiotic

    def load(self) -> None:
        self.genes = [...]  # gene identifiers the model uses, in input order
        weights = get_model_weights_path(self.antibiotic, "my_model")
        ...  # build the model and load the weights

    def predict(self, file) -> float:
        presence = presence_from_list(self.genes, file)  # 1/0 for each gene of the model in the file
        ...  # return the probability of resistance
```

Each registered model becomes a prediction step (`predict_<model_name>`) that runs on the genes of a process. See `app/ai_models/base_bakta_50/` for a complete example.

### Add New Annotation Parsers

Parsers read an annotation file and link its genes to the file. Each registered parser that declares what it consumes becomes a gene extraction step (`extract_<parser_name>`), so other annotation formats can be added without changing the pipeline.

Add a folder under `app/parsers/` with this structure:

```
app/parsers/<parser_name>/
├── __init__.py
└── parser.py                # the parser, registered with @register_parser("<parser_name>")
```

In `parser.py`, register a subclass of `BaseParser`:

```python
from core.models import File
from core.steps import DataKind
from conversion.parsers import BaseParser, register_parser


@register_parser('my_format')
class MyFormatParser(BaseParser):
    label = 'My format'                          # step label: "Gene extraction · My format"
    consumes_kind = DataKind.ANNOTATED_GENOME    # what the input file represents
    consumes_format = File.FileType.CSV          # how it is stored
    default_options = {'min_identity': 90}       # step parameters, passed to parse() as options

    def read(self, file):
        """Read the stored File into the data parse() expects. Raise ValueError if it cannot be read."""
        ...

    def parse(self, data, file, user=None, options=None):
        """Create the Gene and FileGene entries of `file` and return it."""
        ...
```

See `app/parsers/bakta_json/` for a complete example.

---

## Testing

Dependencies are split in two files:

- `requirements.txt` - what the application needs to run (installed in the Docker image).
- `requirements-dev.txt` - test tools (`coverage`, `responses`). It includes `requirements.txt`, so a single command installs everything:

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
