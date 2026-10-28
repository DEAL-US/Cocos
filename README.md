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
- Frontend builder (`frontend`): installs the npm dependencies, copies the JavaScript libraries to `app/static/vendor/` and compiles `app/static/css/tailwind.css`, then compiles the CSS again whenever a template, Python or JavaScript file changes (it checks every 2 seconds, since Docker on Windows does not report changes in mounted folders)

Access at: `http://localhost:8080`

PostgreSQL is published on `127.0.0.1:5432`, so tests and `runserver` on the host can reach it but other machines cannot.

The development environment mounts the application source code into the containers, so changes to the code, the templates and the Tailwind classes are reflected without rebuilding the image. The production image compiles the CSS and copies the libraries when it is built.

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

The application data and uploaded files are stored in Docker volumes. The web and worker containers run as the unprivileged user `app`, not as root.

Cocos reaches the bio service (assembly and annotation) at `ANNOTATION_BASE`, `http://bio-assembly-api:8000` by default, through the `bio-network` Docker network. The bio service has no authentication and publishes no ports, so users only reach it through Cocos. For development, the bio service can also be published on `127.0.0.1:8000` (see `docker-servicios-bio/docker-servicios-bio/INSTRUCCIONES.md` in the deployment repository, or `python deploy.py --dev`).

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

