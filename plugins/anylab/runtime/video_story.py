"""Assemble live AnyLogic views into one consistently encoded demonstration."""
from pathlib import Path
import json, subprocess, math


def assemble_clips(clips, destination):
    from bridge.media import encoder
    target=Path(destination).resolve()
    if target.exists(): raise FileExistsError(target)
    command=[encoder(),"-hide_banner","-loglevel","error","-n"]
    for clip in clips:
        command += ["-ss",str(clip.get("start",0)),"-t",str(clip["seconds"]),"-i",str(Path(clip["path"]).resolve(strict=True))]
    filters=[]
    for i in range(len(clips)):
        filters.append(f"[{i}:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30,setpts=PTS-STARTPTS[v{i}]")
    filters.append("".join(f"[v{i}]" for i in range(len(clips)))+f"concat=n={len(clips)}:v=1:a=0[out]")
    command += ["-filter_complex",";".join(filters),"-map","[out]","-an","-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p","-movflags","+faststart",str(target)]
    subprocess.run(command,check=True)
    return str(target)


def record_story(model, destination, shots):
    from video_demo import record_demo
    if not isinstance(shots,list) or not 1<=len(shots)<=8:
        raise ValueError("Укажите от одного до восьми планов")
    allowed={"seconds","three_d","speed","camera","warmup","source","start"}
    for shot in shots:
        if not isinstance(shot,dict) or set(shot)-allowed or not 3<=shot.get("seconds",0)<=120:
            raise ValueError("План принимает seconds, three_d, speed, camera, warmup, source, start")
        start=shot.get("start",0)
        if not isinstance(start,(int,float)) or not math.isfinite(start) or start<0: raise ValueError("Некорректное время начала плана")
    if sum(s["seconds"] for s in shots)>300: raise ValueError("Общая длительность должна быть до 300 секунд")
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=False)
    clips=[];pictures=[]
    for number,shot in enumerate(shots,1):
        if shot.get("source"):
            path=Path(shot["source"]).resolve(strict=True)
        else:
            folder=root/f"shot-{number}";folder.mkdir()
            record_demo(Path(model).resolve(strict=True),folder,folder,shot["seconds"],shot.get("three_d",True),3,shot.get("speed",2),True,shot.get("camera"),shot.get("warmup",8))
            path=folder/"demo.mp4";pictures.append(str(folder/"scene.png"))
        clips.append({"path":str(path),"start":shot.get("start",0),"seconds":shot["seconds"],"three_d":shot.get("three_d",True)})
    video=assemble_clips(clips,root/"demo.mp4")
    (root/"story.json").write_text(json.dumps({"shots":clips,"editing":"Cuts between actual simulation recordings; 2D first, then 3D."},ensure_ascii=False,indent=2),encoding="utf8")
    return dict(video=video,shots=pictures)
