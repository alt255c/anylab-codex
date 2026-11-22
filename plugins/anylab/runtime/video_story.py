"""Join live simulation shots at their native aspect ratio."""
from pathlib import Path
import json, subprocess


def record_story(model, destination, shots):
    from video_demo import record_demo
    from bridge.media import encoder
    if not isinstance(shots,list) or not 1<=len(shots)<=8:
        raise ValueError("Укажите от одного до восьми планов")
    allowed={"seconds","three_d","speed","camera","warmup"}
    for shot in shots:
        if not isinstance(shot,dict) or set(shot)-allowed or not 3<=shot.get("seconds",0)<=120:
            raise ValueError("План принимает seconds, three_d, speed, camera, warmup")
    if sum(s["seconds"] for s in shots)>300:
        raise ValueError("Общая длительность должна быть до 300 секунд")
    root=Path(destination).resolve()
    root.mkdir(parents=True,exist_ok=False)
    for number,shot in enumerate(shots,1):
        folder=root/f"shot-{number}"
        folder.mkdir()
        record_demo(Path(model).resolve(strict=True),folder,folder,shot["seconds"],
                    shot.get("three_d",True),3,shot.get("speed",2),True,
                    shot.get("camera"),shot.get("warmup",8))
    listing=root/"shots.txt"
    listing.write_text("".join(f"file 'shot-{i}/demo.mp4'\n" for i in range(1,len(shots)+1)),encoding="utf8")
    subprocess.run([encoder(),"-hide_banner","-loglevel","error","-n","-f","concat","-safe","0",
                    "-i",str(listing),"-c","copy","-movflags","+faststart",str(root/"demo.mp4")],check=True)
    (root/"story.json").write_text(json.dumps(shots,ensure_ascii=False,indent=2),encoding="utf8")
    return dict(video=str(root/"demo.mp4"),shots=[str(root/f"shot-{i}/scene.png") for i in range(1,len(shots)+1)])
