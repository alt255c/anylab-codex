"""Resume the two LR4.2 parameter grids at completed simulation runs."""
import csv
from decimal import Decimal, InvalidOperation
import hashlib
from itertools import groupby, product
import json
from pathlib import Path
from tempfile import mkdtemp

from bridge.anylogic import field, put
from models import child, children, load
from projects import copy_resources


def read_grid(model_path, experiment, metrics):
    doc, model = load(model_path)
    experiment_node = next(node for node in children(child(model, "Experiments"), "ParamVariationExperiment")
                           if field(node, "Name") == experiment)
    if field(experiment_node, "UseFreeformParameters") == "true" or field(
            child(experiment_node, "ReplicationsProperties"), "UseReplication") == "true":
        raise ValueError("Для возобновления ЛР4.2 нужна сетка без повторений")
    names = {field(node, "Id"): field(node, "Name") for node in model.getElementsByTagName("Variable")}
    headers = {expression: label for label, expression in metrics.items()}
    axes = []
    for row in children(experiment_node, "RangeVariationParamValue"):
        if field(row, "Type") != "RANGE":
            continue
        lo, hi, step = (Decimal(field(child(row, key), "Code")) for key in ("From", "To", "Step"))
        if step <= 0 or hi < lo:
            raise ValueError(f"Некорректная сетка эксперимента {experiment}")
        values = tuple(lo + i * step for i in range(int((hi - lo) // step) + 1))
        axes.append((field(row, "Id"), headers[names[field(row, "Id")]], values))
    if not axes:
        raise ValueError(f"У эксперимента {experiment} нет варьируемых параметров")
    return doc, experiment_node, axes


def read_rows(path, headers, keys, expected):
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(headers):
            return {}
        result = {}
        for row in reader:
            if None in row or any(not value for value in row.values()):
                continue
            try:
                numbers = {column: Decimal(value) for column, value in row.items()}
            except InvalidOperation:
                continue
            key = tuple(numbers[column] for column in keys)
            if all(value.is_finite() for value in numbers.values()) and key in expected:
                result[key] = row
        return result


def missing_batches(axes, expected, completed):
    # One slice along the first axis. A contiguous range keeps the original step.
    axis = axes[0][2]
    order = {value: i for i, value in enumerate(axis)}
    for suffix in product(*(axis[2] for axis in axes[1:])):
        indices = [order[key[0]] for key in expected if key[1:] == suffix and key not in completed]
        for _, group in groupby(enumerate(indices), lambda item: item[1] - item[0]):
            batch = [axis[index] for _, index in group]
            for i in range(0, len(batch), 3):
                yield [(value, *suffix) for value in batch[i:i + 3]]


def saved_rows(source, experiment, metrics, data, digest, keys, expected):
    completed = {}
    for directory in sorted(data.glob("эксперимент-*"), key=lambda item: item.stat().st_mtime):
        provenance = directory / "Сетка.json"
        result = directory / "run" / "result.json"
        try:
            if provenance.is_file():
                info = json.loads(provenance.read_text(encoding="utf-8"))
            elif result.is_file():
                info = json.loads(result.read_text(encoding="utf-8"))
                if Path(info.get("model", "")).resolve() != source:
                    continue
            else:
                continue
        except (OSError, ValueError):
            continue
        if (info.get("experiment"), info.get("sha256")) == (experiment, digest):
            completed.update(read_rows(directory/"run"/"metrics.csv", metrics, keys, expected))
    return completed


def resume_grid(path, experiment, metrics, data, output, run_model, update):
    source = Path(path).resolve()
    _, _, axes = read_grid(source, experiment, metrics)
    expected = list(product(*(axis[2] for axis in axes)))
    keys = [axis[1] for axis in axes]
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    completed = saved_rows(source, experiment, metrics, data, digest, keys, expected)
    update(len(completed), len(expected), None)
    for batch in missing_batches(axes, expected, completed):
        attempt = Path(mkdtemp(prefix="эксперимент-", dir=data))
        stage = attempt / "Модель"
        stage.mkdir()
        copy_resources(source, stage, False)
        doc, node, _ = read_grid(source, experiment, metrics)
        ranges = {field(row, "Id"):row for row in children(node, "RangeVariationParamValue")}
        for i, (identifier, _, _) in enumerate(axes):
            put(child(ranges[identifier], "From"), "Code", str(batch[0][i]))
            put(child(ranges[identifier], "To"), "Code", str(batch[-1][i]))
        staged = stage / source.name
        staged.write_bytes(doc.toxml(encoding="utf-8"))
        provenance = {"experiment":experiment, "sha256":digest}
        (attempt/"Сетка.json").write_text(json.dumps(provenance, ensure_ascii=False), encoding="utf-8")
        run_folder = attempt / "run"
        table = run_folder / "metrics.csv"
        update(len(completed), len(expected), table)
        error = None
        try:
            run_model(staged, run_folder, experiment, timeout=900, close=True, metrics=metrics)
        except RuntimeError as exc:
            error = exc
        completed.update(read_rows(table, metrics, keys, batch))
        update(len(completed), len(expected), None)
        if any(key not in completed for key in batch):
            raise RuntimeError(f"4.2 · {experiment}. Сохранено прогонов: {len(completed)} из {len(expected)}. "
                               "Продолжение запустит оставшиеся комбинации.") from error
    output = Path(output)
    pending = output.with_suffix(".tmp")
    with pending.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=metrics)
        writer.writeheader()
        writer.writerows(completed[key] for key in expected)
    pending.replace(output)
    update(len(expected), len(expected), None)
    return str(output)
