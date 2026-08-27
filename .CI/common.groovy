// The functions .CI/Jenkinsfile calls, kept out of it the way the OpenModelica
// repository keeps its own: the pipeline loads this file in its `setup` stage
// and reaches everything here as `common.<function>()`.
//
// A file loaded this way shares the binding of the pipeline, so `params`, `env`
// and the steps (`sh`, `docker`, `withCredentials`, ...) are the same here as
// there. The load happens on one node and the object is used from every stage,
// which is what the OpenModelica pipeline does as well.

/**
  * The pull request this job is testing, or "" when it is testing branches.
  *
  * A job only learns of a parameter that has been added to it once a build has
  * run with the definition, so the first build after this file changes sees the
  * new ones as null - which is every build of the pipeline, not only one asking
  * for a pull request, because the stages that ignore them still have to decide
  * whether to run. Everything that reads them therefore falls back to what the
  * definition says the default is.
  */
def pullRequest() {
  return (params.pull_request ?: '').trim()
}

/**
  * Fails the build unless `pull_request` looks like a pull request number.
  */
def checkPullRequestNumber() {
  if (!(pullRequest() ==~ /[0-9]+/)) {
    error "pull_request is a pull request number; got '${params.pull_request}'"
  }
}

/**
  * Fails the build unless OpenModelica/OpenModelica has the pull request
  * `pull_request` names. Issues and pull requests share one numbering, so an
  * issue number passes checkPullRequestNumber(), and only a pull request has
  * refs/pull/<N>/* on GitHub.
  *
  * Asked before the clone, the reset and the build, which cost minutes before
  * they arrive at the same answer.
  */
def checkPullRequestExists() {
  sh """
  if ! git ls-remote --exit-code https://github.com/OpenModelica/OpenModelica.git 'refs/pull/${pullRequest()}/*' > /dev/null; then
    echo "OpenModelica/OpenModelica has no pull request ${pullRequest()}. Issues and pull requests share one numbering there, so check that ${pullRequest()} is not the number of an issue."
    exit 1
  fi
  """
}

/**
  * Removes the cached omc builds of the pull requests tested more than two weeks
  * ago. One build per pull request is kept, as for a branch, and they accumulate:
  * a pull request is tested once and never again. The second line is the layout
  * of the runs before they moved under pr/.
  */
def removeStalePullRequestBuilds() {
  sh '''
  find "$HOME/saved_omc/pr" -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} ";" 2> /dev/null || true
  find "$HOME/saved_omc" -mindepth 1 -maxdepth 1 -name "pr-*" -type d -mtime +14 -exec rm -rf {} ";" || true
  '''
}

/**
  * The cores of the node a build is running on, physical and logical, asked for
  * the way the OpenModelica job asks (numPhysicalCPU in .CI/common.groovy
  * there), so that a machine is built on as itself rather than as the machine
  * the numbers were written for.
  *
  * Unlike that one the answer is not stashed in the environment: this pipeline
  * is agent none and its stages run on several machines within one build, so a
  * cached answer would be the first node's. An override set on the node itself
  * is still honoured.
  */
def numPhysicalCPU() {
  if (env.JENKINS_NUM_PHYSICAL_CPU) {
    return env.JENKINS_NUM_PHYSICAL_CPU
  }
  return sh(script: 'lscpu -p | egrep -v "^#" | sort -u -t, -k 2,4 | wc -l', returnStdout: true).trim()
}

def numLogicalCPU() {
  if (env.JENKINS_NUM_LOGICAL_CPU) {
    return env.JENKINS_NUM_LOGICAL_CPU
  }
  return sh(script: 'nproc', returnStdout: true).trim()
}

/**
  * Installs the libraries a run tests, with the node's own omc, and returns the home directory
  * holding them. `runSh` is how the conversion script is run: that one uses the omc that was just
  * built, which is a binary of the image when the job has one.
  */