With `DJANGO_DEBUG=0`, Django refuses to start (`ImproperlyConfigured`) if `DJANGO_SECRET_KEY` or `DB_PASSWORD` is not set: they have defaults only in development.

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
3. Run `python manage.py check`. It warns about plug-ins that were not registered (invalid descriptor, or a file it declares that is missing or has changed).
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
├── weights/                 # optional: whatever the adapter loads, e.g. weights per antibiotic
│   ├── <antibiotic>.pt
│   └── ...
├── descriptor.ttl           # what the model supports (see below)
├── quality.ttl              # optional: how well it works and on which data (see below)
└── model_classes.py         # model definition & adapter
```

**Rules:**

- The descriptor declares the antibiotics the model predicts (`amrf:predictsResistanceTo` with ARO terms) and the organisms it was built for (`schema:taxonomicRange` with NCBITaxon terms; `obo:NCBITaxon_2`, Bacteria, means any organism). A model for a taxon accepts samples of that taxon and of the taxa under it in NCBITaxon (a model for Enterobacterales accepts *E. coli*), with the hierarchy that `fetch_terms` stores in `terms.ttl`. The organism field of the upload forms and of the page of a process offers the organisms Cocos knows something about: those the models declare and those their data has measurements about (their `quality.ttl`, e.g. the species they were trained on), plus *Other / unknown*.
- A model needs no weights: a rule-based one may have none, and one with weights may keep them in any format and layout, since its adapter loads them. `get_model_weights_path` finds `weights/<antibiotic>.pt`, named after the ARO label of the antibiotic (e.g. `amikacin.pt` for `obo:ARO_0000013`), for adapters that follow that convention.
- The adapter registered with `@register_model("<model_name>")` uses the folder name, so its descriptor (and its weights) are found.

Three optional parts of the description make the predictions of a model easier to trust. They suit any kind of model, trained or rule-based, and the page of the model in the registry shows them:

- **How it was built** (in `descriptor.ttl`, [PROV-O](https://www.w3.org/TR/prov-o/)): the data it was derived from (`prov:wasDerivedFrom`), with the dataset it is part of and its license, and how that data was prepared: an activity (`prov:wasGeneratedBy`) associated with the tools it used, as versioned `prov:SoftwareAgent`s that are `prov:specializationOf` their [bio.tools](https://bio.tools) entry, and the databases it used. This is the pattern of the provenance of a sample, so both can be compared (e.g. the version of Bakta that prepared the training data and the one that annotated a sample). For a rule-based tool, the data is its reference database.
- **How well it works** (in `quality.ttl`, [DQV](https://www.w3.org/TR/vocab-dqv/)): `dqv:QualityMeasurement`s of a metric (a term such as STATO *F1 score* or NCIT *Sample Size*) with a `dqv:value`, what they are about (`obo:IAO_0000136`: an antibiotic of ARO and, optionally, organisms of NCBITaxon) and the data they were computed on (`dqv:computedOn`), so that a training set and a validation set are never confused. The measurements of different models are not comparable unless they were computed on the same data.
- **The files it depends on** (in `descriptor.ttl`): `schema:hasPart` `schema:MediaObject`s with their path in the folder of the model (`schema:name`) and `schema:sha256`. Cocos does not register the model if one is missing or has changed.
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

It does not plan again what would fail again. Each failed task keeps its error and whether it failed **for good** (`Task.failure`): a step of Cocos that cannot read its input (`StepError`, e.g. a corrupt Bakta JSON) or a job of the bio service whose tool exited with an error on its data (`error_kind: input`). A job that ran out of time or memory (`resources`), an internal error of the service, a lost job or an unreachable service may work later, so they are retried. A step that failed for good is not planned on the same file while its software is the same (a new version of a tool, of its database or of Cocos may succeed), nor any other step that would run one of its tools in the same version on that file (`core.orchestration.permanent_failures`); the discovery then takes another way, if there is one, or says why the model is not available.

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

The sample is a `schema:Dataset` named by the URL of its process page, with the organism chosen by the user (`schema:taxonomicRange`, absent if unknown) and the data it has as `schema:DataDownload` parts: the files the user uploaded and the outputs of completed tasks. Each part is a file in the role it plays (e.g. `reads`, `assembly`, `annotation`, `genes`), described with the same EDAM data and format terms as the inputs of steps and models, and with a `schema:contentUrl` to download that file (`/processes/<id>/files/<file id>/`). A Bakta JSON appears twice: as the annotation and, once its genes are extracted, as the genes. The genes are not a file: Cocos keeps them in its database, linked to the annotation, so they are an EDAM *Gene report* with no `schema:encodingFormat` and no download link (the AMRF shapes require a format for every other piece of data and parameter), and only inputs with no format accept them.

Each file also has its SHA-256 (`schema:sha256`), so that anyone can check that a file is the one described.

#### Provenance

The description also says how the data of the sample was obtained, with [PROV-O](https://www.w3.org/TR/prov-o/) and [P-Plan](https://www.opmw.org/model/p-plan/) (`semantics/provenance.py`, validated with the AMRF shapes):

- **Activities**: each task is a `prov:Activity` with its status (`schema:actionStatus`: potential, active, completed or failed, since failed tasks are part of the history of the sample, with their error in `schema:error`), when it started and ended (`prov:startedAtTime`, `prov:endedAtTime`), the data it used (`prov:used`) and generated (`prov:wasGeneratedBy`), and the step or model of the registry it ran (`prov:wasAssociatedWith <https://w3id.org/cocos/step/...>`).
- **Software**: the tools and models it used, with their versions (`Task.software`), are `prov:SoftwareAgent`s associated with the activity and specializations (`prov:specializationOf`) of their [bio.tools](https://bio.tools) entry or of the model of the registry; the databases (identified by their DOI, when they have one) and the weights of the models (by their SHA-256) are `prov:Entity`s the activity used.
- **User**: an anonymous `prov:Person` per sample, which uploaded the files (`prov:wasAttributedTo`) and asked for the activities. Who the user is never appears.
- **Plan**: what the orchestrator and the discovery decided to run is a `p-plan:Plan` whose `p-plan:Step`s say which step of the registry they run (`dcterms:type`) and which steps come before them (`p-plan:isPrecededBy`); each activity says which step it carried out (`p-plan:correspondsToStep`). A step with no activity was cancelled because a step before it failed.

For example, with SPARQL over the description of a sample: which software produced its genes, through which steps, starting from which uploaded files.

```sparql
SELECT ?step ?software ?version WHERE {
  ?genes schema:name "genes" ; prov:wasGeneratedBy/(prov:used/prov:wasGeneratedBy)* ?activity .
  ?activity schema:name ?step ; prov:wasAssociatedWith ?agent .
  ?agent a prov:SoftwareAgent ; schema:name ?software ; schema:softwareVersion ?version .
}
```

The discovery reads the same description without the provenance (`sample_graph(..., with_provenance=False)`, the default), which it does not need.

The data flow of the sample has a *Provenance data* section to download this description, with the trust of the predictions, in Turtle or JSON-LD (`/processes/<id>/rdf/`, only for its owner). The page of each process links to the **data flow of the sample** (`/processes/<id>/flow/`, only for its owner, built by `semantics.flow.sample_flow` from this description and the discovery): the data flow of the registry with the data the sample has (and its files), the state of the latest task of each step and model, the preparation steps the discovery would run for each model, and whether each model is ready, needs preparation or is not available (and why).

#### Predictions as RO-Crates

Each completed prediction can be downloaded as an [RO-Crate](https://w3id.org/ro/crate) (the *RO-Crate* button next to its CSV, only for the owner of the sample; `semantics/rocrate.py`): a zip with every file of the steps that led to it, from the reads to the matrix, Cocos's description of the sample (`provenance.ttl`, with the trust of its predictions) and `ro-crate-metadata.json`, which describes them with schema.org following the [Process Run Crate](https://w3id.org/ro/wfrun/process/0.5) profile, so that tools such as WorkflowHub, Galaxy or Zenodo can read it. It is built from the provenance of the sample, with SPARQL: each activity that led to the prediction is a `CreateAction` with the software that ran it (`instrument`, with its version and its bio.tools entry), what it used (`object`: files, databases by DOI, weights by SHA-256) and what it generated (`result`), and building the matrix is one more action. Files keep their name and SHA-256; the genes, which Cocos keeps in its database, are an entity based on the annotation they come from. The crate sets no license (the data belongs to the user) and follows RO-Crate 1.1 and Process Run Crate 0.5, the versions `roc-validator` checks in the tests.

#### Trust of the Predictions

Cocos does not store how much a prediction can be trusted: it computes it each time from the provenance of the sample and from what the descriptor of the model says (`semantics/trust.py`). It reads the evidence with SPARQL: from the registry, the organisms of the model, its measurements (`quality.ttl`), how its training data was annotated and the SHA-256 of its weights; from the description of the sample with its provenance, its organism, the weights the prediction used and the annotation its input comes from, following the activities that generated it back to what the user uploaded. Each rule judges one piece of evidence as *for*, *caution* or *serious*, and the prediction gets the level of its worst evidence (*High*, *With reservations* or *Low*):

| Rule | Evidence |
| ---- | -------- |
| `species` | The organism of the sample is (a kind of) one the model was built for; unknown organisms are a caution |
| `antibiotic_isolates` | Isolates with a known susceptibility to the antibiotic in the data of the model |
| `class_balance` | Percentage of resistant isolates for the antibiotic, neither too low nor too high |
| `species_isolates` | Isolates of the organism of the sample for the antibiotic (only if the organism is known) |
| `model_quality` | F1 score of the model |
| `same_annotation` | The input was annotated with the same software and database as the training data |
| `weights` | The weights used for the antibiotic are the ones the model declares |
| `annotation_origin` | Cocos knows which software annotated the input (not if the annotation was uploaded) |

**The rules, their thresholds, judgements and texts are in `app/trust_rules.toml`**, to change them without touching the code; a change applies at once, and `python manage.py check` reports any mistake in the file (`semantics.E001`). A rule that cannot be checked (e.g. a model with no `quality.ttl`) gives no evidence. In the prediction matrix of a process, each result has a badge with its level; clicking it lists the evidence for and against. The RDF of the sample includes it too: each result is a `dqv:QualityAnnotation` of its prediction (`oa:hasTarget` the activity, `obo:IAO_0000136` the antibiotic) with the level as `oa:bodyValue` and each piece of evidence as an `oa:TextualBody`, with its rule (`dcterms:identifier`) and judgement (`dcterms:type`).

---

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

## License

The Cocos source code is free software under the [GNU General Public License v3](LICENSE). The AMRF vocabulary and its SHACL shapes (`app/semantics/vocab/`) are published under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
