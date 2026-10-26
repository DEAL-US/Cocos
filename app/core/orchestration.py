"""Process plans: which steps a process runs, in which order and with which inputs.

A plan is a list of nodes {'id', 'step', 'parameters', 'after': [node ids], 'batch': n}, plus
'run' (a PredictionRun id) for prediction nodes. Each node runs as a task; retrying a failed
node adds another task for it. The nodes added by one request (creating the process, annotating
it later, a prediction) share a batch.

A node can be cancelled ('cancelled': True) when a node it depends on fails: it is never launched.

A node's inputs are either files uploaded by the user (only for nodes without dependencies) or
outputs of its dependencies with the same kind of data and format.
"""
from django.db import transaction

# Module import: core.tasks imports this module to advance plans when a task completes.
from core import tasks as core_tasks
from core.models import Failure, ProcessGroup, Task, TaskStatus
from core.steps import UnknownStepError, cocos_software, get_step, list_steps


class PlanError(ValueError):
    pass


def create_process(user, name, nodes, inputs=None, organism=''):
    """Create a process with a plan and launch the nodes that can run.

    `inputs` maps node ids to {role: File} for the files uploaded by the user.
    """
    plan = _new_nodes([], nodes, inputs)
    process = ProcessGroup.objects.create(name=name, user=user, organism=organism, plan=plan)
    advance_plan(process, inputs)
    return process


def extend_plan(process, nodes, inputs=None):
    """Add nodes to the plan of a process and launch those that can run. Return the launched tasks."""
    with transaction.atomic():
        process = ProcessGroup.objects.select_for_update().get(pk=process.pk)
        process.plan = process.plan + _new_nodes(process.plan, nodes, inputs)
        process.save(update_fields=['plan'])
    return advance_plan(process, inputs)


def advance_plan(process, inputs=None):
    """Create and launch a task for each node without task whose dependencies are completed."""
    inputs = inputs or {}
    with transaction.atomic():
        process = ProcessGroup.objects.select_for_update().get(pk=process.pk)
        tasks_by_node = latest_tasks(process)
        launched = []
        for node in process.plan:
            if node['id'] in tasks_by_node or node.get('cancelled'):
                continue
            dependencies = [tasks_by_node.get(node_id) for node_id in node['after']]
            if not all(task is not None and task.status == TaskStatus.COMPLETED for task in dependencies):
                continue
            task = _create_task(process, node, inputs.get(node['id'], {}), dependencies)
            tasks_by_node[node['id']] = task
            launched.append(task)
    _launch(launched)
    return launched


def retry_node(process, node_id):
    """Run a failed node again, with the same inputs as its last task."""
    with transaction.atomic():
        process = ProcessGroup.objects.select_for_update().get(pk=process.pk)
        node = find_node(process, node_id)
        last_task = latest_tasks(process).get(node_id)
        if last_task is None or last_task.status != TaskStatus.FAILED:
            raise PlanError(f"Node {node_id} has not failed, it cannot be retried")
        previous_inputs = {link.role: link.file for link in last_task.task_inputs.select_related('file')}
        task = _create_task(process, node, previous_inputs, dependencies=[])
    _launch([task])
    return task


def blocked_nodes(process, node_id):
    """Nodes without a task that depend, directly or through other nodes, on `node_id`."""
    tasks_by_node = latest_tasks(process)
    blocked_ids, blocked = {node_id}, []
    for node in process.plan:  # nodes only depend on earlier nodes
        if node['id'] not in tasks_by_node and blocked_ids & set(node['after']):
            blocked_ids.add(node['id'])
            blocked.append(node)
    return blocked


def cancel_nodes(process, node_ids):
    """Mark nodes of the plan as cancelled, so they are never launched."""
    with transaction.atomic():
        process = ProcessGroup.objects.select_for_update().get(pk=process.pk)
        for node in process.plan:
            if node['id'] in node_ids:
                node['cancelled'] = True
        process.save(update_fields=['plan'])


def find_node(process, node_id):
    for node in process.plan:
        if node['id'] == node_id:
            return node
    raise PlanError(f"Process {process.pk} has no node {node_id!r}")


def batch_nodes(process, node_id):
    """Return the nodes added to the plan in the same request as `node_id`."""
    batch = find_node(process, node_id)['batch']
    return [node for node in process.plan if node['batch'] == batch]


def is_soft_failure(task, node):
    """A gene extraction that fails after a successful annotation only warns the user:
    the annotation is still available to download."""
    return task.status == TaskStatus.FAILED and bool(node['after']) and task.get_step().category == 'extraction'


def latest_tasks(process):
    """Return {node id: last task of that node}."""
    tasks = Task.objects.filter(process=process).exclude(plan_node='').order_by('id')
    return {task.plan_node: task for task in tasks}


