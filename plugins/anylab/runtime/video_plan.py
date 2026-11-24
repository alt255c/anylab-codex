"""Apply the agreed camera plan without changing simulation parameters."""
import json
import math
from pathlib import Path


def load_plan(source, route, timing, seconds):
    path = Path(source).parent / 'video-plan.json'
    if not path.is_file():
        return route, timing, None
    plan = json.loads(path.read_text(encoding='utf8'))
    chosen = plan.get('camera_route', route)
    holds = plan.get('hold_seconds')
    move = plan.get('transition_seconds', 2)
    first = plan.get('two_d_seconds', 12)
    numeric = lambda n: type(n) in (int,float) and math.isfinite(n)
    if len(chosen)<2 or any(len(row)!=5 or not all(numeric(n) for n in row) for row in chosen):
        raise ValueError('camera_route: нужны координаты и два угла для каждой точки')
    if not isinstance(holds,list) or len(holds)!=len(chosen) or any(not numeric(n) or n<5 for n in holds):
        raise ValueError('hold_seconds: минимум 5 секунд на каждую точку')
    if not numeric(move) or not 2<=move<=3 or not numeric(first) or first<8:
        raise ValueError('Переходы 2–3 секунды; первый показ 2D не короче 8 секунд')
    if abs(first+sum(holds)+move*(len(chosen)-1)-seconds)>.01:
        raise ValueError('Длительность плана камеры не совпадает с seconds')
    labels=plan.get('stop_labels',[])
    if labels and len(labels)!=len(chosen):raise ValueError('stop_labels не соответствует точкам')
    starts=[first]
    for hold in holds[:-1]:starts.append(starts[-1]+hold+move)
    return chosen,dict(two_d_seconds=first,holds=holds,moves=[move]*(len(chosen)-1),starts=starts),plan
