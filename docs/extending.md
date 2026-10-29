# Extending Cocos

Prediction models and annotation parsers are plug-ins: each one is a folder that Cocos discovers when it starts, so adding one does not require changing the rest of the code.

Each plug-in has a **`descriptor.ttl`**: an RDF description (Turtle) of what it consumes and produces and, for models, which organisms and antibiotics it supports. The descriptor is the source of truth: Cocos reads it to decide what a plug-in can be used for. It reuses existing ontologies: [EDAM](https://edamontology.org) for data, formats and operations, [ARO](https://obofoundry.org/ontology/aro.html) for antibiotics, [NCBITaxon](https://obofoundry.org/ontology/ncbitaxon.html) for organisms and [Bioschemas](https://bioschemas.org/profiles/ComputationalTool) for the overall structure, plus the AMRF vocabulary of Cocos (`app/semantics/vocab/amrf.ttl`) for what they do not cover. Copy the descriptor of an existing plug-in and adapt it.

Every descriptor is validated with the [SHACL](https://www.w3.org/TR/shacl/) shapes in `app/semantics/vocab/shapes.ttl` when the plug-in is registered. They require what [Bioschemas ComputationalTool](https://bioschemas.org/profiles/ComputationalTool/1.0-RELEASE) requires (`name`, `description`, `url`), EDAM terms for operations, inputs and outputs and, for models, a version, ARO antibiotics and NCBITaxon organisms; `author`, `license` and `citation` are recommended. **A plug-in whose descriptor is invalid is not registered**: the rest of Cocos keeps working, and `python manage.py check` reports why (`semantics.W001`). The test suite fails while any plug-in is invalid.

**Checklist** to add or change a plug-in (commands run from `app/`, or in the dev container with `docker exec cocos-dev-web python manage.py ...`):

1. Create the folder with the code and its `descriptor.ttl` (see the sections below).
2. Run `python manage.py fetch_terms` (needs internet). It looks every ontology term of every descriptor up in the [EBI Ontology Lookup Service](https://www.ebi.ac.uk/ols4), fails if one does not exist or is obsolete, and stores their labels and hierarchy in `app/semantics/vocab/terms.ttl`. The application and the tests only read that file, so they never need internet.
3. Run `python manage.py check`. It warns about plug-ins that were not registered (invalid descriptor, or a file it declares that is missing or has changed).
4. Commit the folder and `terms.ttl` together.

If you forget step 2, the plug-in does not appear: without the hierarchy of its terms its descriptor cannot be validated, so `python manage.py check` reports it as not registered and suggests running `fetch_terms`. The test suite fails for the same reason.

| To add               | Create                        | Becomes the step        |
| -------------------- | ----------------------------- | ----------------------- |
| A prediction model   | `app/ai_models/<model_name>/` | `predict_<model_name>`  |
| An annotation parser | `app/parsers/<parser_name>/`  | `extract_<parser_name>` |

## Add New Prediction Models

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

- The descriptor declares the antibiotics the model predicts (`amrf:predictsResistanceTo` with ARO terms) and the organisms it was built for (`schema:taxonomicRange` with NCBITaxon terms; `obo:NCBITaxon_2`, Bacteria, means any organism). A model for a taxon accepts samples of that taxon and of the taxa under it in NCBITaxon (a model for Enterobacterales accepts _E. coli_), with the hierarchy that `fetch_terms` stores in `terms.ttl`. The organism field of the upload forms and of the page of a process offers the organisms Cocos knows something about: those the models declare and those their data has measurements about (their `quality.ttl`, e.g. the species they were trained on), plus _Other / unknown_.
- A model needs no weights: a rule-based one may have none, and one with weights may keep them in any format and layout, since its adapter loads them. `get_model_weights_path` finds `weights/<antibiotic>.pt`, named after the ARO label of the antibiotic (e.g. `amikacin.pt` for `obo:ARO_0000013`), for adapters that follow that convention.
- The adapter registered with `@register_model("<model_name>")` uses the folder name, so its descriptor (and its weights) are found.

Three optional parts of the description make the predictions of a model easier to trust. They suit any kind of model, trained or rule-based, and the page of the model in the registry shows them:

- **How it was built** (in `descriptor.ttl`, [PROV-O](https://www.w3.org/TR/prov-o/)): the data it was derived from (`prov:wasDerivedFrom`), with the dataset it is part of and its license, and how that data was prepared: an activity (`prov:wasGeneratedBy`) associated with the tools it used, as versioned `prov:SoftwareAgent`s that are `prov:specializationOf` their [bio.tools](https://bio.tools) entry, and the databases it used. This is the pattern of the provenance of a sample, so both can be compared (e.g. the version of Bakta that prepared the training data and the one that annotated a sample). For a rule-based tool, the data is its reference database.
- **How well it works** (in `quality.ttl`, [DQV](https://www.w3.org/TR/vocab-dqv/)): `dqv:QualityMeasurement`s of a metric (a term such as STATO _F1 score_ or NCIT _Sample Size_) with a `dqv:value`, what they are about (`obo:IAO_0000136`: an antibiotic of ARO and, optionally, organisms of NCBITaxon) and the data they were computed on (`dqv:computedOn`), so that a training set and a validation set are never confused. The measurements of different models are not comparable unless they were computed on the same data.
- **The files it depends on** (in `descriptor.ttl`): `schema:hasPart` `schema:MediaObject`s with their path in the folder of the model (`schema:name`) and `schema:sha256` and, if a file is for one antibiotic (e.g. its weights), that antibiotic (`obo:IAO_0000136`); a file about no antibiotic is for all of them. Cocos does not register the model if one is missing or has changed. The files of an antibiotic, and those for all of them, are the weights its predictions used, in their provenance (by their SHA-256), which the `weights` trust rule compares with the declared ones.
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

## Add New Annotation Parsers

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
