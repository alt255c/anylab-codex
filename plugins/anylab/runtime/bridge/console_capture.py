"""Optional early JVM diagnostics; uses the JDK bundled with AnyLogic."""
from pathlib import Path
import hashlib,os,subprocess,tempfile,zipfile


def agent_jar(home):
    compiler=Path(home)/"jre/bin/javac.exe"
    if not compiler.is_file():return None
    source=Path(__file__).with_name("RunConsole.java")
    digest=hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    cache=Path(os.environ.get("LOCALAPPDATA",Path.home()/".cache"))/"AnyLabCodex/bridge"
    cache.mkdir(parents=True,exist_ok=True)
    target=cache/("console-"+digest+".jar")
    if target.exists():return target
    with tempfile.TemporaryDirectory(dir=cache) as folder:
        subprocess.run([str(compiler),"--release","8","-d",folder,str(source)],check=True,capture_output=True,timeout=30)
        stage=Path(folder)/"capture.jar"
        with zipfile.ZipFile(stage,"w") as jar:
            jar.writestr("META-INF/MANIFEST.MF","Manifest-Version: 1.0\nPremain-Class: RunConsole\n\n")
            jar.write(Path(folder)/"RunConsole.class","RunConsole.class")
        try:os.link(stage,target)
        except FileExistsError:pass
    return target