def installLibraries(boolean removePackageOrder, boolean conversionScript, name, String omhomeTestedOMC, Closure runSh) {
  sh "rm -rf '${env.HOME}/saved_omc/libraries/.openmodelica/libraries'"
  sh "mkdir -p '${env.HOME}/saved_omc/libraries/'"
  sh "HOME='${env.HOME}/saved_omc/libraries/' /usr/bin/omc OpenModelicaLibraryTesting/.CI/installLibraries.mos"
  if (removePackageOrder) {
    sh "find '${env.HOME}/saved_omc/libraries/' -name package.order -exec rm '{}' ';'"
  }
  // These exist (better packaged? on the machines)
  sh "rm -rf '${env.HOME}/saved_omc/libraries/ClaRa' '${env.HOME}/saved_omc/libraries/ClaRa_Obsolete' '${env.HOME}/saved_omc/libraries/TILMedia'"
  sh "cp -ai /mnt/ReferenceFiles/ExtraLibs/packaged/* '${env.HOME}/saved_omc/libraries/'"
  echo "installLibraries removePackageOrder: ${removePackageOrder} conversionScript: ${conversionScript} name: ${name}"
  if (conversionScript) {
    runSh("""
    cd '${env.WORKSPACE}/OpenModelicaLibraryTesting'
    OPENMODELICAHOME="${omhomeTestedOMC}" ./conversionscript.py --diff --allowErrorsInDiff '${env.HOME}/saved_omc/libraries/.openmodelica/libraries'
    scp converted-libraries/.openmodelica/libraries/*.diff 'libraries.openmodelica.org:/var/www/libraries.openmodelica.org/branches/${name}'
    """)
    return "${env.WORKSPACE}/OpenModelicaLibraryTesting/converted-libraries"
  } else {
    return "${env.HOME}/saved_omc/libraries"
  }
}

/**
  * `docker run` flags capping the container's cgroup at 90% of the node's RAM. test.py limits one
  * test at a time, not the sum of the parallel ones. --memory-swap has to repeat the limit; docker
  * reads 0 as "unset" and then allows swapping.
  */
def memoryLimitArgs() {
  def mb = sh(script: '''awk '/^MemTotal:/ { print int($2 / 1024 * 0.85) }' /proc/meminfo''',
              returnStdout: true).trim()
  echo "Test container memory limit: ${mb} MB, no swap"
  return "--memory=${mb}m --memory-swap=${mb}m"
}

/**
  * Runs `body` with the environment of the shared Rust compile cache of the OpenModelica job
  * (OpenModelica/.CI/sccache/), which builds the same commits first. Hitting its keys needs the
  * same rust settings (opt-level 2, -DRUST_OMC_THREADS=4 at the call site), the same toolchain
  * (hence the same docker image) and SCCACHE_BASEDIRS set to the checkout directory, which is a
  * subdirectory of the workspace here but the workspace itself there.
  *
  * The server is started by sccachePreamble() instead, since a build in a container cannot use
  * one started outside it.
  */
def withSccache(Closure body) {
  withCredentials([string(credentialsId: 'sccache-ci-secret-key',
                          variable: 'AWS_SECRET_ACCESS_KEY')]) {
    withEnv(['RUSTC_WRAPPER=sccache',
             'SCCACHE_BUCKET=omc-sccache',
             'SCCACHE_ENDPOINT=https://sccache.openmodelica.org',
             'SCCACHE_REGION=auto',
             'SCCACHE_S3_USE_SSL=true',
             'AWS_ACCESS_KEY_ID=sccache-ci',
             'CARGO_INCREMENTAL=0',
             'CARGO_PROFILE_RELEASE_OPT_LEVEL=2',
             "SCCACHE_BASEDIRS=${env.WORKSPACE}/OpenModelica"]) {
      body()
    }
  }
}

/**
  * Prepended to a build running under withSccache: starts a server with the current environment
  * (a running one keeps the one it was started with), or drops RUSTC_WRAPPER if there is no sccache.
  */
