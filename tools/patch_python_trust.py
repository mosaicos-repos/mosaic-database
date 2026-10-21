#!/usr/bin/env python3
"""Install authenticated local wheels and repair the pip seed for future venvs.

Run inside the target image, after prepare-python-trust.sh verifies the wheels.
"""

import argparse
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheels", type=Path)
    parser.add_argument(
        "--venv-only",
        action="store_true",
        help="patch this venv without changing the host ensurepip seed",
    )
    args = parser.parse_args()
    in_venv = sys.prefix != sys.base_prefix
    if in_venv != args.venv_only:
        raise RuntimeError(
            "use --venv-only inside a venv; seed repair requires an image interpreter"
        )
    wheels = args.wheels.resolve()
    pip_wheel = wheels / "pip-26.2.2-py3-none-any.whl"
    certifi_wheel = wheels / "certifi-2026.10.19-py3-none-any.whl"
    for wheel, expected in (
        (pip_wheel, "fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"),
        (
            certifi_wheel,
            "42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b",
        ),
    ):
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"incorrect wheel checksum: {wheel.name}")
    # Bootstrapping directly from the wheel also works when pip is absent or old.
    env = dict(os.environ, PYTHONPATH=str(pip_wheel), PIP_CONFIG_FILE=os.devnull)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "--isolated",
            "install",
            "--no-index",
            "--no-deps",
            "--upgrade",
            "--break-system-packages",
            str(pip_wheel),
            str(certifi_wheel),
        ],
        env=env,
        check=True,
    )

    if args.venv_only:
        subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import pip, certifi, sys; "
                "sys.exit(0 if (pip.__version__, certifi.__version__) == "
                "('26.2.2', '2026.10.19') else 'unexpected venv trust package versions')",
            ],
            check=True,
        )
        return

    seed = importlib.util.find_spec("ensurepip")
    if seed is None:
        raise RuntimeError(
            "ensurepip is missing; cannot secure future virtual environments"
        )
    source = Path(seed.origin)
    # CPython 3.10/3.11 select a named wheel; newer versions discover it.
    text = source.read_text()
    text = re.sub(
        r"(?m)^_PIP_VERSION\s*=\s*[\"\'][^\"\']+[\"\']", '_PIP_VERSION = "26.2.2"', text
    )
    source.write_text(text)
    destinations = {source.parent / "_bundled"}
    system_wheels = sysconfig.get_config_var("WHEEL_PKG_DIR")
    if system_wheels:
        destinations.add(Path(system_wheels))
    for destination in destinations:
        destination.mkdir(parents=True, exist_ok=True)
        for old in destination.glob("pip-*.whl"):
            old.unlink()
        shutil.copyfile(pip_wheel, destination / pip_wheel.name)
    # Use a fresh interpreter; ensurepip may have cached its package selection.
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import ensurepip, pip, certifi, sys; "
            "versions = (ensurepip.version(), pip.__version__, certifi.__version__); "
            "sys.exit(0 if versions == ('26.2.2', '26.2.2', '2026.10.19') "
            "else 'unexpected trust package versions: ' + repr(versions))",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