def permanent_failures(process):
    """{(step key, file id): why} of the steps that would fail again on a file of `process`, for the
    discovery, which does not plan them again (semantics.discovery.discover).

    A task that failed for good (Failure.PERMANENT) blocks its step on its input files while the
    software of the step is the same (a new version of a tool, of its database or of Cocos may
    succeed), and any other step that would run one of its tools, in the same version, on those
    files (e.g. an assembly without annotation, after an assembly with annotation failed in Raven).
    """
    failed = {}
    tasks = (Task.objects.filter(process=process, status=TaskStatus.FAILED, failure=Failure.PERMANENT)
             .prefetch_related('task_inputs').order_by('id'))
    for task in tasks:
        try:
            step = get_step(task.step)
        except UnknownStepError:
            continue
        error = task.error.strip().splitlines()[0] if task.error.strip() else 'no error message'
        for other in list_steps():
            if other.key == step.key and same_software(task, step):
                why = f'it already failed on this sample with the same software ({error})'
            elif other.key != step.key and same_tools(task, other):
                why = f'{step.label} already failed on this sample with the same tools ({error})'
            else:
                continue
            for link in task.task_inputs.all():
                failed[(other.key, str(link.file_id))] = why
    return failed


def same_software(task, step):
    """Whether a new task of `step` would use the software `task` used, Cocos included. True when
    it cannot be known now (e.g. the bio service does not answer)."""
    expected = step.expected_software()
    if expected is None:
        return True

    def versions(entries):
        return {(entry['name'], entry.get('version', ''), entry.get('variant', '')) for entry in entries}
    return versions(task.software) == versions([cocos_software(), *expected])


def same_tools(task, step):
    """Whether a new task of `step` would run some tool `task` ran (not Cocos), in the same version."""
    used = {entry['name']: entry.get('version', '') for entry in task.software
            if entry.get('type') == 'tool' and entry['name'] != 'Cocos'}
    expected = step.expected_software() or []
    shared = [entry for entry in expected if entry.get('type') == 'tool' and entry['name'] in used]
    return bool(shared) and all(used[entry['name']] == entry.get('version', '') for entry in shared)


def _launch(tasks):
    # Called outside the transaction so workers see the new tasks.
    for task in tasks:
        core_tasks.run_step.delay(task.id)


def _new_nodes(existing, nodes, inputs):
    """Validate the nodes to add to a plan and return them normalized."""
    inputs = inputs or {}
    known = {node['id']: node for node in existing}
    batch = max((node['batch'] for node in existing), default=0) + 1
    new = []
    for node in nodes:
        node_id = node.get('id')
        if not node_id or node_id in known:
            raise PlanError(f"Node ids must be given and unique: {node_id!r}")
        try:
            step = get_step(node.get('step', ''))
        except UnknownStepError:
            raise PlanError(f"Node {node_id}: unknown step {node.get('step')!r}")

        after = list(node.get('after', []))
        missing = [dependency for dependency in after if dependency not in known]
        if missing:
            raise PlanError(f"Node {node_id} depends on unknown nodes: {missing}")

        provided = inputs.get(node_id, {})
        if provided and after:
            raise PlanError(f"Node {node_id}: only nodes without dependencies take uploaded files")
        _check_inputs(node_id, step, provided, [get_step(known[dependency]['step']) for dependency in after])

        entry = {
            'id': node_id,
            'step': step.key,
            'parameters': step.build_parameters(node.get('parameters')),
            'after': after,
            'batch': batch,
        }
        if node.get('run') is not None:
            entry['run'] = node['run']
        known[node_id] = entry
        new.append(entry)

    unknown_inputs = set(inputs) - known.keys()
    if unknown_inputs:
        raise PlanError(f"Files given for unknown nodes: {sorted(unknown_inputs)}")
    return new


def _check_inputs(node_id, step, provided, dependency_steps):
    roles = {port.role for port in step.consumes}
    extra = set(provided) - roles
    if extra:
        raise PlanError(f"Node {node_id}: step {step.key} has no inputs {sorted(extra)}")
    for port in step.consumes:
        if port.role in provided:
            continue
        sources = [output for dependency in dependency_steps for output in dependency.produces
                   if (output.kind, output.format) == (port.kind, port.format)]
        if len(sources) != 1:
            raise PlanError(f"Node {node_id}: input {port.role!r} needs exactly one source, found {len(sources)}")


def _create_task(process, node, provided, dependencies):
    step = get_step(node['step'])
    model = step.task_model or Task
    extra_fields = {'run_id': node['run']} if node.get('run') is not None else {}
    task = model.objects.create(process=process, step=step.key, parameters=node['parameters'],
                                plan_node=node['id'], **extra_fields)
    for port in step.consumes:
        file = provided.get(port.role) or _dependency_output(port, dependencies)
        task.add_input(port.role, file)
    return task


def _dependency_output(port, dependencies):
    for dependency in dependencies:
        dependency_step = dependency.get_step()
        for link in dependency.task_outputs.select_related('file'):
            output = dependency_step.output_port(link.role)
            if (output.kind, output.format) == (port.kind, port.format):
                return link.file
    raise PlanError(f"No dependency produced the input {port.role!r}")
