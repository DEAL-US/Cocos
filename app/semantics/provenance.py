"""Provenance of a sample (PROV-O): what was done with its data, when, and by what.

It is added to the RDF description of the sample (semantics.sample). Each task of the process is a
prov:Activity: its status (schema:actionStatus, also for tasks that failed or have not run yet,
with the error of those that failed, schema:error), when it started and ended, the data of the
sample it used and generated, and the step or model of the registry it ran. The user is a single anonymous prov:Person per sample: the provenance says
that a user of this Cocos instance uploaded the files and asked for the steps, not who.

The software a task used (Task.software) is described too: tools and models are versioned
prov:SoftwareAgents of the activity, specializations of their bio.tools entry or of the model of
the registry; databases (identified by their DOI, when they have one) and the weights of models
(by their SHA-256) are prov:Entities the activity used.

The plan of the process (what the orchestrator and the discovery decided to run, in which order)
is a p-plan:Plan whose p-plan:Steps say which step of the registry they run and which steps come
before them; each activity says which step of the plan it carried out (p-plan:correspondsToStep).
A step of the plan with no activity was not run: it was cancelled because a step before it failed.

The results of a completed prediction are prov:Entities it generated, one per antibiotic, about
(obo:IAO_0000136) its ARO term: their verdict is their type (an NCIT result: resistance,
susceptibility, intermediate susceptibility, presumptive positive or not detected) and their
probability their schema:value. What a tool found is the evidence they are derived from
(prov:wasDerivedFrom): a determinant (schema:name, the gene; its NCBI protein, rdfs:seeAlso; the
rules that interpreted it, dcterms:identifier). A verdict a tool gave about a class of antibiotics,
which Cocos applies to an antibiotic of it, is a result about that class, from which the result
about the antibiotic is derived.
"""
import re
from decimal import Decimal

from rdflib import Literal, URIRef
from rdflib.namespace import DCTERMS, PROV, RDF, RDFS, XSD

from core.models import TaskStatus
from core.steps import UnknownStepError, get_step, software_label

from .namespaces import IS_ABOUT, OBO, PPLAN, SCHEMA
from .registry.descriptors import model_iri
from .registry.steps import step_iri
from .registry.terms import aro_terms

# The verdicts of the results of predictions (see prediction.results), as NCIT results
VERDICTS = {
    'R': OBO.NCIT_C85562,              # Antimicrobial Resistance Result
    'I': OBO.NCIT_C85560,              # Antimicrobial Intermediate Susceptibility Result
    'S': OBO.NCIT_C85563,              # Antimicrobial Susceptibility Result
    'possible': OBO.NCIT_C206382,      # Presumptive Positive
    'not_detected': OBO.NCIT_C191300,  # Not Detected
}
NCBI_PROTEIN = 'https://www.ncbi.nlm.nih.gov/protein/'

ACTION_STATUSES = {
    TaskStatus.PENDING: SCHEMA.PotentialActionStatus,
    TaskStatus.RUNNING: SCHEMA.ActiveActionStatus,
    TaskStatus.COMPLETED: SCHEMA.CompletedActionStatus,
    TaskStatus.FAILED: SCHEMA.FailedActionStatus,
}


