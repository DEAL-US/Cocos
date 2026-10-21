# cocos

Framework for integrating and deploying antibiotic resistance prediction models in genomic analysis workflows.

Cocos provides a web interface that allows users to process genomic data and obtain antibiotic resistance predictions from multiple registered prediction models. The framework is designed to facilitate the use of research models by users without requiring direct interaction with the underlying machine learning implementations.

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
- Frontend dependencies (`tailwindcss` + `daisyui`, `cytoscape` + `cytoscape-dagre`) from `app/package.json`
- Compiled CSS output at `app/static/css/tailwind.css` and the JavaScript libraries in `app/static/vendor/` (`npm run build`)

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

## Extending Cocos

Prediction models and annotation parsers are plug-ins: each one is a folder that Cocos discovers when it starts, so adding one does not require changing the rest of the code.

Each plug-in has a **`descriptor.ttl`**: an RDF description (Turtle) of what it consumes and produces and, for models, which organisms and antibiotics it supports. The descriptor is the source of truth: Cocos reads it to decide what a plug-in can be used for. It reuses existing ontologies: [EDAM](https://edamontology.org) for data, formats and operations, [ARO](https://obofoundry.org/ontology/aro.html) for antibiotics, [NCBITaxon](https://obofoundry.org/ontology/ncbitaxon.html) for organisms and [Bioschemas](https://bioschemas.org/profiles/ComputationalTool) for the overall structure, plus the AMRF vocabulary of Cocos (`app/semantics/vocab/amrf.ttl`) for what they do not cover. Copy the descriptor of an existing plug-in and adapt it.

Every descriptor is validated with the [SHACL](https://www.w3.org/TR/shacl/) shapes in `app/semantics/vocab/shapes.ttl` when the plug-in is registered. They require what [Bioschemas ComputationalTool](https://bioschemas.org/profiles/ComputationalTool/1.0-RELEASE) requires (`name`, `description`, `url`), EDAM terms for operations, inputs and outputs and, for models, a version, ARO antibiotics and NCBITaxon organisms; `author`, `license` and `citation` are recommended. **A plug-in whose descriptor is invalid is not registered**: the rest of Cocos keeps working, and `python manage.py check` reports why (`semantics.W001`). The test suite fails while any plug-in is invalid.

**Checklist** to add or change a plug-in (commands run from `app/`, or in the dev container with `docker exec bio-web-web-1 python manage.py ...`):

1. Create the folder with the code and its `descriptor.ttl` (see the sections below).
2. Run `python manage.py fetch_terms` (needs internet). It looks every ontology term of every descriptor up in the [EBI Ontology Lookup Service](https://www.ebi.ac.uk/ols4), fails if one does not exist or is obsolete, and stores their labels and hierarchy in `app/semantics/vocab/terms.ttl`. The application and the tests only read that file, so they never need internet.
3. Run `python manage.py check`. It warns about plug-ins that were not registered (invalid descriptor, or a declared antibiotic without weights) and about weights the descriptor does not declare.
4. Commit the folder and `terms.ttl` together.

If you forget step 2, the plug-in does not appear: without the hierarchy of its terms its descriptor cannot be validated, so `python manage.py check` reports it as not registered and suggests running `fetch_terms`. The test suite fails for the same reason.

| To add               | Create                        | Becomes the step        |
| -------------------- | ----------------------------- | ----------------------- |
| A prediction model   | `app/ai_models/<model_name>/` | `predict_<model_name>`  |
| An annotation parser | `app/parsers/<parser_name>/`  | `extract_<parser_name>` |

### Add New Prediction Models

Add a folder under `app/ai_models/` with this structure:

```
app/ai_models/<model_name>/
├── weights/
│   ├── <antibiotic>.pt      # model weights per antibiotic
│   └── ...
├── descriptor.ttl           # what the model supports (see below)
└── model_classes.py         # model definition & adapter
```

**Rules:**

- The descriptor declares the antibiotics the model predicts (`amrf:predictsResistanceTo` with ARO terms) and the organisms it was built for (`schema:taxonomicRange` with NCBITaxon terms; `obo:NCBITaxon_2`, Bacteria, means any organism). The organisms offered to users come from these declarations: the organism field of the upload forms only appears once some model declares specific organisms.
- Weight files must be named after the ARO label of each declared antibiotic (e.g. `amikacin.pt` for `obo:ARO_0000013`). A model with a declared antibiotic without weights is not registered (reported by `python manage.py check`); weights for an undeclared antibiotic are ignored, with a warning.
- The adapter registered with `@register_model("<model_name>")` uses the folder name, so its weights and descriptor are found.
- The adapter must accept an `antibiotic` argument in `__init__` and implement `load()` and `predict(file)`, where `file` is the input the descriptor declares (today, a Bakta JSON `File` whose genes have been extracted). `predict` returns the probability of resistance.

```python
from prediction.adapters import ModelInterface, get_model_weights_path, presence_from_list, register_model


@register_model("my_model")
class MyAdapter(ModelInterface):
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

Each registered model becomes a prediction step (`predict_<model_name>`) that consumes what its descriptor declares. See `app/ai_models/base_bakta_50/` for a complete example.

### Add New Annotation Parsers

Parsers read an annotation file and link its genes to the file. Each registered parser with a descriptor becomes a gene extraction step (`extract_<parser_name>`) with the label, input and output the descriptor declares, so other annotation formats can be added without changing the pipeline.

Add a folder under `app/parsers/` with this structure:

```
app/parsers/<parser_name>/
├── __init__.py
├── descriptor.ttl           # the extraction step: its label, input (data and format) and output
└── parser.py                # the parser, registered with @register_parser("<parser_name>")
```

In `parser.py`, register a subclass of `BaseParser`:

```python
from conversion.parsers import BaseParser, register_parser


@register_parser('my_format')
class MyFormatParser(BaseParser):
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

## Semantic Layer

Cocos describes what it can do, and what each sample has, in RDF, and uses those descriptions to decide which models can run on a sample. The code is in `app/semantics/`:

```
app/semantics/
├── vocab/          amrf.ttl (the AMRF vocabulary), shapes.ttl (SHACL shapes), terms.ttl (reused ontology terms)
├── registry/       what Cocos offers: the steps (generated from the code), the plug-in descriptors
│                   and the registry graph that joins them with the vocabulary and terms.ttl
├── validation.py   SHACL validation of descriptors and samples against shapes.ttl
├── sample.py       the RDF description of a sample
├── flow.py         the registry as a data flow, drawn on the registry page
└── discovery/      which models can run on a sample
```

### Discovery

`semantics.discovery.discover(registry, sample, antibiotics=None)` decides, for every model, whether a sample is **ready** (it has every input of the model), **reachable** (some preparation steps, such as assembly, annotation or gene extraction, produce the missing inputs; it returns them, with the file of the sample that feeds each step) or **incompatible** (with the reasons: no steps can produce the inputs, the model is not for the organism of the sample, or it predicts none of the requested antibiotics). It only reads the RDF graphs, with SPARQL: what steps and models consume and produce (EDAM data and format, and the sequencing technique of reads), and the hierarchy of the terms, so a Bakta JSON file is accepted where any JSON is. Among the shortest preparations it chooses the one that recomputes the least data the sample already has, then the one that runs the fewest jobs in the bio service.

The prediction page is built on it. It offers every sample of the user (those still being processed are disabled until they finish) and shows, for the selected sample, which models are ready, which need preparation (and which steps) and which are not available (and why). When the user predicts, the server runs the discovery again and adds to the plan of the sample the preparation steps the selected models need, once even if several models need them, followed by the predictions. If a preparation step fails, the predictions that depended on it are cancelled and appear without result; if every model was cancelled, the prediction fails. The organism of a sample can be set or changed later from its page.

### Public Registry and SPARQL Endpoint

The registry (steps, models, the AMRF vocabulary and shapes) is public; the data of the users never is. Every IRI of the registry has a page on the server, which `https://w3id.org/cocos/...` and `https://w3id.org/amrf/...` will redirect to. Browsers get HTML; RDF clients get Turtle or JSON-LD (`Accept` header, or `?format=ttl` / `?format=jsonld`):

| Path                           | What                                                                      |
| ------------------------------ | ------------------------------------------------------------------------- |
| `/registry/`                   | every step and model, and their data flow (and the whole registry as RDF) |
| `/model/<name>`, `/step/<key>` | one model or step, with its inputs and outputs                            |
| `/amrf/`, `/amrf/<term>`       | the AMRF vocabulary and its terms                                         |
| `/amrf/shapes`                 | the AMRF SHACL shapes                                                     |
| `/sparql`                      | read-only SPARQL endpoint over the registry                               |

Without a browser, ask for the format you want:

```bash
curl -H "Accept: text/turtle" http://localhost:8080/model/base_bakta_50       # one model, Turtle
curl "http://localhost:8080/registry/?format=jsonld" -o registry.jsonld        # the whole registry, JSON-LD
```

RDF libraries send that `Accept` header themselves, so in Python `rdflib.Graph().parse("http://localhost:8080/registry/")` is enough.

The registry page draws the **data flow** of the registry (`semantics/flow.py`, drawn with Cytoscape.js and dagre): the kinds of data (EDAM data and format, and the sequencing technique of reads), the steps and the models, with an arrow from each kind of data to every step or model it can feed and from each step to what it produces. It is built with the same reading and matching as the discovery, so it shows the paths the discovery can take. Selecting a box highlights everything that leads to it and everything it leads to, and lists what it needs and produces; the page of each step and model links to its box (`/registry/?focus=model-base_bakta_50`). The graph can be downloaded as a PNG.

The SPARQL endpoint follows the SPARQL 1.1 protocol (`GET ?query=...`, or `POST` as a form or as `application/sparql-query`) and allows cross-origin requests. `SELECT` and `ASK` results are JSON (default), XML or CSV; `CONSTRUCT` and `DESCRIBE` results are Turtle or JSON-LD. The prefixes `schema:`, `edam:`, `obo:`, `bsc:`, `amrf:` and `rdfs:` are predefined. Updates, `SERVICE` and queries longer than 10,000 characters are refused. For example, the models and the antibiotics they predict:

```bash
curl -G http://localhost:8080/sparql --data-urlencode 'query=
SELECT ?model ?antibiotic WHERE {
  ?model schema:featureList edam:operation_3482 ; amrf:predictsResistanceTo ?drug .
  ?drug rdfs:label ?antibiotic .
}'
```

### Sample Descriptions (RDF)

Each process can be retrieved as an RDF description of the sample, for integration with other tools (it is not linked from the web interface). Only its owner can get it, logged in:

```
GET /processes/<id>/rdf/                   Turtle
GET /processes/<id>/rdf/?format=jsonld     JSON-LD (or send Accept: application/ld+json)
```

The sample is a `schema:Dataset` named by the URL of its process page, with the organism chosen by the user (`schema:taxonomicRange`, absent if unknown) and the data it has as `schema:DataDownload` parts: the files the user uploaded and the outputs of completed tasks. Each part is a file in the role it plays (e.g. `reads`, `assembly`, `annotation`, `genes`), described with the same EDAM data and format terms as the inputs of steps and models, and with a `schema:contentUrl` to download that file (`/processes/<id>/files/<file id>/`). A Bakta JSON appears twice: as the annotation and, once its genes are extracted, as the genes.

The page of each process links to the **data flow of the sample** (`/processes/<id>/flow/`, only for its owner, built by `semantics.flow.sample_flow` from this description and the discovery): the data flow of the registry with the data the sample has (and its files), the state of the latest task of each step and model, the preparation steps the discovery would run for each model, and whether each model is ready, needs preparation or is not available (and why).

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

## License

The Cocos source code is free software under the [GNU General Public License v3](LICENSE). The AMRF vocabulary and its SHACL shapes (`app/semantics/vocab/`) are published under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
