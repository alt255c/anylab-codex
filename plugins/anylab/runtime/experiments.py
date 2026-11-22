"""Budget native AnyLogic experiments by a timed, single-replication pilot."""
from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.dom import minidom
import json

from projects import copy_resources, materialize, new_directory


def children(node, tag):
    return [n for n in node.childNodes if n.nodeName == tag]


def field(node, path, *, optional=False):
    for tag in path.split("/"):
        found = children(node, tag)
        if len(found) != 1:
            if optional and not found:
                return None
            raise ValueError(f"Неизвестная структура ALP: {path}")
        node = found[0]
    return node


def value(node, path):
    return "".join(n.data for n in field(node, path).childNodes
                   if n.nodeType in (n.TEXT_NODE, n.CDATA_SECTION_NODE)).strip()


def put(node, path, text):
    element = field(node, path)
    for child in list(element.childNodes):
        element.removeChild(child)
    element.appendChild(node.ownerDocument.createTextNode(str(text)))


def configure(alp, output, name, capacity, pilot):
    doc = minidom.parse(str(alp))
    group = doc.getElementsByTagName("Experiments")[0]
    matches = [e for e in group.childNodes if e.nodeType == e.ELEMENT_NODE and
               value(e, "Name") == name]
    if len(matches) != 1:
        raise ValueError(f"Эксперимент не найден: {name}")
    e = matches[0]
    kind = e.tagName
    if kind not in ("ParamVariationExperiment", "OptimizationExperiment"):
        raise ValueError(f"Бюджетирование недоступно для {kind}")
    stop = value(e, "ModelTimeProperties/StopOption")
    if "specified" not in stop.lower():
        raise ValueError("Установите конечный горизонт каждого прогона в исходной модели")
    reps = field(e, "ReplicationsProperties", optional=True)
    enabled = reps is not None and value(reps, "UseReplication") == "true"
    fixed = enabled and value(reps, "FixedReplicationsNumber") == "true"
    count_path = "ReplicationPerIteration" if fixed else "MaximumReplication"
    old_reps = int(value(reps, count_path)) if enabled else 1
    minimum = int(value(reps, "MinimumReplication")) if enabled and not fixed else 1
    if kind == "OptimizationExperiment":
        iteration_field = "ModelTimeProperties/IterationCount"
        if value(e, "ModelTimeProperties/StopAfterIterationCount") != "true":
            raise ValueError("Для оптимизации задайте верхнюю границу числа итераций")
    elif value(e, "UseFreeformParameters") == "true":
        iteration_field = "NumberOfRuns"
    else:
        iteration_field = None
    ranges = []
    old_iterations = 1
    if iteration_field:
        old_iterations = int(value(e, iteration_field))
    else:
        for row in children(e, "RangeVariationParamValue"):
            if value(row, "Type") == "RANGE":
                try:
                    lo, hi, step = [Decimal(value(row, f"{key}/Code")) for key in ("From", "To", "Step")]
                    if not all(x.is_finite() for x in (lo, hi, step)) or step <= 0 or hi < lo:
                        raise ValueError("Некорректный диапазон")
                except InvalidOperation as exc:
                    raise ValueError("Для расчёта сетки нужны числовые границы и шаг") from exc
                n = int((hi - lo) // step) + 1
                old_iterations *= n
                ranges.append((row, lo + (n-1) * step))
    if min(old_iterations, old_reps, minimum) < 1:
        raise ValueError("В эксперименте заданы неположительные счётчики")
    if pilot:
        iterations, repeats = 1, 1
        if enabled and not fixed:
            put(reps, "FixedReplicationsNumber", "true")
        for row, upper in ranges:
            for bound in ("From", "To"):
                put(row, bound + "/Code", format(upper, "f"))
    else:
        iterations = min(old_iterations, capacity // minimum) if iteration_field else old_iterations
        if not iterations or iterations * minimum > capacity:
            raise ValueError(f"В бюджет помещается {capacity} прогонов. План требует минимум "
                             f"{old_iterations * minimum if not iteration_field else minimum}. "
                             "Согласуйте более редкую сетку или меньший горизонт с условием работы.")
        repeats = min(old_reps, capacity // iterations)
    if iteration_field:
        put(e, iteration_field, iterations)
    if enabled:
        put(reps, "ReplicationPerIteration" if pilot else count_path, repeats)
    output.write_bytes(doc.toxml(encoding="UTF-8"))
    return dict(experiment=name, kind=kind, original_iterations=old_iterations,
                original_max_repeats=old_reps, iterations=iterations, max_repeats=repeats,
                max_total_runs=iterations * repeats, pilot=pilot)


def budget(source, destination, experiment, minutes=12, pilot_seconds=None, member=None, overhead_seconds=0):
    minutes = float(minutes)
    if not math.isfinite(minutes) or not 0 < minutes <= 15:
        raise ValueError("Бюджет должен быть положительным и не превышать 15 минут")
    pilot = pilot_seconds is None
    if not pilot:
        pilot_seconds = float(pilot_seconds)
        if not math.isfinite(pilot_seconds) or pilot_seconds <= 0:
            raise ValueError("Нужно положительное измеренное время полного пилота в секундах")
    overhead_seconds = float(overhead_seconds)
    if not math.isfinite(overhead_seconds) or overhead_seconds < 0:
        raise ValueError("Время подготовки должно быть неотрицательным")
    capacity = 1 if pilot else max(0, math.floor((60 * minutes * .8 - overhead_seconds) / pilot_seconds))
    with materialize(source, member) as (alp, archived), new_directory(destination) as stage:
        copy_resources(alp, stage, archived)
        result = configure(alp, stage / alp.name, experiment, capacity, pilot)
        result.update(minutes=minutes, pilot_seconds=pilot_seconds, capacity=capacity,
                      overhead_seconds=overhead_seconds,
                      model=str(Path(destination).resolve() / alp.name))
        if not pilot:
            result["estimated_seconds"] = round(overhead_seconds + result["max_total_runs"] * pilot_seconds, 2)
        (stage / "budget.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    return result
