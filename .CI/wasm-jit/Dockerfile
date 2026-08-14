# Image for the targets needing the Rust omc (wasm-jit); the nodes run an Ubuntu
# too old to build it. Built by .CI/Jenkinsfile, with this directory as the
# context (the job copies requirements.txt into it).
FROM docker.openmodelica.org/build-deps:ubuntu-26.04-rust

# rsync/ssh publish the results; time and killall are used around test.py.
# libcomedi-dev libx11-dev is used by Modelica_DeviceDrivers
RUN export DEBIAN_FRONTEND=noninteractive \
  && apt-get update \
  && apt-get install -qy --no-install-recommends openssh-client psmisc rsync time \
  && apt-get install -qy --no-install-recommends libcomedi-dev libx11-dev \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

# On PATH rather than named explicitly: test.py starts testmodel.py through its
# `#!/usr/bin/env python3` shebang.
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/libtest-venv \
  && /opt/libtest-venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
  # Python dependencies of library install scripts (e.g. Buildings EnergyPlus)
  && /opt/libtest-venv/bin/pip install --no-cache-dir jinja2 \
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