def add_provenance(graph, process, sample, entries):
    """Add to `graph` the provenance of `process`, whose sample is the IRI `sample`.

    `entries` is {(file id, role): IRI} of the data of the sample (see semantics.sample).
    """
    user = URIRef(f'{sample}#user')
    graph.add((user, RDF.type, PROV.Person))
    graph.add((user, RDFS.label, Literal('A user of this Cocos instance', lang='en')))
    graph.add((sample, PROV.wasAttributedTo, user))
    add_plan(graph, process, sample)

    for task in process.tasks.prefetch_related('task_inputs__file', 'task_outputs__file').order_by('id'):
        try:
            step = task.get_step()
        except UnknownStepError:
            continue  # e.g. a prediction with a model that is no longer registered
        activity = task_iri(sample, task)
        graph.add((activity, RDF.type, PROV.Activity))
        graph.add((activity, SCHEMA.name, Literal(step.label)))
        graph.add((activity, SCHEMA.actionStatus, ACTION_STATUSES[task.status]))
        graph.add((activity, PROV.wasAssociatedWith, user))
        graph.add((activity, PROV.wasAssociatedWith, registry_iri(step)))
        if task.started_at:
            graph.add((activity, PROV.startedAtTime, Literal(task.started_at, datatype=XSD.dateTime)))
        if task.finished_at:
            graph.add((activity, PROV.endedAtTime, Literal(task.finished_at, datatype=XSD.dateTime)))
        if task.status == TaskStatus.FAILED and task.error:
            graph.add((activity, SCHEMA.error, Literal(task.error)))
        if task.plan_node:
            graph.add((activity, PPLAN.correspondsToStep, plan_step_iri(sample, task.plan_node)))
        for entry in task.software:
            add_software(graph, sample, activity, entry)
        if step.category == 'prediction' and task.status == TaskStatus.COMPLETED:
            add_results(graph, task.concrete, activity)

        for link in task.task_inputs.all():
            entry = _entry(entries, link)
            if entry is not None:
                graph.add((activity, PROV.used, entry))
                if not link.file.produced_by_tasks.exists():  # uploaded by the user
                    graph.add((entry, PROV.wasAttributedTo, user))
        if task.status == TaskStatus.COMPLETED:
            for link in task.task_outputs.all():
                entry = entries.get((link.file.pk, link.role))
                if entry is not None:
                    graph.add((entry, PROV.wasGeneratedBy, activity))
    return graph


def add_plan(graph, process, sample):
    """Add the plan of `process`: its steps, the step of the registry each runs and their order."""
    if not process.plan:
        return
    plan = URIRef(f'{sample}#plan')
    graph.add((plan, RDF.type, PPLAN.Plan))
    graph.add((plan, RDFS.label, Literal('Plan of the steps of this sample', lang='en')))
    for node in process.plan:
        step = plan_step_iri(sample, node['id'])
        graph.add((step, RDF.type, PPLAN.Step))
        graph.add((step, PPLAN.isStepOfPlan, plan))
        try:
            graph.add((step, DCTERMS.type, registry_iri(get_step(node['step']))))
        except UnknownStepError:
            pass
        for before in node['after']:
            graph.add((step, PPLAN.isPrecededBy, plan_step_iri(sample, before)))
        if node.get('cancelled'):
            graph.add((step, RDFS.comment, Literal('Cancelled: a step before it failed.', lang='en')))


def plan_step_iri(sample, node_id):
    return URIRef(f'{sample}#plan-{node_id}')


def add_software(graph, sample, activity, entry):
    """Add an entry of Task.software, which `activity` used: a tool or model is one of its agents,
    a database (and the weights of a model) something it used."""
    label = Literal(software_label(entry))
    if entry.get('type') == 'database':
        if entry.get('doi'):
            database = URIRef(f"https://doi.org/{entry['doi']}")
        else:
            database = URIRef(f"{sample}#database-{_slug(entry['name'])}-{entry.get('version', '')}")
        graph.add((database, RDF.type, PROV.Entity))
        graph.add((database, RDFS.label, label))
        graph.add((database, SCHEMA.name, Literal(entry['name'])))
        graph.add((database, SCHEMA.version, Literal(entry.get('version', ''))))
        if entry.get('date'):
            graph.add((database, SCHEMA.datePublished, Literal(entry['date'], datatype=XSD.date)))
        graph.add((activity, PROV.used, database))
        return

    # A model and a tool may share a name and version (the model amrfinderplus runs the tool AMRFinderPlus)
    kind = 'model' if entry.get('type') == 'model' else 'software'
    agent = URIRef(f"{sample}#{kind}-{_slug(entry['name'])}-{entry.get('version', '')}")
    graph.add((agent, RDF.type, PROV.SoftwareAgent))
    graph.add((agent, RDFS.label, label))
    graph.add((agent, SCHEMA.name, Literal(entry['name'])))
    graph.add((agent, SCHEMA.softwareVersion, Literal(entry.get('version', ''))))
    if entry.get('biotools'):
        graph.add((agent, PROV.specializationOf, URIRef(f"https://bio.tools/{entry['biotools']}")))
    if entry.get('type') == 'model':
        graph.add((agent, PROV.specializationOf, model_iri(entry['name'])))
        for weights in entry.get('weights', []):
            node = URIRef(f"{sample}#weights-{weights['sha256'][:16]}")
            graph.add((node, RDF.type, PROV.Entity))
            about = f" for {weights['antibiotic']}" if weights.get('antibiotic') else ''
            graph.add((node, RDFS.label, Literal(f"{entry['name']} weights{about}")))
            graph.add((node, SCHEMA.sha256, Literal(weights['sha256'])))
            graph.add((activity, PROV.used, node))
    graph.add((activity, PROV.wasAssociatedWith, agent))


