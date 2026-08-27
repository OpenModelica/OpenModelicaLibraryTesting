# The image every library testing job runs in: it builds omc, OMSimulator and runs test.py.
# Built by .CI/Jenkinsfile, with this directory as the context (the job copies requirements.txt
# into it).
#
# One image for all of them rather than one per target: what a node then needs is docker, git and
# an ssh key instead of a set of packages kept up to date by hand, and a job moved to another
# machine tests what it tested before. The base is the one the wasm-jit target needs - the OMDev
# image the OpenModelica repository builds against, in the variant carrying the Rust toolchain,
# since a Rust omc cannot be built on the Ubuntu the nodes run, and its sccache keys only hit for
# the toolchain that job used.
FROM docker.openmodelica.org/build-deps:ubuntu-26.04-rust

# rsync/ssh publish the results; time and killall are used around test.py.
# libcomedi-dev libx11-dev is used by Modelica_DeviceDrivers
# Python 3.8 and 3.12 are used by Buildings
# autoconf/automake/libtool and omniORB build the targets that do not ask for a cmake omc: those
# still go through `autoreconf && ./configure --with-omniORB`. The base image carries what the
# cmake build needs, which is not quite the same set.
RUN export DEBIAN_FRONTEND=noninteractive \
  && apt-get update \
  && apt-get install -qy software-properties-common \
  && add-apt-repository -y ppa:deadsnakes/ppa \
  && apt-get install -qy --no-install-recommends openssh-client psmisc rsync time \
  && apt-get install -qy --no-install-recommends libcomedi-dev libx11-dev \
  && apt-get install -qy --no-install-recommends autoconf automake libtool omniidl libomniorb4-dev \
  && apt-get install -qy python3.8 python3.12 libpython3.8-dev libpython3.12-dev \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

# On PATH rather than named explicitly: test.py starts testmodel.py through its
# `#!/usr/bin/env python3` shebang.
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/libtest-venv \
  && /opt/libtest-venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
  # Python dependencies of library install scripts (e.g. Buildings EnergyPlus)
  && /opt/libtest-venv/bin/pip install --no-cache-dir jinja2 \
  # The simulator of the -fmi-fmpy targets, which test.py runs as `python3 -m fmpy`. Its version
  # is the image's: a job cannot pip install one over it that outlives the container.
  && /opt/libtest-venv/bin/pip install --no-cache-dir FMPy \
  && rm /tmp/requirements.txt
ENV PATH=/opt/libtest-venv/bin:$PATH

# The omc for --ompython_omhome (the tested one is built in the workspace). The
# base image points apt at the nightly component; use stable instead.
# OMC_VERSION pins a version, empty takes the newest stable one.
ARG OMC_VERSION=
RUN export DEBIAN_FRONTEND=noninteractive \
  && . /etc/os-release \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/openmodelica-keyring.gpg]" \
          "https://build.openmodelica.org/apt ${VERSION_CODENAME} stable" \
     > /etc/apt/sources.list.d/openmodelica.list \
  && apt-get update \
  && apt-get install -qy omc${OMC_VERSION:+=${OMC_VERSION}} \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/* \
  && omc --version
