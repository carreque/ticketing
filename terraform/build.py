import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "..", "src")
BUILD = os.path.join(ROOT, "build")
REQUIREMENTS = os.path.join(ROOT, "..", "requirements.txt")

FUNCS = {
    "create_ticket": ["create_ticket", "common", "exceptions"],
    "get_ticket": ["get_ticket", "common", "exceptions"],
}


def pathExists():
    if os.path.exists(BUILD):
        shutil.rmtree(BUILD)

def vendorRuntimeDependenciesIntoLambdaPackage(target: str):
    subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "--platform", "manylinux2014_x86_64",
            "--implementation", "cp",
            "--python-version", "3.13",
            "--only-binary=:all:",
            "--target", target,
            "-r", REQUIREMENTS,
        ])
    
def build():
    pathExists()
    for func, packages in FUNCS.items():
        target = os.path.join(BUILD, func)
        os.makedirs(target)
        for pkg in packages:
            shutil.copytree(os.path.join(SRC, pkg), os.path.join(target, pkg))
        vendorRuntimeDependenciesIntoLambdaPackage(target)


if __name__ == "__main__":
    build()