def task_iri(sample, task):
    return URIRef(f'{sample}#task-{task.pk}')


def result_iri(activity, about):
    """The IRI of the result of the prediction `activity` about an antibiotic (its name) or a class (its CURIE)."""
    return URIRef(f'{activity}-result-{_slug(about)}')


def add_results(graph, task, activity):
    """Add to `graph` the results of the completed prediction `task` (its `activity`), see above."""
    for antibiotic, result in task.results.items():
        term = aro_terms().get(antibiotic)
        if not isinstance(result, dict) or term is None:
            continue  # no result, or an antibiotic that is not in terms.ttl
        node = result_iri(activity, antibiotic)
        classes = result.get('inferred_from', [])
        # A verdict inferred from classes is derived from the results about them, which have the evidence
        _add_result(graph, node, activity, term, {key: value for key, value in result.items()
                                                  if not (classes and key == 'evidence')}, antibiotic)
        for curie in classes:
            source = result_iri(activity, curie)
            _add_result(graph, source, activity, OBO[curie.replace(':', '_')],
                        {'call': result.get('call'), 'evidence': result.get('evidence', [])}, curie)
            graph.add((node, PROV.wasDerivedFrom, source))


def _add_result(graph, node, activity, term, result, label):
    """Add the result `result` about `term`, with its evidence."""
    graph.add((node, RDF.type, PROV.Entity))
    graph.add((node, RDFS.label, Literal(f'Result about {label}', lang='en')))
    graph.add((node, PROV.wasGeneratedBy, activity))
    graph.add((node, IS_ABOUT, term))
    if result.get('call') in VERDICTS:
        graph.add((node, RDF.type, VERDICTS[result['call']]))
    if result.get('score') is not None:
        graph.add((node, SCHEMA.value, Literal(Decimal(str(round(result['score'], 4))), datatype=XSD.decimal)))
    for index, item in enumerate(result.get('evidence', []), start=1):
        graph.add((node, PROV.wasDerivedFrom, _add_evidence(graph, URIRef(f'{node}-evidence-{index}'), item)))


def _add_evidence(graph, node, item):
    graph.add((node, RDF.type, PROV.Entity))
    if item.get('gene'):
        graph.add((node, SCHEMA.name, Literal(item['gene'])))
    if item.get('accession'):
        graph.add((node, RDFS.seeAlso, URIRef(NCBI_PROTEIN + item['accession'])))
    for rule in item.get('rules', []):
        graph.add((node, DCTERMS.identifier, Literal(rule)))
    return node



def registry_iri(step):
    """The resource of the registry that describes a step: its model, for a prediction."""
    return model_iri(step.model_name) if step.category == 'prediction' else step_iri(step)


def _slug(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def _entry(entries, link):
    """The piece of data of the sample a task input is: the file in that role or, if the file is
    part of the sample in another role (e.g. a Bakta JSON read as genes), in that one."""
    if (link.file.pk, link.role) in entries:
        return entries[(link.file.pk, link.role)]
    return next((iri for (file_id, _), iri in sorted(entries.items()) if file_id == link.file.pk), None)
