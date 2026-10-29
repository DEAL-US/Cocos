# Cocos

Framework for integrating and deploying antibiotic resistance prediction models in genomic analysis workflows.

Cocos provides a web interface that allows users to process genomic data and obtain antibiotic resistance predictions from multiple registered prediction models. The framework is designed to facilitate the use of research models by users without requiring direct interaction with the underlying machine learning implementations.

## Features

- **From reads to predictions**: users upload sequencing reads (Illumina or ONT), an assembly or a Bakta annotation, and Cocos runs the assembly, annotation and gene extraction each model needs before predicting.
- **Models as plug-ins**: a prediction model or an annotation parser is a folder with its code and an RDF descriptor of what it consumes and produces, validated with SHACL. Adding one does not require changing the rest of the code.
- **Discovery of models**: Cocos decides from the descriptors which models can run on a sample, and which preparation steps they need, with SPARQL over the registry.
- **Public registry**: every step, model and term of the AMRF vocabulary has an IRI with an HTML and RDF page, and the registry has a SPARQL endpoint.
- **Provenance**: each sample can be downloaded as RDF with how its data was obtained (PROV-O and P-Plan), and each prediction as an RO-Crate.
- **Trust of the predictions**: each prediction says how much it can be trusted, and why, from the provenance of the sample and what the model declares about its training data and quality.

## Getting Started

Cocos needs a bio service for the assembly and annotation jobs. The [Cocos-deployment](https://github.com/DEAL-US/Cocos-deployment) repository has it, a mock of it, and this repository as a submodule. To try Cocos with the mock, with Docker installed:

```bash
git clone --recurse-submodules https://github.com/DEAL-US/Cocos-deployment.git
cd Cocos-deployment
python deploy.py --mock
```

Cocos is then at `http://localhost:8080`.

## Documentation

| Guide                                       | What                                                                                     |
| ------------------------------------------- | ---------------------------------------------------------------------------------------- |
| [Development](docs/development.md)          | Development environment, configuration and tests                                         |
| [Production](docs/production.md)            | Production stack and its configuration                                                    |
| [Extending Cocos](docs/extending.md)        | Adding prediction models and annotation parsers                                           |
| [Semantic Layer](docs/semantic-layer.md)    | Registry and SPARQL endpoint, discovery, RDF of the samples, provenance, RO-Crates and trust |

## Repository Layout

```
app/                 Django project
├── ai_models/       prediction models (plug-ins)
├── parsers/         annotation parsers (plug-ins)
├── semantics/       semantic layer: AMRF vocabulary, registry, discovery, provenance, trust
└── trust_rules.toml rules of the trust of the predictions
docker/              Docker Compose files for development and production, and Nginx
docs/                documentation
scripts/             setup of the development and production environments
```

## Authors

Cocos is developed by María Quirós in collaboration with the [DEAL research group](https://deal.us.es) at the Universidad de Sevilla.

## License

The Cocos source code is free software under the [GNU General Public License v3](LICENSE). The AMRF vocabulary and its SHACL shapes (`app/semantics/vocab/`) are published under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
