# OpenModelica Library Testing

[![Continuous Integration](https://github.com/OpenModelica/OpenModelicaLibraryTesting/actions/workflows/test.yml/badge.svg)](https://github.com/OpenModelica/OpenModelicaLibraryTesting/actions/workflows/test.yml)
[![License: OSMC-PL](https://img.shields.io/badge/license-OSMC--PL-lightgrey.svg)](OSMC-License.txt)

This repository provides scripts and documentation to run the nightly Modelica
library tests for OpenModelica.

## OpenModelica nightly testsuite

Some of the open-source Modelica libraries managed by the
[Open Modelica Package Manager](https://github.com/OpenModelica/OMPackageManager)
are tested on a daily basis on the OSMC servers.

[Test results reports](testresults.md#open-source-modelica-library-testing-using-openmodelica)
are publicly available.

The configuration file for the regular library nightly testsuite is
[conf.json](configs/conf.json). Additional old and non-standard libraries are
listed in [conf-old.json](configs/conf-old.json) and
[conf-nonstandard.json](configs/conf-nonstandard.json), note that failures in
those libraries may be due to the fact that they are not fully complying with
the Modelica standard, rather than to OpenModelica issues. The setup of the
configuration files is discussed in [conf-howto.md](conf-howto.md).

Test results reports are collected in the
[https://libraries.openmodelica.org/branches/](libraries.openmodelica.org/branches)
directory. The
[overview.html](https://libraries.openmodelica.org/branches/overview.html)
report gives the results of the regular testsuite with the default C runtime and
solvers. Other reports contain the results using the C++ runtime, FMI, daeMode,
and the old frontend. Combined reports also include results from the old and
nonstandard libraries. The
[https://libraries.openmodelica.org/branches/history/](libraries.openmodelica.org/branches/history)
directory contains regression reports and plots using different versions
(including master) and simulation runtime configurations (C++, daeMode, FMI, old
frontend) of OpenModelica.

If you want to include your open-source library in the testsuite, please open a
pull request on [conf.json](configs/conf.json), or open an issue on the
OpenModelica
[issue tracker](https://github.com/OpenModelica/OpenModelica/issues/new/choose)
and ask us to do it for you.

## Running the library testing infrastructure on your own server

The scripts from this repository can be used to run regression tests for public,
private, and commercial Modelica libraries to keep track of coverage with
different OpenModelica versions, according to the conditions of the
[OSMC-PL license](OSMC-License.txt).

### Dependencies

- [OpenModelica](https://openmodelica.org)
- [Python](https://www.python.org/)
- (Optional) Reference simulation result files

### Set-Up

- Install or build OpenModelica
  - [Install instructions](https://openmodelica.org/download/download-linux)
  - [Build instructions](https://github.com/OpenModelica/OpenModelica#readme)
  - Make sure `omc` is in your `PATH`
- Install Python requirements

  ```bash
  pip install -r requirements.txt
  ```

- OMC will search for libraries in the location provided with test.py argument
  `--libraries`. The default value is `/home/username/.openmodelica/libraries/`
  (Linux) or `%APPDATA%/.openmodelica/libraries` (Windows).
  - Install your libraries into the location specified with `--libraries`
    or use `loadFile` command inside `loadFileCommands` in the config JSON:

    ```yml
    "loadFileCommands": [
      "loadFile(\"/path/to/package.mo\")"
    ]
    ```

- Create configs/myConf.json to specify what libraries to test.

  ```json
  [
    {
      "library":"MyModelicaLibrary",
      "libraryVersion":"main",
      "libraryVersionExactMatch":true, // to be sure that the exact version is loaded, not the latest compatible
      "libraryVersionLatestInPackageManager":true, // load the latest from the package manager
      "referenceFileExtension":"mat",
      "referenceFileNameDelimiter":"/",
      "referenceFileNameExtraName":"$ClassName",
      "referenceFiles": "/path/to/some/SomeDirectory", // specifies a directory with the files
      "referenceFiles": "$ENV_VAR/SomeDirectory", // specifies a directory with the files via an env var
      "referenceFiles":{ // specified as an URL, directory destination, git branch and git directory
        "giturl":"https://github.com/myName/MyModelicaLibrary-ref",
        "destination":"ReferenceFiles/MyModelicaLibrary",
        "git-ref": "main",
        "git-directory": "ReferenceFiles"
      },
      "defaultTolerance": 1e-6, // tolerance for tests if not specified by the model, defaults to 1e-6
      "defaultNumberOfIntervals": 2500, // number of intervals for tests if not specified by the model, defaults to 2500
      "ulimitOmc":800, // specify a max timeout for a model build
      "ulimitExe":300, // specify a max timeout for a model simulation
      "ulimitMemory":62000000, // specify a max for the virtual memory of the running process when building a model
      "procOMC":0, // [if procOMC = 0 use max procs, use procOMC = 1 if not defined, else use the given value] how many CPU cores should be used to run omc (load Modelica libraries in parallel and generate the C code in parallel)
      "procCCompile":0, // [if procCCompile = 0 use max procs, use procCCompile = 1 if not defined, else use the given value] how many CPU cores should be used to compile the generated code
      "optlevel":"-Os -march=native" // what optimizations should be used by the C compiler
    }
  ]
  ```

  You can add extra compiler settings

  ```json
  "extraCustomCommands":["setCommandLineOptions(\"--std=3.2\");"]
  ```

  and extra simulation flags

  ```json
  "extraSimFlags": "-s=ida -nls=kinsol"
  ```

  Check [configs/conf.json](./configs/conf.json) for more.
- If you used [.CI/installLibraries.mos](./.CI/installLibraries.mos) to test all
  libraries you'll need to install reference results and set environment
  variables, see [Reference Results](#reference-results).

  ```bash
  export MSLREFERENCE="/path/to/ReferenceFiles/"
  export REFERENCEFILES="/path/to/OpenModelica/testsuite/ReferenceFiles"
  export PNLIBREFS="/path/to/ReferenceFiles/PNlib/ReferenceFiles"
  export THERMOFLUIDSTREAMREFS="/path/to/ReferenceFiles/ThermofluidStream-main-regression/ReferenceData"
  export THERMOFLUIDSTREAMREFSOM="/path/to/ReferenceFiles/ThermofluidStream-OM-regression/ReferenceData"
  ```

### Library Test

Run the library test:

```bash
./test.py --noclean configs/myConf.json
```

Use `configs/*.json` to specify what to test.
The test results are saved in `sqlite3.db`.

Options:

- `--branch=master`: Branch of OpenModelica
- `--fmi=False`: Test FMI
- `--output=''`: Result location
- `--libraries=~/.openmodelica/libraries/`: Location of Modelica libraries
- `--extraflags=''`: Extra compiler flags.
- `--extrasimflags=''`: Extra simulation flags.
- `--ompython_omhome=''`: Path to OpenModelica for OMPython (can be different to
                          the OM running the tests)
- `--noclean=False`: Clean (most) generated files.
- `--fmisimulator=''`: The FMI simulator to run the FMUs with, as `name=command`
                       or just the command, e.g. the path to the OMSimulator
                       executable or `'python3 -m fmpy'`. Repeat the option to
                       simulate every FMU with several tools without building it
                       more than once, see [Testing FMI with several
                       simulators](#testing-fmi-with-several-simulators)
- `--ulimitvmem=8388608`: Virtual memory limit (in kB)
- `--default=[]`: Add a default value for some configuration key, such as
                  `--default=ulimitExe=60`. The equals sign is mandatory
- `-j`,`--jobs`: Number of cores to use for testing, default is `0` (max cores),
                 use `1` to run serial (for large tests) and see `procOMC` and
                 `procCCompile` above for more insight into individual test
                 parallelization.

### Testing FMI with several simulators

Building an FMU costs far more than simulating it. Measured on the twelve
models of ExternData: 178 seconds building the FMUs, 0.7 simulating them with
OMSimulator and 2.6 with FMPy. Testing the same FMUs with a second tool
therefore used to cost almost twice as much as testing them with one, because
each job built its own copy of them.

Give `--fmisimulator` once per tool and the FMUs are built once and simulated
with each of them:

```bash
./test.py --branch=v1.27-fmi --fmi=true \
          --fmisimulator=/path/to/OMSimulator \
          --fmisimulator='python3 -m fmpy' \
          configs/myConf.json
```

`--branch` names the job; every simulator stores its results in a branch of its
own derived from it, so the run above fills

| simulator | branch | published to |
| --- | --- | --- |
| OMSimulator | `v1.27-fmi` | `branches/v1.27-fmi` |
| FMPy | `v1.27-fmi-fmpy` | `branches/v1.27-fmi-fmpy` |

which is where those results have always been. OMSimulator keeps the plain
`-fmi` branch; every other tool adds its name. The branch a tool fills depends
on the tool and not on the order, so asking for FMPy alone still fills
`v1.27-fmi-fmpy` and leaves `v1.27-fmi` alone.

A branch directory looks the same as it always did, file names included. The
`.err` of a model is written by the build, so every simulator of it publishes
the same one; the `.sim` and the difference files are the ones that simulator
produced.

Only the simulator may differ between the results that share an FMU. Anything
that changes the FMU itself - a different compiler, a different library, a
different `--fmuType` or `--fmiFlags` - is a different job, which is why the
Co-Simulation jobs with CVODE are not merged with the Model Exchange ones.

In Jenkins the parameters keep their meaning: `fmi_v1_27` asks for OMSimulator
and `fmpy_fmi_v1_27` for FMPy. Ticking both runs one job that builds every FMU
once and simulates it with both; ticking one runs that tool alone.

### Adding an FMI simulator

The simulators live in [configs/fmi-simulators.json](configs/fmi-simulators.json).
Adding one is an entry there and no change to any script:

```json
"fmusim": {
  "resultExtension": "csv",
  "versionArgument": "--version",
  "optionalArguments": { "stepSizeArgument": " --output-interval {stepSize:g}" },
  "arguments": "--interface-type ModelExchange --output-file {result} --start-time {startTime:g} --stop-time {stopTime:g}{stepSizeArgument} {fmu}"
}
```

- `arguments` is the command line, a template over `simulator`, `fmu`,
  `result`, `requestedResult`, `tempDir`, `startTime`, `stopTime`, `tolerance`,
  `timeout`, `stepSize` and anything named in `optionalArguments`.
- `optionalArguments` are the flags that have to disappear when there is nothing
  to put in them. OMSimulator hangs on `--stepSize=0` rather than ignoring it,
  so its step size flag lives here, while FMPy wants `--output-interval 0` all
  the same and writes the value straight into its `arguments`.
- `command` is how the tool is invoked, `{simulator}` by default. FMPy needs a
  subcommand, `{simulator} simulate`.
- `resultExtension` is what the tool writes, so that the comparison against the
  reference file knows what to read.
- `versionArgument` prints the version, which is recorded with the results.
- `branchSuffix` overrides the `-<name>` a tool adds to the branch. Only
  OMSimulator needs it, with `""`.
- `untested` marks an entry nobody has run yet; the run then says so instead of
  failing every model with a puzzling error. Remove it once it works.

Then run it with `--fmisimulator=fmusim=/path/to/fmusim`, or just
`--fmisimulator=/path/to/fmusim` if the command contains the name.

A tool that is a Python package rather than a command line needs a small driver
script that takes the arguments its entry passes, simulates, writes the result
file and exits non-zero when it fails; the entry then points `command` at it.

### Testing a pull request

A branch is tested against its own previous run, which says what broke *after* a
change was merged. A pull request can be tested before that, against the newest
run of `master`.

In Jenkins, set the **`pull_request`** parameter to the pull request number and
start the job; `pull_request_baseline`, `pull_request_config` and
`pull_request_node` say what it is compared against, what it tests and where.
None of the branch jobs run unless their own parameter is ticked as well.

By hand it is two steps. The compiler is built from the merge ref - the pull
request as it would land, not the branch on its own - and the run fills a
`pr/<N>` table like any other branch:

```bash
git fetch --force https://github.com/OpenModelica/OpenModelica.git refs/pull/<N>/merge
git checkout -f --detach FETCH_HEAD
# build omc, then
./test.py --branch=pr/<N> configs/conf.json
```

`pr/<N>` rather than `pr-<N>`: the results of a pull request are stored and
published under `pr/`, so that `branches/` holds branches and the pull requests
sit together in one directory of it. It is the one job name that keeps the
directory part of its name - `maintenance/v1.27` is tested as `v1.27`.

and the report compares that run against the newest run of `master`:

```bash
./pr-report.py <N>                 # --baseline=master by default
```

It writes `history/pr/<N>/<baseline run>..<pull request run>.html`, the same
kind of page as the nightly regression reports, next to `00_comment.md`, a
summary to comment on the pull request with. Both are published with the other
reports.

`--comment` posts that summary on the pull request, and replaces it rather than
adding to it when the same pull request is tested again. It posts as whoever the
token belongs to: `GITHUB_TOKEN` or `GH_TOKEN` in the environment, or the account
[`gh`](https://cli.github.com) is logged in as. In Jenkins it is the
`pull_request_comment` parameter, which takes the token from a `github-token`
credential; without one the report is still written and published, and the
summary is in the build log.

Two things make a difference mean something other than "the pull request did
this", and the report says so when they apply: **the machine**, since two runs
produced on different hardware compare the hardware as much as the change, and
**the libraries**, since two runs that tested different library versions, or
verified against different reference files, differ for reasons of their own. The
baseline is also the newest `master` run rather than the commit the pull request
is based on, so a difference can come from anything merged since it was
branched - a reason to rebase before believing a surprising result.

A full run takes days, so testing every pull request this way is not the idea;
point `--branch=pr/<N>` at a smaller configuration file when the question is
narrower.

The tables accumulate, about 19500 rows each. `drop-pr-tables.py` drops the ones
whose pull request has been merged or closed, and those tested more than
`--older-than` days ago, together with the rows their runs left in the other
tables; it lists them and does nothing unless it is given `--yes`. The reports
published for them are not touched.

### Generate HTML results

  ```bash
  ./report.py configs/myConf.json
  ```

- Upload and backup
  - Upload HTML files somewhere
  - backup sqlite3.db

### Reference Results

If you use the default configs `config/conf.json` and
`config/conf-c++.json` to test all libraries you need to
download the reference files and make them available by
defining `MSLREFERENCE` and `REFERENCEFILES`.

Some result file locations:

- Modelica Association: [modelica/MAP-LIB_ReferenceResults](https://github.com/modelica/MAP-LIB_ReferenceResults)
- PNLib: [AMIT-HSBI/PNlib](https://github.com/AMIT-HSBI/PNlib)
- DLR-SR: [DLR-SR/ThermoFluidStream-Regression](https://github.com/DLR-SR/ThermoFluidStream-Regression)
  and [DLR-SR/PlanarMechanics_ReferenceResults](https://github.com/DLR-SR/PlanarMechanics_ReferenceResults)

To download the MSL reference files create a file
installReferenceResults.sh with

```sh
#!/bin/sh

refdir="/some/path/to/ReferenceFiles"   # Change the path!

# Update git repo for MSL Reference files
mkdir -p $refdir/modelica.org/ReferenceResults
cd $refdir/modelica.org/ReferenceResults
rm -rf $refdir/MAP-LIB_ReferenceResults/

test -f MAP-LIB_ReferenceResults.git/config || git clone --bare https://github.com/modelica/MAP-LIB_ReferenceResults.git MAP-LIB_ReferenceResults.git
cd MAP-LIB_ReferenceResults.git
git fetch origin '*:*'
git fetch --tags --force

for tag in $(git for-each-ref --format="%(refname:lstrip=-1)" refs/heads/)
do
  echo "tag: $tag"
  base="$refdir/MAP-LIB_ReferenceResults/$tag"
  mkdir -p $base
  echo "mkdir -p $base"
  git archive --format=tar $tag | (cd $base && tar xvf -)
done
```

and run it

```bash
chmod a+rx installReferenceResults.sh
./installReferenceResults.sh
export MSLREFERENCE="/some/path/to/ReferenceFiles/"
```

For the other libraries just clone the repositories to `/some/path/to/ReferenceFiles/`.
