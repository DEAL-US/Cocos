---
title: Semantic Layer
nav_order: 5
---

# Semantic Layer

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

## Discovery

`semantics.discovery.discover(registry, sample, antibiotics=None)` decides, for every model, whether a sample is **ready** (it has every input of the model), **reachable** (some preparation steps, such as assembly, annotation or gene extraction, produce the missing inputs; it returns them, with the file of the sample that feeds each step) or **incompatible** (with the reasons: no steps can produce the inputs, the model is not for the organism of the sample, or it predicts none of the requested antibiotics). It only reads the RDF graphs, with SPARQL: what steps and models consume and produce (EDAM data and format, and the sequencing technique of reads), and the hierarchy of the terms, so a Bakta JSON file is accepted where any JSON is. Among the shortest preparations it chooses the one that recomputes the least data the sample already has, then the one that runs the fewest jobs in the bio service.

It does not plan again what would fail again. Each failed task keeps its error and whether it failed **for good** (`Task.failure`): a step of Cocos that cannot read its input (`StepError`, e.g. a corrupt Bakta JSON) or a job of the bio service whose tool exited with an error on its data (`error_kind: input`). A job that ran out of time or memory (`resources`), an internal error of the service, a lost job or an unreachable service may work later, so they are retried. A step that failed for good is not planned on the same file while its software is the same (a new version of a tool, of its database or of Cocos may succeed), nor any other step that would run one of its tools in the same version on that file (`core.orchestration.permanent_failures`); the discovery then takes another way, if there is one, or says why the model is not available.

The prediction page is built on it. It offers every sample of the user (those still being processed are disabled until they finish) and shows, for the selected sample, which models are ready, which need preparation (and which steps) and which are not available (and why). When the user predicts, the server runs the discovery again and adds to the plan of the sample the preparation steps the selected models need, once even if several models need them, followed by the predictions. If a preparation step fails, the predictions that depended on it are cancelled and appear without result; if every model was cancelled, the prediction fails. The organism of a sample can be set or changed later from its page.

## Public Registry and SPARQL Endpoint

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

## Sample Descriptions (RDF)

Each process can be retrieved as an RDF description of the sample, for integration with other tools (it is not linked from the web interface). Only its owner can get it, logged in:

```
GET /processes/<id>/rdf/                   Turtle
GET /processes/<id>/rdf/?format=jsonld     JSON-LD (or send Accept: application/ld+json)
```

The sample is a `schema:Dataset` named by the URL of its process page, with the organism chosen by the user (`schema:taxonomicRange`, absent if unknown) and the data it has as `schema:DataDownload` parts: the files the user uploaded and the outputs of completed tasks. Each part is a file in the role it plays (e.g. `reads`, `assembly`, `annotation`, `genes`), described with the same EDAM data and format terms as the inputs of steps and models, and with a `schema:contentUrl` to download that file (`/processes/<id>/files/<file id>/`). A Bakta JSON appears twice: as the annotation and, once its genes are extracted, as the genes. The genes are not a file: Cocos keeps them in its database, linked to the annotation, so they are an EDAM _Gene report_ with no `schema:encodingFormat` and no download link (the AMRF shapes require a format for every other piece of data and parameter), and only inputs with no format accept them.

Each file also has its SHA-256 (`schema:sha256`), so that anyone can check that a file is the one described.

### Provenance

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

The data flow of the sample has a _Provenance data_ section to download this description, with the trust of the predictions, in Turtle or JSON-LD (`/processes/<id>/rdf/`, only for its owner). The page of each sample links to the **data flow of the sample** (`/processes/<id>/flow/`, only for its owner, built by `semantics.flow.sample_flow` from this description and the discovery): the data flow of the registry with the data the sample has (and its files), the state of the latest task of each step and model, the preparation steps the discovery would run for each model, and whether each model is ready, needs preparation or is not available (and why).

### Predictions as RO-Crates

Each completed prediction can be downloaded as an [RO-Crate](https://w3id.org/ro/crate) (the _RO-Crate_ button next to its CSV, only for the owner of the sample; `semantics/rocrate.py`): a zip with every file of the steps that led to it, from the reads to the matrix, Cocos's description of the sample (`provenance.ttl`, with the trust of its predictions) and `ro-crate-metadata.json`, which describes them with schema.org following the [Process Run Crate](https://w3id.org/ro/wfrun/process/0.5) profile, so that tools such as WorkflowHub, Galaxy or Zenodo can read it. It is built from the provenance of the sample, with SPARQL: each activity that led to the prediction is a `CreateAction` with the software that ran it (`instrument`, with its version and its bio.tools entry), what it used (`object`: files, databases by DOI, weights by SHA-256) and what it generated (`result`), and building the matrix is one more action. Files keep their name and SHA-256; the genes, which Cocos keeps in its database, are an entity based on the annotation they come from. The crate sets no license (the data belongs to the user) and follows RO-Crate 1.1 and Process Run Crate 0.5, the versions `roc-validator` checks in the tests.

### Trust of the Predictions

Cocos does not store how much a prediction can be trusted: it computes it each time from the provenance of the sample and from what the descriptor of the model says (`semantics/trust.py`). It reads the evidence with SPARQL: from the registry, the organisms of the model, its measurements (`quality.ttl`), how its training data was annotated and the SHA-256 of its weights; from the description of the sample with its provenance, its organism, the weights the prediction used and the annotation its input comes from, following the activities that generated it back to what the user uploaded. Each rule judges one piece of evidence as _for_, _caution_ or _serious_, and the prediction gets the level of its worst evidence (_High_, _With reservations_ or _Low_):

| Rule                  | Evidence                                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------------------ |
| `species`             | The organism of the sample is (a kind of) one the model was built for; unknown organisms are a caution |
| `antibiotic_isolates` | Isolates with a known susceptibility to the antibiotic in the data of the model                        |
| `class_balance`       | Percentage of resistant isolates for the antibiotic, neither too low nor too high                      |
| `species_isolates`    | Isolates of the organism of the sample for the antibiotic (only if the organism is known)              |
| `model_quality`       | F1 score of the model                                                                                  |
| `same_annotation`     | The input was annotated with the same software and database as the training data                       |
| `weights`             | The weights used for the antibiotic are the ones the model declares                                    |
| `annotation_origin`   | Cocos knows which software annotated the input (not if the annotation was uploaded)                    |

**The rules, their thresholds, judgements and texts are in `app/trust_rules.toml`**, to change them without touching the code; a change applies at once, and `python manage.py check` reports any mistake in the file (`semantics.E001`). A rule that cannot be checked (e.g. a model with no `quality.ttl`) gives no evidence. In the prediction matrix of a process, each result has a badge with its level; clicking it lists the evidence for and against. The RDF of the sample includes it too: each result is a `dqv:QualityAnnotation` of its prediction (`oa:hasTarget` the activity, `obo:IAO_0000136` the antibiotic) with the level as `oa:bodyValue` and each piece of evidence as an `oa:TextualBody`, with its rule (`dcterms:identifier`) and judgement (`dcterms:type`).
