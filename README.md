# OpenModelica Library Testing

[![Continuous Integration](https://github.com/OpenModelica/OpenModelicaLibraryTesting/actions/workflows/test.yml/badge.svg)](https://github.com/OpenModelica/OpenModelicaLibraryTesting/actions/workflows/test.yml)
[![License: OSMC-PL](https://img.shields.io/badge/license-OSMC--PL-lightgrey.svg)](OSMC-License.txt)

This repository provides scripts and documentation to run the nightly Modelica library tests for OpenModelica.

## OpenModelica nightly testsuite

Some of the open-source Modelica libraries managed by the [Open Modelica Package Manager](https://github.com/OpenModelica/OMPackageManager) are tested on a daily basis on the OSMC servers.

[Test results reports](testresults.md#open-source-modelica-library-testing-using-openmodelica) are publicly available.

The configuration file for the regular library nightly testsuite is [conf.json](configs/conf.json). Additional old and non-standard libraries are listed in [conf-old.json](configs/conf-old.json) and [conf-nonstandard.json](configs/conf-nonstandard.json), note that failures in those libraries may be due to the fact that they are not fully complying with the Modelica standard, rather than to OpenModelica issues. The setup of the configuration files is discussed in [conf-howto.md](conf-howto.md).

Test results reports are collected in the https://libraries.openmodelica.org/branches/ directory. The [overview.html](https://libraries.openmodelica.org/branches/overview.html) report gives the results of the regular testsuite with the default C runtime and solvers. Other reports contain the results using the C++ runtime, FMI, daeMode, and the old frontend. Combined reports also include results from the old and nonstandard libraries. The https://libraries.openmodelica.org/branches/history/ directory contains regression reports and plots using different versions (including master) and simulation runtime configurations (C++, daeMode, FMI, old frontend) of OpenModelica.

If you want to include your open-source library in the testsuite, please open a pull request on [conf.json](configs/conf.json), or open an issue on the [OpenModelica issue tracker](https://github.com/OpenModelica/OpenModelica/issues/new/choose) and ask us to do it for you.

## Running the library testing infrastructure on your own server

The scripts from this repository can be used to run regression tests for public, private, and commercial Modelica libraries to keep track of coverage with different OpenModelica versions, according to the conditions of the [OSMC-PL license](OSMC-License.txt).

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
  - OMC will search for libraries in the location provided with test.py argument `--libraries`.
    The default value is `/home/username/.openmodelica/libraries/` (Linux) or `%APPDATA%/.openmodelica/libraries` (Windows).
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
        "referenceFileExtension":"mat",
        "referenceFileNameDelimiter":"/",
        "referenceFileNameExtraName":"$ClassName",
        "referenceFiles":{
          "giturl":"https://github.com/myName/MyModelicaLibrary-ref",
          "destination":"ReferenceFiles/MyModelicaLibrary",
          "git-ref": "main",
          "git-directory": "ReferenceFiles"
        },
        "optlevel":"-Os -march=native"
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

    Check `config/conf.json` for more.
  - If you used `.CI/installLibraries.mos` to test all libraries you'll need to install reference results and set environment variables, see [Reference Results](#reference-results).
    ```bash
    export MSLREFERENCE="/path/to/ReferenceFiles/"
    export REFERENCEFILES="/path/to/OpenModelica/testsuite/ReferenceFiles"
    export PNLIBREFS="/path/to/ReferenceFiles/PNlib/ReferenceFiles"
    export THERMOFLUIDSTREAMREFS="/path/to/ReferenceFiles/ThermofluidStream-main-regression/ReferenceData"
    export THERMOFLUIDSTREAMREFSOM="/path/to/ReferenceFiles/ThermofluidStream-OM-regression/ReferenceData"
    ```

  - Run the library test
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
      - `--ompython_omhome=''`: Path to OpenModelica for OMPython (can be different to the OM running the tests)
      - `--noclean=False`: Clean (most) generated files.
      - `--fmisimulator=''`: The default is nothing but you can use the path to OMSimulator executable or 'fmpy'
      - `--ulimitvmem=8388608`: Virtual memory limit (in kB)
      - `--default=[]`: Add a default value for some configuration key, such as --default=ulimitExe=60. The equals sign is mandatory
      - `-j`,`--jobs`: Number of threads to use for testing.

  - Generate HTML results
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
  - Modelica Association: https://github.com/modelica/MAP-LIB_ReferenceResults
  - PNLib: https://github.com/AMIT-FHBielefeld/PNlib
  - DLR-SR: https://github.com/DLR-SR/ThermoFluidStream-Regression.git and https://github.com/DLR-SR/PlanarMechanics_ReferenceResults.git


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
git fetch --tags

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
