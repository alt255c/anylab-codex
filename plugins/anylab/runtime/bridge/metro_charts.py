"""Compact native AnyLogic experiment screens for the Lab 4 templates."""
from xml.dom import Node


TITLES = {
    "ВарьированиеИнтенсивностиВход": "4.1 · Варьирование интенсивности входа",
    "ВарьированиеВремявТЦ": "4.2 · Варьирование времени в ТЦ",
    "ВлияниеПотокаМетроНаТц": "4.2 · Влияние потока метро на ТЦ",
}


def elements(parent, tag=None):
    return [node for node in parent.childNodes if node.nodeType == Node.ELEMENT_NODE
            and (tag is None or node.tagName == tag)]


def update(fields, **values):
    for tag, value in values.items():
        if tag in fields and fields[tag].firstChild is not None:
            fields[tag].firstChild.data = str(value)


def compact_experiment(experiment):
    fields = {node.tagName: node for node in elements(experiment)}
    title = TITLES.get(fields["Name"].firstChild.data)
    if not title or "Presentation" not in fields:
        return
    presentation = fields["Presentation"]
    plots = elements(presentation, "Plot")
    if len(plots) not in (1, 4):
        return

    # Keep the editor's 1000×600 model frame and leave room below the legends.
    compact_grid = len(plots) == 4
    for index, plot in enumerate(plots):
        x, y = (336 + 270 * (index % 2), 82 + 186 * (index // 2)) if compact_grid else (336, 104)
        width, height = (250, 174) if compact_grid else (450, 310)
        properties = {node.tagName: node for node in elements(plot)}
        update(properties, X=x, Y=y, Width=width, Height=height)
        if "ChartArea" in properties:
            area = {node.tagName: node for node in elements(properties["ChartArea"])}
            update(area, YOffset=18, Width=width - 80, Height=height - 75)

    for element in elements(presentation):
        properties = {node.tagName: node for node in elements(element)}
        if element.tagName == "Text":
            name = properties["Name"].firstChild.data
            if name == "text":
                update(properties, X=24, Y=24, Text=title)
                update({node.tagName: node for node in elements(properties["Font"])}, Size=20)
            elif name.startswith("text") and name[4:].isdigit():
                index = int(name[4:])
                y = {1: 60, 2: 60, 3: 82}.get(index, 107 + 18 * ((index - 4) // 2))
                right = index == 2 or (index >= 5 and index % 2 == 1)
                update(properties, X=290 if right else 34, Y=y)
        elif element.tagName == "Line":
            update(properties, X=24, Y=96, Dx=276)
        elif element.tagName == "Rectangle":
            name = properties["Name"].firstChild.data
            if name == "rectangle" or (name.startswith("rectangle") and name[9:].isdigit()):
                index = int(name[9:] or 0)
                update(properties, X=24, Y=121 + index * 36, Width=276, Height=18)

    # The chart still uses these datasets. Hide their editor icons in the player.
    for group, tag in (("Variables", "Variable"), ("AnalysisData", "DataSet")):
        if group in fields:
            for item in elements(fields[group], tag):
                update({node.tagName: node for node in elements(item)}, PresentationFlag="false")


def compact_metro_charts(model):
    for experiments in elements(model, "Experiments"):
        for experiment in elements(experiments, "ParamVariationExperiment"):
            compact_experiment(experiment)
