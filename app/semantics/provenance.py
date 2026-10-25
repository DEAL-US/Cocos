"""Provenance of a sample (PROV-O): what was done with its data, when, and by what.

It is added to the RDF description of the sample (semantics.sample). Each task of the process is a
prov:Activity: its status (schema:actionStatus, also for tasks that failed or have not run yet),
when it started and ended, the data of the sample it used and generated, and the step or model of
the registry it ran. The user is a single anonymous prov:Person per sample: the provenance says
that a user of this Cocos instance uploaded the files and asked for the steps, not who.

The software a task used (Task.software) is described too: tools and models are versioned
prov:SoftwareAgents of the activity, specializations of their bio.tools entry or of the model of
the registry; databases (identified by their DOI, when they have one) and the weights of models
(by their SHA-256) are prov:Entities the activity used.
"""
import re

from rdflib import Literal, URIRef
from rdflib.namespace import PROV, RDF, RDFS, XSD

from core.models import TaskStatus
from core.steps import UnknownStepError, software_label

from .namespaces import SCHEMA
from .registry.descriptors import model_iri
from .registry.steps import step_iri

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
        for entry in task.software:
            add_software(graph, sample, activity, entry)

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

    agent = URIRef(f"{sample}#software-{_slug(entry['name'])}-{entry.get('version', '')}")
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
            graph.add((node, RDFS.label, Literal(f"{entry['name']} weights for {weights['antibiotic']}")))
            graph.add((node, SCHEMA.sha256, Literal(weights['sha256'])))
            graph.add((activity, PROV.used, node))
    graph.add((activity, PROV.wasAssociatedWith, agent))


def task_iri(sample, task):
    return URIRef(f'{sample}#task-{task.pk}')


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
