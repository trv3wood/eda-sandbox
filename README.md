# Open-source EDA sandbox

This repository provides two small container environments for the same EDA
experiments:

- `eda-fast`: Ubuntu 24.04 for fast development and distribution packages.
- `eda-scc`: Ubuntu 24.04 with the same fast toolchain plus a compiled SCC/SystemC prefix.
- `eda-enterprise`: Rocky Linux 8 for RHEL-family compatibility checks.

The containers use prebuilt conda-forge packages for Surelog and UHDM instead
of compiling those C++ projects in the image. The primary `eda` environment
uses Python 3.10. Surelog 1.84 currently has Linux conda builds for Python
3.11/3.12, so it is installed in a separate environment and exposed through
the `surelog` wrapper. Commercial EDA tools are intentionally excluded.

## Build and run

With Docker:

```bash
docker compose build
docker compose run --rm eda-fast bash scripts/regress.sh
docker compose run --rm eda-scc bash scripts/regress.sh
docker compose run --rm eda-enterprise bash scripts/regress.sh
```

With Podman (recommended in this environment):

```bash
podman-compose build
podman-compose run --rm eda-fast bash scripts/regress.sh
podman-compose run --rm eda-scc bash scripts/regress.sh
podman-compose run --rm eda-enterprise bash scripts/regress.sh
```

The `eda-fast` target only installs prebuilt packages. The `eda-scc` target
adds a builder stage that checks out the pinned SCC release `2026.05` and
builds it with Conan and CMake, matching SCC's official Ubuntu 24.04 test
image. 
Build it only when SCC is needed:

```bash
podman-compose build eda-fast
podman-compose build eda-scc
```

If you only need to build the images, use Podman's native build command
directly. This does not require a Docker-compatible API socket:

```bash
podman build -f Dockerfile.ubuntu -t eda-fast:local .
podman build -f Dockerfile.ubuntu --target scc -t eda-scc:local .
podman build -f Dockerfile.rocky8 -t eda-enterprise:local .
podman run --rm -it -v "$PWD:/workspace" eda-fast
podman run --rm -it -v "$PWD:/workspace" eda-scc
podman run --rm -it -v "$PWD:/workspace" eda-enterprise
```

Avoid `podman compose` when it reports that it is executing
`docker-compose`. That provider needs a running rootless Podman API socket and
is the source of errors such as `failed to connect to the docker API`.

If you specifically want to keep using that provider, start the user socket
first and then retry:

```bash
systemctl --user enable --now podman.socket
podman compose build
```

Project files should live in `workspace/`. The host directory is mounted at
`/workspace` so source changes persist after a container exits.

The conda-forge environment contains Python 3.10, CMake, Ninja, UHDM,
Verilator, and Yosys. The separate Surelog environment contains Surelog 1.84
and Python 3.11 only for the prebuilt Surelog package. Do not install the
unrelated PyPI package named `surelog`; the container uses the CHIPS Alliance
Surelog executable.

## Scope

This is a containerized open-source toolchain smoke environment, not a VM.
It does not emulate the host kernel, CentOS 7 userspace, LSF, network mounts,
license servers, or commercial tools such as VCS and Verdi. Use a real legacy
environment for the final CentOS 7 compatibility check.