def sccachePreamble() {
  return '''
  if command -v sccache > /dev/null; then
    log="`mktemp`"
    sccache --stop-server > /dev/null 2>&1 || true
    SCCACHE_ERROR_LOG="$log" SCCACHE_LOG=warn sccache --start-server
    sccache --show-stats
    if grep -qiE "storage (write )?check failed|read-only storage|cache storage failed" "$log"; then
      echo "WARNING: the sccache S3 backend is unusable; building without a shared cache:" >&2
      cat "$log" >&2
    fi
    rm -f "$log"
  else
    echo "sccache was not found; building without a compile cache"
    unset RUSTC_WRAPPER
  fi
  '''
}

/* The FMI simulators a job runs, from the parameters that used to start one job each.
 * Both ticked is one job that builds every FMU once and simulates it with both,
 * filling <branch>-fmi and <branch>-fmi-fmpy exactly as the two jobs did. */
def fmiSimulators(boolean omsimulator, boolean fmpy) {
  def simulators = []
  if (omsimulator) {
    simulators << 'OMSimulator'
  }
  if (fmpy) {
    simulators << 'fmpy'
  }
  return simulators
}

/**
  * Launches the test.py script with the given options.
  *
  * @param branch:              OpenModelica branch to test. Will checkout the branch and build omc from it.
  * @param name:                Unique name of the library test. Passed to test.py via flag `--branch`.
  *                             Also used for stashing omc and uploading results to https://test.openmodelica.org.
  * @param extraFlags:          Additional compiler flags passed to test.py via flag `--extraflags`.
  * @param omsHash:             The OMSimulator commit to build and simulate the FMUs with: a SHA,
  *                             a tag, or a ref of the remote such as `origin/master`. Not a local
  *                             branch name - `git fetch` does not update those, so resetting to one
  *                             keeps whatever commit the workspace was left at. Empty tests no FMUs.
  * @param extrasimflags:       Additional simulation flags passed to test.py via flag `--extrasimflags`.
  * @param testFlags:           Additional flags passed to test.py verbatim, e.g. `--nobuildmodel`.
  * @param removePackageOrder:  Passed to `installLibraries`.
  * @param conversionScript:    Passed to `installLibraries`.
  * @param jobs:                The number of tests/jobs to launch in parallel.
  *                             By default this is set to `0` which means launch as many tests as there are available
  *                             physical cpus on the machine'.
  * @param libsConfigFile:      The config file to be used for testing.
  *                             This file specifies which libraries to test and what options to use for them.
  * @param cmakeFlags:          Target-specific cmake flags, e.g. `-DOM_OMC_ENABLE_RUST=ON`. If non-empty, omc is
  *                             built with cmake instead of autotools; the shared release flags are added here.
  * @param dockerfile:          Directory with a Dockerfile, relative to the testing repository. Defaults to
  *                             `.CI/testing`, the image every job runs in: the omc build, the OMSimulator
  *                             build and test.py happen inside it, and only the steps using the node's own
  *                             omc stay outside. Passing `''` runs the job on the node itself.
  */
