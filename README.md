# OpenModelica Library Testing

[![License: OSMC-PL](https://img.shields.io/badge/license-OSMC--PL-lightgrey.svg)](OSMC-License.txt)

This repository provides scripts to run the nightly Modelica library tests for OpenModelica.

The scripts from this repository can be uses to run regression tests for public, non-public or commercial Modelica libraries to keep track of coverage with different OpenModelica versions.

## Dependencies (Linux)
- [OpenModelica](https://openmodelica.org)
- [Python](https://www.python.org/)
- [Optional] Reference Files


## Set-Up

- Install or build OpenModelica
  - [Install instructions](https://openmodelica.org/download/download-linux)
  - [Build instructions](https://github.com/OpenModelica/OpenModelica#readme)
  - Make sure `omc` is in your `PATH`
- Install Python requirements
  ```bash
  pip install -r requirements.txt
  ```
- Install libraries you want to test
  - (Optional) Remove already installed libraries
    ```bash
    rm -rf ~/.openmodelica/libraries/
    rm -rf /path/to/OpenModelica/build/lib/omlibraries
    ```
  - Install all available libraries.
    ```bash
    /path/to/omc .CI/installLibraries.mos
    ```

    *or*
  - Install your libraries.
- Create configs/myConf.json to specify what libraries to test.
  ```json
  [
    {
      "library":"MyModelicaLibrary",
      "libraryVersion":"master",
      "referenceFileExtension":"mat",
      "referenceFileNameDelimiter":"/",
      "referenceFileNameExtraName":"$ClassName",
      "referenceFiles":{
        "giturl":"https://github.com/myName/MyModelicaLibrary-ref",
        "destination":"ReferenceFiles/MyModelicaLibrary"
      },
      "optlevel":"-Os -march=native"
    }
  ]
  ```

  You can add extra compiler settings
  ```json
  "extraCustomCommands":["setCommandLineOptions(\"--std=3.2\");"]
  ```
  and more. Check `config/conf.json` for more.
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
  - DLR-SR: https://github.com/DLR-SR/ThermoFluidStream-Regression.git and https://github.com/DLR-SR/ThermoFluidStream-Regression.git


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