def runRegressiontest(branch, name, extraFlags, omsHash, extrasimflags, testFlags, boolean removePackageOrder, boolean conversionScript, int jobs=0, libsConfigFile = 'configs/conf.json', cmakeFlags = '', dockerfile = '.CI/testing', fmiSimulators = null) {
  sh '''
  find /tmp  -name "*openmodelica.hudson*" -exec rm {} ";" || true

  if test -z "$WORKSPACE"; then
    echo "Odd workspace"
    exit 1
  fi
  '''

  // Checked out before the omc build rather than just before test.py: it provides the Dockerfile.
  sh """
  if test ! -d OpenModelicaLibraryTesting; then
    git clone --recursive https://openmodelica.org/git-readonly/OpenModelicaLibraryTesting.git OpenModelicaLibraryTesting
  fi
  cd OpenModelicaLibraryTesting
  git fetch
  git reset --hard origin/master
  """

  def image = null
  if (dockerfile) {
    // Build context is the Dockerfile directory; the workspace has a directory per tested model.
    sh "cp OpenModelicaLibraryTesting/requirements.txt OpenModelicaLibraryTesting/${dockerfile}/"
    // Tagged after the Dockerfile rather than after the job, so that jobs sharing an image share
    // its tag as well and a node keeps one of them instead of one per job it has ever run.
    image = docker.build("openmodelica-library-testing:${dockerfile.tokenize('/').last()}",
                         "--pull OpenModelicaLibraryTesting/${dockerfile}")
  }
  // --init reaps the omc processes test.py orphans. ssh refuses to run for a uid it cannot look
  // up, so the node's passwd entry is needed to publish the results. The home holds the cached omc
  // build, the libraries (HOME during the test) and the ssh key; test.py writes a hash next to
  // every reference file. rust-cargo-registry is the volume the OpenModelica job uses.
  def dockerArgs = "--init" +
                   (image ? " ${memoryLimitArgs()}" : '') +
                   " -v /etc/passwd:/etc/passwd:ro -v /etc/group:/etc/group:ro" +
                   " -v ${env.HOME}:${env.HOME}" +
                   " -v /mnt/ReferenceFiles:/mnt/ReferenceFiles" +
                   " --mount type=volume,source=rust-cargo-registry,target=/opt/rust/cargo/registry"
  // Only in a container is the cgroup this job's own; a breach kills the greediest omc, which need
  // not be the model that caused it.
  def cgroupReport = image ? """
    cat /sys/fs/cgroup/memory.max || true
    trap 'cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.events || true' EXIT
  """ : ''
  // Jenkins exports the node's environment into the container, hiding the image's.
  def dockerEnv = ['PATH+VENV=/opt/libtest-venv/bin',
                   'PATH+CARGO=/opt/rust/cargo/bin',
                   'CARGO_HOME=/opt/rust/cargo',
                   'RUSTUP_HOME=/opt/rust/rustup']
  // Runs a script in the image if the target uses one, on the node otherwise.
  def runSh = { args ->
    if (image) {
      image.inside(dockerArgs) { withEnv(dockerEnv) { sh(args) } }
    } else {
      sh(args)
    }
  }

  // A job that does not say which simulators it wants gets the one its name implies.
  def simulators = fmiSimulators
  if (simulators == null) {
    simulators = name.contains('fmpy') ? ['fmpy'] : (omsHash ? ['OMSimulator'] : [])
  }
  def FMI_TESTING_FLAG = ""
  if (simulators.contains('OMSimulator') && omsHash) {
    // In the image rather than on the node: test.py runs this binary from inside it, and one built
    // against the node's libraries need not load there.
    runSh("""
    if ! test -d OMSimulator; then
      git clone --recursive https://openmodelica.org/git-readonly/OMSimulator.git || exit 1
    fi
    cd OMSimulator || exit 1

    git fetch || exit 1
    git reset --hard "${omsHash}" || exit 1

    git rev-parse HEAD > .newhash
    echo "OMSimulator Hash: ${omsHash} and commit:"
    cat .newhash || true
    echo Old Hash:
    cat ~/saved_omc/OMSimulator/.githash || true

    # The second test rebuilds a cached build that does not run here: one made on
    # the node before the job moved into a container, or against an older image,
    # matches by hash but misses the libraries it was linked against.
    if ! cmp ~/saved_omc/OMSimulator/.githash .newhash || ! ~/saved_omc/OMSimulator/install/bin/OMSimulator --version; then

      git submodule sync --recursive || exit 1
      git clean -ffdx || exit 1
      git submodule update --init --recursive --force || exit 1
      git submodule foreach --recursive  "git fetch --tags --force && git reset --hard && git clean -fdxq -e /git -e /svn" || exit 1
      cmake -S . -B build/ -DCMAKE_INSTALL_PREFIX=install/
      cmake --build build/ --target install || exit 1
      ./install/bin/OMSimulator --version || exit 1
      mkdir -p ~/saved_omc/OMSimulator || exit 1
      cp -a * ~/saved_omc/OMSimulator/ || exit 1
      git rev-parse HEAD > ~/saved_omc/OMSimulator/.githash || exit 1

    fi
    echo OMSimulator version:
    ${env.HOME}/saved_omc/OMSimulator/install/bin/OMSimulator --version
    """)
    FMI_TESTING_FLAG = " --fmisimulator=${env.HOME}/saved_omc/OMSimulator/install/bin/OMSimulator"
  }

  if (simulators.contains('fmpy')) {
    // The version is the image's; check it in the interpreter test.py will reach rather than
    // installing one over it, which in a container would be thrown away with the container.
    runSh('python3 -m fmpy -h > /dev/null || exit 1')
    FMI_TESTING_FLAG += " --fmisimulator='python3 -m fmpy'"
  }

  if (FMI_TESTING_FLAG) {
    FMI_TESTING_FLAG = "--fmi=true${FMI_TESTING_FLAG} --default=ulimitExe=50"
    if (name.contains('cvode')) {
      FMI_TESTING_FLAG += " --fmuType=cs"
    }
  }

  // A pull request is fetched from GitHub itself: refs/pull/* is not on the
  // read-only mirror the rest of the job clones. The merge ref rather than the
  // head one, since the question is what happens once it is merged, and it is
  // checked out detached so that nothing is left behind for the next run of the
  // same workspace to trip over.
  def pullRequest = branch.startsWith('pr/') && branch.substring(3).isInteger() ? branch.substring(3) : ''
  def checkoutRef = pullRequest ? """
    REFS=`git ls-remote https://github.com/OpenModelica/OpenModelica.git "refs/pull/${pullRequest}/head" "refs/pull/${pullRequest}/merge"` || exit 1
    case "\$REFS" in
      *"refs/pull/${pullRequest}/merge"*)
        PRREF="refs/pull/${pullRequest}/merge" ;;
      *"refs/pull/${pullRequest}/head"*)
        # GitHub only has a merge ref while it can merge the pull request into
        # its base branch. Without one there is still something to test, only it
        # is the pull request on its own rather than as it would land.
        echo "WARNING: pull request ${pullRequest} has no merge ref: it conflicts with its base branch, or it is closed."
        echo "WARNING: testing refs/pull/${pullRequest}/head, which does not have what was merged into the base branch since it was branched."
        PRREF="refs/pull/${pullRequest}/head" ;;
      *)
        echo "OpenModelica/OpenModelica has no pull request ${pullRequest}."
        exit 1 ;;
    esac
    echo "Testing \$PRREF"
    git fetch --force https://github.com/OpenModelica/OpenModelica.git "\$PRREF" || exit 1
    git checkout -f --detach FETCH_HEAD || exit 1
    git fetch --tags --force || exit 1
""" : """
    git reset --hard && git checkout -f "${branch}" && (git rev-parse --verify "tags/${branch}"  || (git reset --hard "origin/${branch}" && git pull)) && git fetch --tags --force || exit 1
"""

  // The build used to say -j9, the cores of the machine this file was written
  // for in 2019, and -j16, the cores of the ryzen-5950x machines that replaced
  // it - the commit that raised the others to 16 left the omc build at 9. Named
  // buildJobs rather than jobs: that is this method's own parameter, how many
  // models test.py tests at a time.
  def buildJobs = numPhysicalCPU()
  echo "Building omc with -j${buildJobs} on ${env.NODE_NAME}"

  def buildOMC
  if (cmakeFlags) {
    // Run from OpenModelica/OMCompiler, one directory below the cmake source tree.
    buildOMC = sccachePreamble() + """
    cmake -S .. -B ../build_cmake -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX="`pwd`/build" \
      -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_Fortran_COMPILER=gfortran \
      -DCMAKE_C_FLAGS=-march=native -DCMAKE_CXX_FLAGS=-march=native \
      -DOM_USE_CCACHE=OFF -DOM_ENABLE_GUI_CLIENTS=OFF -DOM_ENABLE_OMSIMULATOR=OFF \
      ${cmakeFlags} || exit 1
    if ! time cmake --build ../build_cmake --parallel ${buildJobs} --target install > log 2>&1; then
      cat log
      exit 1
    fi
    build/bin/omc --version || exit 1
    sccache --show-stats || true
    """
  } else {
    buildOMC = """
    autoreconf --install
    ./configure --with-cppruntime --without-omc --disable-modelica3d CC=clang CXX=clang++ FC=gfortran CFLAGS='-O2 -march=native' --with-omniORB
    time make -j${buildJobs} clean
    if ! time make -j${buildJobs} omc > log 2>&1; then
      cat log
      exit 1
    fi
    if ! time make -j${buildJobs} runtimeCPPinstall > log 2>&1; then
      cat log
      if test "${name}" = "master"; then
        exit 1
      else
        echo "Ignoring failed C++ runtime"
      fi
    fi
    """
  }

  sh '''
  FREE=`df -k --output=avail "$PWD" | tail -n1`   # df -k not df -h
  if test "$FREE" -lt 31457280; then               # 30G = 30*1024*1024k
    echo "Less than 30 GB free disk space"
    exit 1
  fi;
  '''

  sh 'killall omc || true'

  def checkoutAndBuild = """
  if test ! -d OpenModelica; then
    git clone --recursive https://openmodelica.org/git-readonly/OpenModelica.git OpenModelica
  fi
  cd OpenModelica
  git fetch
  git reset --hard origin/master
  git clean -fdx

  cd OMCompiler

  if ! test -f ~/saved_omc/${name}/.nogit; then
    ${checkoutRef}
    git submodule update --init --recursive --force || (rm -rf * && git reset --hard && git submodule update --init --recursive --force) || exit 1
    git submodule foreach --recursive  "git fetch --tags --force && git reset --hard && git clean -fdxq -e /git -e /svn" || exit 1
    git clean -fdxq || exit 1
    git submodule status --recursive
  fi

  export OPENMODELICAHOME="`pwd`/build"

  git rev-parse --verify HEAD > .newhash
  echo New Hash:
  cat .newhash
  echo Old Hash:
  cat ~/saved_omc/${name}/.githash || true
  REBUILD=""
  if cmp ~/saved_omc/${name}/.githash .newhash || test -f ~/saved_omc/${name}/.nogit; then
    rsync -a --delete ~/saved_omc/${name}/ build/ || exit 1
    echo "Restoring cached OMC version: ${name}, `cat ~/saved_omc/${name}/.githash`"
    # The hash says the sources match, not that the binary runs here: a cache
    # filled on the node before the jobs moved into a container, or before the
    # image changed, holds an omc linked against libraries that are missing now.
    # Without this check the run dies much later, when test.py asks the restored
    # binary for its version and gets exit code 127.
    if ! build/bin/omc --version; then
      if test -f ~/saved_omc/${name}/.nogit; then
        echo "The cached omc of ${name} does not run in this environment, and .nogit forbids rebuilding it."
        exit 1
      fi
      echo "The cached omc of ${name} does not run in this environment; rebuilding it."
      REBUILD=1
    fi
  else
    REBUILD=1
  fi
  if test -n "\$REBUILD"; then
    ${buildOMC}
    rm -rf ~/saved_omc/${name}/
    mkdir -p ~/saved_omc/${name}/
    CMD="rsync -a --delete build/ \$HOME/saved_omc/${name}/"
    echo \$CMD
    \$CMD || exit 1
    cp .newhash ~/saved_omc/${name}/.githash
  fi
  """

  if (cmakeFlags) {
    withSccache { runSh(checkoutAndBuild) }
  } else {
    runSh(checkoutAndBuild)
  }

  sh """
  cd OpenModelica
  if ! time make -j${numLogicalCPU()} -C testsuite/ReferenceFiles > log 2>&1; then
    cat log
    exit 1
  fi

  cd ../
  rm -rf Reference-modelica.org
  ln -s /mnt/ReferenceFiles/modelica.org Reference-modelica.org
  """
  // sh 'rsync -av modelica-ro:/files/RegressionTesting/ReferenceResults Reference-modelica.org || true # exit 1'

  def MSLREFERENCE = "${env.WORKSPACE}/Reference-modelica.org/ReferenceResults"
  def REFERENCEFILES = "${env.WORKSPACE}/OpenModelica/testsuite/ReferenceFiles"
  def GITREPOS = "${env.WORKSPACE}/OpenModelica/libraries/git"
  def PNLIBREFS = "/mnt/ReferenceFiles/PNlib/ReferenceFiles"
  def THERMOFLUIDSTREAMREFS = "/mnt/ReferenceFiles/ThermofluidStream-main-regression/ReferenceData"
  def THERMOFLUIDSTREAMREFSOM = "/mnt/ReferenceFiles/ThermofluidStream-OM-regression/ReferenceData"

  sh """
  test -f "${MSLREFERENCE}/MAP-LIB_ReferenceResults/v4.0.0/README.md" || exit 1

  mkdir -p "/var/www/libraries.openmodelica.org/branches/${name}/"
  """

  def libraryPath = installLibraries(removePackageOrder, conversionScript, name, "${env.WORKSPACE}/OpenModelica/OMCompiler/build", runSh)

  sh "test -d '${libraryPath}/.openmodelica/libraries/Modelica trunk'"

  sh 'date'

  // The password of the results database comes from a secret file, bound here
  // rather than for the pipeline as a whole: writing the file needs the
  // workspace of a node, and the pipeline has agent none.
  withCredentials([file(credentialsId: 'omdb-pgpass', variable: 'PGPASSFILE')]) {
    runSh("""
    export OPENMODELICAHOME="${env.WORKSPACE}/OpenModelica/OMCompiler/build"
    export MSLREFERENCE="${MSLREFERENCE}"
    export REFERENCEFILES="${REFERENCEFILES}"
    export GITREPOS="${GITREPOS}"
    export PNLIBREFS="${PNLIBREFS}"
    export THERMOFLUIDSTREAMREFS="${THERMOFLUIDSTREAMREFS}"
    export THERMOFLUIDSTREAMREFSOM="${THERMOFLUIDSTREAMREFSOM}"
    export PREVIOUSHOME="${env.HOME}"
    export HOME="${libraryPath}"
    # we need to do some crap magic here to make sure python3 finds fmpy as we change the HOME here
    # too bad if we cannot do it, just continue
    ln -s -t \${HOME} \${PREVIOUSHOME}/.local .local || true

    ${cgroupReport}
    cd OpenModelicaLibraryTesting
    # Force /usr/bin/omc as being used for generating the mos-files. Ensures consistent behavior among all tested OMC versions
    stdbuf -oL -eL time ./test.py --ompython_omhome=/usr ${FMI_TESTING_FLAG} --extraflags='${extraFlags}' --extrasimflags='${extrasimflags}' ${testFlags} --branch="${name}" --output="libraries.openmodelica.org:/var/www/libraries.openmodelica.org/branches/${name}/" --libraries='${libraryPath}/.openmodelica/libraries/'  --jobs=${jobs} ${libsConfigFile} ${params.OLDLIBS ? "configs/conf-old.json configs/conf-nonstandard.json" : ""} || (killall omc ; false) || exit 1
    """)
    sh 'date'
    // In the image: the script talks to the results database through psycopg2,
    // which is in the image's python environment and not on the node.
    runSh("cd OpenModelicaLibraryTesting/ && ./clean-empty-omcversion-dates.py")
  }
}

return this
